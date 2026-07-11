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

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.data.knowledge_seed import ALL_SEED_KNOWLEDGE
from app.models.knowledge_draft import KnowledgeDraft

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


# ── 端点 ────────────────────────────────────────────────────────────

@router.get("/drafts")
def list_drafts(
    status: Optional[str] = Query(None, description="按状态过滤：pending/approved/rejected"),
    host_id: Optional[str] = Query(None, description="按主机 ID 过滤"),
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
def list_seeds():
    """获取内置种子知识数据（10 条 MITRE/C2/Malware）.

    返回 MITRE_TECHNIQUES（5）、C2_FRAMEWORKS（3）、MALWARE_PATTERNS（2）共 10 条。
    """
    return {
        "code": 0,
        "data": ALL_SEED_KNOWLEDGE,
        "message": f"共 {len(ALL_SEED_KNOWLEDGE)} 条种子数据",
    }


@router.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: int):
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
def reject_draft(draft_id: int):
    """拒绝知识草稿.

    将草稿 status 更新为 'rejected'，该条目不会进入知识库.
    """
    try:
        draft = KnowledgeDraft.reject(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"code": 0, "data": draft, "message": "草稿已拒绝"}


@router.post("/drafts/{draft_id}/recall")
def recall_draft(draft_id: int):
    """撤回已批准或已拒绝的草稿，恢复为 pending 状态.

    撤回后 reviewed_at 记录为撤回时间。
    """
    try:
        draft = KnowledgeDraft.recall(draft_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"code": 0, "data": draft, "message": "草稿已撤回至待审核"}


@router.post("/drafts/batch")
def batch_action(body: BatchRequest):
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
def import_knowledge(body: ImportRequest):
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
    return {
        "code": 0,
        "data": {
            "total": total,
            "imported": imported,
            "skipped": skipped,
            "skipped_reasons": skipped_reasons,
        },
        "message": f"导入 {imported} 条待审核知识条目，{skipped} 条跳过",
    }


@router.post("/sync/{provider}")
def sync_from_provider(provider: str, body: Optional[SyncRequest] = None):
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
