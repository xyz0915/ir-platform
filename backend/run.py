#!/usr/bin/env python3
"""启动脚本 - 使用 uvicorn 启动 FastAPI 应用."""

import uvicorn


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
