# 个人应急响应平台（IR Platform）用户手册

> **文档版本**: v1.0  
> **日期**: 2026-07-12  
> **适配平台版本**: commit `8bb6d77`  
> **面向角色**: 👤 用户 / 🔧 运维 / 💻 开发

---

## 目录（TOC）

1. [系统概览](#1-系统概览)
2. [快速开始](#2-快速开始)
3. [案件与主机管理](#3-案件与主机管理)
4. [数据采集（Agent）](#4-数据采集agent)
5. [数据导入与分析](#5-数据导入与分析)
6. [规则系统](#6-规则系统)
7. [异常进程检测](#7-异常进程检测)
8. [WebShell 文件检测](#8-webshell-文件检测)
9. [内存码（Memory Shell）检测](#9-内存码memory-shell检测)
10. [统一关联引擎（correlate_incident）](#10-统一关联引擎correlate_incident)
11. [网络连接检测](#11-网络连接检测)
12. [持久化与启动项](#12-持久化与启动项)
13. [IOC（威胁情报）匹配](#13-ioc威胁情报匹配)
14. [进程树视图](#14-进程树视图)
15. [前端功能面板](#15-前端功能面板)
16. [AI 分析模块](#16-ai-分析模块)
17. [知识库系统](#17-知识库系统)
    - [17.3A 向量检索质量自检](#173a-向量检索质量自检)
    - [17.4.1 自动审核规则](#1741-自动审核规则)
    - [17.9A RAG 与异常检测集成（双路检测）](#179a-rag-与异常检测集成双路检测)
    - [17.9B 规则→知识批量导入](#179b-规则知识批量导入)
    - [17.9C 第三方威胁情报同步增强](#179c-第三方威胁情报同步增强)
    - [17.11 模型下载指南](#1711-模型下载指南)
18. [系统配置与管理](#18-系统配置与管理)
19. [API 参考](#19-api-参考)
20. [技术架构与数据流](#20-技术架构与数据流)
21. [部署与运维](#21-部署与运维)
22. [版本管理与维护策略](#22-版本管理与维护策略)

---

## 1. 系统概览

### 1.1 平台定位

个人应急响应平台（IR Platform）是一款**本地部署、轻量化的应急响应工具**。数据全部留存在本地（SQLite + JSON），不依赖任何云服务，适配 Windows 和 Linux。平台覆盖从主机数据采集、自动化分析到报告生成的全链路应急响应工作流。

### 1.2 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                     IR Platform 架构                         │
│                                                              │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │  Agent   │───▶│   Backend    │◀───│     Frontend      │  │
│  │ (Python) │    │ (FastAPI)    │    │ (Vue3+ElementPlus)│  │
│  │  采集端   │    │  分析服务     │    │   用户界面         │  │
│  └──────────┘    └──────┬───────┘    └───────────────────┘  │
│                         │                                    │
│                  ┌──────▼───────┐                            │
│                  │   SQLite DB  │                            │
│                  │  (36+ 张表)   │                            │
│                  └──────────────┘                            │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **后端** | FastAPI 0.111 + Uvicorn | REST API，自动 OpenAPI 文档 |
| **数据库** | SQLite 3 | 本地文件型数据库，零配置 |
| **认证** | JWT (HS256) + passlib/bcrypt | Token 有效期 24h |
| **前端** | Vue 3 + Element Plus + Pinia + Vue Router | SPA 单页应用 |
| **图表** | ECharts 5 | 进程树、统计图表 |
| **报告** | Jinja2 + WeasyPrint | HTML + PDF 双格式 |
| **Agent** | Python + psutil + WMI | 跨平台采集端 |
| **AI** | httpx + tiktoken + ChromaDB + sentence-transformers | LLM 分析 + RAG 向量检索 |
| **打包** | PyInstaller | Agent 单文件分发 |

### 1.4 部署拓扑

```
单机部署：
  目标主机 ──(Agent JSON)──▶ 分析工作站
                              ├── Backend :8000
                              ├── Frontend :5173 (dev) / 静态文件 (prod)
                              └── SQLite DB + 原始 JSON
```

### 1.5 核心功能一览

1. **案件管理** — 创建、编辑、删除应急响应案件
2. **主机管理** — 注册主机、管理状态、下载 Agent
3. **数据采集** — Agent 一键采集 20 大类系统信息
4. **数据导入** — 导入 Agent JSON 输出到平台（双端点：`/import` + `/process-events`）
5. **分析引擎** — 规则引擎驱动的自动化分析（异常进程/可疑外连/持久化/IOC/WebShell/内存码）
6. **统一关联引擎** — 跨维度加权关联 + 贝叶斯置信度计算
7. **规则管理** — 可配置的检测规则集（process/behavior/execution/webshell/memory_shell）
8. **AI 分析** — LLM 驱动的深度分析报告 + 多版本管理 + PDF 导出
9. **报告生成** — HTML + PDF 双格式，支持 technical/executive 两种层级
10. **威胁情报外联** — 多源 IOC Enrichment（ThreatBook/微步等）
11. **知识库系统** — AI 驱动的威胁知识管理（向量语义检索 + 知识草稿审核 + 种子数据 + 第三方情报同步）

> **面向角色**: 👤用户 🔧运维 💻开发

---

## 2. 快速开始

### 2.1 环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Python | 3.11+ | 后端 + Agent 运行环境 |
| Node.js | 18+ | 前端构建 |
| 磁盘空间 | ~2 GB | 含依赖安装 + AI 模型（~80MB RAG 模型） |
| 内存 | 4 GB+ | AI 分析推荐 8GB+ |

### 2.2 一键启动（推荐）

仓库根目录提供了跨平台一键启动编排器 `start.py`（纯标准库，无第三方依赖）：

**Windows**:
```bat
start.bat                 :: 或 python start.py
restart.bat               :: 重启（先杀端口再启动）
```

**Linux / macOS**:
```bash
bash start.sh             :: 或 python3 start.py
python3 start.py --restart   :: 重启
```

**常用参数**:
```
--no-backend       只启动前端
--no-frontend      只启动后端
--host 0.0.0.0    绑定地址（默认 0.0.0.0）
--port 8000        后端端口（默认 8000）
--restart          先清理 8000/5173 端口再启动
```

### 2.3 分步启动

#### 后端

```bash
cd backend
python run.py
```
> ⚠️ **重要**: 必须使用 `python run.py` 启动，不要直接 `uvicorn app.main:app`。`run.py` 会自动 `load_dotenv()` 读取 `backend/.env` 中的威胁情报 API Key。

后端启动后访问 `http://localhost:8000/docs` 查看交互式 API 文档。

#### 前端

```bash
cd frontend
npm install
npm run dev
```
前端开发服务器运行在 `http://localhost:5173`。

### 2.4 默认凭据

| 字段 | 值 |
|------|-----|
| 用户名 | `admin` |
| 密码 | `admin123` |
| 角色 | admin |

> 管理员账号在数据库初始化时自动创建（`backend/app/database.py:547-562`），使用 bcrypt 加密存储。

### 2.5 威胁情报 Key 配置

将 API Key 写入 `backend/.env`：
```bash
THREATBOOK_KEY=your_key_here
```
未配置时对应情报源会自动跳过，不影响平台运行。

### 2.6 启动后访问

| 服务 | URL |
|------|-----|
| 前端界面 | http://localhost:5173 |
| API 文档 (Swagger) | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/api/health |

> **面向角色**: 👤用户 🔧运维

---

## 3. 案件与主机管理

### 3.1 功能描述

案件（Case）是应急响应的顶层组织单元，一个案件可以包含多台主机。主机（Host）代表被调查的目标机器。

### 3.2 案件管理

#### 操作流程

1. 登录后进入**案件列表页**（`/`），点击"创建案件"
2. 填写案件信息：
   - **案件名称**（必填）— 如 "2026-07 勒索事件"
   - **案件编号**（可选）— 唯一编号，如 "IR-2026-001"
   - **描述**（可选）— 案件背景信息
3. 点击"确定"创建
4. 在案件列表可执行**编辑**、**删除**操作

#### 相关 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/cases` | GET | 分页获取案件列表（`?page=1&size=20&search=`） |
| `/api/cases` | POST | 创建案件 |
| `/api/cases/{case_id}` | GET | 获取案件详情 |
| `/api/cases/{case_id}` | PUT | 更新案件 |
| `/api/cases/{case_id}` | DELETE | 删除案件（级联删除关联主机） |

**实现文件**: `backend/app/api/cases.py` / `backend/app/services/case_service.py`

#### 案件状态

| 状态 | 含义 |
|------|------|
| `open` | 进行中 |
| `closed` | 已结案 |

### 3.3 主机管理

#### 添加主机

1. 进入案件详情页（`/cases/:id`）
2. 点击"添加主机"
3. 填写主机信息：
   - **主机名**（必填）
   - **IP 地址**（可选）
   - **操作系统类型**（可选）— windows / linux
   - **操作系统版本**（可选）
4. 点击"确定"创建

#### 主机状态流转

```
pending ──▶ imported ──▶ analyzed
  │                         │
  └── (未导入数据)          └── (分析完成)
```

| 状态 | 含义 |
|------|------|
| `pending` | 新建，尚未导入采集数据 |
| `imported` | 已导入 Agent JSON |
| `analyzed` | 已完成分析 |

#### 主机详情页

进入 `/hosts/:id` 后，顶部显示主机基本信息卡片，下方含多个 Tab：

| Tab | 内容 |
|-----|------|
| 概览 | 主机画像（CPU/内存/磁盘/网络） + 风险评级 |
| 异常进程 | 异常进程表格（含 risk_score/matched_rules/attack_path） |
| 网络连接 | 网络连接列表 + 威胁情报一键检测按钮 |
| IOC 命中 | IOC 匹配结果 |
| WebShell | WebShell 文件型检测命中面板 |
| Memory Shell | 内存码检测命中面板 |
| 事件/Incident | 统一关联引擎输出的 incident / single_alert |
| 时间线 | 按时间排序的安全事件时间线（支持筛选/导出/处置） |
| 启动项 | 可疑启动项列表 |
| 持久化 | 持久化痕迹分析结果 |
| 进程树 | ECharts 交互式进程树可视化 |
| AI 分析 | AI 深度分析报告面板 |
| 报告 | HTML/PDF 报告查看与导出 |

#### 相关 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/cases/{case_id}/hosts` | GET | 获取案件下主机列表 |
| `/api/cases/{case_id}/hosts` | POST | 添加主机 |
| `/api/hosts/{host_id}` | GET | 获取主机详情 |
| `/api/hosts/{host_id}` | DELETE | 删除主机（级联删除分析数据） |

**实现文件**: `backend/app/api/hosts.py` / `backend/app/services/host_service.py`

#### 数据库表

- `cases` — 案件主表，含 name/case_number/description/status
- `hosts` — 主机表，含 case_id(FK)/hostname/ip_address/os_type/status/raw_json_path

> **面向角色**: 👤用户

---

## 4. 数据采集（Agent）

### 4.1 功能描述

Agent 是在目标主机上**按需手动运行**的 Python 采集端，负责收集系统取证数据并输出为 JSON 格式。Agent 不纳入一键启动，在主机详情页点"下载 Agent / 导入 JSON"时使用。

### 4.2 Agent 命令行

```bash
cd agent
python agent.py --output result.json           # 采集全部
python agent.py --collect system_info,processes  # 采集指定类别
python agent.py --output result.json --log-file agent.log --log-days 3  # 带日志+时间过滤
python build.py                                 # 打包为单文件
```

**参数说明**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output` / `-o` | `{hostname}_{timestamp}.json` | 输出 JSON 文件路径 |
| `--collect` / `-c` | `all` | 采集类别（逗号分隔） |
| `--verbose` / `-v` | false | 详细日志输出 |
| `--log-file` | 无 | Agent 运行日志文件 |
| `--log-days` | 7 | 采集最近 N 天的系统日志 |

### 4.3 全部 20 个采集器详表

| # | 名称 | 用途 | 平台支持 | 输出内容 |
|---|------|------|----------|----------|
| 1 | `system_info` | 系统基本信息 | Windows/Linux | hostname, os_type, os_version, cpu, memory, disk, network interfaces |
| 2 | `users` | 用户账户 | Windows/Linux | username, SID/UID, group, last_login, is_admin |
| 3 | `processes` | 进程列表（增强版） | Windows/Linux | pid, ppid, name, path, command_line, user, start_time, threads, memory_sections, connections |
| 4 | `services` | 系统服务 | Windows/Linux | name, display_name, status, start_type, path |
| 5 | `startup_items` | 启动项 | Windows/Linux | name, command, location, type, user |
| 6 | `network` | 网络连接 | Windows/Linux | protocol, local/remote address, local/remote port, state, pid, process_name |
| 7 | `files` | 文件系统扫描 | Windows/Linux | 可疑文件/哈希/签名信息 |
| 8 | `registry` | 注册表键值 | Windows | key_path, value_name, value_type, value_data, last_write_time |
| 9 | `logs` | 系统日志 | Windows/Linux | Windows Event Log / Linux syslog |
| 10 | `security` | 安全产品检测 | Windows | 已安装的安全产品（AV/EDR/HIPS） |
| 11 | `browser` | 浏览器痕迹 | Windows/Linux | 历史记录/下载/扩展 |
| 12 | `usb` | USB 设备记录 | Windows/Linux | devices（VID/PID/序列号/首次/末次接入时间） |
| 13 | `remote_control` | 远程工具检测 | Windows | 远程桌面/TeamViewer/AnyDesk 等痕迹 |
| 14 | `persistence` | 持久化机制 | Windows/Linux | 注册表 Run/RunOnce, cron, systemd, WMI 订阅 |
| 15 | `ioc` | IOC 扫描 | Windows/Linux | known_bad_hashes, matched_items |
| 16 | `timeline` | 时间线采集 | Windows/Linux | 文件时间戳/事件时间聚合 |
| 17 | `webshells` | WebShell 文件扫描 | Windows/Linux | path, sha256, suspicious_funcs, obfuscation_score, behinder_godzilla_signal |
| 18 | `memory_shells` | 内存码检测 | Windows/Linux | pid, process_name, type(java_filter/java_agent/php), evidence |
| 19 | `linux_baseline` | Linux 基线 | Linux | known_items, diff_new, collection_health |
| 20 | `process_events` | 进程实时事件 | Windows/Linux | event_type(process_start/exit/remote_thread/etw/amsi), pid, ppid, detail |

### 4.4 融合采集器详解

#### WebShellCollector (`agent/collectors/webshell.py`)

- **用途**: 扫描 Web 目录中的 WebShell 文件
- **输出字段**: `path`, `name`, `sha256`, `suspicious_funcs` (JSON 数组), `obfuscation_score` (0-1), `behinder_godzilla_signal` (0/1)
- **检测维度**: 危险函数匹配（eval/exec/system/base64_decode 等）、混淆度评分、冰蝎/哥斯拉指纹

#### MemoryShellCollector (`agent/collectors/memory.py`)

- **用途**: 检测 Java 内存马（Filter/Agent 型）和 PHP 内存扩展
- **输出字段**: `pid`, `process_name`, `type` (java_filter/java_agent/php/unknown), `evidence`
- **检测维度**: JVM attach 检测、Java Agent 检测、Filter 链注入痕迹

#### LinuxBaselineCollector (`agent/collectors/linux.py`)

- **用途**: 建立 Linux 主机基线（正常服务/端口/进程快照）
- **输出字段**: `known_items`, `diff_new`, `collection_health`
- **配置**: 依赖 `--save-baseline` 模式首次建立基线

#### ProcessEventsCollector (`agent/collectors/process_events.py`)

- **用途**: 采集进程实时事件流（生/灭/注入/ETW/AMSI 旁路）
- **输出字段**: `event_type`, `pid`, `ppid`, `process_name`, `command_line`, `event_time`, `detail`（JSON: memory_sections/etw_events/remote_thread_events）
- **注意**: 走独立 `/process-events` 事件管线，不并入 `/import` JSON

#### 增强 ProcessesCollector (`agent/collectors/processes.py`)

- **增强内容**: 加入 `memory_sections` 字段（各内存段 base_address/region_size/protect/type），进程 `connections` 字段

### 4.5 资源配置

Agent 内置资源预算限制（`agent/collectors/resource_budget.py`）：
- `MAX_REPORT_BYTES` — 输出 JSON 最大字节数限制
- 超限时按优先级逐级裁剪：memory_sections → process_events → linux_baseline → webshells/memory_shells 摘要化

### 4.6 采集器平台支持矩阵

| 采集器 | Windows | Linux | 需要管理员/root | 说明 |
|--------|---------|-------|-----------------|------|
| system_info | ✅ | ✅ | 否 | 基本系统信息 |
| users | ✅ | ✅ | 否 | 用户账户列表 |
| processes | ✅ | ✅ | 建议 | 进程列表（增强版含 memory_sections） |
| services | ✅ | ✅ | 否 | 系统服务状态 |
| startup_items | ✅ | ✅ | 否 | 启动项 |
| network | ✅ | ✅ | 否 | 网络连接（psutil/netstat） |
| files | ✅ | ✅ | 建议 | 文件系统扫描（可疑文件/哈希） |
| registry | ✅ | ❌ | 建议 | Windows 注册表键值 |
| logs | ✅ | ✅ | 建议 | 系统日志（Event Log/syslog） |
| security | ✅ | ❌ | 否 | 安全产品检测（WMI） |
| browser | ✅ | ✅ | 否 | 浏览器历史/下载/扩展 |
| usb | ✅ | ✅ | 建议 | USB 设备记录 |
| remote_control | ✅ | ❌ | 否 | 远程工具痕迹 |
| persistence | ✅ | ✅ | 建议 | 持久化机制检测 |
| ioc | ✅ | ✅ | 否 | 内置 IOC 扫描 |
| timeline | ✅ | ✅ | 否 | 时间线采集 |
| webshells | ✅ | ✅ | 否 | WebShell 文件扫描 |
| memory_shells | ✅ | ✅ | 建议 | 内存码检测（需 attach 权限） |
| linux_baseline | ❌ | ✅ | 建议 | Linux 基线建立 |
| process_events | ✅ | ✅ | 建议 | 进程实时事件流 |

### 4.7 Agent 输出 JSON Schema（顶层结构）

```json
{
  "metadata": {
    "agent_version": "1.0.0",
    "collection_time": "2026-07-12T10:00:00",
    "platform": "windows",
    "hostname": "WIN-SERVER-01",
    "operator": "agent",
    "log_days": 7
  },
  "system_info": { ... },
  "users": [ ... ],
  "processes": [ ... ],
  "services": [ ... ],
  "startup_items": [ ... ],
  "network": { "connections": [ ... ] },
  "files": { ... },
  "registry": { ... },
  "logs": { ... },
  "security": { ... },
  "browser": { ... },
  "usb": { "devices": [ ... ] },
  "remote_control": [ ... ],
  "persistence": [ ... ],
  "ioc": { "known_bad_hashes": [ ... ], "matched_items": [ ... ] },
  "timeline": [ ... ],
  "network_connections": [ ... ],
  "file_hashes": [ ... ],
  "wmi_subscriptions": [ ... ],
  "registry_keys": [ ... ],
  "webshells": [ ... ],
  "memory_shells": [ ... ],
  "linux_baseline": { ... },
  "process_events": [ ... ],
  "collection_health": { ... }
}
```

> **面向角色**: 👤用户 🔧运维 💻开发

---

## 5. 数据导入与分析

### 5.1 功能描述

将 Agent 在目标主机上采集的 JSON 文件导入平台，触发自动化分析管线。

### 5.2 导入流程

#### 方式一：`POST /import`（标准导入）

1. 在主机详情页点击"导入数据"
2. 选择 Agent 生成的 JSON 文件
3. 上传后系统自动校验 JSON 格式，存储原始文件到 `backend/data/imports/`
4. 导入成功后主机状态变更为 `imported`

**API**: `POST /api/hosts/{host_id}/import`
- Content-Type: `multipart/form-data`
- 字段: `file` (UploadFile, 必填)
- 响应: `{code: 0, data: {id, host_id, file_name, status, data_summary, imported_at}}`

#### 方式二：`POST /process-events`（进程事件流）

专门用于接收 Agent 推送的实时进程事件：

**API**: `POST /api/hosts/{host_id}/process-events`
- Content-Type: `application/json`
- 请求体: `[{event_type, pid, ppid, process_name, ...}]`
- 响应: `{written: int}`

**实现文件**: `backend/app/api/import_data.py:16-43`, `backend/app/api/process_events.py:43-56`

### 5.3 分析触发

导入完成后，点击"开始分析"触发分析管线：

**API**: `POST /api/hosts/{host_id}/analyze`
- 前置条件: 主机状态必须为 `imported` 或 `analyzed`
- 响应: `{code: 0, data: {id, host_id, risk_level, risk_score, total_findings, summary, details}}`

### 5.4 分析管线（完整步骤）

`backend/app/services/analysis_service.py:95-323` 中的 `AnalysisService.analyze()` 按顺序执行：

| 步骤 | 操作 | 文件 |
|------|------|------|
| 1 | 清除旧分析结果 | `analysis_service.py:120` |
| 2 | 加载全量规则 | `rule_engine.py` |
| 3 | 构建主机画像 | `profile_builder.py` |
| 4 | 异常进程检测（含白名单过滤 + exe 哈希 JOIN） | `anomaly_detector.py:64-321` |
| 5 | 可疑外连检测 | `anomaly_detector.py:323-364` |
| 6 | 可疑启动项检测 | `anomaly_detector.py:366-400` |
| 7 | 持久化痕迹分析 | `persistence_finder.py` |
| 8 | IOC 检测 | `ioc_checker.py` |
| 9 | 时间线构建 | `timeline_builder.py` |
| 10 | 数据采集增强落库（network_connections/file_hashes/wmi/registry） | `analysis_service.py:179-199` |
| 11 | 文件哈希情报匹配（TI_malware_hash） | `analysis_service.py:206-240` |
| 12 | 攻击链关联检测 | `analysis_service.py:245-251` |
| 13 | 融合检测（WebShell + 内存码） | `anomaly_detector.py:438-484` |
| 14 | 进程事件流评估 | `process_event_consumer.py` |
| 15 | 统一关联引擎 | `anomaly_detector.py:549-672` |
| 16 | 风险评估 | `risk_assessor.py` |
| 17 | 保存分析结果 + 更新主机状态为 `analyzed` | `analysis_service.py:307-317` |

### 5.5 分析结果结构

```json
{
  "id": 1,
  "host_id": 1,
  "risk_level": "high",
  "risk_score": 75,
  "total_findings": 12,
  "summary": "发现 5 个异常进程，3 个可疑外连...",
  "details": {
    "abnormal_processes": 5,
    "suspicious_connections": 3,
    "suspicious_startup": 1,
    "persistence_suspicious": 2,
    "ioc_hits": 1,
    "attack_chains": [...],
    "fusion_incidents": [...]
  },
  "analyzed_at": "2026-07-12 10:30:00",
  "webshells": [...],
  "memory_shells": [...],
  "incidents": [...]
}
```

### 5.6 风险评级

| 等级 | 分数范围 | 含义 |
|------|----------|------|
| `critical` | 80-100 | 严重风险，需立即处置 |
| `high` | 60-79 | 高风险 |
| `medium` | 30-59 | 中等风险 |
| `low` | 10-29 | 低风险 |
| `info` | 0-9 | 信息级 |

**实现文件**: `backend/app/analysis/risk_assessor.py`

> **面向角色**: 👤用户 💻开发

---

## 6. 规则系统

### 6.1 功能描述

规则引擎是整个分析系统的核心。所有检测（进程/网络/启动项/WebShell/内存码）都通过规则引擎驱动。规则定义检测逻辑，引擎对采集数据进行批量匹配。

### 6.2 规则类型

| 类型 | 说明 | 示例 |
|------|------|------|
| `regex` | 正则表达式匹配（针对字段值） | PowerShell 编码命令检测 |
| `list` | 列表/黑名单匹配 | 已知恶意哈希检测 |
| `behavior` | 行为模式检测（无固定正则，跨字段逻辑） | orphan_process / suspicious_parent / unsigned_exe |
| `attack_chain` | 攻击链关联（跨维度顺序匹配） | C2 通信 → 横向移动 → 凭据窃取 |
| `exists` | 字段存在性检测 | scheduled_task_xml 存在即命中 |

### 6.3 规则 Schema

```json
{
  "name": "powershell_encoded_command",
  "description": "检测 PowerShell 编码命令执行",
  "category": "process",
  "rule_type": "regex",
  "severity": "high",
  "enabled": true,
  "label": "PowerShell 编码命令执行",
  "source": "default",
  "condition": {
    "field": "command_line",
    "pattern": "powershell.*(-enc|-encodedcommand)\\s+",
    "flags": "ignorecase",
    "_meta": {"mitre_attack": "T1059/001"}
  }
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 规则唯一标识（英文名） |
| `label` | string | 中文展示名 |
| `description` | string | 规则描述 |
| `category` | string | 规则类别：process / behavior / execution / network / startup / persistence / ioc / webshell / memory_shell |
| `rule_type` | string | 匹配类型：regex / list / behavior / attack_chain / exists |
| `condition` | object | 匹配条件（field + pattern / pattern + 行为参数） |
| `severity` | string | 严重度：critical / high / medium / low / info |
| `enabled` | boolean | 启用状态 |
| `source` | string | 来源：default（内置）/ user（自定义） |
| `mitre_attack` | string | 可选 MITRE ATT&CK 技术映射 |

### 6.4 行为模式（BEHAVIOR_PATTERNS）

规则引擎内置的行为模式（`backend/app/rules/rule_engine.py`）：

| 模式名称 | 检测逻辑 |
|----------|----------|
| `orphan_process` | 父进程不存在或 PPID=0 |
| `suspicious_parent` | 父进程为可疑服务（如 svchost 直接启动 cmd/powershell） |
| `unsigned_exe` | 非系统目录 exe 且无数字签名 |
| `ancestry_chain` | 多级祖先回溯异常（祖父母链检测） |
| `time_cluster` | 短时间窗口内进程爆发 |
| `short_lived` | 短生命周期进程（存活时间 < 阈值） |
| `zombie_process` | 僵尸进程（无实际活动但存在记录） |
| `parent_pid_spoof` | PPID 伪造（ppid==pid 或父子互指环） |
| `anomalous_path` | 路径异常（临时目录/隐藏目录执行） |
| `anomalous_net_process` | 可疑网络进程（非浏览器/系统进程建立外连） |
| `hidden_process` | 隐藏进程（无可见窗口/无文件路径） |
| `fileless_residency` | fileless 内存驻留（path 为空但有连接/线程） |
| `whitelist_derived_chain` | 白名单进程派生的可疑子链 |
| `process_injection` | 进程注入痕迹（memory_sections 异常/远程线程） |

### 6.5 规则管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/rules` | GET | 规则列表（支持 ?category= & ?enabled= & ?q= 搜索） |
| `/api/rules` | POST | 新增规则（含 condition schema 校验） |
| `/api/rules/{rule_id}` | PUT | 更新规则（含审计写入 rule_audit_log） |
| `/api/rules/{rule_id}` | DELETE | 删除规则（仅 source='user' 可删） |
| `/api/rules/bulk-enable` | PUT | 批量启用/禁用（`{ids:[...], enabled:bool}`） |
| `/api/rules/reset` | POST | 重置默认规则（管理员，保留用户自定义） |

**实现文件**: `backend/app/api/rules.py`, `backend/app/rules/rule_engine.py`, `backend/app/rules/loader.py`

### 6.6 种子规则 vs 默认规则 vs 用户规则

| 来源 | source 值 | 可编辑 | 可删除 | 更新策略 |
|------|-----------|--------|--------|----------|
| 种子规则 | `default` | 可启用/禁用 | ❌ | 按 name upsert |
| 用户规则 | `user` | ✅ | ✅ | 永不覆盖 |

**规则文件**:
- `backend/app/rules/default_rules.json` — 主默认规则集（process/execution 类型）
- `backend/app/rules/process_enhancement_rules.json` — 进程检测增强规则（behavior 类型）
- 规则通过 `backend/app/rules/loader.py` 聚合加载

> **面向角色**: 🔧运维 💻开发

---

## 7. 异常进程检测

### 7.1 功能描述

异常进程检测是整个分析引擎的核心模块。它对 Agent 采集的进程列表进行多维度的规则匹配和行为分析，输出带风险评分的异常进程清单。

### 7.2 检测流程

`backend/app/analysis/anomaly_detector.py:65-321` 中的 `detect_processes()`:

```
1. 白名单标注（标注而非剔除，保证派生链不遗漏）
2. 构建 process_map + ancestor_map（多级祖先回溯，深度 ≤10）
3. 补充 parent_name + connection_count
4. 规则匹配（process/behavior/execution 三类，含全局上下文）
5. 累加评分合并（同 PID 多规则命中累加，max=100）
6. 链路级聚合（祖先+后代同链的 risk_score 累加）
7. 白名单抑制（纯 whitelisted + 低/信息级命中 → 不误报）
```

### 7.3 检测维度

#### 进程匹配（命令行 Regex）

通过正则表达式匹配命令行中的恶意模式（`backend/app/rules/default_rules.json`）：

- `powershell_encoded_command` — PowerShell -Enc / -EncodedCommand
- `powershell_bypass_execution` — -ExecutionPolicy Bypass
- `certutil_download` — certutil -urlcache -split
- `bitsadmin_download` — bitsadmin /transfer
- `suspicious_mshta` — mshta + http/https/javascript
- `regsvr32_squiblydoo` — regsvr32 /s /u + http/https/scrobi
- `wmic_process_create` — wmic process call create
- `dotnet_inline_compilation` — csc.exe/dotnet.exe 内联编译
- `msbuild_inline_task_execution` — MSBuild InlineTasks
- `msiexec_remote_lolbin` — msiexec /i + https://

#### 行为检测

| 行为模式 | severity | 说明 |
|----------|----------|------|
| `orphan_process` | high | 父进程不存在 |
| `suspicious_parent` | high | 系统服务直接启动脚本解释器 |
| `unsigned_exe` | high | 非系统目录 exe 无签名 |
| `ancestry_chain` | high | 祖辈异常（如 svchost→cmd→powershell） |
| `time_cluster` | medium | 短时间内进程爆发 |
| `short_lived` | medium | 进程存活时间极短 |
| `zombie_process` | low | 僵尸进程 |
| `parent_pid_spoof` | high | PPID 伪造 |
| `anomalous_path` | medium | 临时目录/隐藏目录执行 |
| `anomalous_net_process` | medium | 非浏览器进程建立外连 |
| `hidden_process` | medium | 无可见窗口/路径 |
| `fileless_residency` | high | 内存驻留无磁盘落地的进程 |
| `whitelist_derived_chain` | high | 白名单父进程派生可疑子链 |
| `process_injection` | high | 进程注入痕迹 |

### 7.4 P0/P1/P2 加强规则

来自 `backend/app/rules/process_enhancement_rules.json`：

| 规则名 | 优先级 | 说明 |
|--------|--------|------|
| `fileless_reflective_injection` | P0 | Reflective DLL/Loader 注入 |
| `script_interpreter_memory_pe` | P0 | 脚本解释器内检测到 PE 内存映射 |
| `cross_session_parent` | P1 | 跨会话父进程 |
| `injection_window` | P1 | 注入窗口期（进程创建后极短时间内异常行为） |
| `process_vanished` | P1 | 进程在快照间消失 |
| `revoked_expired_sig` | P2 | 签名吊销/过期的 exe |
| `memory_injection` | P2 | 通用进程注入特征 |

### 7.5 输出字段

每个异常进程记录（`abnormal_processes` 表）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `pid` | int | 进程 ID |
| `process_name` | string | 进程名 |
| `process_path` | string | 可执行文件路径 |
| `command_line` | string | 完整命令行 |
| `parent_pid` | int | 父进程 PID |
| `parent_name` | string | 父进程名 |
| `reason` | string | 判定原因 |
| `rule_name` | string | 最高严重度规则名 |
| `severity` | string | 严重度 |
| `risk_score` | int | 累加风险评分（0-100） |
| `matched_rules` | JSON | 所有命中规则列表 `[{name, label, severity, reason}]` |
| `attack_path` | string | 攻击路径链 "A → B → C" |

> **面向角色**: 👤用户 💻开发

---

## 8. WebShell 文件检测

### 8.1 功能描述

WebShell 检测模块识别 Web 目录中的恶意脚本文件（PHP/JSP/ASP/ASPX 等），结合规则引擎的多维度匹配输出结构化的检测结果。

### 8.2 采集端

**WebShellCollector** (`agent/collectors/webshell.py`) 在目标主机上扫描 Web 目录：
- 遍历常见 Web 根目录（`/var/www`, `C:\inetpub`, Tomcat webapps 等）
- 提取文件 `sha256`，识别 `suspicious_funcs`（eval/exec/system/assert/base64_decode/passthru 等）
- 计算 `obfuscation_score`（0-1 混淆度评分）
- 冰蝎/哥斯拉通信指纹识别（`behinder_godzilla_signal`）

### 8.3 检测端

`backend/app/analysis/anomaly_detector.py:438-459` 中的 `detect_webshells()`:
- 筛选 `category=webshell` 的规则
- 通过 `RuleEngine.evaluate()` 逐条评估
- 按 `path` 聚合累加评分

### 8.4 规则示例

WebShell 规则位于 `backend/app/rules/` 中，`category: "webshell"`：

```json
{
  "name": "webshell_dangerous_funcs",
  "category": "webshell",
  "rule_type": "list",
  "condition": {
    "field": "suspicious_funcs",
    "values": ["eval", "exec", "system", "assert", "base64_decode"]
  }
}
```

### 8.5 前端面板

主机详情页 → WebShell Tab (`frontend/src/components/WebShellPanel.vue`):
- 展示 `webshells` 表命中数据
- 字段：文件路径(host path)、SHA256、严重度、风险评分(0-100)、命中规则列表
- 支持展开查看 `suspicious_funcs` 详情和完整 evidence JSON

### 8.6 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 文件路径 |
| `name` | string | 文件名 |
| `sha256` | string | SHA256 哈希 |
| `severity` | string | 严重度 |
| `risk_score` | int | 累加风险评分 |
| `matched_rules` | JSON | 命中规则列表 |
| `suspicious_funcs` | JSON | 危险函数列表 |
| `obfuscation_score` | float | 混淆度评分 (0-1) |
| `behinder_godzilla_signal` | int | 冰蝎/哥斯拉指纹 (0/1) |

> **面向角色**: 👤用户 💻开发

---

## 9. 内存码（Memory Shell）检测

### 9.1 功能描述

内存码检测针对不落盘的攻击手段，主要检测 Java 内存马（Filter 型/Agent 型）和 PHP 内存扩展，这类攻击载荷驻留在 JVM/PHP 运行时内存中，传统文件扫描无法发现。

### 9.2 采集端

**MemoryShellCollector** (`agent/collectors/memory.py`):
- JVM attach API 检测（`com.sun.tools.attach`）
- Java Agent JAR 加载痕迹
- Filter/Servlet 注册链异常检测
- PHP `dl()` / `extension` 动态加载痕迹

### 9.3 检测端

`backend/app/analysis/anomaly_detector.py:461-484` 中的 `detect_memory_shells()`:
- 筛选 `category=memory_shell` 的规则
- 按 `pid` 聚合累加评分
- `pid` 作为与进程富化的关联锚点

### 9.4 内存码类型

| 类型 | 说明 | 常见场景 |
|------|------|----------|
| `java_filter` | Java Filter 型内存马 | Tomcat/Jetty/WebLogic Filter 链注入 |
| `java_agent` | Java Agent 型内存马 | -javaagent/JVM attach 注入 |
| `php` | PHP 内存扩展 | dl()/extension 动态加载恶意 .so/.dll |
| `unknown` | 无法归类 | 保留类型 |

### 9.5 前端面板

主机详情页 → Memory Shell Tab (`frontend/src/components/MemoryShellPanel.vue`):
- PID 关联进程
- 内存码类型颜色编码
- evidence 证据展示
- 关联进程跳转

### 9.6 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `pid` | int | 关联进程 PID |
| `process_name` | string | 关联进程名 |
| `type` | string | java_filter / java_agent / php / unknown |
| `evidence` | string | 检测证据 |
| `severity` | string | 严重度 |
| `risk_score` | int | 累加风险评分 |
| `matched_rules` | JSON | 命中规则列表 |

> **面向角色**: 👤用户 💻开发

---

## 10. 统一关联引擎（correlate_incident）

### 10.1 功能描述

统一关联引擎将 WebShell 文件、内存码、进程注入、可疑外连、异常进程等多维度证据进行**加权组合**，输出 incident 级别的置信度和攻击路径，区分"单点告警"与"组合 incident"。

### 10.2 核心算法

`backend/app/analysis/anomaly_detector.py:549-672` 中的 `correlate_incident()`:

#### 加权组合（朴素贝叶斯 + Combo Boost）

1. **信号构建** (`_build_signals`): 将各维度命中转为统一信号结构 `{category, severity, evidence, finding_id, attck}`
2. **贝叶斯融合**: `C = (1 - Π(1-p_i)) × 100`，其中 `p_i` 为严重度对应基线概率：
   - critical: 0.95 | high: 0.80 | medium: 0.50 | low: 0.20 | info: 0.10
3. **Combo Boost**: 同时存在 WebShell 落盘 + 同主机内存马 → 置信度 +25（上限 100）

#### single_alert vs incident

| 分类条件 | 类型 | needs_review |
|----------|------|-------------|
| 仅 1 个信号类别 | `single_alert` | 始终 true（必经人工复核） |
| ≥2 个信号类别 | `incident` | 置信度 < 90 时 true |

#### 严重度提权

- 组合 incident + 置信度 ≥ 90 → `critical`
- 组合 incident + 置信度 ≥ 70 → `high`

### 10.3 输出结构

```json
{
  "incident_id": "INC-1234567890",
  "type": "webshell+memory_shell",
  "kind": "incident",
  "confidence": 92.5,
  "severity": "critical",
  "needs_review": false,
  "attack_path": [
    "webshell:/var/www/html/shell.php",
    "memory_shell:pid=1234 type=java_filter"
  ],
  "related_findings": ["WS-abc123", "MS-1234"],
  "attck_techniques": ["T1505.003", "T1609"],
  "attck_technique_map": {
    "T1505.003": ["WS-abc123"],
    "T1609": ["MS-1234"]
  },
  "signals": [...]
}
```

### 10.4 ATT&CK 技术映射

| 信号类别 | ATT&CK 技术 |
|----------|------------|
| `webshell` | T1505.003 (Server Software Component: Web Shell) |
| `memory_shell` | T1609 (Container Administration Command) |
| `process_injection` | T1055 (Process Injection) |
| `suspicious_connection` | T1059 (Command and Scripting Interpreter) |
| `suspicious_process` | T1547, T1564 |

> **面向角色**: 💻开发

---

## 11. 网络连接检测

### 11.1 功能描述

检测主机上的可疑外连，包括 C2 通信、反弹 Shell、恶意域名解析、异常端口等，支持威胁情报外联查询进行 IP/域名 Enrichment。

### 11.2 检测维度

`backend/app/analysis/anomaly_detector.py:323-364` 中的 `detect_connections()`:

- **IOC 规则匹配**: 网络连接中的 IP/域名命中 IOC 黑名单
- **C2 端口识别**: 默认 C2 端口集合 `{4444, 1337, 4445, 8443, 6667, 6666, 31337, 1080, 9050, 5900, 23}`
- **可疑进程外连**: 非浏览器/系统进程建立的异常外连

### 11.3 威胁情报 Enrichment

一键威胁情报检测 (`backend/app/services/enrichment_service.py`):

1. 提取公网 IP（过滤私网/回环/链路本地/多播）
2. 按 IP 去重后调用威胁情报 Provider（ThreatBook/微步等）
3. 获取 `threat_level` / `risk_score` / `tags`
4. 写回 `suspicious_connections` 表（新增列：threat_level/threat_score/threat_tags/enriched_at）

**API**: `POST /api/hosts/{host_id}/suspicious-connections/enrich`

响应:
```json
{
  "total": 50, "public": 12, "enriched": 10,
  "malicious": 3, "suspicious": 4, "skipped_private": 35,
  "errors": [{"ip": "8.8.8.8", "error": "配额耗尽"}]
}
```

### 11.4 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `protocol` | string | TCP/UDP |
| `local_address` | string | 本地地址 |
| `local_port` | int | 本地端口 |
| `remote_address` | string | 远程地址 |
| `remote_port` | int | 远程端口 |
| `state` | string | 连接状态 |
| `process_name` | string | 关联进程 |
| `pid` | int | 进程 PID |
| `threat_level` | string | 威胁等级 (high/medium/low/null) |
| `threat_score` | int | 威胁评分 (0-100) |
| `threat_tags` | JSON | 威胁标签 |

> **面向角色**: 👤用户 💻开发

---

## 12. 持久化与启动项

### 12.1 功能描述

检测主机上的持久化机制（注册表 Run 键、计划任务、系统服务、WMI 订阅、cron/systemd 等），识别攻击者用于维持访问的后门。

### 12.2 检测范围

`backend/app/analysis/persistence_finder.py` 覆盖以下持久化位置：

**Windows**:
- 注册表 Run/RunOnce 键（HKLM/HKCU）
- 计划任务（Scheduled Tasks）
- 系统服务（Services，含异常 ImagePath）
- WMI 事件订阅（`__EventFilter` / `__EventConsumer` 绑定）
- 启动文件夹
- AppInit_DLLs / Winlogon Shell

**Linux**:
- cron 任务（/etc/crontab, /var/spool/cron）
- systemd 服务（/etc/systemd/system, /usr/lib/systemd/system）
- /etc/rc.local
- .bashrc / .profile 注入
- LD_PRELOAD

### 12.3 检测流程

1. `PersistenceFinder.find_all()` — 枚举所有持久化点
2. `PersistenceFinder.assess_suspicious()` — 与规则引擎匹配评估可疑度
3. 结果写入 `persistence_items` 表（`is_suspicious=0/1`）

### 12.4 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 持久化类型（registry/scheduled_task/service/wmi/cron/systemd） |
| `name` | string | 持久化项名称 |
| `command` | string | 执行的命令 |
| `location` | string | 所在位置 |
| `user` | string | 所属用户 |
| `is_suspicious` | int | 是否可疑 (0/1) |
| `reason` | string | 判定原因 |

### 12.5 启动项检测

`backend/app/analysis/anomaly_detector.py:366-400` 中的 `detect_startup_items()` 专门检测启动项异常：

**API**: `GET /api/hosts/{host_id}/startup-items`

> **面向角色**: 👤用户 💻开发

---

## 13. IOC（威胁情报）匹配

### 13.1 功能描述

IOC 匹配模块在采集数据中搜索已知的威胁指标（IP/域名/哈希/URL），包括 built-in known_bad_hashes、WebShell SHA256 黑名单、签名吊销（revoked_ca）匹配和文件哈希 JOIN 检测。

### 13.2 IOC 检测源

`backend/app/analysis/ioc_checker.py:16-138` 中的 `IocChecker.check()`:

1. **Agent 自带 IOC**: 读取 `raw_data.ioc.matched_items`
2. **网络连接 IOC**: `known_bad_ip` / `known_bad_domain` 规则匹配
3. **进程命令行 IOC**: `list` 型规则（`field=remote_address` 等）在进程中匹配
4. **文件哈希 IOC**: 从 `raw_data.files.suspicious_files` 匹配 `known_bad_hashes`
5. **WebShell 哈希 IOC**: `webshells[].sha256` 与 `known_bad_hashes` 匹配

### 13.3 FIELD_TO_IOC_TYPE 动态注入

规则引擎在执行 `list` 型规则时，通过 `FIELD_TO_IOC_TYPE` 映射自动将字段值归入对应的 IOC 类型：

```python
FIELD_TO_IOC_TYPE = {
    "remote_address": "ip",
    "domain": "domain",
    "sha256": "hash",
    "exe_sha256": "hash",
    "file_hash": "hash",
    ...
}
```

这使得 `malicious_hash_process` 规则（`backend/app/rules/process_enhancement_rules.json:2-18`）可以动态将进程 `exe_sha256` 与 `iocs.hash` 表进行实时匹配。

### 13.4 IOC 管理

IOC 管理独立于分析引擎，提供 CRUD 接口（`backend/app/api/iocs.py`）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/iocs` | GET | IOC 列表（?ioc_type=ip/domain/url/hash） |
| `/api/iocs` | POST | 新增单条 IOC |
| `/api/iocs/{ioc_id}` | PUT | 更新 IOC（启用开关/描述） |
| `/api/iocs/{ioc_id}` | DELETE | 删除 IOC |
| `/api/iocs/import` | POST | 批量导入 IOC |

### 13.5 IOC 外联查询（Enrichment）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/iocs/{ioc_id}/enrich` | POST | 外联查询单个 IOC（仅 ip/domain） |
| `/api/iocs/enrich/batch` | POST | 批量外联查询 |
| `/api/iocs/{ioc_id}/threat-intel` | GET | 获取 IOC 全部情报历史 |

### 13.6 IOC 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `ioc_type` | string | ip / domain / url / hash / cert |
| `ioc_value` | string | IOC 值 |
| `matched_in` | string | 命中位置描述 |
| `context` | string | 上下文信息（命令行/路径等） |
| `severity` | string | 严重度 |

### 13.7 种子 IOC

数据库初始化时自动导入 4 条示例种子 IOC（`backend/app/database.py:672-703`）：
- `malware-c2.example.com` (domain)
- `botnet-cc.example.net` (domain)
- `http://185.220.101.1/loader` (url)
- `185.220.101.1` (ip)

> **面向角色**: 👤用户 💻开发

---

## 14. 进程树视图

### 14.1 功能描述

进程树视图提供交互式的进程父子关系可视化，帮助分析人员快速理解进程派生关系并定位异常进程链。

### 14.2 进程树构建

`backend/app/analysis/process_tree_builder.py` 中的 `ProcessTreeBuilder.build()`:

- **输入**: `processes` 列表（pid/ppid/name/path/command_line）
- **输出**: 嵌套树结构，适配 ECharts tree series
- **富信息模式** (`enrich=True`): 节点增量追加 `severity` / `parent_name` / `connections` / `attack_path` 等增强字段

**API**: `GET /api/hosts/{host_id}/process-tree?enrich=1`

### 14.3 前端组件

#### ProcessTreeView

在主机详情页的"进程树"Tab 中渲染，使用 ECharts tree series，支持：
- 节点展开/折叠
- 异常进程红色高亮
- 节点悬浮显示详情（PID/路径/命令行/风险评分）
- 点击节点跳转进程详情

#### ProcessTreeChart

基于 ECharts 的交互式树图，`enrich=false` 兼容历史模式。

### 14.4 KPI 统计

进程树视图附带 KPI 统计卡片：
- 总进程数
- 异常进程数
- 最大进程深度
- 异常链数量

### 14.5 搜索筛选

支持按 PID、进程名、命令行关键字搜索并高亮定位。

> **面向角色**: 👤用户

---

## 15. 前端功能面板

### 15.1 路由地图

`frontend/src/router/index.js`:

| 路由 | 组件 | 说明 |
|------|------|------|
| `/login` | LoginView | 登录页（无需认证） |
| `/` | CaseListView | 案件列表（首页/仪表盘） |
| `/cases/:id` | CaseDetailView | 案件详情 + 主机列表 |
| `/hosts/:id` | HostDetailView | 主机详情（含所有分析 Tab） |
| `/hosts/:id/report` | ReportView | HTML 报告查看 |
| `/rules` | RulesView | 规则管理 |
| `/whitelist` | WhitelistView | 白名单管理 |
| `/iocs` | IocsView | IOC 管理 |
| `/ai` | AiView | AI 配置 + 分析管理 |
| `/threat-intel-config` | ThreatIntelConfigView | 威胁情报外联配置 |
| `/knowledge` | KnowledgeView | 知识库 |
| `/knowledge/detail/:entryRef` | KnowledgeDetailView | 知识条目详情 |

### 15.2 登录页面

- 用户名 + 密码表单
- JWT Token 存储于 Pinia authStore
- 路由守卫：未认证重定向到 `/login`

### 15.3 导航（AppLayout）

左侧垂直菜单栏，含：
- 案件管理
- 规则管理
- 白名单
- IOC 管理
- AI 分析
- 威胁情报配置
- 知识库

### 15.4 仪表盘

案件列表页展示关键统计：
- 案件总数 / 活跃案件 / 已结案
- 主机总数 / 各状态分布
- 近期分析活动

### 15.5 主机详情页

主机详情 (`HostDetailView.vue`) 是所有分析数据的中心展示页面，通过多个 Tab 切换：

| Tab 名称 | 组件/内容 |
|----------|----------|
| 概览 | 主机画像卡片 + 风险评级 |
| 异常进程 | 异常进程表格，含 risk_score/severity/matched_rules/attack_path |
| 网络连接 | 网络连接列表 + 一键威胁情报检测按钮 |
| IOC 命中 | IOC 匹配结果表 |
| WebShell | WebShellPanel (`frontend/src/components/WebShellPanel.vue`) |
| Memory Shell | MemoryShellPanel (`frontend/src/components/MemoryShellPanel.vue`) |
| 事件 | IncidentPanel + FusionAttckMatrix |
| 时间线 | 时间线视图（支持筛选/处置/CSV导出/PDF导出/多主机对比） |
| 启动项 | 可疑启动项表 |
| 持久化 | 持久化痕迹表 |
| 进程树 | ProcessTreeView / ProcessTreeChart |
| AI 分析 | AI 分析报告面板 |
| 报告 | 报告查看 + 处置清单 Checklist |

### 15.6 威胁情报配置

`ThreatIntelConfigView.vue` 管理威胁情报 Provider 和运行策略：
- Provider 列表（ThreatBook/微步等）
- 启用/禁用 Provider
- 速率限制（QPS）
- API Key 配置（安全存储，不暴露在 UI 中）
- 运行策略：日配额、重检间隔、自动模式开关

### 15.7 AI 分析模块

`AiView.vue` 提供：
- AI 配置 Profile 管理（多 Provider 支持）
- 活跃 Profile 切换
- API 连接测试
- AI 分析任务提交
- 任务状态轮询 + SSE 流式进度
- 报告版本管理 + Diff 对比
- 审计日志查询

### 15.8 报告导出

- **HTML 报告**: `GET /api/hosts/{host_id}/report?report_level=technical|executive`
- **PDF 报告**: `GET /api/hosts/{host_id}/report/pdf`
- **AI PDF 报告**: `GET /api/ai/report/{host_id}/pdf`
- **时间线 CSV**: `GET /api/analysis/timeline/{host_id}/export/csv`
- **时间线 PDF**: `GET /api/analysis/timeline/{host_id}/export/pdf`

> **面向角色**: 👤用户

---

## 16. AI 分析模块

### 16.1 功能描述

AI 分析模块利用大语言模型（LLM）对主机分析结果进行深度解读，生成结构化的分析报告。支持多 Provider、报告版本管理、提示词优化、异步任务、审计日志等企业级功能。

### 16.2 AI 分析模式

| 模式 | `mode` 值 | 说明 |
|------|-----------|------|
| 标准分析 | `standard` | 全量四维度分析（风险评估/威胁分析/时间线/处置建议） |
| 概览模式 | `overview` | 领导层适用的简要概述 |
| 处置建议 | `remediation` | 聚焦处置建议 |
| 多轮对话 | `chat` | 带上下文的交互式 AI 对话 |

### 16.3 AI Provider 支持

| Provider | 说明 |
|----------|------|
| `openai` | OpenAI (ChatGPT/GPT-4) |
| `azure` | Azure OpenAI |
| `anthropic` | Anthropic (Claude) |
| `ollama` | Ollama 本地模型 |
| `deepseek` | DeepSeek |
| `zhipu` | 智谱 (GLM) |
| `qwen` | 通义千问 |
| `moonshot` | Moonshot (Kimi) |
| `custom` | 自定义兼容接口 |

### 16.4 分析流程

```
1. 触发分析 → POST /api/ai/analyze/{host_id}?mode=standard&masked_mode=1
2. 异步任务创建 → ai_tasks 表 (status=pending)
3. 后台执行 (AiTaskService):
   a. 加载主机分析结果 + 原始数据
   b. 数据脱敏处理（脱敏模式下替换敏感信息）
   c. 构建 Prompt（含规则命中/IOC/异常进程/时间线/基线差分）
   d. 调用 LLM API（带重试+断路器）
   e. 解析 LLM 响应 → risk_assessment/threat_analysis/timeline_analysis/recommendations
   f. 保存报告到 ai_analysis_reports（版本管理）
   g. 写入审计日志 ai_audit_log
4. 前端 SSE 流式获取进度 → GET /api/ai/tasks/{task_id}/stream
5. 结果获取 → GET /api/ai/report/{host_id}
```

### 16.5 AI 分析报告结构

```json
{
  "risk_assessment": {
    "risk_level": "high",
    "confidence": 85,
    "key_findings": [...],
    "data_gaps": [...]
  },
  "threat_analysis": {
    "attack_vectors": [...],
    "threat_actors": "...",
    "mitre_attack_mapping": [...]
  },
  "timeline_analysis": {
    "key_events": [...],
    "attack_chain": [...]
  },
  "recommendations": {
    "immediate_actions": [...],
    "long_term": [...]
  },
  "version": 1,
  "analysis_type": "full",
  "audience": {"role": "technical", "detail_level": "deep"},
  "mitre_attack": ["T1059", "T1505.003"],
  "attack_chain_hits": [...],
  "rare_high_signals": [...]
}
```

### 16.6 版本管理

- 每次 AI 分析生成新版本（`version` 递增）
- `is_latest` 标记最新版本
- 支持版本 Diff 对比: `GET /api/ai/report/{host_id}/diff?v1=1&v2=2`
- 最多保留全部历史版本

### 16.7 Prompt 优化

`POST /api/ai/prompt/optimize` — 基于用户反馈调用 LLM 自动优化 system_prompt：
- 保存到 `ai_prompt_versions` 表
- 最多保留 5 个历史版本

### 16.8 审计日志

`ai_audit_log` 表记录每次 AI 调用：
- 调用的 Profile/模型
- Token 消耗（prompt_tokens/completion_tokens）
- 延迟（latency_ms）
- 脱敏模式（masked_mode）
- 完整 prompt 和 response（可选存储）

### 16.9 Token 统计

`GET /api/ai/stats/tokens?days=30` — 按日聚合 Token 消耗
`GET /api/ai/stats/summary` — 汇总统计卡片

### 16.10 只读派发

`POST /api/ai/analyze/{host_id}/dispatch-readonly` — AI 建议的只读采集命令派发：
- 仅接受 `auto_runnable=true` 的只读命令
- `timeout=120s` 子进程执行
- 全程审计
- 结果回填 `ai_evidence_refills`
- **绝不 kill/隔离/改配**

> **面向角色**: 👤用户 💻开发

---

## 17. 知识库系统

### 17.1 知识库概述

知识库系统是 IR 平台的 **AI 驱动的威胁知识管理中心**。它形成完整闭环：AI 分析主机时发现未知威胁模式 → 自动生成知识条目草稿 → 管理员审核（批准/拒绝/撤回）→ 批准后自动入库 ChromaDB 向量索引 → 后续 AI 分析通过 RAG 检索复用这些知识，提升分析准确性和可解释性。

**核心能力**:
- **向量语义检索**: ChromaDB + sentence-transformers，根据当前分析数据语义匹配最相关的威胁知识
- **种子知识数据**: 内置 10 条 MITRE ATT&CK + C2 框架 + 恶意软件行为模式，开箱即用
- **知识草稿管理**: AI 自动建议 → 人工审核 → 入库的闭环工作流，三元组去重
- **手动导入**: 支持结构化 JSON 条目和自由文本 IOC 列表导入
- **第三方同步**: 对接 VirusTotal / AbuseIPDB / AlienVault OTX，拉取外部威胁情报

**数据库表**: `knowledge_drafts`（`backend/app/database.py:499-515`），含 14 列（id / host_id / analysis_report_id / title / description / category / severity / mitre_attack / pattern / status / source / raw_ioc / created_at / reviewed_at）。

> **面向角色**: 👤用户 🔧运维 💻开发

### 17.2 种子知识数据

平台内置 10 条种子知识（`backend/app/data/knowledge_seed.py`），通过 `ALL_SEED_KNOWLEDGE` 聚合，在 ChromaDB 向量库为空时作为初始索引数据源。

**种子知识分类**:

| 分类 | 条目数 | 内容 |
|------|--------|------|
| MITRE ATT&CK 技术 | 5 条 | T1059.001 PowerShell 无文件攻击 / T1546.003 WMI 事件订阅 / T1547 启动项持久化 / T1055 进程注入 / T1071 应用层 C2 协议 |
| C2 框架特征 | 3 条 | Cobalt Strike Beacon / Metasploit Meterpreter / PowerShell Empire |
| 恶意软件行为模式 | 2 条 | 勒索软件行为模式（加密→删影副本→勒索信） / 窃密木马行为模式（窃浏览器凭据→压缩→外传） |

**种子条目格式**（`knowledge_seed.py:15-78`）:

```json
{
  "id": "T1059.001",
  "name": "PowerShell (无文件攻击)",
  "description": "攻击者利用 PowerShell 执行无文件恶意代码...",
  "tactic": "Execution",
  "severity": "high",
  "category": "mitre_attack"
}
```

C2 框架和恶意软件条目额外包含 `pattern` 字段（空格分隔的检测关键词），用于关键词回退匹配时额外加分（`knowledge_retriever.py:1037-1039`）。

种子数据通过 `GET /api/knowledge/seeds` API 可查询，前端可直接展示。

> **面向角色**: 💻开发

### 17.3 向量语义检索

知识库检索器（`backend/app/services/knowledge_retriever.py`）是 RAG（检索增强生成）的核心组件。

**架构**:

```
┌─────────────────────────────────────────────────────────────┐
│                   KnowledgeRetriever                        │
│                                                             │
│  ┌──────────────────┐    ┌──────────────────────────────┐  │
│  │ sentence-         │    │  ChromaDB (PersistentClient) │  │
│  │ transformers      │───▶│  collection: ir_rules        │  │
│  │ all-MiniLM-L6-v2  │    │  backend/data/chroma/        │  │
│  │ (384 维向量)       │    │  hnsw:space = cosine         │  │
│  └──────────────────┘    └──────────────────────────────┘  │
│                                                             │
│  检索优先级:                                                 │
│  1. 向量语义检索 (cosine distance < 0.7)                    │
│  2. 关键词匹配回退 (chromadb/embedding 不可用时)             │
└─────────────────────────────────────────────────────────────┘
```

**关键参数**（`knowledge_retriever.py:50-56`）:
- 模型: `all-MiniLM-L6-v2`（384 维，轻量快速，首次下载约 80MB 到 `~/.cache/torch/sentence_transformers/`）
- Collection: `ir_rules`，距离度量 `cosine`
- 持久化路径: `backend/data/chroma/`
- 相似度阈值: `cosine distance < 0.7`（等价于 similarity > 0.3）

**检索流程**（`KnowledgeRetriever.retrieve()`, `knowledge_retriever.py:757-796`）:

1. **延迟初始化**（`_ensure_index`, `knowledge_retriever.py:681-703`）: 首次调用时自动构建规则索引（`_build_index`）和种子索引（`_build_seed_index`），均为幂等操作
2. **构建查询文本**（`_build_query_text`, `knowledge_retriever.py:467-596`）: 从分析数据中提取主机信息、异常进程名/命令行、可疑外连地址、IOC 命中、持久化痕迹、时间线事件，拼接为自然语言查询串
3. **向量检索**（`_vector_retrieve`, `knowledge_retriever.py:803-927`）: 将查询文本编码为 384 维向量，在 ChromaDB 中查询 Top-K，按 distance 阈值过滤，去重后返回
4. **关键词回退**（`_keyword_retrieve`, `knowledge_retriever.py:934-1121`）: 当 ChromaDB 或 embedding 模型不可用时，降级为关键词匹配（规则名精确命中 ≥3 分、描述词命中 ≥2 个 +1.5 分、严重度加权加分等）

**索引构建幂等性**:
- 规则索引（`_build_index`, `knowledge_retriever.py:220-305`）: 检查 `collection.count() > 0`，已有记录跳过
- 种子索引（`_build_seed_index`, `knowledge_retriever.py:325-459`）: 按 `source` 元数据精确判定 `seed/draft` 是否已写入，不依赖 `collection.count()`（规则 `rule_*` 的存在会误判早退）

**结构化证据输出**: `retrieve(structured=True)` 返回带 `entry_ref` / `entry_type` / `confidence` / `match_reason` 字段的字典列表，前端可点击溯源跳转到知识详情页。

#### 17.3.4 模型升级 (v1.0 修订)

自 v1.0 发布后，嵌入模型已从 `all-MiniLM-L6-v2`（384维/80MB）升级为 **`BAAI/bge-base-zh-v1.5`**（768维/420MB），针对性优化中英混合安全知识库场景：
- BGE 系列在中文安全术语（如"PowerShell 无文件攻击""编码命令执行""Cobalt Strike Beacon"）的语义区分能力优于通用多语言模型
- 768维向量提供更高的语义精度，余弦距离阈值保持 <0.7
- 模型名定义：`knowledge_retriever.py:50` `EMBEDDING_MODEL_NAME = "BAAI/bge-base-zh-v1.5"`
- 模型需手动下载（见 17.11 模型下载指南）

#### 17.3.5 规则全量索引修复

当前 `_load_rules()` 已从仅加载 `default_rules.json`（102条）改为调用 `rules/loader.py::load_default_rules()`，遍历全部 5 个 JSON 规则文件，共索引 **133 条**规则（含 `process_enhancement_rules.json` 的 webshell/memory_shell 规则、`seed_rules_process.json`、`default_attack_chain.json`、`revoked_ca.json`）。代码位置：`knowledge_retriever.py:137-157`。

#### 17.3.6 查询截断

向量检索前自动对查询文本和规则描述做截断处理：超过 512 字符时截断（与 sentence-transformers max_seq_length=256 tokens 匹配）。代码位置：`knowledge_retriever.py:598-607` `_build_query_text()`。

> **面向角色**: 💻开发

### 17.3A 向量检索质量自检

**功能描述**：提供 `POST /api/knowledge/validate-retrieval` 端点，支持输入测试查询列表，返回 Top-3 语义匹配结果及置信度。用于在模型部署后验证向量检索召回质量。

**使用场景**：
- 部署新模型后验证检索是否可用
- 知识库内容更新后检查召回率
- 排查"检索无结果"问题时快速定位

**操作流程**：
1. 确保嵌入模型已下载并重启服务
2. POST `/api/knowledge/validate-retrieval`（需认证），请求体：`{"queries": ["Cobalt Strike Beacon HTTP 心跳", "PowerShell base64 编码执行", "勒索软件 vssadmin 删除卷影"]}`
3. 响应返回每条 query 的 top3 匹配结果及 score

**预期结果**：每个 query 返回 1-3 条语义相关条目，score > 0.5 视为有效召回。

**技术实现**：
- API 端点：`knowledge_draft.py`（`POST /api/knowledge/validate-retrieval`）
- 逻辑：遍历 queries → 逐条调用 `KnowledgeRetriever.retrieve({"query": q}, limit=3, structured=True)` → 聚合返回
- **嵌入模型未下载时**：返回 `{"error": "embedding_not_available", "message": "嵌入模型未下载，无法运行向量检索质量自检"}`（不抛异常）

> **面向角色**: 💻开发

### 17.4 知识草稿管理

知识草稿是 AI 分析与知识库之间的桥梁，实现"发现未知 → 自动建议 → 人工审核 → 入库检索"的闭环。

**状态流转**（`backend/app/models/knowledge_draft.py`）:

```
AI 分析发现未知威胁
       │
       ▼
  ┌─────────┐     approve     ┌──────────┐
  │ pending  │ ──────────────▶ │ approved │ ──▶ ChromaDB 种子索引自动重建
  └─────────┘                 └──────────┘
       │                           │
       │ reject                    │ recall
       ▼                           ▼
  ┌─────────┐                 ┌──────────┐ (恢复为 pending)
  │ rejected│                 │ pending   │
  └─────────┘                 └──────────┘
```

**关键方法**（`knowledge_draft.py`）:

| 方法 | 行号 | 功能 |
|------|------|------|
| `create()` | 24-81 | 创建草稿（AI 建议 / 手动导入 / 外部同步） |
| `get_by_id()` | 84-90 | 按 ID 查询详情 |
| `get_all()` | 93-122 | 列表查询，支持 `status` + `host_id` 过滤 |
| `list_pending()` | 125-127 | 查询全部待审核草稿 |
| `list_approved()` | 130-132 | 查询全部已批准草稿 |
| `approve()` | 135-166 | 批准：更新 status='approved'，记录 reviewed_at |
| `reject()` | 169-198 | 拒绝：更新 status='rejected'，记录 reviewed_at |
| `recall()` | 201-232 | 撤回：将 approved/rejected 恢复为 pending |
| `batch_action()` | 235-279 | 批量批准/拒绝，统计成功/失败/错误原因 |
| `is_duplicate()` | 282-309 | 三元组去重 (title, category, mitre_attack) |
| `get_as_seed_entries()` | 312-337 | 将已批准草稿转为种子格式（id=`draft_{id}`） |

**批准自动入库**（`backend/app/api/knowledge_draft.py:144-165`）: 批准 API 调用 `approve()` 后，自动触发 `KnowledgeRetriever.rebuild_seed_index()`（`knowledge_retriever.py:706-751`），先删除 ChromaDB 中旧 seed/draft 条目，再重新加载已批准草稿并向量化写入。拒绝和撤回操作同样触发索引重建。

**三元组去重**: `is_duplicate(title, category, mitre_attack)` 确保同一标题+分类+MITRE 技术的草稿不会重复创建。

#### 17.4.1 自动审核规则 (v1.0 修订)

导入知识草稿时，系统自动判断是否可自动批准，减少人工审核负担：

| 条件 | 行为 |
|------|------|
| source="rule_import" 且 severity∈{"critical","high"} | 自动批准 → 触发 ChromaDB 索引重建 |
| source∈{"virustotal","abuseipdb","alienvault_otx"} 且 IOC 恶意数 > 5 | 自动批准 → 触发 ChromaDB 索引重建 |
| source="rule_import" 且 severity="medium" | status=pending（需人工审核） |
| 其余 | status=pending |

代码位置：`knowledge_draft.py` `_auto_approve()` 函数。

> **面向角色**: 👤用户 🔧运维 💻开发

### 17.5 手动导入

手动导入支持两种格式（`backend/app/api/knowledge_draft.py:241-323`），通过 `POST /api/knowledge/import` 提交。

**格式一：结构化 JSON 条目**

```json
{
  "items": [
    {
      "title": "Sliver C2 框架",
      "description": "Sliver 是基于 Go 语言的开源 C2 框架...",
      "category": "c2_framework",
      "severity": "high",
      "mitre_attack": "T1071",
      "pattern": "sliver mtls wireguard operator"
    }
  ]
}
```

**格式二：自由文本 IOC 列表**（`_parse_text_items`, `knowledge_draft.py:61-85`）

```
# 支持中文冒号
可疑域名 C2: 攻击者使用该域名进行 C2 通信
# 支持英文冒号
Malicious IP: Known C2 server IP address
# 纯标题行（description 与 title 相同）
异常注册表键值 RunOnce 持久化
```

解析规则：每行一个条目，`#` 开头的注释行跳过，按 `：` 或 `:` 分割标题与描述，纯标题行则 description 与 title 相同。

**校验**:
- title + description 必填，不合格跳过
- 三元组去重检查（`is_duplicate`）
- 导入后 status = pending，source = manual，需管理员审核

> **面向角色**: 👤用户 🔧运维

### 17.6 第三方威胁情报同步

`POST /api/knowledge/sync/{provider}` 从外部威胁情报平台拉取 IOC 列表并写入知识草稿区（`backend/app/api/knowledge_draft.py:326-425`）。

**支持的 Provider**:

| Provider | 参数 | 描述 |
|----------|------|------|
| `virustotal` | `?limit=50` | VirusTotal 威胁情报 |
| `abuseipdb` | `?limit=50` | AbuseIPDB 恶意 IP 数据库 |
| `alienvault_otx` | `?limit=50` | AlienVault Open Threat Exchange |

**同步流程**:
1. 校验 provider 名称（仅支持以上三种）
2. 调用 `enrichment_service.fetch_ioc_list(provider, limit)` 获取 IOC 列表
3. 逐条写入 `knowledge_drafts`（status=pending, source=external）
4. 三元组去重，避免重复同步
5. 返回 `{provider, synced: N, message}`

**限制**: 同步依赖 `enrichment_service` 可用，需正确配置威胁情报 API Key（`backend/.env`）。同步条目需管理员审核后方可入库。

> **面向角色**: 🔧运维

### 17.7 前端面板

知识库前端由三个核心组件构成，路由在 `frontend/src/router/index.js` 中注册。

#### 知识库列表页（KnowledgeView）

路由: `/knowledge`（`frontend/src/views/KnowledgeView.vue`）

功能:
- **三 Tab 切换**: 已入库（approved）/ 待审核（pending）/ 已拒绝（rejected），各 Tab 带数量角标
- **表格展示**: 标题、描述（截断 60 字符）、分类标签、严重程度标签、来源标签（ai_suggest/manual/external）、审核时间
- **批量操作**: 待审核 Tab 支持多选 + 批量批准/拒绝，顶部显示已选数量
- **手动导入**: 弹窗表单，支持结构化条目（动态添加行）和自由文本 IOC（textarea）
- **第三方同步**: 下拉菜单选择 VirusTotal / AbuseIPDB / AlienVault OTX，触发同步
- **撤回**: 已入库/已拒绝条目可撤回至待审核
- **搜索过滤**: 支持按状态和主机过滤

#### 知识条目详情页（KnowledgeDetailView）

路由: `/knowledge/detail/:entryRef`（`frontend/src/views/KnowledgeDetailView.vue`）

`entryRef` 解析逻辑（`parseEntryRef`）:
- `seed_*` → 种子知识条目（展示 name/description/category/severity/tactic/pattern）
- `draft_*` → 已批准草稿条目（展示完整元数据 + 审批/拒绝/撤回按钮）
- `rule_*` → 规则引擎命中（引导用户前往规则库查看）
- `unknown` → 旧版数据或无法识别（展示友好空态）

#### 主机关联知识 Tab（HostKnowledgeTab）

入口: 主机详情页 → 知识库 Tab（`frontend/src/components/HostKnowledgeTab.vue`）

功能:
- 展示该主机相关的待审核知识草稿（按 `host_id` 过滤）
- 支持快速审核（批准 / 拒绝）
- "全部批准"一键操作

#### 侧边栏导航

`frontend/src/components/AppLayout.vue` 侧边栏包含「知识库」菜单项，链接至 `/knowledge`。

> **面向角色**: 👤用户

### 17.8 API 参考

知识库 API 由 `backend/app/api/knowledge_draft.py` 提供，全部 11 个端点均需 JWT 认证（`Depends(get_current_user)`）。

| # | 路径 | 方法 | 说明 |
|---|------|------|------|
| 1 | `/api/knowledge/drafts` | GET | 草稿列表 `?status=pending\|approved\|rejected&host_id=` |
| 2 | `/api/knowledge/seeds` | GET | 内置种子知识数据（10 条） |
| 3 | `/api/knowledge/drafts/{id}` | GET | 单条草稿详情（供证据溯源跳转） |
| 4 | `/api/knowledge/drafts/{id}/approve` | POST | 批准草稿 → 自动重建 ChromaDB 种子索引 |
| 5 | `/api/knowledge/drafts/{id}/reject` | POST | 拒绝草稿 → 自动重建种子索引 |
| 6 | `/api/knowledge/drafts/{id}/recall` | POST | 撤回至待审核 → 自动重建种子索引 |
| 7 | `/api/knowledge/drafts/batch` | POST | 批量批准/拒绝 `{ids:[...], action:"approve\|reject"}` |
| 8 | `/api/knowledge/import` | POST | 手动导入 `{items:[...], text:"..."}` |
| 9 | `/api/knowledge/sync/virustotal` | POST | VirusTotal 同步 `{limit:50}` |
| 10 | `/api/knowledge/sync/{provider}` | POST | 通用同步（abuseipdb / alienvault_otx） |
| 11 | `/api/knowledge/validate-retrieval` | POST | 向量检索质量自检 `{"queries":["..."]}` |

**curl 示例**:

```bash
TOKEN="eyJ..."
BASE="http://localhost:8000/api/knowledge"

# 获取待审核草稿
curl -s "$BASE/drafts?status=pending" -H "Authorization: Bearer $TOKEN"

# 获取种子数据
curl -s "$BASE/seeds" -H "Authorization: Bearer $TOKEN"

# 批准草稿（自动入库 ChromaDB）
curl -s -X POST "$BASE/drafts/1/approve" -H "Authorization: Bearer $TOKEN"

# 批量批准
curl -s -X POST "$BASE/drafts/batch" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ids":[1,2,3],"action":"approve"}'

# 手动导入（结构化 + 自由文本）
curl -s -X POST "$BASE/import" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"title":"测试规则","description":"描述","category":"auto","severity":"medium"}],"text":"可疑域名: 用于C2通信"}'

# 第三方同步
curl -s -X POST "$BASE/sync/virustotal" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit":30}'

# 向量检索质量自检
curl -s -X POST "$BASE/validate-retrieval" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"queries":["Cobalt Strike Beacon HTTP 心跳","PowerShell base64 编码执行"]}'
```

**统一响应格式**: `{"code":0,"data":{...},"message":"..."}`

| 场景 | HTTP 状态码 | code |
|------|------------|------|
| 成功 | 200 | 0 |
| 无效 status 参数 | 400 | — |
| 草稿不存在 | 404 | — |
| 非 pending 状态操作 | 400 | — |
| 无效 provider | 400 | — |
| 同步 upstream 失败 | 502 | 1 |

> **面向角色**: 💻开发

### 17.9A RAG 与异常检测集成 — 双路检测 (v1.0 修订)

**功能描述**：分析阶段（`analysis_service.analyze()`）同时运行规则引擎和向量语义检索，两者结果做交叉验证合并，弥补传统规则引擎对"变种攻击"的盲区。

**架构**：
```
raw_data → 规则引擎(正则匹配) ─┐
                              ├→ 交叉验证 → 合并结果
raw_data → 向量语义检索 ──────┘
```

**交叉验证逻辑**（`analysis_service.py` `_cross_validate()`）：
- `process_name` 相同的规则命中和语义命中 → 合并为一条，取最高置信度
- 规则命中 + 语义命中同时存在 → confidence 提升一档（medium→high, low→medium）
- 仅语义命中无规则命中 → `needs_review=True`, `confidence="low"`
- 合并后的 `knowledge_hits` 写入分析结果的 `findings` 字段

**前端展示**：`AbnormalProcessTable.vue` 中，有语义匹配标签的进程行后方显示 "📚" badge（clickable，el-tooltip 显示匹配到的知识条目名称和 confidence）。

**性能考量**：
- 模型推理：CPU ~150-400ms/次（768维 BGE 模型）
- ChromaDB 查询：<10ms
- 全流程增加约 1-3s（取决于命中进程数）

> **面向角色**: 💻开发

### 17.9B 规则→知识批量导入 (v1.0 修订)

**功能描述**：提供独立脚本 `backend/scripts/import_rules_to_knowledge.py`，将全部 135 条检测规则批量导入知识库草稿，用于初始化向量索引的数据基础。

**使用场景**：
- 首次部署嵌入模型后，快速填充 ChromaDB 索引
- 规则更新后重新同步到知识库

**操作流程**：
1. 预览模式：`python scripts/import_rules_to_knowledge.py --dry-run`（输出映射预览，不实际提交）
2. 正式导入：`python scripts/import_rules_to_knowledge.py`（调用 POST /api/knowledge/import 批量提交）
3. 登录前端审核 pending 状态的草稿（或自动审核通过 critical/high 规则）

**字段映射**：`name→title, description→description, category→category, severity→severity, _meta.mitre_attack→mitre_attack, label→pattern, source="rule_import"`

**技术实现**：
- 读取：`rules/loader.py::load_default_rules()` 获取全部规则
- 导入：HTTP 调 POST /api/knowledge/import
- 去重：复用 `KnowledgeDraft.is_duplicate(title, category, mitre_attack)`
- 自动审核：critical/high 规则导入后自动批准 + 触发 ChromaDB 索引重建

> **面向角色**: 💻开发

### 17.9C 第三方威胁情报同步增强 (v1.0 修订)

**功能描述**：三个威胁情报 provider 新增 `fetch_list()` 方法，支持拉取最新 IOC 列表并自动导入知识草稿。

**Provider 实现**（代码位置）：

| Provider | 方法 | API 端点 | 文件 |
|----------|------|---------|------|
| VirusTotal | `fetch_list(limit=20)` | /api/v3/intelligence/search | `virustotal_provider.py` |
| AbuseIPDB | `fetch_list(limit=20)` | /api/v2/blacklist | `abuseipdb_provider.py` |
| AlienVault OTX | `fetch_list(limit=20)` | /api/v1/pulses/subscribed | `alienvault_otx_provider.py` |

**统一聚合**：`EnrichmentService.fetch_all_ioc_lists(limit=20)` → 并行调用三个 provider → 按 ioc_value 去重 → 汇聚返回统一格式：`[{"ioc_type":"ip"/"domain"/"hash","ioc_value":"...","description":"...","severity":"high"/"medium"/"low","source":"virustotal"/"abuseipdb"/"alienvault_otx"}]`

**定时同步**（`main.py` `_register_scheduled_tasks()`）：使用 apscheduler，每天凌晨 03:00 自动调用 `fetch_all_ioc_lists(limit=100)` → 批量导入知识草稿 → 自动审核。同步失败仅记录日志，不影响服务。

**容错**：API key 未配置时 `fetch_list()` 返回 `[]` 不抛异常。

> **面向角色**: 💻开发

### 17.9 RAG 与 AI 分析集成

知识库检索结果通过 RAG 模式注入 LLM 分析上下文，提升分析准确性与可解释性。

**Prompt 注入**（`backend/app/services/prompt_builder.py:139,160,181,207,234,260,281,302,324,345,366,387,438`）:

所有 AI 分析模式（standard / overview / remediation / chat）的 system prompt 模板中均包含 `evidence_trace.knowledge_evidence` 字段，要求 LLM 在 `threat_analysis` 中填充知识库证据列表：

```json
{
  "threat_analysis": {
    "evidence_trace": {
      "knowledge_evidence": [],
      "local_evidence": [],
      "evidence_count": 0,
      "explainability_labels": []
    }
  }
}
```

**可解释性服务**（`backend/app/services/explainability_service.py:351-414`）:

`ExplainabilityService.build_evidence_trace()` 将 RAG 检索结果组装为前端可渲染的证据链：

- `knowledge_evidence`: 直接复用 RAG 检索结果（含 `entry_ref` / `entry_type` / `source` / `confidence` / `match_reason` 等字段）
- `local_evidence`: 从 LLM 解析结果中提炼的本地证据（威胁分析 + 时间线分析）
- `explainability_labels`: 证据来源标签（如 `vector` / `keyword` / `seed` / `draft`），前端 `EvidenceTracePanel` 据此展示可点击溯源的知识条目链接

**完整数据流**:

```
分析数据 → KnowledgeRetriever.retrieve(structured=True)
         → PromptBuilder 注入 knowledge_evidence 字段
         → LLM 分析（模型引用知识库证据辅助判断）
         → ExplainabilityService 组装 evidence_trace
         → 前端 EvidenceTracePanel 渲染可溯源证据链
```

> **面向角色**: 💻开发

### 17.10 配置与维护

**依赖包**（`backend/requirements.txt`）:

| 包 | 版本 | 说明 |
|----|------|------|
| `chromadb` | ≥1.5.0 | 向量数据库（持久化 + 内存双模式） |
| `sentence-transformers` | ≥3.0.0 | 文本向量化（all-MiniLM-L6-v2） |

**持久化路径**:

| 路径 | 内容 |
|------|------|
| `backend/data/chroma/` | ChromaDB 持久化数据（collection `ir_rules` 的向量索引） |
| `~/.cache/torch/sentence_transformers/` | 模型缓存（`all-MiniLM-L6-v2`，约 80MB） |

**索引重建策略**:

| 触发条件 | 操作 | 文件:行 |
|----------|------|---------|
| 首次启动（ChromaDB 为空） | 自动构建规则索引 + 种子索引 | `knowledge_retriever.py:681-703` |
| 批准知识草稿 | 自动重建种子索引（删旧 seed/draft → 重新向量化） | `knowledge_draft.py:157-165` |
| 拒绝/撤回草稿 | 自动重建种子索引（移除该条目的向量） | `knowledge_draft.py:180-187, 203-209` |
| API 调用 `rebuild_seed_index()` | 手动触发重建（清空 seed/draft 缓存 → 重新加载 → 重新编码 → 写入） | `knowledge_retriever.py:706-751` |

**故障排查**:

| 问题 | 原因 | 解决 |
|------|------|------|
| 检索始终走关键词回退 | ChromaDB 或 sentence-transformers 未安装 | `pip install chromadb>=1.5.0 sentence-transformers>=3.0.0` |
| 模型下载失败/超时 | 网络受限，`local_files_only=True` 无本地缓存 | 手动下载 `all-MiniLM-L6-v2` 到 `~/.cache/torch/sentence_transformers/` |
| ChromaDB 数据损坏 | 持久化文件异常 | 删除 `backend/data/chroma/` 目录，重启后自动重建 |
| 批准后检索未生效 | `_SEED_CACHE` 进程级缓存未刷新 | 调用 `rebuild_seed_index()` 或重启后端 |
| 种子数据未被索引 | `collection.count()>0` 导致 _build_seed_index 被跳过 | 检查是否有 rule_* 条目占位，调用 rebuild_seed_index 强制重建 |

> **面向角色**: 🔧运维 💻开发

### 17.11 模型下载指南

**模型信息**：
- 名称：`BAAI/bge-base-zh-v1.5`
- 大小：约 420MB
- 维度：768 维
- 用途：中英混合安全知识库语义检索

**方式一：Python 脚本预下载（推荐）**

在项目根目录创建并运行以下 Python 脚本：

```python
# download_embedding_model.py
from sentence_transformers import SentenceTransformer

model_name = "BAAI/bge-base-zh-v1.5"
print(f"正在下载 {model_name} ...")
model = SentenceTransformer(model_name)
print(f"下载完成，缓存路径：{model._modules['0'].auto_model.config._name_or_path}")

# 验证模型可用
emb = model.encode(["测试文本"], normalize_embeddings=True)
print(f"编码测试通过，向量维度：{emb.shape[1]}")
```

运行：`cd backend && backend/venv/Scripts/python.exe download_embedding_model.py`

首次运行会自动从 HuggingFace Hub 下载模型文件到本地缓存：
- Windows: `C:\Users\<用户名>\.cache\torch\sentence_transformers\BAAI_bge-base-zh-v1.5\`
- Linux/macOS: `~/.cache/torch/sentence_transformers/BAAI_bge-base-zh-v1.5/`

**方式二：修改 local_files_only 为 False（首次部署）**

将 `backend/app/services/knowledge_retriever.py:91` 的 `local_files_only=True` 临时改为 `local_files_only=False`，重启服务后首次调用向量检索时会自动下载模型。下载完成后**务必改回 `True`**（生产环境不应每次启动都检查远程）。

**下载后验证**：
1. 重启后端服务
2. 调用 `POST /api/knowledge/validate-retrieval` 质量自检端点
3. 确认每个 query 返回有效的 Top-3 结果且 score > 0.5

**常见问题**：
- **下载超时**：HuggingFace Hub 国内访问可能较慢，可设置镜像：`export HF_ENDPOINT=https://hf-mirror.com`
- **磁盘空间不足**：模型约 420MB + sentence-transformers 依赖约 500MB，确保至少 1GB 可用空间
- **模型加载失败**：检查 `~/.cache/torch/sentence_transformers/` 目录下是否存在 `BAAI_bge-base-zh-v1.5/` 文件夹

> **面向角色**: 🔧运维 💻开发

---

## 18. 系统配置与管理

### 18.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IR_SECRET_KEY` | 内置默认值 | JWT 签名密钥（生产环境务必修改） |
| `IR_AI_ENCRYPTION_KEY` | 内置默认值 | AI API Key 加密密钥（Fernet 格式） |
| `THREATBOOK_KEY` | 无 | 威胁情报 API Key（放入 `.env`） |

### 18.2 配置项（`backend/app/config.py`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DB_PATH` | `backend/data/ir_platform.db` | SQLite 数据库路径 |
| `DATA_DIR` | `backend/data/` | 数据目录 |
| `UPLOAD_DIR` | `backend/data/imports/` | 原始 JSON 存储目录 |
| `AGENT_DIR` | `agent/dist/` | Agent 二进制目录 |
| `MAX_FILE_SIZE_MB` | 100 | 上传文件大小限制 |
| `TOKEN_EXPIRE_HOURS` | 24 | JWT Token 有效期 |
| `CORS_ORIGINS` | localhost:5173/8000 | 允许的跨域来源 |
| `AI_ENCRYPTION_KEY` | 环境变量 | AI API Key 加密 |
| `AI_CIRCUIT_BREAKER_TIMEOUT` | 300 | 断路器熔断超时（秒） |
| `AI_MASKING_DEFAULT` | True | 默认启用脱敏 |
| `AI_MAX_RETRIES` | 3 | AI 调用最大重试 |
| `AI_CONTEXT_WINDOW` | 128000 | 模型上下文窗口 |
| `AI_INPUT_BUDGET` | 80000 | 输入预算 tokens |
| `ENABLE_THREAT_INTEL_ENRICHMENT` | True | 威胁情报回灌总开关 |
| `AUTO_ENRICHMENT` | False | 自动外联总开关 |
| `DEFAULT_DAILY_QUOTA` | 1000 | 日查询配额 |
| `DEFAULT_RECHECK_DAYS` | 30 | 重检间隔 |

### 18.3 数据目录结构

```
backend/
├── data/
│   ├── ir_platform.db         # SQLite 数据库
│   ├── imports/               # 原始 Agent JSON 文件
│   └── agents/                # Agent 二进制（windows/linux）
├── config/
│   ├── threat_intel_providers.json    # Provider 配置
│   ├── threat_intel_settings.json     # 运行策略
│   └── report_template.json           # 报告模板
└── .env                      # 敏感配置（API Key 等）
```

### 18.4 白名单配置

白名单管理 API（`backend/app/api/whitelist.py`）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/whitelist` | GET | 列表（?category=path/process_name/signature） |
| `/api/whitelist` | POST | 新增 |
| `/api/whitelist/{id}` | PUT | 更新 |
| `/api/whitelist/{id}` | DELETE | 删除 |

**默认白名单** (`backend/app/database.py:967-1055`)：
- **路径类**: `C:\Windows\System32\`, `/usr/bin/`, 等 12 个系统路径
- **进程名类**: `svchost.exe`, `lsass.exe`, `explorer.exe`, 等 21 个系统进程

### 18.5 差分基线

`backend/app/api/baseline.py` 提供基线管理：
- `POST /api/baselines/{host_id}` — 上传基线
- `GET /api/baselines/{host_id}` — 读取最新基线
- `GET /api/baselines/{host_id}/list` — 列出所有基线
- `DELETE /api/baselines/{baseline_id}` — 删除指定基线

> **面向角色**: 🔧运维 💻开发

---

## 19. API 参考

### 19.1 认证

所有 API（除登录和报告查看外）需要 JWT Token。

**获取 Token**:
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
```
响应:
```json
{"code":0, "data":{"token":"eyJ...","user":{"id":1,"username":"admin","role":"admin"}}, "message":"success"}
```

**使用方式**: 请求头 `Authorization: Bearer {token}`

### 19.2 全部 API 端点

#### 认证（`auth.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 登录获取 Token |
| `/api/auth/me` | GET | 获取当前用户信息 |

#### 案件（`cases.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/cases` | GET | 分页列表 `?page=1&size=20&search=` |
| `/api/cases` | POST | 创建案件 `{name, case_number?, description?}` |
| `/api/cases/{case_id}` | GET | 案件详情 |
| `/api/cases/{case_id}` | PUT | 更新案件 |
| `/api/cases/{case_id}` | DELETE | 删除案件 |

#### 主机（`hosts.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/cases/{case_id}/hosts` | GET | 案件下的主机列表 |
| `/api/cases/{case_id}/hosts` | POST | 添加主机 `{hostname, ip_address?, os_type?, os_version?}` |
| `/api/hosts/{host_id}` | GET | 主机详情 |
| `/api/hosts/{host_id}` | DELETE | 删除主机 |

#### 导入（`import_data.py` + `process_events.py`）

| 路径 | 方法 | Content-Type | 说明 |
|------|------|-------------|------|
| `/api/hosts/{host_id}/import` | POST | multipart/form-data | 导入 Agent JSON（`file` 字段） |
| `/api/hosts/{host_id}/import-records` | GET | — | 导入记录列表 |
| `/api/hosts/{host_id}/process-events` | POST | application/json | 导入进程事件流 |

#### 分析（`analysis.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/hosts/{host_id}/analyze` | POST | 触发分析 |
| `/api/hosts/{host_id}/analysis` | GET | 获取分析结果汇总 |
| `/api/hosts/{host_id}/profile` | GET | 主机画像 |
| `/api/hosts/{host_id}/abnormal-processes` | GET | 异常进程列表 |
| `/api/hosts/{host_id}/suspicious-connections` | GET | 可疑外连列表 |
| `/api/hosts/{host_id}/suspicious-connections/enrich` | POST | 一键威胁情报检测 |
| `/api/hosts/{host_id}/ioc-hits` | GET | IOC 命中列表 |
| `/api/hosts/{host_id}/persistence` | GET | 持久化痕迹 |
| `/api/hosts/{host_id}/startup-items` | GET | 可疑启动项 |
| `/api/hosts/{host_id}/timeline` | GET | 时间线 `?start=&end=&event_types=&severity=&ioc_hit=` |
| `/api/hosts/{host_id}/timeline/stats` | GET | 时间线统计 |
| `/api/hosts/{host_id}/process-tree` | GET | 进程树 `?enrich=true/false` |
| `/api/hosts/{host_id}/users` | GET | 用户列表 |
| `/api/hosts/{host_id}/services` | GET | 服务列表 |
| `/api/hosts/{host_id}/usb` | GET | USB 设备记录 |
| `/api/hosts/{host_id}/remote-control` | GET | 远程工具记录 |
| `/api/hosts/{host_id}/network-connections` | GET | 网络连接（增强） |
| `/api/hosts/{host_id}/network-connections/enrich` | POST | 网络连接一键检测 |
| `/api/hosts/{host_id}/file-hashes` | GET | 文件哈希列表 |
| `/api/hosts/{host_id}/wmi-subscriptions` | GET | WMI 订阅列表 |
| `/api/hosts/{host_id}/registry-keys` | GET | 注册表键值 |
| `/api/analysis/timeline/{event_id}` | PATCH | 更新事件状态 `{status, assigned_to?, resolution?}` |
| `/api/analysis/timeline/compare` | GET | 多主机时间线对比 `?host_ids=1,2,3` |
| `/api/analysis/timeline/{host_id}/export/csv` | GET | 导出时间线 CSV |
| `/api/analysis/timeline/{host_id}/export/pdf` | GET | 导出时间线 PDF |

#### Agent 下载（`agent.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/agent/download/{os_type}` | GET | 下载 Agent 二进制（windows/linux） |

#### 规则（`rules.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/rules` | GET | 规则列表 `?category=&enabled=&q=` |
| `/api/rules` | POST | 新增规则（含 condition 校验） |
| `/api/rules/{rule_id}` | PUT | 更新规则（含审计） |
| `/api/rules/{rule_id}` | DELETE | 删除规则（仅 user 源） |
| `/api/rules/bulk-enable` | PUT | 批量启禁 `{ids:[...], enabled:bool}` |
| `/api/rules/reset` | POST | 重置默认规则（管理员） |

#### 白名单（`whitelist.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/whitelist` | GET | 列表 `?category=` |
| `/api/whitelist` | POST | 新增 |
| `/api/whitelist/{id}` | PUT | 更新 |
| `/api/whitelist/{id}` | DELETE | 删除 |

#### IOC（`iocs.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/iocs` | GET | 列表 `?ioc_type=` |
| `/api/iocs` | POST | 新增 |
| `/api/iocs/{ioc_id}` | PUT | 更新 |
| `/api/iocs/{ioc_id}` | DELETE | 删除 |
| `/api/iocs/import` | POST | 批量导入 |
| `/api/iocs/{ioc_id}/enrich` | POST | 外联查询单个 |
| `/api/iocs/enrich/batch` | POST | 批量外联查询 |
| `/api/iocs/{ioc_id}/threat-intel` | GET | 情报历史 |

#### 威胁情报配置（`threat_intel.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/threat-intel/providers` | GET | Provider 列表（不含密钥） |
| `/api/threat-intel/providers` | POST/PUT | 新增/更新 Provider |
| `/api/threat-intel/providers` | DELETE | 删除 Provider `?name=` |
| `/api/threat-intel/settings` | GET/PUT | 运行策略 |

#### AI 分析（`ai.py`）— 完整 28 个端点

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/ai/profiles` | GET | Profile 列表 |
| `/api/ai/profiles` | POST | 创建 Profile |
| `/api/ai/profiles/{id}` | PUT | 更新 Profile |
| `/api/ai/profiles/{id}` | DELETE | 删除 Profile |
| `/api/ai/profiles/{id}/activate` | POST | 激活 Profile |
| `/api/ai/test-connection` | POST | 测试连接 |
| `/api/ai/config` | GET | 获取当前配置（兼容） |
| `/api/ai/config` | POST | 保存配置（兼容） |
| `/api/ai/toggle` | POST | 开关 AI |
| `/api/ai/provider-options` | GET | Provider 选项列表 |
| `/api/ai/analyze/{host_id}` | POST | 提交分析任务 `?mode=&masked_mode=&focus_area=` |
| `/api/ai/analyze/{host_id}/chat` | POST | 多轮对话 |
| `/api/ai/analyze/{host_id}/dispatch-readonly` | POST | 只读派发 |
| `/api/ai/analyze/compare` | POST | 多主机对比 |
| `/api/ai/analyze/compare/{task_id}/stream` | GET | 对比 SSE 流 |
| `/api/ai/tasks` | GET | 任务列表 `?host_id=` |
| `/api/ai/tasks/{task_id}` | GET | 任务状态 |
| `/api/ai/tasks/{task_id}/stream` | GET | SSE 进度流 |
| `/api/ai/tasks/{task_id}/cancel` | POST | 取消任务 |
| `/api/ai/report/{host_id}` | GET | 最新报告 |
| `/api/ai/report/{host_id}/versions` | GET | 报告版本列表 |
| `/api/ai/report/{host_id}/versions/{v}` | GET | 指定版本报告 |
| `/api/ai/report/{host_id}/diff` | GET | 版本 Diff `?v1=&v2=` |
| `/api/ai/report/{host_id}/pdf` | GET | 导出 AI PDF |
| `/api/ai/report/{host_id}` | DELETE | 删除报告 |
| `/api/ai/dispatch/{task_id}` | GET | 派发状态 |
| `/api/ai/dispatch/{task_id}/cancel` | POST | 取消派发 |
| `/api/ai/stats/tokens` | GET | Token 统计 |
| `/api/ai/stats/summary` | GET | 汇总统计 |
| `/api/ai/audit-logs` | GET | 审计日志 `?page=&page_size=&host_id=&status=` |
| `/api/ai/audit-logs/{log_id}` | GET | 审计详情 |
| `/api/ai/prompt/optimize` | POST | Prompt 优化 |
| `/api/ai/prompt/versions/{profile_id}` | GET | Prompt 版本历史 |

#### 报告（`report.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/hosts/{host_id}/report` | GET | HTML 报告 `?report_level=technical\|executive` |
| `/api/hosts/{host_id}/report/pdf` | GET | PDF 报告 |
| `/api/reports/{host_id}/checklist` | GET | 处置清单 |
| `/api/reports/{host_id}/checklist` | PUT | 更新处置清单 |

#### 差分基线（`baseline.py`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/baselines/{host_id}` | POST | 上传基线 |
| `/api/baselines/{host_id}` | GET | 读取最新基线 |
| `/api/baselines/{host_id}/list` | GET | 基线列表 |
| `/api/baselines/{baseline_id}` | DELETE | 删除基线 |

#### 知识库（`knowledge_draft.py`）— 详见第 17 章

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge/drafts` | GET | 知识草稿列表（完整 11 个端点见第 17.8 节） |
| `/api/knowledge/seeds` | GET | 内置种子知识数据 |
| `/api/knowledge/drafts/{id}` | GET | 草稿详情 |
| `/api/knowledge/drafts/{id}/approve` | POST | 批准草稿 → 自动入库 |
| `/api/knowledge/drafts/{id}/reject` | POST | 拒绝草稿 |
| `/api/knowledge/drafts/{id}/recall` | POST | 撤回至待审核 |
| `/api/knowledge/drafts/batch` | POST | 批量操作 |
| `/api/knowledge/import` | POST | 手动导入 |
| `/api/knowledge/sync/{provider}` | POST | 第三方同步 |
| `/api/knowledge/validate-retrieval` | POST | 向量检索质量自检 |

#### 健康检查

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/routes-debug` | GET | 列出所有路由（诊断） |

### 19.3 关键端点 curl 示例

#### 登录
```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
# → {"code":0,"data":{"token":"eyJ...","user":{"id":1,"username":"admin","role":"admin"}}}
```

#### 创建案件
```bash
TOKEN="eyJ..."
curl -s -X POST http://localhost:8000/api/cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"应急响应-2026-07","case_number":"IR-2026-001","description":"勒索病毒事件"}'
# → {"code":0,"data":{"id":1,"name":"...","status":"open",...}}
```

#### 添加主机
```bash
curl -s -X POST http://localhost:8000/api/cases/1/hosts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hostname":"WIN-SERVER-01","ip_address":"192.168.1.100","os_type":"windows","os_version":"Server 2019"}'
# → {"code":0,"data":{"id":1,"hostname":"WIN-SERVER-01",...}}
```

#### 导入 Agent JSON（multipart）
```bash
curl -s -X POST http://localhost:8000/api/hosts/1/import \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@WIN-SERVER-01_20260712_100000.json"
# → {"code":0,"data":{"id":1,"host_id":1,"file_name":"...","status":"imported",...}}
```

#### 导入进程事件流
```bash
curl -s -X POST http://localhost:8000/api/hosts/1/process-events \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '[{"event_type":"process_start","pid":1234,"ppid":5678,"process_name":"powershell.exe","command_line":"powershell -enc ...","event_time":"2026-07-12T10:00:00"}]'
# → {"written":1}
```

#### 触发分析
```bash
curl -s -X POST http://localhost:8000/api/hosts/1/analyze \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"id":1,"risk_level":"high","risk_score":75,"total_findings":12,...}}
```

#### 获取分析结果
```bash
curl -s http://localhost:8000/api/hosts/1/analysis \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"risk_level":"high","risk_score":75,..."webshells":[...],"memory_shells":[...],"incidents":[...]}}
```

#### 获取异常进程
```bash
curl -s http://localhost:8000/api/hosts/1/abnormal-processes \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":[{"pid":1234,"process_name":"powershell.exe","severity":"high","risk_score":55,"matched_rules":[...],"attack_path":"explorer → cmd → powershell"}],...}
```

#### 进程树（富信息模式）
```bash
curl -s "http://localhost:8000/api/hosts/1/process-tree?enrich=true" \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"name":"System","children":[...]},...}
```

#### 一键威胁情报检测
```bash
curl -s -X POST http://localhost:8000/api/hosts/1/suspicious-connections/enrich \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"total":50,"public":12,"enriched":10,"malicious":3,"suspicious":4,...}}
```

#### 提交 AI 分析
```bash
curl -s -X POST "http://localhost:8000/api/ai/analyze/1?mode=standard&masked_mode=1" \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"task_id":1,"status":"pending","progress":0,...}}
```

#### SSE 流式进度（前端 JavaScript 示例）
```javascript
const evtSource = new EventSource(`/api/ai/tasks/${taskId}/stream`);
evtSource.addEventListener('progress', (e) => {
  const data = JSON.parse(e.data);
  console.log(`Progress: ${data.progress}% - ${data.progress_message}`);
});
evtSource.addEventListener('done', (e) => {
  console.log('Analysis complete');
  evtSource.close();
});
```

#### 导出 PDF 报告
```bash
curl -s -o report.pdf "http://localhost:8000/api/hosts/1/report/pdf?report_level=technical" \
  -H "Authorization: Bearer $TOKEN"
```

#### 导出时间线 CSV
```bash
curl -s -o timeline.csv "http://localhost:8000/api/analysis/timeline/1/export/csv?severity=high,critical" \
  -H "Authorization: Bearer $TOKEN"
```

#### AI 报告版本 Diff
```bash
curl -s "http://localhost:8000/api/ai/report/1/diff?v1=1&v2=2" \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"v1":1,"v2":2,"diffs":[{...}],"changed_fields":2}}
```

#### 批量启用/禁用规则
```bash
curl -s -X PUT http://localhost:8000/api/rules/bulk-enable \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ids":[1,3,5],"enabled":false}'
# → {"code":0,"data":{"updated":3},...}
```

#### 重置默认规则（管理员）
```bash
curl -s -X POST http://localhost:8000/api/rules/reset \
  -H "Authorization: Bearer $TOKEN"
# → {"code":0,"data":{"updated":15,"inserted":2,"preserved":0,"total":17},...}
```

#### 上传差分基线
```bash
curl -s -X POST http://localhost:8000/api/baselines/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"baseline_json":{"known_items":[...]},"source":"uploaded","note":"初始基线"}'
```

### 19.4 统一响应格式

所有 API 响应遵循：
```json
{"code": 0, "data": {...}, "message": "success"}
```

错误码：
- `code=0` 成功
- HTTP 400 请求参数错误
- HTTP 401 Token 无效/过期
- HTTP 403 权限不足
- HTTP 404 资源不存在
- HTTP 409 冲突（如重复案件编号）
- HTTP 422 规则 condition 校验失败
- HTTP 429 IOC 外联配额耗尽
- HTTP 500 服务器内部错误

> **面向角色**: 💻开发

---

## 20. 技术架构与数据流

### 20.1 全链路数据流

```
┌─────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────┐    ┌──────────┐
│  Agent  │   ▶│  /import     │   ▶│  分析管线     │   ▶│  SQLite  │   ▶│ Frontend │
│ 采集 JSON│    │ multipart    │    │ AnalysisService│   │  36+ 表  │    │ Vue3 SPA │
└─────────┘    └──────────────┘    └──────┬───────┘    └──────────┘    └──────────┘
                    │                      │
              ┌─────▼──────┐        ┌──────▼───────┐
              │ 原始 JSON   │        │ RuleEngine    │
              │ imports/    │        │ + 规则匹配     │
              └────────────┘        └──────────────┘
```

### 20.2 双端点设计

| 端点 | 用途 | 数据格式 | 触发分析 |
|------|------|----------|----------|
| `POST /import` | 标准全量采集数据 | multipart JSON 文件 | 手动调用 `/analyze` |
| `POST /process-events` | 进程实时事件流 | JSON 数组 | Agent 推送时同步评估 |

### 20.3 数据库 ER 简图

```
cases ──1:N──▶ hosts ──1:1──▶ host_profiles
                 │
                 ├──1:N──▶ import_records
                 ├──1:N──▶ analysis_results
                 ├──1:N──▶ abnormal_processes
                 ├──1:N──▶ suspicious_connections
                 ├──1:N──▶ suspicious_startup_items
                 ├──1:N──▶ persistence_items
                 ├──1:N──▶ timeline_events
                 ├──1:N──▶ ioc_hits
                 ├──1:N──▶ network_connections
                 ├──1:N──▶ file_hashes
                 ├──1:N──▶ wmi_subscriptions
                 ├──1:N──▶ registry_keys
                 ├──1:N──▶ process_events
                 ├──1:N──▶ webshells
                 ├──1:N──▶ memory_shells
                 ├──1:N──▶ agent_baselines
                 └──1:N──▶ ai_analysis_reports

rules ──1:N──▶ rule_audit_log
iocs ──1:N──▶ threat_intel
ai_config_profiles ──1:N──▶ ai_prompt_versions
ai_tasks ──1:1──▶ ai_analysis_reports
```

### 20.4 关键算法

#### 进程树构建（process_tree_build）

`backend/app/analysis/process_tree_builder.py`:
- 输入: `[{pid, ppid, name, ...}]`
- 算法: 哈希表找根节点 → 递归构建子树 → 嵌套 dict 输出
- 复杂度: O(n)

#### 统一关联引擎（correlate_incident — 贝叶斯）

`backend/app/analysis/anomaly_detector.py:549-672`:
- 信号构建: `_build_signals()` → 统一 `{category, severity, evidence, attck}` 结构
- 贝叶斯融合: `C = (1 - Π(1-p_i)) × 100`
- Combo Boost: WebShell + 内存马 = +25 置信度
- 输出: incident (≥2 类别) / single_alert (1 类别)

#### 规则引擎匹配（rule_engine）

`backend/app/rules/rule_engine.py`:
- `regex` 类型: `re.search(pattern, item[field], flags)`
- `list` 类型: 字段值 ∈ values 或动态 IOC 匹配
- `behavior` 类型: 调用内置行为检测函数
- `attack_chain` 类型: 跨维度 DB 查询顺序匹配
- 全局上下文传递: `process_map`, `ancestor_map`, `connections`, `iocs_by_type`

#### IOC 匹配

`backend/app/analysis/ioc_checker.py`:
- Agent IOC → 联网规则 → 进程列表规则 → 文件哈希 → WebShell 哈希 → 去重

### 20.5 累加评分机制

`backend/app/analysis/anomaly_detector.py:168-321` 中的 `_apply_accumulated_scoring()`:

1. 同 PID 多规则命中: 累加 `risk_score = min(Σ severity_score, 100)`
2. 链路级聚合: 祖先+后代同链所有节点 risk_score 累加
3. 白名单抑制: whitelisted 且仅 info/low 命中 → 不误报

**严重度权重**:
| severity | 分数 |
|----------|------|
| critical | 35 |
| high | 20 |
| medium | 10 |
| low | 5 |
| info | 1 |

> **面向角色**: 💻开发

---

## 21. 部署与运维

### 21.1 生产部署建议

1. **修改默认密钥**:
   - 设置环境变量 `IR_SECRET_KEY`（64+ 位随机字符串）
   - 设置环境变量 `IR_AI_ENCRYPTION_KEY`（Fernet 格式 32 字节 base64）
2. **修改默认密码**: 首次登录后立即修改 `admin` 密码
3. **限制 CORS**: 修改 `backend/app/config.py` 中的 `CORS_ORIGINS` 为实际前端域名
4. **数据库备份**: 定期备份 `backend/data/ir_platform.db` 和 `backend/data/imports/`

### 21.2 依赖安装

#### 后端
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**关键依赖** (`backend/requirements.txt`):
- `fastapi==0.111.0` + `uvicorn[standard]==0.30.1`
- `python-jose[cryptography]==3.3.0` + `passlib[bcrypt]==1.7.4`
- `weasyprint==62.1` — PDF 生成（需要系统级 GTK 库）
- `chromadb>=1.5.0` + `sentence-transformers>=3.0.0` — RAG 向量检索（首次启动自动下载 ~80MB 模型）

#### 前端
```bash
cd frontend
npm install
npm run build   # 生产构建
```

### 21.3 数据库迁移

数据库迁移通过 `backend/app/database.py:1150-1202` 中的 `init_db()` 自动完成：
- 建表: `CREATE TABLE IF NOT EXISTS`
- 列迁移: `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`（幂等）
- 数据迁移: `_migrate_old_ai_config()` 等

**无需手动执行迁移脚本**，启动时自动完成。

### 21.4 日志

后端日志使用 Python `logging` 模块，`INFO` 级别：
- 启动信息
- 分析步骤进度
- AI 调用审计
- 错误堆栈

Agent 日志支持 `--log-file` 参数输出到文件。

### 21.5 性能配置

| 配置项 | 建议值 | 说明 |
|--------|--------|------|
| `AI_MAX_RETRIES` | 3 | AI 调用重试次数 |
| `AI_RETRY_BASE_DELAY` | 1.0 | 指数退避基础延迟 |
| `AI_CIRCUIT_BREAKER_TIMEOUT` | 300 | 断路器熔断超时 |
| `DEFAULT_RATE_LIMIT_QPS` | 2 | 威胁情报查询 QPS |
| `DEFAULT_DAILY_QUOTA` | 1000 | 日查询配额 |

### 21.6 容器化建议

```dockerfile
# 后端 Dockerfile 示例
FROM python:3.11-slim
RUN apt-get update && apt-get install -y libpango-1.0-0 libpangocairo-1.0-0
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
RUN mkdir -p data/imports data/agents
CMD ["python", "run.py"]
```

### 21.7 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| PDF 生成失败 | WeasyPrint 缺少系统 GTK 库 | `apt install libpango-1.0-0 libpangocairo-1.0-0` (Linux) |
| 威胁情报查询无结果 | 未配置 `THREATBOOK_KEY` | 检查 `backend/.env` |
| Agent 权限不足 | 非管理员运行 | `sudo` / 右键"以管理员身份运行" |
| 前端跨域错误 | CORS 未配置 | 检查 `CORS_ORIGINS` 包含前端域名 |
| AI 分析超时 | LLM API 不可达 | 检查网络/API Key，或调整 `AI_CIRCUIT_BREAKER_TIMEOUT` |
| RAG 模型下载慢 | 首次启动自动下载 | 可手动放置到 `~/.cache/torch/sentence_transformers/` |

> **面向角色**: 🔧运维 💻开发

---

## 22. 版本管理与维护策略

### 22.1 版本号规范

采用语义化版本（SemVer）：`MAJOR.MINOR.PATCH`

| 版本号 | 规则 |
|--------|------|
| MAJOR | 不兼容的 API 变更、架构重大调整 |
| MINOR | 向后兼容的功能新增（如新增检测规则类型） |
| PATCH | 向后兼容的错误修复、文档更新 |

当前平台版本: `1.0.0`（`backend/app/main.py:29`）

### 22.2 更新流程

1. 代码变更 + 测试
2. 更新 `backend/app/main.py` 中的 `version` 字段
3. 如需新增规则：修改 `backend/app/rules/` 中的 JSON 文件
4. 如需新增数据库列：在 `backend/app/database.py` 中添加 `_alter_*_table()` 函数
5. 如需新增 API：在 `backend/app/api/` 中添加路由并在 `backend/app/main.py` 中注册

### 22.3 文档同步策略

当以下文件发生变更时，需同步更新本手册对应章节：

| 变更文件 | 需更新的章节 |
|----------|-------------|
| `backend/app/main.py` (路由注册) | 第 19 章 API 参考 |
| `backend/app/database.py` (表结构) | 第 20 章 技术架构与数据流 |
| `backend/app/analysis/anomaly_detector.py` | 第 7/8/9/10 章 |
| `backend/app/rules/*.json` (规则) | 第 6/7 章 |
| `backend/app/services/analysis_service.py` | 第 5/20 章 |
| `backend/app/api/*.py` (任一端点) | 第 19 章 API 参考 |
| `agent/agent.py` (COLLECTOR_MAP) | 第 4 章 数据采集 |
| `agent/collectors/*.py` (采集器) | 第 4 章 采集器列表 |
| `agent/utils/output.py` (OUTPUT_KEYS) | 第 4 章 Schema |
| `frontend/src/router/index.js` | 第 15 章 前端功能面板 |
| `frontend/src/views/*.vue` | 第 15 章 前端功能面板 |
| `backend/app/config.py` | 第 18 章 系统配置 |
| `backend/app/services/knowledge_retriever.py` | 第 17 章 知识库系统 |
| `backend/app/models/knowledge_draft.py` | 第 17 章 知识库系统 |
| `backend/app/api/knowledge_draft.py` | 第 17/19 章 |
| `backend/app/data/knowledge_seed.py` | 第 17 章 知识库系统 |
| `backend/app/services/prompt_builder.py` | 第 16/17 章 |
| `backend/app/services/explainability_service.py` | 第 16/17 章 |
| `frontend/src/views/KnowledgeView.vue` | 第 15/17 章 |
| `frontend/src/views/KnowledgeDetailView.vue` | 第 15/17 章 |
| `frontend/src/components/HostKnowledgeTab.vue` | 第 15/17 章 |
| `docs/integrated_webshell_memory_detection_plan.md` | 第 8/9/10 章 |
| `docs/process_detection_enhancement.md` | 第 7 章 |
| `README.md` | 第 1/2 章 |

### 22.4 贡献指南

1. Fork 仓库 → 创建功能分支
2. 遵循现有代码风格（PEP 8 for Python, Vue Style Guide for Vue）
3. API 变更需同步更新 Swagger 文档字符串
4. 新增采集器需在 `agent/agent.py` 的 `COLLECTOR_MAP` 和 `agent/utils/output.py` 的 `OUTPUT_KEYS` 中注册
5. 新增规则需符合 `backend/app/schemas/analysis.py` 中的 schema 校验
6. 提交前确保 `python run.py` 和 `npm run dev` 均正常运行

### 22.5 变更日志格式

```
## [版本号] - YYYY-MM-DD

### 新增
- 功能描述 (#PR)

### 修复
- 问题描述 (#PR)

### 变更
- 修改描述 (#PR)
```

> **面向角色**: 💻开发

---

## 附录：文档维护清单

下列文件变更时，请检查是否需要同步更新本手册：

| # | 文件 | 影响章节 | 检查点 |
|---|------|----------|--------|
| 1 | `backend/app/main.py` | 1, 19, 22 | 版本号、路由注册 |
| 2 | `backend/app/database.py` | 20 | 表结构、迁移逻辑 |
| 3 | `backend/app/config.py` | 18 | 配置项 |
| 4 | `backend/app/api/auth.py` | 19 | 认证端点 |
| 5 | `backend/app/api/cases.py` | 3, 19 | 案件 CRUD |
| 6 | `backend/app/api/hosts.py` | 3, 19 | 主机 CRUD |
| 7 | `backend/app/api/import_data.py` | 5, 19 | 导入端点 |
| 8 | `backend/app/api/analysis.py` | 5, 7, 19 | 分析端点 |
| 9 | `backend/app/api/rules.py` | 6, 19 | 规则管理 |
| 10 | `backend/app/api/ai.py` | 16, 19 | AI 全端点 |
| 11 | `backend/app/api/report.py` | 15, 19 | 报告端点 |
| 12 | `backend/app/api/iocs.py` | 13, 19 | IOC 管理 |
| 13 | `backend/app/api/threat_intel.py` | 15, 19 | 情报配置 |
| 14 | `backend/app/api/baseline.py` | 18, 19 | 基线端点 |
| 15 | `backend/app/api/agent.py` | 4, 19 | Agent 下载 |
| 16 | `backend/app/api/whitelist.py` | 18, 19 | 白名单管理 |
| 17 | `backend/app/api/process_events.py` | 5, 19 | 进程事件 |
| 18 | `backend/app/services/analysis_service.py` | 5, 20 | 分析管线 |
| 19 | `backend/app/analysis/anomaly_detector.py` | 7, 8, 9, 10, 20 | 检测+关联引擎 |
| 20 | `backend/app/analysis/ioc_checker.py` | 13, 20 | IOC 匹配 |
| 21 | `backend/app/analysis/process_tree_builder.py` | 14, 20 | 进程树 |
| 22 | `backend/app/rules/default_rules.json` | 6, 7 | 主规则集 |
| 23 | `backend/app/rules/process_enhancement_rules.json` | 7 | 增强规则集 |
| 24 | `backend/requirements.txt` | 1, 21 | 依赖 |
| 25 | `agent/agent.py` | 4 | COLLECTOR_MAP |
| 26 | `agent/collectors/*.py` (所有) | 4 | 采集器 |
| 27 | `agent/utils/output.py` | 4 | OUTPUT_KEYS / Schema |
| 28 | `agent/collectors/resource_budget.py` | 4 | 资源配置 |
| 29 | `frontend/src/router/index.js` | 15 | 路由 |
| 30 | `frontend/src/views/*.vue` (所有) | 15 | 页面 |
| 31 | `frontend/package.json` | 1 | 前端依赖 |
| 32 | `docs/integrated_webshell_memory_detection_plan.md` | 8, 9, 10 | 融合检测设计 |
| 33 | `docs/process_detection_enhancement.md` | 7 | 进程增强 |
| 34 | `docs/process_tree_optimization_design.md` | 14 | 进程树优化 |
| 35 | `README.md` | 1, 2 | 项目简介/快速开始 |
| 36 | `backend/app/services/knowledge_retriever.py` | 17 | ChromaDB 向量检索 |
| 37 | `backend/app/models/knowledge_draft.py` | 17 | 知识草稿 CRUD |
| 38 | `backend/app/api/knowledge_draft.py` | 17, 19 | 知识库 10 个 API 端点 |
| 39 | `backend/app/data/knowledge_seed.py` | 17 | 10 条种子知识数据 |
| 40 | `backend/app/services/prompt_builder.py` | 16, 17 | knowledge_evidence RAG 注入 |
| 41 | `backend/app/services/explainability_service.py` | 16, 17 | 知识库证据可解释性 |
| 42 | `frontend/src/views/KnowledgeView.vue` | 15, 17 | 知识库列表页 |
| 43 | `frontend/src/views/KnowledgeDetailView.vue` | 15, 17 | 知识条目详情页 |
| 44 | `frontend/src/components/HostKnowledgeTab.vue` | 15, 17 | 主机关联知识审核 |
| 45 | `frontend/src/api/knowledge.js` | 17 | 知识库 API 客户端 |
| 46 | `backend/app/services/analysis_service.py` | 17.9A | 双路检测交叉验证 `_cross_validate()` |
| 47 | `backend/scripts/import_rules_to_knowledge.py` | 17.9B | 规则→知识批量导入脚本 |
| 48 | `backend/app/services/virustotal_provider.py` | 17.9C | VirusTotal `fetch_list()` |
| 49 | `backend/app/services/abuseipdb_provider.py` | 17.9C | AbuseIPDB `fetch_list()` |
| 50 | `backend/app/services/alienvault_otx_provider.py` | 17.9C | AlienVault OTX `fetch_list()` |
| 51 | `backend/app/services/enrichment_service.py` | 17.9C | `fetch_all_ioc_lists()` 统一聚合 |
| 52 | `backend/app/main.py` | 17.9C | `_register_scheduled_tasks()` 定时同步 |
| 53 | `frontend/src/components/AbnormalProcessTable.vue` | 17.9A | 语义匹配 📚 badge 展示 |
| 54 | `backend/app/rules/loader.py` | 17.3.5 | `load_default_rules()` 全量规则加载 |

---

*文档结束 — IR 平台用户手册 v1.0*
