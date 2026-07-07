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

```bash
cd backend
pip install -r requirements.txt
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
