# 个人应急响应平台 (IR Platform)

本地部署、轻量化的个人应急响应平台工具。数据留存在本地（SQLite + JSON），不依赖云服务，适配 Windows 和 Linux。

## 项目结构

```
ir_platform/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 应用入口
│   │   ├── config.py        # 配置管理
│   │   ├── database.py      # 数据库管理
│   │   ├── models/          # 数据模型
│   │   ├── schemas/         # Pydantic Schema
│   │   ├── api/             # API 路由
│   │   ├── services/        # 业务逻辑层
│   │   ├── analysis/        # 分析引擎
│   │   ├── rules/           # 规则引擎
│   │   ├── templates/       # 报告模板
│   │   └── utils/           # 工具函数
│   ├── requirements.txt
│   └── run.py
├── frontend/         # Vue 3 前端
│   ├── src/
│   │   ├── views/           # 页面组件
│   │   ├── components/      # 公共组件
│   │   ├── stores/          # Pinia 状态管理
│   │   ├── api/             # API 封装
│   │   └── router/          # 路由配置
│   ├── index.html
│   └── package.json
├── agent/            # Python 采集端 Agent
│   ├── agent.py             # 主入口
│   ├── collectors/          # 16 大类采集器
│   ├── utils/               # 工具函数
│   └── build.py             # 打包脚本
└── README.md
```

## 技术栈

- **后端**: FastAPI + SQLite + Pydantic + Jinja2 + WeasyPrint
- **前端**: Vue 3 + Element Plus + Pinia + Vue Router + Axios + ECharts
- **Agent**: Python + psutil + PyInstaller

## 快速开始

### 后端启动

> 后端统一入口是 `backend/run.py`（`python run.py`）。它会在启动时自动 `load_dotenv()` 读取 `backend/.env`，因此威胁情报 API Key（如 `THREATBOOK_KEY`）等敏感配置无需手动 export，即可被后端正确加载。**请勿直接裸 `uvicorn app.main:app` 启动**，否则会跳过 `.env` 加载，导致情报 Key 缺失。

```bash
cd backend
python run.py
```

后端启动后访问 `http://localhost:8000/docs` 查看 API 文档。

默认管理员账号：`admin` / `admin123`

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器运行在 `http://localhost:5173`。

### Agent 使用

```bash
cd agent
python agent.py --output result.json          # 采集全部
python agent.py --collect system_info,processes  # 采集指定类别
python build.py                                 # 打包为单文件
```

> Agent 为按需手动运行的采集端，**不纳入一键启动**；在「主机详情」页点「下载 Agent / 导入 JSON」时使用。

## 一键启动（推荐）

仓库根目录提供了跨平台一键启动编排器 `start.py`（纯标准库，无第三方依赖），自动完成：创建后端 venv → 安装后端依赖 → 安装前端依赖 → 同时拉起前后端，并转发日志、支持 `Ctrl+C` 优雅退出。

**前置依赖**：Python 3.11+ 、Node 18+（新机 clone 后直接跑即可，脚本会自行 bootstrap）。

- **Windows**
  ```bat
  start.bat                 :: 或 python start.py
  restart.bat               :: 等价于 python start.py --restart（先杀 8000/5173 再启动）
  ```
- **Linux / macOS**
  ```bash
  bash start.sh             :: 或 python3 start.py
  python3 start.py --restart   :: 重启
  ```

常用参数：`--no-backend` / `--no-frontend`（只起一端）、`--host`（默认 0.0.0.0）、`--port`（默认 8000）、`--restart`（先清理端口再启动）。

启动完成后：
- 后端：http://localhost:8000/docs
- 前端：http://localhost:5173

**威胁情报 Key**：放到 `backend/.env`（如 `THREATBOOK_KEY=xxx`）。未配置时对应情报源会自动跳过，不影响平台运行。

## 核心功能

1. **案件管理**: 创建、管理应急响应案件
2. **主机管理**: 添加目标主机、下载采集 Agent
3. **数据采集**: Agent 一键采集 16 大类系统信息
4. **数据导入**: 导入 Agent JSON 输出到平台
5. **分析引擎**: 规则引擎驱动的自动化分析（异常进程/可疑外连/持久化/IOC）
6. **报告生成**: HTML + PDF 双格式分析报告
7. **规则管理**: 可配置的检测规则集

## 数据存储

- SQLite 数据库: `backend/data/ir_platform.db`
- 原始 JSON: `backend/data/imports/`
- Agent 二进制: `backend/data/agents/`
