"""FastAPI 应用入口.

配置 CORS、注册路由、启动时初始化数据库.
"""

import logging
from pathlib import Path

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
from app.api import auth, cases, hosts, import_data, analysis, report, agent, rules, ai, whitelist  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(cases.router, prefix="/api/cases", tags=["案件"])
app.include_router(hosts.router, prefix="/api", tags=["主机"])
app.include_router(import_data.router, prefix="/api", tags=["导入"])
app.include_router(analysis.router, prefix="/api", tags=["分析"])
app.include_router(report.router, prefix="/api", tags=["报告"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(rules.router, prefix="/api/rules", tags=["规则"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI分析"])
app.include_router(whitelist.router, prefix="/api", tags=["白名单"])


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
