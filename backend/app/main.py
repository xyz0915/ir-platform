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
    """应用启动时初始化数据库."""
    logger.info("Starting IR Platform backend...")
    init_db()
    logger.info("IR Platform backend started successfully")


# 注册 API 路由
from app.api import auth, cases, hosts, import_data, analysis, report, agent, rules, ai, whitelist, iocs  # noqa: E402
from app.api import threat_intel  # noqa: E402
from app.api import baseline  # noqa: E402  # v1.3.0 差分基线
from app.api import knowledge_draft  # noqa: E402  # AI 自动知识入库

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
