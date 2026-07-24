# IR 平台 CI/CD 流水线

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                   GitHub Actions (CI)                       │
├──────────────────┬──────────────────────────────────────────┤
│   Frontend CI     │           Backend CI                    │
│  (frontend-ci.yml)│        (backend-ci.yml)                 │
├──────────────────┼──────────────────────────────────────────┤
│                  │                                          │
│  Lint ─→ Test ─→ Build    Lint ─→ Test ─→ Build            │
│  (echo skip) (vitest) (vite) (ruff)  (pytest) (import)     │
│                  │                                          │
└──────────────────┴──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Docker (部署)                             │
│                                                             │
│  docker-compose.yml                                         │
│  ├── backend  (python:3.13-slim, port 8000)                 │
│  └── frontend (nginx:alpine,      port 3000)                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 本地开发

### 容器化启动（推荐）

```bash
# 构建并启动所有服务
docker compose up --build

# 后台运行
docker compose up --build -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down

# 停止并删除数据卷
docker compose down -v
```

### 本地直接运行

```bash
# 前端
cd frontend
npm install
npm run dev        # → http://localhost:5173

# 后端
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload  # → http://localhost:8000
```

### 本地运行 CI 检查

```bash
# 前端
cd frontend
npm run test       # vitest 单元测试
npm run build      # Vite 构建验证

# 后端
cd backend
pip install ruff pytest
ruff check app/ --ignore E501,F401
python -m pytest app/tests/ -v
python -c "from app.main import app; print('Import OK')"
```

## CI/CD 流程说明

### 触发条件

| 事件 | 分支 | 效果 |
|------|------|------|
| Push | `main`, `develop` | 触发对应模块的完整三阶段 CI |
| Pull Request | → `main`, `develop` | 触发对应模块的完整三阶段 CI |
| 路径过滤 | 前端: `frontend/**` | 仅前端变更触发前端 CI |
| | 后端: `backend/**` | 仅后端变更触发后端 CI |

### 流水线阶段

| 阶段 | 前端 | 后端 |
|------|------|------|
| **Lint** | `echo "lint skipped"` (占位) | `ruff check backend/ --ignore E501,F401` |
| **Test** | `npm run test` (vitest) | `pytest app/tests/ -v` |
| **Build** | `npm run build` (vite) | `python -c "from app.main import app"` |

### 阶段依赖

```
Lint → Test → Build → (可选部署)
```

## 环境变量配置

### GitHub Secrets（生产环境必需）

| Secret 名称 | 对应环境变量 | 说明 | 必需 |
|------------|-------------|------|------|
| `IR_SECRET_KEY` | `IR_SECRET_KEY` | JWT 签名密钥 (HS256) | 是 |
| `IR_AI_ENCRYPTION_KEY` | `IR_AI_ENCRYPTION_KEY` | AI API Key 加密密钥 (Fernet) | 是 |
| `DOCKER_USERNAME` | — | Docker Hub 用户名（Docker push 用） | 可选 |
| `DOCKER_PASSWORD` | — | Docker Hub 密码或 Access Token | 可选 |

### docker-compose 环境变量

```bash
# 使用自定义密钥启动
IR_SECRET_KEY=my-secret-key IR_AI_ENCRYPTION_KEY=my-encryption-key docker compose up
```

默认值（仅开发用）：
- `IR_SECRET_KEY`: `ir-platform-secret-key-2025-please-change-in-production`
- `IR_AI_ENCRYPTION_KEY`: `QSLeoOZ1ZXDfBM0SrbJq1cBcRznji1L62SMCJae7nEo=`

## 依赖更新

Dependabot 每周五自动检查：
- `frontend/package-lock.json`（npm 依赖）
- `backend/requirements.txt`（pip 依赖）

## 常见问题

### 1. `venv/` 目录导致 Docker 构建缓慢

**问题**：`backend/` 下的 `venv/` 包含 2600+ 文件，会严重拖慢 Docker build context 传输。

**解决**：`backend/.dockerignore` 已排除 `venv/`。构建时由 `pip install -r requirements.txt` 重新安装。

### 2. ChromaDB 首次启动下载模型

**问题**：ChromaDB 首次启动时会下载约 80MB 的 embedding 模型（all-MiniLM-L6-v2），耗时较长。

**解决**：
- CI 测试阶段已排除需要 chromadb 的测试用例
- 本地首次启动请耐心等待模型下载
- Docker 构建后首次运行会自动下载

### 3. SQLite 文件权限

**问题**：Docker 中运行后端时，挂载的数据卷可能因用户 ID 不一致导致权限问题。

**解决**：
- 数据卷 `backend_data` 持久化至 Docker volume，自动处理权限
- 若需挂载本地目录，确保目录权限与容器内用户一致

### 4. Playwright E2E 测试

**问题**：`npm run e2e` 需要安装浏览器二进制文件，CI 环境（ubuntu-latest）默认不可用。

**解决**：CI 只运行 `npm run test`（vitest 单元测试），不使用 `npm run e2e`。如需在 CI 中运行 E2E，需额外配置 Playwright 浏览器安装步骤。

### 5. Windows-only 依赖

**问题**：`wmi`、`pywin32-ctypes` 等依赖标记了 `platform_system == "Windows"`，在 Linux CI 环境中会自动跳过。

**解决**：无需干预，pip 会自动处理条件依赖。

### 6. SECRET_KEY 安全性

**问题**：代码中硬编码了默认的 `SECRET_KEY` 和 `AI_ENCRYPTION_KEY`，生产环境存在安全风险。

**解决**：务必在 GitHub Secrets 中设置 `IR_SECRET_KEY` 和 `IR_AI_ENCRYPTION_KEY`，CI 运行时会自动注入。测试环境使用默认值不影响功能。
