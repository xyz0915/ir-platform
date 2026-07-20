"""FastAPI 应用入口.

配置 CORS、注册路由、启动时初始化数据库.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv

# 即使直接用 `uvicorn app.main:app` 启动也加载 backend/.env（app/main.py 在 backend/app，
# parent.parent 即 backend 根）。override=False：终端环境变量优先，.env 作兜底。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # backend/.env

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="个人应急响应平台",
    description="本地部署的轻量化应急响应工具，支持 Agent 采集、数据导入、分析引擎与报告生成",
    version="1.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# SSE 响应中间件：禁止代理/nginx 缓冲流式响应
@app.middleware("http")
async def sse_cors_middleware(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type or "text/stream" in content_type:
        response.headers["Cache-Control"] = "no-cache, no-transform"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
    return response


@app.on_event("startup")
def startup_event() -> None:
    """应用启动时初始化数据库并注册定时任务."""
    logger.info("Starting IR Platform backend...")
    init_db()

    # ── 默认策略初始化/更新 ──
    try:
        from app.models.policy import DetectionPolicy
        from app.models.rule import Rule
        policies = DetectionPolicy.get_all()
        all_rules = Rule.list(enabled=True)
        rule_ids = [r["id"] for r in all_rules]
        if not policies:
            # 首次启动：创建默认策略并激活
            pid = DetectionPolicy.create(
                name="默认策略（全量检测）",
                description="涵盖全部检测规则，适用于首次全量分析和日常全面巡检。使用全部规则，RAG 语义分析开启，攻击链检测开启。",
                enable_rag=1, enable_attack_chain=1,
            )
            if pid:
                DetectionPolicy.set_rules(pid, rule_ids)
                DetectionPolicy.activate(pid)
                logger.info("Created default policy with %d rules", len(rule_ids))
        else:
            # 后续启动：找到原始默认策略（不含"副本"）并更新其规则
            default = next((p for p in policies if "默认" in p.get("name", "") and "副本" not in p.get("name", "")), None)
            if default:
                cur = default.get("rule_count", 0)
                if cur != len(rule_ids):
                    DetectionPolicy.set_rules(default["id"], rule_ids)
                    logger.info("Updated default policy(ID=%d): %d→%d rules", default["id"], cur, len(rule_ids))
    except Exception as e:
        logger.warning("Default policy init skipped: %s", e)

    # ── Phase 2 定时同步调度（任务11）──
    _register_scheduled_tasks()

    logger.info("IR Platform backend started successfully")


def _register_scheduled_tasks() -> None:
    """注册 apscheduler 定时任务：每天凌晨 3:00 同步第三方 IOC 列表.

    同步失败仅记录日志，不影响服务。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(daemon=True)

        @scheduler.scheduled_job("cron", hour=3, minute=0, id="sync_ioc_lists")
        def _sync_ioc_lists_job() -> None:
            """定时同步第三方 IOC 列表 → 知识草稿 → 自动审核."""
            try:
                from app.services.enrichment_service import get_enrichment_service
                from app.models.knowledge_draft import KnowledgeDraft
                import json as _json

                svc = get_enrichment_service()
                iocs = svc.fetch_all_ioc_lists(limit=100)

                if not iocs:
                    logger.info("定时同步：未获取到 IOC 数据")
                    return

                synced = 0
                for item in iocs:
                    title = f"{item['ioc_type'].upper()} IOC: {item['ioc_value']}"
                    description = item.get("description", "")
                    source = item.get("source", "external")
                    severity = item.get("severity", "medium")

                    if KnowledgeDraft.is_duplicate(title, "auto", None):
                        continue

                    try:
                        KnowledgeDraft.create(
                            title=title,
                            description=description,
                            category="auto",
                            severity=severity,
                            source=source,
                            raw_ioc=_json.dumps(item, ensure_ascii=False),
                        )
                        synced += 1
                    except Exception as exc:
                        logger.debug("定时同步写入失败: %s — %s", title, exc)

                logger.info("定时同步完成: synced=%d/%d", synced, len(iocs))
            except Exception as exc:
                logger.warning("定时同步 IOC 列表失败: %s", exc)

        @scheduler.scheduled_job("cron", hour=3, minute=30, id="cleanup_uploaded_logs")
        def _cleanup_uploaded_logs_job() -> None:
            """每天 3:30 清理过期的上传日志文件."""
            import os as _os
            import shutil as _shutil
            from datetime import datetime as _datetime, timedelta as _timedelta
            from app.config import settings as _settings

            upload_base = getattr(_settings, "UPLOAD_DIR", "./uploads")
            retention_days = getattr(_settings, "LOG_FILE_RETENTION_DAYS", 7)
            cutoff = _datetime.now() - _timedelta(days=retention_days)
            cleaned = 0

            if not _os.path.isdir(upload_base):
                return

            for root, dirs, files in _os.walk(upload_base):
                for f in files:
                    fpath = _os.path.join(root, f)
                    try:
                        mtime = _datetime.fromtimestamp(_os.path.getmtime(fpath))
                        if mtime < cutoff:
                            _os.remove(fpath)
                            cleaned += 1
                    except Exception:
                        continue
                # 清理空目录
                for d in dirs:
                    dpath = _os.path.join(root, d)
                    try:
                        if not _os.listdir(dpath):
                            _os.rmdir(dpath)
                    except Exception:
                        continue

            if cleaned:
                logger.info("清理过期上传文件: %d 个文件已删除", cleaned)

        scheduler.start()
        logger.info("已注册定时同步任务（每天 03:00）")
    except ImportError:
        logger.info("apscheduler 未安装，跳过定时任务注册")
    except Exception as exc:
        logger.warning("注册定时同步任务失败: %s", exc)


# 注册 API 路由
from app.api import auth, cases, hosts, import_data, analysis, report, agent, rules, ai, whitelist, iocs  # noqa: E402
from app.api import threat_intel  # noqa: E402
from app.api import baseline  # noqa: E402  # v1.3.0 差分基线
from app.api import knowledge_draft  # noqa: E402  # AI 自动知识入库
from app.api import knowledge  # noqa: E402  # P2-H 知识库自进化闭环
from app.api import process_events  # noqa: E402  # T-P2-3 进程事件流入口（PoC）
from app.api import rule_suppression  # noqa: E402  # #18 规则抑制
from app.api import dashboard  # noqa: E402  # 全局态势仪表盘
from app.api import alerts  # noqa: E402  # 实时告警管理
from app.api import agents  # noqa: E402  # Agent 注册与心跳
from app.api import case_hosts  # noqa: E402  # 案件→主机级联数据
from app.api import logs  # noqa: E402  # 日志分析中心
from app.api import policies  # noqa: E402  # 检测策略配置
from app.api import ai_advanced  # noqa: E402  # AI 高级关联功能
from app.api import events  # noqa: E402  # 分析中心事件 API
from app.api import dq  # noqa: E402  # v2.1 数据质量监控 API
from app.api import sync  # noqa: E402  # v2 SyncLayer 同步 API
from app.api import log_search  # noqa: E402  # 日志检索模块 v2
from app.api import disposition  # noqa: E402  # 处置记录 API
from app.api import ai_noise  # noqa: E402  # AI 降噪 + 路由注册
from app.api import event_verdict  # noqa: E402  # AI 事件研判打标（生产者）
from app.api import import_logs  # noqa: E402  # 手工日志导入
from app.api import users  # noqa: E402  # 用户管理
from app.api import audit_logs  # noqa: E402  # 审计日志
from app.api import settings_api  # noqa: E402  # 系统参数
from app.api import rules_coverage  # noqa: E402  # T-P1-3 规则覆盖率看板

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(case_hosts.router, prefix="/api", tags=["案件"])  # 必须在 cases.router 之前注册
app.include_router(cases.router, prefix="/api/cases", tags=["案件"])
app.include_router(hosts.router, prefix="/api", tags=["主机"])
app.include_router(import_data.router, prefix="/api", tags=["导入"])
app.include_router(analysis.router, prefix="/api", tags=["分析"])
app.include_router(report.router, prefix="/api", tags=["报告"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(rules.router, prefix="/api/rules", tags=["规则"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI分析"])
app.include_router(baseline.router, prefix="/api/baselines", tags=["差分基线"])
app.include_router(whitelist.router, prefix="/api", tags=["白名单"])
app.include_router(iocs.router, prefix="/api/iocs", tags=["IOC"])
app.include_router(threat_intel.router, prefix="/api/threat-intel", tags=["威胁情报外联"])
app.include_router(knowledge_draft.router, prefix="/api/knowledge", tags=["知识入库"])
app.include_router(knowledge.router, prefix="/api/kb", tags=["知识自进化"])  # P2-H 自进化闭环
app.include_router(process_events.router, prefix="/api", tags=["进程事件"])  # T-P2-3 进程事件流入口
app.include_router(rule_suppression.router, prefix="/api", tags=["规则抑制"])  # #18 规则抑制
app.include_router(dashboard.router, prefix="/api", tags=["仪表盘"])  # 全局态势仪表盘
app.include_router(alerts.router, prefix="/api", tags=["告警"])  # 实时告警
app.include_router(agents.router, prefix="/api", tags=["Agent管理"])  # Agent 管理
app.include_router(case_hosts.router, prefix="/api", tags=["案件"])  # 案件→主机级联
app.include_router(logs.router, prefix="/api", tags=["日志分析"])  # 日志分析中心
app.include_router(policies.router, prefix="/api", tags=["策略配置"])  # 检测策略配置
app.include_router(ai_advanced.router, prefix="/api", tags=["AI高级关联"])  # AI高级关联功能
app.include_router(events.router, prefix="/api/analysis", tags=["分析中心"])  # 分析中心事件 API
app.include_router(dq.router, prefix="/api/dq", tags=["数据质量"])  # v2.1 DQMonitor 接口
app.include_router(sync.router, prefix="/api/sync", tags=["同步"])  # v2 SyncLayer 接口
app.include_router(log_search.router, prefix="/api/log-search", tags=["日志检索"])  # 日志检索 v2
app.include_router(disposition.router, tags=["处置"])  # 处置记录
app.include_router(ai_noise.router, prefix="/api/ai", tags=["AI降噪"])  # AI 降噪研判
app.include_router(event_verdict.router, prefix="/api/security-events", tags=["AI研判"])  # AI 事件研判打标
app.include_router(import_logs.router, tags=["手工日志导入"])  # 手工日志导入
app.include_router(users.router, prefix="/api", tags=["用户管理"])  # 用户管理
app.include_router(audit_logs.router, prefix="/api/audit-logs", tags=["审计日志"])  # 审计日志
app.include_router(settings_api.router, prefix="/api/settings", tags=["系统参数"])  # 系统参数
app.include_router(rules_coverage.router, tags=["规则覆盖率"])  # T-P1-3 规则覆盖率看板


@app.get("/api/health")
def health_check() -> dict:
    """健康检查接口."""
    return {"code": 0, "data": {"status": "ok"}, "message": "success"}


@app.get("/api/routes-debug")
def list_routes() -> dict:
    """列出所有已注册的路由路径（诊断用）."""
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    return {"code": 0, "data": routes, "message": "success"}


# 挂载前端静态文件（生产模式）
frontend_dist = Path(settings.BASE_DIR) / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
