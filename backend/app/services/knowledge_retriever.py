"""知识库检索器 — 向量语义检索 + 关键词回退.

使用 sentence-transformers + ChromaDB 做语义向量检索，
如果依赖不可用则自动降级为关键词匹配。
检索精度目标：~85%+（关键词匹配基线 ~60%）。

架构：
- 启动时从 default_rules.json 提取规则名+描述，向量化存入 ChromaDB
- collection 名称: ir_rules，持久化到 backend/data/chroma/
- 首次启动自动构建索引（_build_index），幂等：已有记录则跳过
- retrieve() 优先使用向量检索，失败/不可用时降级为关键词匹配
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 依赖可用性检测
# ---------------------------------------------------------------------------

_CHROMA_AVAILABLE: bool = False
_EMBEDDING_AVAILABLE: bool = False

try:
    import chromadb  # noqa: F811

    _CHROMA_AVAILABLE = True
except ImportError:
    logger.warning("chromadb not available, will fall back to keyword matching")

try:
    from sentence_transformers import SentenceTransformer  # noqa: F811

    _EMBEDDING_AVAILABLE = True
except ImportError:
    logger.warning("sentence-transformers not available, will fall back to keyword matching")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

EMBEDDING_MODEL_NAME: str = "BAAI/bge-base-zh-v1.5"  # 768 维，中英双语优化，安全领域预训练
COLLECTION_NAME: str = "ir_rules"
CHROMA_PERSIST_DIR: str = str(settings.DATA_DIR / "chroma")

# 向量检索相似度阈值（cosine distance，越小越相似）
# 经验值：distance < 0.7 → similarity > 0.3，能覆盖语义相近的情况
VECTOR_DISTANCE_THRESHOLD: float = 0.7

# ---------------------------------------------------------------------------
# 进程级缓存
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL: Optional[Any] = None
_COLLECTION: Optional[Any] = None
_RULES_CACHE: list[dict] = []
_C2_SIGNATURES_CACHE: list[str] = []
_SEED_CACHE: list[dict] = []
_SEED_INDEXED: bool = False


# ============================================================================
# 核心工具函数
# ============================================================================


def _get_embedding_model() -> Optional[Any]:
    """延迟加载 sentence-transformers 模型（进程级单例）.

    在离线/受限网络环境下只尝试本地缓存，避免首次联网下载阻塞整条 AI 分析链路。
    本地无模型时快速回退到关键词检索。
    """
    global _EMBEDDING_MODEL, _EMBEDDING_AVAILABLE

    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    if not _EMBEDDING_AVAILABLE:
        return None

    try:
        _EMBEDDING_MODEL = SentenceTransformer(
            EMBEDDING_MODEL_NAME,
            local_files_only=True,
        )
        logger.info("Loaded embedding model from local cache: %s", EMBEDDING_MODEL_NAME)
    except Exception as exc:
        logger.warning(
            "Embedding model %s unavailable in local cache, falling back to keyword matching: %s",
            EMBEDDING_MODEL_NAME,
            exc,
        )
        _EMBEDDING_MODEL = None
        _EMBEDDING_AVAILABLE = False
    return _EMBEDDING_MODEL


def _get_collection() -> Optional[Any]:
    """获取或创建 ChromaDB collection（进程级单例）."""
    global _COLLECTION

    if _COLLECTION is not None:
        return _COLLECTION
    if not _CHROMA_AVAILABLE:
        return None

    try:
        persist_dir = Path(CHROMA_PERSIST_DIR)
        persist_dir.mkdir(parents=True, exist_ok=True)

        client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
        _COLLECTION = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDB collection '%s' ready (count=%d)",
            COLLECTION_NAME,
            _COLLECTION.count(),
        )
    except Exception as exc:
        logger.error("Failed to initialize ChromaDB: %s", exc)
        _COLLECTION = None
    return _COLLECTION


def _load_rules() -> list[dict]:
    """加载所有默认规则（进程级缓存）.

    改用 ``rules/loader.py::load_default_rules()`` 遍历 rules/ 目录下
    所有 ``*.json`` 文件（default_rules.json + process_enhancement_rules.json
    + seed_rules_process.json + default_attack_chain.json + revoked_ca.json），
    解决此前仅加载 default_rules.json（102条）遗漏 33 条的问题。
    """
    global _RULES_CACHE
    if _RULES_CACHE:
        return _RULES_CACHE

    try:
        from app.rules.loader import load_default_rules

        _RULES_CACHE = load_default_rules()
        logger.info("Loaded %d rules from all rules/*.json files", len(_RULES_CACHE))
    except Exception as exc:
        logger.warning("Failed to load rules via loader.load_default_rules(): %s", exc)
        _RULES_CACHE = []
    return _RULES_CACHE


def _load_c2_signatures() -> list[str]:
    """加载 C2 框架特征签名（进程级缓存）."""
    global _C2_SIGNATURES_CACHE
    if _C2_SIGNATURES_CACHE:
        return _C2_SIGNATURES_CACHE

    try:
        from app.rules.rule_engine import _C2_FRAMEWORK_SIGNATURES

        _C2_SIGNATURES_CACHE = list(_C2_FRAMEWORK_SIGNATURES)
    except ImportError as e:
        logger.warning("Failed to load C2 signatures: %s", e)
        _C2_SIGNATURES_CACHE = []
    return _C2_SIGNATURES_CACHE


# ============================================================================
# 种子数据加载
# ============================================================================


def _load_seed_data() -> list[dict]:
    """加载内置种子知识数据 + 已批准的知识草稿（进程级缓存）.

    合并来源：
    - knowledge_seed.ALL_SEED_KNOWLEDGE（MITRE_TECHNIQUES + C2_FRAMEWORKS + MALWARE_PATTERNS）
    - knowledge_drafts 表中 status='approved' 的条目

    Returns:
        合并后的种子知识列表.
    """
    global _SEED_CACHE
    if _SEED_CACHE:
        return _SEED_CACHE

    try:
        from app.data.knowledge_seed import ALL_SEED_KNOWLEDGE

        _SEED_CACHE = list(ALL_SEED_KNOWLEDGE)
        logger.info("Loaded %d hardcoded seed knowledge items", len(_SEED_CACHE))
    except ImportError as exc:
        logger.warning("Failed to load knowledge_seed: %s", exc)
        _SEED_CACHE = []

    # ── 加载已批准的知识草稿作为额外种子源 ──
    try:
        from app.models.knowledge_draft import KnowledgeDraft

        approved_drafts = KnowledgeDraft.get_as_seed_entries()
        if approved_drafts:
            _SEED_CACHE.extend(approved_drafts)
            logger.info(
                "Loaded %d approved draft(s) as additional seed knowledge",
                len(approved_drafts),
            )
    except Exception as exc:
        logger.warning("Failed to load approved drafts as seed data: %s", exc)

    return _SEED_CACHE


# ============================================================================
# 向量索引构建
# ============================================================================


def _build_index() -> bool:
    """构建向量索引（幂等：已有记录则跳过）.

    从 default_rules.json 提取规则名 + 描述，通过 sentence-transformers
    编码为向量，存入 ChromaDB collection。

    Returns:
        True 表示索引可用（已构建或已存在），False 表示构建失败。
    """
    collection = _get_collection()
    model = _get_embedding_model()

    if collection is None or model is None:
        logger.warning(
            "_build_index: collection=%s model=%s — skipping",
            collection is not None,
            model is not None,
        )
        return False

    # ---------- 幂等检查 ----------
    if collection.count() > 0:
        logger.info("Index already built: %d records exist in '%s'",
                     collection.count(), COLLECTION_NAME)
        return True

    rules = _load_rules()
    if not rules:
        logger.warning("No rules to index — default_rules.json is empty")
        return True  # 不算失败，只是空索引

    # ---------- 准备数据 ----------
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []

    for i, rule in enumerate(rules):
        name: str = (rule.get("name") or "").strip()
        desc: str = (rule.get("description") or "").strip()
        severity: str = rule.get("severity", "medium")
        category: str = rule.get("category", "")

        if not name:
            continue

        doc_id: str = f"rule_{i}_{name}"
        # 文档文本 = 规则名 + 描述，让 embedding 编码完整语义
        doc_text: str = f"{name}: {desc}"

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({
            "rule_name": name,
            "severity": severity,
            "category": category,
        })

    if not ids:
        logger.warning("No valid rules with names to index")
        return True

    # ---------- 批量编码 ----------
    try:
        embeddings = model.encode(
            documents,
            show_progress_bar=False,
            normalize_embeddings=True,  # cosine 距离下建议归一化
        ).tolist()
    except Exception as exc:
        logger.error("Embedding encoding failed: %s", exc)
        return False

    # ---------- 写入 ChromaDB ----------
    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info("Built vector index: %d rules indexed into '%s'",
                     len(ids), COLLECTION_NAME)
        return True
    except Exception as exc:
        logger.error("ChromaDB add failed: %s", exc)
        return False


def _seed_or_draft_exists(collection: Any) -> bool:
    """判断集合里是否已存在种子/草稿向量（按 source 元数据精确判定）.

    替代原先的 `collection.count() > 0` 早退逻辑：规则(rule_*) 的存在
    不应阻止种子知识(真正的攻防 KB)与已批准草稿写入向量库。
    """
    try:
        existing = collection.get(
            where={"source": {"$in": ["seed", "draft"]}},
            limit=1,
        )
        return bool(existing and existing.get("ids"))
    except Exception as exc:  # pragma: no cover - 探测失败不算错误
        logger.debug("Probe seed/draft existence failed: %s", exc)
        return False


def _build_seed_index() -> bool:
    """将内置种子知识数据 + 已批准草稿索引到 ChromaDB.

    种子条目使用 `seed_` 前缀 ID，已批准草稿使用 `draft_` 前缀 ID（与
    models.knowledge_draft.get_as_seed_entries 返回的 id 一致）。每条都会
    打上 source 元数据（seed / draft）以便精确判定是否已索引。

    幂等：仅当集合里确实不存在种子/草稿向量时才 upsert 进去，
    不再用 collection.count() > 0（规则 rule_* 的存在会误判早退）。

    Returns:
        True 表示索引成功或已存在，False 表示构建失败。
    """
    global _SEED_INDEXED

    collection = _get_collection()
    model = _get_embedding_model()

    if collection is None or model is None:
        logger.info("_build_seed_index: collection or model unavailable, skip")
        return False

    # 幂等检查：按 source 元数据精确判断种子/草稿是否已写入，
    # 不再依赖 collection.count() > 0（规则 rule_* 的存在会误判早退）。
    if _seed_or_draft_exists(collection):
        _SEED_INDEXED = True
        return True

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []

    # ── 1) 内置种子知识（ALL_SEED_KNOWLEDGE：MITRE/C2/Malware 共 10 条）──
    try:
        from app.data.knowledge_seed import ALL_SEED_KNOWLEDGE

        seed_knowledge = list(ALL_SEED_KNOWLEDGE)
        logger.info("Loaded %d hardcoded seed knowledge items", len(seed_knowledge))
    except ImportError as exc:
        logger.warning("Failed to load knowledge_seed: %s", exc)
        seed_knowledge = []

    for i, seed in enumerate(seed_knowledge):
        name: str = (seed.get("name") or "").strip()
        desc: str = (seed.get("description") or "").strip()
        severity: str = seed.get("severity", "medium")
        category: str = seed.get("category", "")
        seed_id: str = seed.get("id", "")

        if not name:
            continue

        doc_id: str = f"seed_{i}_{seed_id or name}"
        doc_text: str = f"{name}: {desc}"

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({
            "rule_name": name,
            "severity": severity,
            "category": category,
            "source": "seed",
        })

    # ── 2) 已批准草稿（draft_<id> 前缀）──
    try:
        from app.models.knowledge_draft import KnowledgeDraft

        approved_drafts = KnowledgeDraft.get_as_seed_entries()
        if approved_drafts:
            logger.info(
                "Loaded %d approved draft(s) as additional seed knowledge",
                len(approved_drafts),
            )
    except Exception as exc:
        logger.warning("Failed to load approved drafts as seed data: %s", exc)
        approved_drafts = []

    for draft in approved_drafts:
        name: str = (draft.get("name") or draft.get("title") or "").strip()
        desc: str = (draft.get("description") or "").strip()
        severity: str = draft.get("severity", "medium")
        category: str = draft.get("category", "")
        draft_id: str = draft.get("id", "")

        if not name:
            continue

        # get_as_seed_entries 返回的 id 形如 "draft_<numeric_id>"
        doc_id: str = draft_id if draft_id else f"draft_{name}"
        doc_text: str = f"{name}: {desc}"

        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append({
            "rule_name": name,
            "severity": severity,
            "category": category,
            "source": "draft",
        })

    if not ids:
        # 没有任何种子/草稿可索引时也视为已完成，避免反复尝试
        logger.info("No seed data to index")
        _SEED_INDEXED = True
        return True

    # 批量编码
    try:
        embeddings = model.encode(
            documents,
            show_progress_bar=False,
            normalize_embeddings=True,
        ).tolist()
    except Exception as exc:
        logger.error("Seed embedding encoding failed: %s", exc)
        return False

    # 写入 ChromaDB
    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        _SEED_INDEXED = True
        logger.info(
            "Built seed index: %d knowledge items indexed into '%s'",
            len(ids), COLLECTION_NAME,
        )
        return True
    except Exception as exc:
        logger.error("ChromaDB seed add failed: %s", exc)
        return False


# ============================================================================
# 查询文本构建
# ============================================================================


def _build_query_text(analysis_data: dict) -> str:
    """从分层分析数据构建语义查询文本.

    提取进程名、外连地址、IOC、持久化痕迹等关键字段，
    拼接为自然语言查询串供 embedding 编码。

    Args:
        analysis_data: PromptBuilder 组装的 tiered_data 字典。

    Returns:
        查询文本字符串。
    """
    parts: list[str] = []

    # ---- 主机基本信息 ----
    host_basic = analysis_data.get("host_basic", {})
    if isinstance(host_basic, dict):
        hostname = host_basic.get("hostname", "")
        ip_addr = host_basic.get("ip_address", "")
        os_info = host_basic.get("os_type", "")
        if hostname:
            parts.append(f"主机: {hostname}")
        if ip_addr:
            parts.append(f"IP: {ip_addr}")
        if os_info:
            parts.append(f"系统: {os_info}")

    # ---- 分析结果摘要 ----
    ar = analysis_data.get("analysis_result", {})
    if isinstance(ar, dict):
        risk_level = ar.get("risk_level", "")
        summary = ar.get("summary", "")
        if risk_level:
            parts.append(f"风险等级: {risk_level}")
        if summary:
            parts.append(f"分析摘要: {summary}")

    # ---- 异常进程（提取名称、命令行、原因） ----
    for proc_key in (
        "abnormal_processes_high",
        "abnormal_processes_medium",
        "abnormal_processes_low",
    ):
        for proc in analysis_data.get(proc_key, []):
            if not isinstance(proc, dict):
                continue
            name = proc.get("name", "") or proc.get("process_name", "")
            cmd = proc.get("cmd", "") or proc.get("command_line", "")
            reason = proc.get("reason", "")
            path = proc.get("path", "") or proc.get("process_path", "")
            if name:
                parts.append(f"异常进程: {name}")
            if cmd:
                parts.append(f"命令行: {cmd[:300]}")
            if reason:
                parts.append(f"触发原因: {reason}")
            if path:
                parts.append(f"路径: {path}")

    # ---- 可疑外连 ----
    for conn_key in (
        "suspicious_connections_high",
        "suspicious_connections_medium",
        "suspicious_connections_low",
    ):
        for conn in analysis_data.get(conn_key, []):
            if not isinstance(conn, dict):
                continue
            remote = conn.get("remote", "")
            protocol = conn.get("protocol", "")
            proc_name = conn.get("process", "") or conn.get("process_name", "")
            reason = conn.get("reason", "")
            if remote:
                parts.append(f"可疑外连: {remote} ({protocol})")
            if proc_name:
                parts.append(f"外连进程: {proc_name}")
            if reason:
                parts.append(f"外连原因: {reason}")

    # ---- IOC 命中 ----
    for ioc_key in ("ioc_hits_high", "ioc_hits_medium", "ioc_hits_low"):
        for ioc in analysis_data.get(ioc_key, []):
            if not isinstance(ioc, dict):
                continue
            ioc_type = ioc.get("type", "")
            value = ioc.get("value", "")
            matched_in = ioc.get("matched_in", "")
            context = ioc.get("context", "")
            parts.append(
                f"IOC命中: {ioc_type}|{value}|{matched_in}|{context}".strip("|")
            )

    # ---- 可疑持久化 ----
    for pers in analysis_data.get("persistence_suspicious", []):
        if not isinstance(pers, dict):
            continue
        ptype = pers.get("type", "")
        pname = pers.get("name", "")
        reason = pers.get("reason", "")
        location = pers.get("location", "")
        cmd = pers.get("command", "")
        items = [s for s in (ptype, pname, location, cmd) if s]
        if items:
            parts.append(f"持久化痕迹: {' | '.join(items)}")
        if reason:
            parts.append(f"持久化原因: {reason}")

    # ---- 时间线关键事件 ----
    for tl_key in ("timeline_high", "timeline_medium"):
        for event in analysis_data.get(tl_key, []):
            if not isinstance(event, dict):
                continue
            event_type = event.get("type", "")
            desc = event.get("desc", "")
            if event_type or desc:
                parts.append(f"时间线事件: {event_type} {desc}".strip())

    # ---- 去重后拼接 ----
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    query = "。".join(deduped)
    if not query:
        query = "无异常数据"

    # 查询文本截断：sentence-transformers 的 max_seq_length 默认 256 tokens，
    # 512 字符是保守上限，超长查询文本不仅浪费编码资源还会降低检索精度。
    MAX_QUERY_CHARS: int = 512
    if len(query) > MAX_QUERY_CHARS:
        query = query[:MAX_QUERY_CHARS]
        logger.debug("Query text truncated to %d chars", MAX_QUERY_CHARS)

    logger.debug("Query text: %d chars", len(query))
    return query


# ============================================================================
# 关键词提取（回退策略用）
# ============================================================================


def _extract_keywords_from_text(text: str) -> set[str]:
    """从纯文本中提取关键词（用于回退策略）."""
    keywords: set[str] = set()
    for word in text.lower().split():
        word = word.strip(".,;:'\"!@#$%^&*()-=_+[]{}|\\/<>?`~")
        if len(word) >= 2:
            keywords.add(word)
    return keywords


def _extract_keywords(data: dict) -> set[str]:
    """从分析数据中提取关键词（用于回退策略，兼容旧 API）.

    遍历 dict 的所有值（递归展平），提取可作为匹配关键词的文本。
    """
    keywords: set[str] = set()

    def _recurse(obj: Any) -> None:
        if isinstance(obj, str):
            for word in obj.lower().split():
                word = word.strip(".,;:'\"!@#$%^&*()-=_+[]{}|\\/<>?`~")
                if len(word) >= 2:
                    keywords.add(word)
        elif isinstance(obj, dict):
            for v in obj.values():
                _recurse(v)
        elif isinstance(obj, list):
            for item in obj[:50]:
                _recurse(item)

    _recurse(data)
    return keywords


def _derive_entry_type(entry_ref: Optional[str]) -> str:
    """根据 entry_ref 前缀派生 entry_type（与前端 parseEntryRef 逻辑一致）.

    约定：
    - seed_*  → seed   （内置种子知识，entry_ref 形如 seed_{i}_{mitre_id}）
    - draft_* → draft  （已批准 AI 建议草稿，entry_ref 形如 draft_{numeric_id}）
    - rule_*  → rule   （规则引擎命中，entry_ref 形如 rule_{i}_{name}）
    - 其它 / 缺失 → unknown（前端按不可点击纯文本降级）

    Args:
        entry_ref: chroma 文档 ID 或等效引用字符串。

    Returns:
        entry_type 字符串。
    """
    if not entry_ref:
        return "unknown"
    prefix = entry_ref.split("_", 1)[0]
    if prefix in ("seed", "draft", "rule"):
        return prefix
    return "unknown"


# ============================================================================
# KnowledgeRetriever
# ============================================================================


class KnowledgeRetriever:
    """知识库检索器.

    从规则库和 C2 签名中检索与当前分析数据相关的安全知识。

    检索策略（优先级降序）：
    1. ChromaDB 向量语义检索（sentence-transformers 编码）
    2. 关键词匹配回退（当 ChromaDB 或 embedding 模型不可用时）

    API 签名保持兼容，同时支持结构化证据输出。
    """

    _index_initialized: bool = False

    @classmethod
    def _ensure_index(cls) -> None:
        """延迟初始化向量索引（仅执行一次）."""
        if cls._index_initialized:
            return
        cls._index_initialized = True

        if _CHROMA_AVAILABLE and _EMBEDDING_AVAILABLE:
            ok = _build_index()
            if ok:
                logger.info("Vector index ready for semantic retrieval")
            else:
                logger.warning("Vector index build failed, will fall back to keyword")
            # 无论 _build_index 结果如何，均尝试种子数据索引
            _build_seed_index()
        else:
            logger.info(
                "Vector retrieval unavailable (chroma=%s, embedding=%s), "
                "using keyword fallback",
                _CHROMA_AVAILABLE,
                _EMBEDDING_AVAILABLE,
            )
        # 预加载种子数据供关键词回退使用
        _load_seed_data()

    @classmethod
    def rebuild_seed_index(cls) -> bool:
        """重建种子索引（批准知识草稿后调用）.

        清空进程级缓存并重新加载种子数据（含已批准草稿），
        然后重建 ChromaDB 种子索引。

        Returns:
            True 表示重建成功，False 表示跳过或失败.
        """
        global _SEED_CACHE, _SEED_INDEXED

        # 清空缓存，强制重新加载（含已批准草稿）
        _SEED_CACHE = []
        _SEED_INDEXED = False

        # 重新加载种子数据
        _load_seed_data()

        # 如果 ChromaDB 可用，删除旧种子条目并重建
        collection = _get_collection()
        if collection is not None and _EMBEDDING_AVAILABLE:
            try:
                # 删除所有 seed_ 前缀的旧条目
                existing_ids = collection.get()
                if existing_ids and existing_ids.get("ids"):
                    seed_ids = [
                        rid for rid in existing_ids["ids"]
                        if rid.startswith("seed_") or rid.startswith("draft_")
                    ]
                    if seed_ids:
                        collection.delete(ids=seed_ids)
                        logger.info(
                            "Deleted %d old seed/draft entries from ChromaDB", len(seed_ids),
                        )
            except Exception as exc:
                logger.warning("Failed to delete old seed entries: %s", exc)

            result = _build_seed_index()
            logger.info("Seed index rebuild: %s", "success" if result else "failed")
            return result
        else:
            logger.info(
                "Seed index rebuild skipped (collection=%s, embedding=%s)",
                collection is not None, _EMBEDDING_AVAILABLE,
            )
            return False

    # ========================================================================
    # Public API
    # ========================================================================

    @staticmethod
    def retrieve(
        analysis_data: dict,
        limit: int = 5,
        structured: bool = False,
    ) -> list[Any]:
        """检索匹配的规则描述.

        Args:
            analysis_data: 主机分析数据字典（PromptBuilder 组装的结构化数据）。
            limit: 最多返回的规则描述条数。
            structured: 为 True 时返回结构化证据项；否则返回兼容旧调用方的字符串列表。

        Returns:
            匹配规则描述列表（按相似度/匹配度排序，最多 limit 条）。
        """
        KnowledgeRetriever._ensure_index()

        collection = _get_collection()
        model = _get_embedding_model()

        if collection is not None and model is not None and collection.count() > 0:
            results = KnowledgeRetriever._vector_retrieve(
                analysis_data, limit, collection, model, structured=structured
            )
        else:
            logger.info(
                "Falling back to keyword matching "
                "(collection_ok=%s, model_ok=%s, count=%d)",
                collection is not None,
                model is not None,
                collection.count() if collection is not None else 0,
            )
            results = KnowledgeRetriever._keyword_retrieve(
                analysis_data, limit, structured=structured
            )

        if structured:
            return results
        return [item if isinstance(item, str) else item.get("formatted_text", "") for item in results]

    # ========================================================================
    # 向量检索
    # ========================================================================

    @staticmethod
    def _vector_retrieve(
        analysis_data: dict,
        limit: int,
        collection: Any,
        model: Any,
        structured: bool = False,
    ) -> list[Any]:
        """向量语义检索.

        1. 从 analysis_data 构建查询文本 → embedding
        2. ChromaDB query 返回 Top-K
        3. 相似度阈值过滤 + 去重
        4. 格式化输出

        Args:
            analysis_data: 分析数据字典。
            limit: 最大返回数。
            collection: ChromaDB collection。
            model: SentenceTransformer 模型。

        Returns:
            格式化规则描述列表。
        """
        # ---- Step 0: 构建查询文本 ----
        query_text = _build_query_text(analysis_data)
        if not query_text or query_text == "无异常数据":
            logger.info("Empty query text, returning empty results")
            return []

        # ---- Step 1: 编码查询 ----
        try:
            query_embedding = model.encode(
                [query_text],
                show_progress_bar=False,
                normalize_embeddings=True,
            ).tolist()
        except Exception as exc:
            logger.error("Query encoding failed: %s, falling back to keyword", exc)
            return KnowledgeRetriever._keyword_retrieve(analysis_data, limit)

        # ---- Step 2: ChromaDB 查询 ----
        n_fetch = min(limit * 3, collection.count())  # 多取一些做过滤
        try:
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=n_fetch,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.error("ChromaDB query failed: %s, falling back to keyword", exc)
            return KnowledgeRetriever._keyword_retrieve(analysis_data, limit)

        if not results or not results.get("ids") or not results["ids"][0]:
            logger.info("No vector matches found for query")
            return []

        # ---- Step 3: 过滤 + 格式化 ----
        ids_list: list[str] = results["ids"][0]
        metadatas_list: list[dict] = results.get("metadatas", [[]])[0]
        distances_list: list[float] = results.get("distances", [[]])[0]

        rules = _load_rules()
        rules_by_name: dict[str, dict] = {
            r.get("name", ""): r for r in rules
        }

        formatted: list[Any] = []
        seen: set[str] = set()

        for i, doc_id in enumerate(ids_list):
            meta = metadatas_list[i] if i < len(metadatas_list) else {}
            distance = distances_list[i] if i < len(distances_list) else 1.0

            # 相似度阈值过滤
            if distance > VECTOR_DISTANCE_THRESHOLD:
                logger.debug("Skipping '%s': distance=%.3f > threshold", doc_id, distance)
                continue

            rule_name = meta.get("rule_name", "")
            severity = meta.get("severity", "medium")
            category = meta.get("category", "")

            # 从规则缓存获取完整描述
            rule = rules_by_name.get(rule_name, {})
            rule_desc = rule.get("description", "")
            formatted_text = f"[{category}/{severity}] {rule_name}: {rule_desc}"
            if formatted_text in seen:
                continue

            seen.add(formatted_text)
            if structured:
                confidence = "high" if distance <= 0.35 else "medium"
                formatted.append(
                    {
                        "source": "vector",
                        "rule_name": rule_name,
                        "title": rule_name,
                        "severity": severity,
                        "category": category,
                        "description": rule_desc,
                        "summary": rule_desc,
                        "formatted_text": formatted_text,
                        "score": round(max(0.0, 1.0 - distance), 4),
                        "confidence": confidence,
                        "match_reason": "语义相似检索命中",
                        "tags": [category, severity],
                        "evidence_text": formatted_text,
                        # ── 证据可点击溯源：entry_ref = chroma 文档 ID 本身 ──
                        "entry_ref": doc_id,
                        "entry_type": _derive_entry_type(doc_id),
                    }
                )
            else:
                formatted.append(formatted_text)

            if len(formatted) >= limit:
                break

        logger.info(
            "VectorRetriever: fetched=%d, after_filter=%d, returned=%d "
            "(threshold=%.2f)",
            len(ids_list), len(formatted), min(len(formatted), limit),
            VECTOR_DISTANCE_THRESHOLD,
        )
        return formatted

    # ========================================================================
    # 关键词匹配回退
    # ========================================================================

    @staticmethod
    def _keyword_retrieve(
        analysis_data: dict,
        limit: int = 5,
        structured: bool = False,
    ) -> list[Any]:
        """关键词匹配回退策略（保留原实现）.

        匹配策略：
        1. 规则名精确命中：analysis_data 中任意字段值包含规则名关键词
        2. 规则描述关键词命中 ≥2：描述中的词在 data keywords 中出现 ≥2 个
        3. C2 签名命中

        Args:
            analysis_data: 分析数据字典。
            limit: 最大返回数。

        Returns:
            格式化规则描述列表。
        """
        rules = _load_rules()
        c2_sigs = _load_c2_signatures()
        seeds = _load_seed_data()
        keywords = _extract_keywords(analysis_data)

        if not rules and not c2_sigs and not seeds:
            return []

        # 四元组：(score, text, src_type, entry_ref)
        # - src_type: 来源类型（rule/seed/draft/c2），用于分类
        # - entry_ref: chroma 文档 ID（seed_*/draft_*/rule_*），C2 签名为 None
        scored: list[tuple[float, str, str, Optional[str]]] = []

        # ── 规则匹配 ──
        # i 为 enumerate(rules) 索引，须与 _build_index 中 rule_{i}_{name} 的 i 同序
        for i, rule in enumerate(rules):
            rule_name = rule.get("name", "")
            rule_desc = rule.get("description", "")
            rule_category = rule.get("category", "")
            rule_severity = rule.get("severity", "medium")

            name_parts = set(rule_name.lower().replace("_", " ").split())
            desc_words = set(rule_desc.lower().split())

            name_hits = len(name_parts & keywords)
            exact_name_hit = any(
                name_part in " ".join(keywords) for name_part in name_parts
            )

            desc_hits = len(desc_words & keywords)

            score: float = 0.0
            if exact_name_hit and name_hits >= 1:
                score += 3.0
            if desc_hits >= 2:
                score += 1.5
            elif desc_hits >= 1:
                score += 0.5

            sev_bonus: dict[str, float] = {
                "critical": 2.0,
                "high": 1.0,
                "medium": 0.5,
                "low": 0.2,
            }
            score += sev_bonus.get(rule_severity, 0.0)

            if score > 0:
                formatted_rule = (
                    f"[{rule_category}/{rule_severity}] {rule_name}: {rule_desc}"
                )
                scored.append((score, formatted_rule, "rule", f"rule_{i}_{rule_name}"))

        # ── 种子知识匹配 ──
        # i 为 enumerate(seeds) 索引：内置种子恒为前 10 条（i=0..9），
        # 已批准草稿（id 形如 draft_<n>）追加在尾部，二者顺序与 _build_seed_index 一致。
        for i, seed in enumerate(seeds):
            seed_name = seed.get("name", "")
            seed_desc = seed.get("description", "")
            seed_category = seed.get("category", "knowledge")
            seed_severity = seed.get("severity", "medium")
            seed_pattern = seed.get("pattern", "")

            # 区分内置种子（seed.get("id") 为 MITRE ID）与已批准草稿（id 形如 draft_<n>）
            seed_id = seed.get("id", "")
            if seed_id.startswith("draft_"):
                # 来自 get_as_seed_entries，entry_ref 直接复用 draft_{numeric_id}
                seed_entry_ref: Optional[str] = seed_id
                seed_entry_type = "draft"
            else:
                # 纯种子：seed_{i}_{mitre_id}，i 与 _build_seed_index 同序
                seed_entry_ref = f"seed_{i}_{seed_id}" if seed_id else None
                seed_entry_type = "seed"

            name_parts = set(seed_name.lower().replace("_", " ").split())
            desc_words = set(seed_desc.lower().split())
            pat_words = set(seed_pattern.lower().split())

            name_hits = len(name_parts & keywords)
            exact_name_hit = any(
                name_part in " ".join(keywords) for name_part in name_parts
            )

            desc_hits = len(desc_words & keywords)
            # 额外匹配 pattern 中的关键词（如"beacon""meterpreter"等技术术语）
            pat_hits = len(pat_words & keywords)

            score: float = 0.0
            if exact_name_hit and name_hits >= 1:
                score += 3.0
            if desc_hits >= 2:
                score += 1.5
            elif desc_hits >= 1:
                score += 0.5
            # pattern 命中额外加分
            if pat_hits >= 2:
                score += 1.0
            elif pat_hits >= 1:
                score += 0.3

            sev_bonus: dict[str, float] = {
                "critical": 2.0,
                "high": 1.0,
                "medium": 0.5,
                "low": 0.2,
            }
            score += sev_bonus.get(seed_severity, 0.0)

            if score > 0:
                formatted_seed = (
                    f"[{seed_category}/{seed_severity}] {seed_name}: {seed_desc}"
                )
                scored.append((score, formatted_seed, seed_entry_type, seed_entry_ref))

        # ── C2 签名匹配 ──
        for sig in c2_sigs:
            if sig.lower() in " ".join(keywords):
                scored.append(
                    (3.0, f"[network/critical] C2 框架特征: {sig}", "c2", None)
                )

        scored.sort(key=lambda x: x[0], reverse=True)

        seen: set[str] = set()
        results: list[Any] = []
        for score, text, src_type, entry_ref in scored:
            if text in seen:
                continue
            seen.add(text)
            if structured:
                title = text.split(":", 1)[0].strip()
                summary = text.split(":", 1)[1].strip() if ":" in text else text
                parts = title.strip("[]").split("] ")
                category = "general"
                severity = "medium"
                rule_name = title
                if len(parts) == 2 and "/" in parts[0]:
                    category, severity = parts[0].split("/", 1)
                    rule_name = parts[1]
                result = {
                    "source": "keyword",
                    "rule_name": rule_name,
                    "title": rule_name,
                    "severity": severity,
                    "category": category,
                    "description": summary,
                    "summary": summary,
                    "formatted_text": text,
                    "score": round(score, 4),
                    "confidence": "medium" if score < 4 else "high",
                    "match_reason": "关键词匹配回退命中",
                    "tags": [category, severity],
                    "evidence_text": text,
                }
                # 仅当 entry_ref 非空时注入（C2 签名分支为 None，前端按纯文本渲染）
                if entry_ref:
                    result["entry_ref"] = entry_ref
                    result["entry_type"] = _derive_entry_type(entry_ref)
                results.append(result)
            else:
                results.append(text)
            if len(results) >= limit:
                break

        logger.info(
            "KeywordRetriever (fallback): matched %d rules from %d total (limit=%d)",
            len(results), len(rules), limit,
        )
        return results
