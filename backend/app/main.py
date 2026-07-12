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


@app.on_event("startup")
def startup_event() -> None:
    """应用启动时初始化数据库并注册定时任务."""
    logger.info("Starting IR Platform backend...")
    init_db()

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
from app.api import process_events  # noqa: E402  # T-P2-3 进程事件流入口（PoC）
from app.api import rule_suppression  # noqa: E402  # #18 规则抑制
from app.api import dashboard  # noqa: E402  # 全局态势仪表盘
from app.api import alerts  # noqa: E402  # 实时告警管理
from app.api import agents  # noqa: E402  # Agent 注册与心跳

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
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
app.include_router(process_events.router, prefix="/api", tags=["进程事件"])  # T-P2-3 进程事件流入口
app.include_router(rule_suppression.router, prefix="/api", tags=["规则抑制"])  # #18 规则抑制
app.include_router(dashboard.router, prefix="/api", tags=["仪表盘"])  # 全局态势仪表盘
app.include_router(alerts.router, prefix="/api", tags=["告警"])  # 实时告警
app.include_router(agents.router, prefix="/api", tags=["Agent管理"])  # Agent 管理


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
