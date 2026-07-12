"""知识草稿 API — 管理员审核 AI 自动生成的知识条目.

提供草稿列表查询、批准（自动入库 ChromaDB）、拒绝接口。
批准时触发 ChromaDB 种子索引的重建，将已批准条目纳入向量检索。

P0-P3 完整功能：
- 侧边栏知识库与主机Tab审核
- 手动导入（格式校验 + 三元组去重）
- 第三方同步（virustotal / abuseipdb / alienvault_otx）
- 批量操作（批量批准/拒绝）与撤回机制
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.data.knowledge_seed import ALL_SEED_KNOWLEDGE
from app.models.knowledge_draft import KnowledgeDraft
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 请求模型 ────────────────────────────────────────────────────────

class ImportItem(BaseModel):
    """单条导入条目."""
    title: str = Field(..., min_length=1, description="标题（必填）")
    description: str = Field(..., min_length=1, description="描述（必填）")
    category: str = Field(default="auto", description="分类")
    severity: str = Field(default="medium", description="严重程度")
    mitre_attack: Optional[str] = Field(default=None, description="MITRE 技术编号")
    pattern: Optional[str] = Field(default=None, description="检测关键词")
    source: str = Field(default="manual", description="来源标记")


class ImportRequest(BaseModel):
    """导入请求体."""
    items: list[ImportItem] = Field(default_factory=list, description="结构化条目列表")
    text: Optional[str] = Field(default=None, description="IOC 文本列表（自由文本导入）")


class BatchRequest(BaseModel):
    """批量操作请求体."""
    ids: list[int] = Field(..., min_length=1, description="草稿 ID 列表")
    action: str = Field(..., pattern=r"^(approve|reject)$", description="操作：approve | reject")


class SyncRequest(BaseModel):
    """同步请求体（可选参数）."""
    limit: int = Field(default=50, ge=1, le=500, description="最大同步条目数")


# ── 辅助函数 ────────────────────────────────────────────────────────

def _parse_text_items(text: str) -> list[dict]:
    """从自由文本中解析 IOC 列表条目.

    支持格式：
      - 每行一个"标题：描述"（中文冒号）
      - 每行一个"标题: 描述"（英文冒号）
      - 纯标题行（无冒号，description 与 title 相同）
    """
    items: list[dict] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "：" in line:
            parts = line.split("：", 1)
        elif ":" in line:
            parts = line.split(":", 1)
        else:
            items.append({"title": line, "description": line, "category": "auto"})
            continue
        title = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else title
        if title:
            items.append({"title": title, "description": desc or title, "category": "auto"})
    return items


def _auto_approve(draft: dict) -> bool:
    """自动审核规则（Phase 2 — 任务10）.

    判定逻辑：
    - source="rule_import" AND severity in ("critical","high") → 自动批准
    - source in ("virustotal","abuseipdb","alienvault_otx") AND ioc 恶意数 > 5 → 自动批准
    - source="rule_import" AND severity="medium" → status=pending（需人工）
    - 其余：status=pending
    """
    source = (draft.get("source") or "").lower()
    severity = (draft.get("severity") or "medium").lower()

    # 条件1：规则导入且高危/严重 → 自动批准
    if source == "rule_import" and severity in ("critical", "high"):
        return True

    # 条件2：第三方 provider IOC 且恶意数 > 5（raw_ioc 含恶意判定信息）
    if source in ("virustotal", "abuseipdb", "alienvault_otx"):
        raw_ioc = draft.get("raw_ioc")
        if raw_ioc:
            try:
                ioc_data = json.loads(raw_ioc) if isinstance(raw_ioc, str) else raw_ioc
                malicious_count = ioc_data.get("malicious_count", 0)
                if malicious_count > 5:
                    return True
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

    # 条件3：rule_import + medium → 需人工审核
    # 其余：status=pending
    return False


# ── 端点 ────────────────────────────────────────────────────────────

@router.get("/drafts")
def list_drafts(
    status: Optional[str] = Query(None, description="按状态过滤：pending/approved/rejected"),
    host_id: Optional[str] = Query(None, description="按主机 ID 过滤"),
    current_user: dict = Depends(get_current_user),
):
    """获取所有知识草稿列表，支持按状态和主机过滤.

    - 不传 status 返回全部
    - status=pending 返回待审核
    - status=approved 返回已批准
    - status=rejected 返回已拒绝
    - host_id 按来源主机过滤
    """
    if status and status not in ("pending", "approved", "rejected"):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 status 值 '{status}'，有效值：pending / approved / rejected",
        )

    drafts = KnowledgeDraft.get_all(status=status, host_id=host_id)
    return {"code": 0, "data": drafts, "message": "success"}


@router.get("/seeds")
def list_seeds(current_user: dict = Depends(get_current_user)):
    """获取内置种子知识数据（10 条 MITRE/C2/Malware）.

    返回 MITRE_TECHNIQUES（5）、C2_FRAMEWORKS（3）、MALWARE_PATTERNS（2）共 10 条。
    """
    return {
        "code": 0,
        "data": ALL_SEED_KNOWLEDGE,
        "message": f"共 {len(ALL_SEED_KNOWLEDGE)} 条种子数据",
    }


@router.get("/drafts/{draft_id}")
def get_draft_detail(draft_id: int, current_user: dict = Depends(get_current_user)):
    """获取单条知识草稿详情（供证据溯源跳转）.

    纯透传封装 KnowledgeDraft.get_by_id。
    草稿不存在时返回 404（FastAPI HTTPException），前端 axios 以 HTTP 错误
    进入 catch 分支，渲染「该知识条目已不存在（可能已被拒绝/撤回）」空态。

    注意：路径 `/drafts/{draft_id}` 与既有 `POST /drafts/{draft_id}/approve`
    等方法不冲突（GET vs POST + 子路径），无需调整路由注册顺序。
    """
    draft = KnowledgeDraft.get_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail=f"知识草稿 {draft_id} 不存在")
    return {"code": 0, "data": draft, "message": "success"}


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, current_user: dict = Depends(get_current_user)):
    """批准知识草稿.

    批准后：
    1. 将草稿 status 更新为 'approved'
    2. 已批准的草稿在下次 ChromaDB 种子索引重建时自动纳入向量检索
    """
    try:
        draft = KnowledgeDraft.approve(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 批准后触发种子索引重建，将已批准条目纳入 ChromaDB 向量检索
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever

        KnowledgeRetriever.rebuild_seed_index()
    except Exception as exc:
        logger.warning("批准后重建种子索引失败（不影响批准操作）: %s", exc)

    return {"code": 0, "data": draft, "message": "草稿已批准并入库"}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: int, current_user: dict = Depends(get_current_user)):
    """拒绝知识草稿.

    将草稿 status 更新为 'rejected'，该条目不会进入知识库。
    拒绝后触发种子索引重建，确保该条目（若曾被批准）的向量从 ChromaDB 移除。
    """
    try:
        draft = KnowledgeDraft.reject(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 拒绝后触发种子索引重建，移除该条目在 ChromaDB 中的向量
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever

        KnowledgeRetriever.rebuild_seed_index()
    except Exception as exc:
        logger.warning("拒绝后重建种子索引失败（不影响拒绝操作）: %s", exc)

    return {"code": 0, "data": draft, "message": "草稿已拒绝"}


@router.post("/drafts/{draft_id}/recall")
def recall_draft(draft_id: int, current_user: dict = Depends(get_current_user)):
    """撤回已批准或已拒绝的草稿，恢复为 pending 状态.

    撤回后 reviewed_at 记录为撤回时间。
    撤回后触发种子索引重建，确保该条目（若曾被批准）的向量从 ChromaDB 移除。
    """
    try:
        draft = KnowledgeDraft.recall(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 撤回后触发种子索引重建，移除该条目在 ChromaDB 中的向量
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever

        KnowledgeRetriever.rebuild_seed_index()
    except Exception as exc:
        logger.warning("撤回后重建种子索引失败（不影响撤回操作）: %s", exc)

    return {"code": 0, "data": draft, "message": "草稿已撤回至待审核"}


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, current_user: dict = Depends(get_current_user)):
    """永久删除知识草稿.

    任何状态的草稿均可删除。
    删除后触发种子索引重建，清除 ChromaDB 中的对应向量。
    """
    success = KnowledgeDraft.delete(draft_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"知识草稿 {draft_id} 不存在")

    # 删除后重建种子索引，确保向量从 ChromaDB 移除
    try:
        from app.services.knowledge_retriever import KnowledgeRetriever

        KnowledgeRetriever.rebuild_seed_index()
    except Exception as exc:
        logger.warning("删除后重建种子索引失败（不影响删除操作）: %s", exc)

    return {"code": 0, "data": None, "message": "草稿已永久删除"}


@router.post("/drafts/batch")
def batch_action(body: BatchRequest, current_user: dict = Depends(get_current_user)):
    """批量批准或拒绝知识草稿.

    Args:
        body: 包含 ids 列表和 action（approve/reject）.

    Returns:
        {"success": N, "failed": M, "errors": [...]} 统计结果.
    """
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    result = KnowledgeDraft.batch_action(body.ids, body.action)

    # 批量批准后触发一次种子索引重建
    if body.action == "approve" and result["success"] > 0:
        try:
            from app.services.knowledge_retriever import KnowledgeRetriever

            KnowledgeRetriever.rebuild_seed_index()
        except Exception as exc:
            logger.warning("批量批准后重建种子索引失败: %s", exc)

    return {"code": 0, "data": result, "message": f"已{body.action} {result['success']} 条"}


@router.post("/import")
def import_knowledge(body: ImportRequest, current_user: dict = Depends(get_current_user)):
    """手动导入知识条目（支持 JSON 条目与自由文本）.

    校验规则：
    - 每条必填 title 和 description，不合格跳过
    - 三元组 (title, category, mitre_attack) 去重检查
    - 导入的条目 status = pending，source = manual

    返回: {"total": N, "imported": M, "skipped": K, "skipped_reasons": [...]}
    """
    items_to_import: list[dict] = []

    # 处理结构化条目
    for item in body.items:
        items_to_import.append({
            "title": item.title.strip(),
            "description": item.description.strip(),
            "category": item.category,
            "severity": item.severity,
            "mitre_attack": item.mitre_attack,
            "pattern": item.pattern,
            "source": item.source,
        })

    # 处理自由文本
    if body.text:
        text_items = _parse_text_items(body.text)
        items_to_import.extend(text_items)

    if not items_to_import:
        raise HTTPException(status_code=400, detail="导入内容不能为空")

    total = len(items_to_import)
    imported = 0
    skipped = 0
    skipped_reasons: list[str] = []

    for item in items_to_import:
        title = item.get("title", "")
        description = item.get("description", "")
        category = item.get("category", "auto")
        severity = item.get("severity", "medium")
        mitre_attack = item.get("mitre_attack")

        # 必填字段校验
        if not title or not description:
            skipped += 1
            skipped_reasons.append(f"必填字段缺失: title='{title}'")
            continue

        # 三元组去重
        if KnowledgeDraft.is_duplicate(title, category, mitre_attack):
            skipped += 1
            skipped_reasons.append(f"duplicate: ({title}, {category}, {mitre_attack or 'N/A'})")
            continue

        try:
            KnowledgeDraft.create(
                title=title,
                description=description,
                category=category,
                severity=severity,
                mitre_attack=mitre_attack,
                pattern=item.get("pattern"),
                source=item.get("source", "manual"),
            )
            imported += 1
        except Exception as exc:
            skipped += 1
            skipped_reasons.append(f"写入失败: {title} — {exc}")

    logger.info("Import result: total=%d, imported=%d, skipped=%d", total, imported, skipped)

    # ── 自动审核（Phase 2）──
    auto_approved = 0
    if imported > 0:
        all_drafts = KnowledgeDraft.get_all(status="pending")
        for draft in all_drafts:
            if _auto_approve(draft):
                try:
                    KnowledgeDraft.approve(draft["id"])
                    auto_approved += 1
                except Exception as exc:
                    logger.warning("自动批准草稿 %d 失败: %s", draft["id"], exc)

    # 自动批准后触发一次种子索引重建
    if auto_approved > 0:
        try:
            from app.services.knowledge_retriever import KnowledgeRetriever

            KnowledgeRetriever.rebuild_seed_index()
        except Exception as exc:
            logger.warning("自动批准后重建种子索引失败: %s", exc)

    return {
        "code": 0,
        "data": {
            "total": total,
            "imported": imported,
            "skipped": skipped,
            "auto_approved": auto_approved,
            "skipped_reasons": skipped_reasons,
        },
        "message": f"导入 {imported} 条待审核知识条目，{skipped} 条跳过，{auto_approved} 条自动批准",
    }


class ValidateRetrievalRequest(BaseModel):
    """向量检索质量自检请求体."""
    queries: list[str] = Field(..., min_length=1, description="待验证的攻击描述列表")


@router.get("/entry")
def get_entry(ref: str = Query(..., description="知识条目引用 ref（如 rule_5_cmd_powershell_chain）"),
              current_user: dict = Depends(get_current_user)):
    """根据 entry_ref 查找知识条目详情.

    查找顺序：
    1. rules 缓存（rule_* 前缀）
    2. 种子知识缓存（seed_* 前缀）
    3. 知识草稿 DB（draft_* 前缀）

    Returns:
        {name, description, severity, category, mitre_attack, source, entry_type}
    """
    if not ref:
        raise HTTPException(status_code=400, detail="ref 参数不能为空")

    prefix = ref.split("_", 1)[0] if "_" in ref else ""

    # 1) rule_* — 从 rules 缓存查找
    if prefix == "rule":
        try:
            from app.rules.loader import load_default_rules
            rules = load_default_rules()
            # ref 格式: rule_{i}_{name}
            parts = ref.split("_", 2)
            if len(parts) >= 3:
                rule_i = parts[1]
                rule_name_key = parts[2]
                # 先按索引查找
                try:
                    idx = int(rule_i)
                    if 0 <= idx < len(rules):
                        rule = rules[idx]
                        return {
                            "code": 0,
                            "data": {
                                "name": rule.get("name", ""),
                                "description": rule.get("description", ""),
                                "severity": rule.get("severity", "medium"),
                                "category": rule.get("category", ""),
                                "mitre_attack": rule.get("mitre_attack", rule.get("mitre", "")),
                                "source": "rule",
                                "entry_type": "rule",
                            },
                            "message": "success",
                        }
                except ValueError:
                    pass
                # 按名称查找
                for rule in rules:
                    if (rule.get("name") or "").strip() == rule_name_key:
                        return {
                            "code": 0,
                            "data": {
                                "name": rule.get("name", ""),
                                "description": rule.get("description", ""),
                                "severity": rule.get("severity", "medium"),
                                "category": rule.get("category", ""),
                                "mitre_attack": rule.get("mitre_attack", rule.get("mitre", "")),
                                "source": "rule",
                                "entry_type": "rule",
                            },
                            "message": "success",
                        }
        except Exception as exc:
            logger.warning("Lookup rule entry '%s' failed: %s", ref, exc)

    # 2) seed_* — 从种子知识缓存查找
    if prefix == "seed":
        try:
            from app.data.knowledge_seed import ALL_SEED_KNOWLEDGE
            # ref 格式: seed_{i}_{mitre_id}
            parts = ref.split("_", 2)
            if len(parts) >= 3:
                seed_i = parts[1]
                try:
                    idx = int(seed_i)
                    seeds = list(ALL_SEED_KNOWLEDGE)
                    if 0 <= idx < len(seeds):
                        seed = seeds[idx]
                        return {
                            "code": 0,
                            "data": {
                                "name": seed.get("name", ""),
                                "description": seed.get("description", ""),
                                "severity": seed.get("severity", "medium"),
                                "category": seed.get("category", ""),
                                "mitre_attack": seed.get("mitre_attack", seed.get("id", "")),
                                "source": "seed",
                                "entry_type": "seed",
                            },
                            "message": "success",
                        }
                except ValueError:
                    pass
        except Exception as exc:
            logger.warning("Lookup seed entry '%s' failed: %s", ref, exc)

    # 3) draft_* — 从 knowledge_drafts DB 查找
    if prefix == "draft":
        try:
            draft_id_str = ref[len("draft_"):]
            draft_id = int(draft_id_str)
            draft = KnowledgeDraft.get_by_id(draft_id)
            if draft:
                return {
                    "code": 0,
                    "data": {
                        "name": draft.get("title", ""),
                        "description": draft.get("description", ""),
                        "severity": draft.get("severity", "medium"),
                        "category": draft.get("category", ""),
                        "mitre_attack": draft.get("mitre_attack", ""),
                        "source": draft.get("source", "draft"),
                        "entry_type": "draft",
                    },
                    "message": "success",
                }
        except (ValueError, Exception) as exc:
            logger.warning("Lookup draft entry '%s' failed: %s", ref, exc)

    raise HTTPException(status_code=404, detail=f"知识条目 '{ref}' 不存在")


@router.post("/validate-retrieval")
def validate_retrieval(
    body: ValidateRetrievalRequest,
    current_user: dict = Depends(get_current_user),
):
    """向量检索质量自检端点（Phase 0 — 新增-①）.

    对每项 query 调用 KnowledgeRetriever.retrieve() 返回 top3 匹配结果及 score，
    用于在模型部署后验证检索质量（人工抽查 10 个典型攻击模式）。

    请求体：
        {"queries": ["Cobalt Strike Beacon HTTP 心跳", "勒索软件 vssadmin 删除卷影", ...]}

    响应：
        {"results": [{"query": "...", "top3": [{"name": "...", "score": 0.85, "confidence": "high"}, ...]}, ...]}

    无向量模型时返回 error=embedding_not_available。
    """
    from app.services.knowledge_retriever import (
        KnowledgeRetriever,
        _get_embedding_model,
    )

    # 检查嵌入模型是否可用
    model = _get_embedding_model()
    if model is None:
        return {
            "code": 1,
            "error": "embedding_not_available",
            "message": "嵌入模型未下载，无法运行向量检索质量自检",
        }

    results: list[dict] = []
    for query in body.queries:
        analysis_data = {
            "host_basic": {},
            "analysis_result": {"risk_level": "medium", "summary": query},
        }
        try:
            hits = KnowledgeRetriever.retrieve(
                analysis_data, limit=3, structured=True
            )
            top3 = []
            for hit in hits[:3]:
                top3.append({
                    "name": hit.get("title", hit.get("rule_name", "")),
                    "score": hit.get("score", 0.0),
                    "confidence": hit.get("confidence", "low"),
                    "category": hit.get("category", ""),
                    "severity": hit.get("severity", ""),
                    "entry_type": hit.get("entry_type", "unknown"),
                })
            results.append({"query": query, "top3": top3})
        except Exception as exc:
            logger.warning("validate-retrieval query '%s' failed: %s", query, exc)
            results.append({"query": query, "top3": [], "error": str(exc)})

    return {
        "code": 0,
        "data": {"results": results},
        "message": f"已验证 {len(body.queries)} 个查询",
    }


@router.post("/sync/{provider}")
def sync_from_provider(
    provider: str,
    body: Optional[SyncRequest] = None,
    current_user: dict = Depends(get_current_user),
):
    """从第三方威胁情报平台同步 IOC 列表到知识草稿区.

    支持的 provider：
    - virustotal: VirusTotal 威胁情报
    - abuseipdb: AbuseIPDB 威胁情报
    - alienvault_otx: AlienVault OTX 威胁情报

    同步结果写入 knowledge_drafts（status=pending, source=external），
    管理员审核后可批准入库。
    """
    valid_providers = ("virustotal", "abuseipdb", "alienvault_otx")
    if provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 provider '{provider}'，有效值：{' / '.join(valid_providers)}",
        )

    limit = body.limit if body else 50

    # 尝试获取 enrichment_service
    try:
        from app.services.enrichment_service import get_enrichment_service

        svc = get_enrichment_service()
    except Exception as exc:
        logger.warning("enrichment_service 不可用: %s", exc)
        return {
            "code": 1,
            "data": None,
            "message": f"provider '{provider}' not configured: {exc}",
        }

    # 通过 enrichment_service 获取 IOC 列表
    try:
        raw_results = svc.fetch_ioc_list(provider=provider, limit=limit)
    except AttributeError:
        logger.warning("enrichment_service 不支持 fetch_ioc_list 方法")
        return {
            "code": 1,
            "data": None,
            "message": f"provider '{provider}' not configured (fetch_ioc_list not available)",
        }
    except Exception as exc:
        logger.exception("同步 provider=%s 失败", provider)
        raise HTTPException(
            status_code=502,
            detail=f"同步 {provider} 失败: {exc}",
        )

    if not raw_results:
        return {
            "code": 0,
            "data": {"provider": provider, "synced": 0, "message": "未获取到 IOC 数据"},
            "message": "未获取到 IOC 数据",
        }

    # 写入 knowledge_drafts
    synced = 0
    for item in raw_results:
        ioc_type = item.get("ioc_type", "")
        ioc_value = item.get("ioc_value", "")
        title = f"{ioc_type.upper()} IOC: {ioc_value}" if ioc_value else item.get("title", "External IOC")
        description = item.get("description", json.dumps(item, ensure_ascii=False))
        category = item.get("category", "auto")
        severity = item.get("severity", "medium")
        mitre_attack = item.get("mitre_attack") or item.get("attck")

        # 去重检查
        if KnowledgeDraft.is_duplicate(title, category, mitre_attack):
            continue

        try:
            KnowledgeDraft.create(
                title=title,
                description=description,
                category=category,
                severity=severity,
                mitre_attack=mitre_attack,
                source="external",
                raw_ioc=json.dumps(item, ensure_ascii=False),
            )
            synced += 1
        except Exception as exc:
            logger.warning("同步写入失败: %s — %s", title, exc)

    return {
        "code": 0,
        "data": {
            "provider": provider,
            "synced": synced,
            "message": f"已写入 {synced} 条草稿，请审核后入库",
        },
        "message": f"已写入 {synced} 条草稿，请审核后入库",
    }
