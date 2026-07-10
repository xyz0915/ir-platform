#!/usr/bin/env python3
"""启动脚本 - 使用 uvicorn 启动 FastAPI 应用."""

import uvicorn
from pathlib import Path
from dotenv import load_dotenv

# 后端启动时从 backend/.env 加载环境变量（终端/IDE/计划任务均可靠读到 THREATBOOK_KEY 等）。
# override=False：已存在的终端环境变量优先，.env 作兜底，不会覆盖显式设置。
load_dotenv(Path(__file__).resolve().parent / ".env")  # backend/.env


def main() -> None:
    """启动 FastAPI 服务."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
