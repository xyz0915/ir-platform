# 智能体管理模块 — Phase 2 设计方案

## 一、概述

将当前**硬编码 4 阶段管道**（Triage → Investigation → Responder → Reporter）升级为**插件化 Agent 管理 + 可视化拖拽编排**的架构，支持：

- 页面上**注册/启用/禁用**自定义 Agent
- 选择事件后**自由勾选 Agent**、**拖拽排序**
- **依赖图自动解析**，无依赖的 Agent 并行执行
- **执行结果缓存复用**，相同参数不重复调 LLM

---

## 二、系统架构

### 2.1 组件关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Management Module                      │
│                                                                   │
│  ┌────────────────┐   ┌────────────────┐   ┌────────────────┐   │
│  │  AgentRegistry  │   │ PipelineBuilder│   │ PipelineEngine │   │
│  │  (插件注册表)   │   │ (管道构建器)   │   │  (执行引擎)    │   │
│  │                │   │                │   │                │   │
│  │  register()    │   │  build()       │   │  run(ctx)      │   │
│  │  unregister()  │   │  validate()    │   │  cancel()      │   │
│  │  get() / list()│   │  serialize()   │   │  get_status()  │   │
│  │  get_deps()    │   │  deserialize() │   │  resume()      │   │
│  └───────┬────────┘   └───────┬────────┘   └───────┬────────┘   │
│          │                    │                    │             │
│          ▼                    ▼                    ▼             │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Executor (asyncio 并行调度器)               │    │
│  │                                                          │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │    │
│  │  │Agent A   │  │Agent B   │  │Agent C   │  │Agent D  │ │    │
│  │  │(独立)    │  │(独立)    │  │(依赖 B)  │  │(依赖B/C)│ │    │
│  │  └─────┬────┘  └────┬───┘  └────┬─────┘  └────┬────┘ │    │
│  │        └──┬──────────┘           │             │       │    │
│  │           ▼           ┌──────────┘             │       │    │
│  │      parallel batch 1 │                        │       │    │
│  │                 ┌─────┴─────┐                  │       │    │
│  │                 │parallel 2 │                  │       │    │
│  │                 └─────┬─────┘                  │       │    │
│  │                       └──────────┬─────────────┘       │    │
│  │                                  ▼                      │    │
│  │                            parallel batch 3              │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 后端新增文件

| 文件 | 说明 |
|------|------|
| `backend/app/services/agents/agent_registry.py` | Agent 插件注册表（CRUD + 依赖声明） |
| `backend/app/services/agents/agent_definition.py` | AgentDefinition 模型（name/type/data_sources/depends_on/prompt_template） |
| `backend/app/services/agents/pipeline_engine.py` | 并行管道执行引擎（DAG 解析 + asyncio.gather 并行） |
| `backend/app/services/agents/cache_manager.py` | 执行结果缓存（key=agent+params_hash，TTL=1h） |
| `backend/app/api/agent_management.py` | Agent 管理 API（CRUD + 列表 + 预置） |
| `backend/app/models/agent_definition.py` | agent_definitions 表模型 |

### 2.3 前端新增/修改文件

| 文件 | 说明 |
|------|------|
| `frontend/src/views/AgentManagementView.vue` (NEW) | 智能体管理主视图（Pipeline Builder + Agent Library） |
| `frontend/src/components/agents/AgentPipelineCanvas.vue` (NEW) | 拖拽排序管道画布 |
| `frontend/src/components/agents/AgentLibraryPanel.vue` (NEW) | Agent 库管理面板 |
| `frontend/src/components/agents/AgentConfigDialog.vue` (NEW) | 注册/编辑 Agent 的表单弹窗 |
| `frontend/src/stores/agentManagement.js` (NEW) | 管理模块 Pinia store |
| `frontend/src/views/AgentRunView.vue` (MODIFY) | 在"启动闭环"按钮旁加"选择智能体"入口 |
| `frontend/src/router/index.js` (MODIFY) | 注册新路由 |

### 2.4 数据库新增

```sql
CREATE TABLE IF NOT EXISTS agent_definitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,           -- 唯一标识名（如 file_analysis）
    display_name TEXT NOT NULL,                  -- 显示名（如"文件分析智能体"）
    type        TEXT NOT NULL DEFAULT 'custom',  -- built-in | custom
    description TEXT DEFAULT '',
    data_sources TEXT DEFAULT '[]',              -- JSON: 依赖的数据源表列表
    depends_on  TEXT DEFAULT '[]',               -- JSON: 前置 Agent 名称列表
    prompt_template TEXT DEFAULT '',             -- LLM prompt 模板（可选）
    config      TEXT DEFAULT '{}',               -- JSON: 配置参数
    enabled     INTEGER NOT NULL DEFAULT 1,      -- 是否启用
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    agents      TEXT NOT NULL,                   -- JSON: 有序 Agent 名称数组
    created_at  TEXT DEFAULT (datetime('now'))
);
```

### 2.5 预置 Agent 数据

```json
[
  {"name": "triage",          "display_name": "分诊智能体",   "type": "built-in", "enabled": true},
  {"name": "file_analysis",   "display_name": "文件分析",     "type": "custom",   "data_sources": ["security_events.file_create"], "depends_on": ["triage"]},
  {"name": "process_analysis","display_name": "进程分析",     "type": "custom",   "data_sources": ["process_events"], "depends_on": ["triage"]},
  {"name": "network_analysis","display_name": "网络分析",     "type": "custom",   "data_sources": ["network_connection"], "depends_on": ["triage"]},
  {"name": "registry_analysis","display_name": "注册表分析",  "type": "custom",   "data_sources": ["security_events.registry_modify"], "depends_on": ["triage"]},
  {"name": "threat_intel",    "display_name": "威胁情报",     "type": "custom",   "data_sources": ["ioc_matches"], "depends_on": ["triage"]},
  {"name": "timeline",        "display_name": "时间线重建",   "type": "custom",   "data_sources": ["process_events", "security_events"], "depends_on": ["triage"]},
  {"name": "root_cause",      "display_name": "根因定位",     "type": "custom",   "depends_on": ["file_analysis", "process_analysis", "network_analysis"]},
  {"name": "responder",       "display_name": "处置建议",     "type": "built-in", "hitl": true, "depends_on": ["root_cause"]},
  {"name": "reporter",        "display_name": "报告输出",     "type": "built-in", "depends_on": ["responder"]}
]
```

---

## 三、核心功能设计

### 3.1 Agent 注册表 (AgentRegistry)

```python
class AgentRegistry:
    """Agent 插件注册表 — 单例。"""

    def register(agent_def: AgentDefinition) -> None:
        """注册 Agent（持久化到 DB agent_definitions 表 + 内存缓存）。"""

    def unregister(name: str) -> None:
        """卸载 Agent（从 DB + 缓存移除）。"""

    def get(name: str) -> AgentDefinition:
        """根据名称获取 Agent 定义。"""

    def list(enabled_only: bool = True) -> list[AgentDefinition]:
        """列出所有 Agent（按名称排序）。"""

    def get_dependency_graph(agent_names: list[str]) -> dict:
        """返回依赖图（邻接表），用于 DAG 解析。"""

    def validate_pipeline(agent_names: list[str]) -> list[str]:
        """验证管道：检查依赖完整性 + 环检测，返回警告/错误列表。"""
```

### 3.2 并行执行引擎 (PipelineEngine)

```python
class PipelineEngine:
    """管道执行引擎：DAG 解析 + 分批并行 + 缓存 + HITL。"""

    async def run(
        run_id: str,
        agent_names: list[str],
        ctx: dict,
        user: dict,
        use_cache: bool = True,
    ) -> dict:
        """
        1. 从 AgentRegistry 获取所有 Agent 定义
        2. 构建依赖 DAG
        3. 拓扑排序，按无依赖批次分组
        4. 每批次 asyncio.gather 并行执行
        5. 批次间 await 等待前置批次完成
        6. 每步结果写入 ctx，供下游读取
        7. 遇到 HITL 触发则暂停，等待审批
        8. 整体耗时记录到 agent_runs
        """

    async def run_batch(
        agents: list[tuple[str, BaseAgent]],
        ctx: dict,
        user: dict,
        use_cache: bool,
    ) -> list[dict]:
        """并行执行一批无依赖的 Agent。"""
```

### 3.3 缓存复用 (CacheManager)

```python
class CacheManager:
    """执行结果缓存。key = f"{agent_name}:{params_hash}"，TTL=3600s。"""

    def get(agent_name: str, params: dict) -> Optional[AgentResult]:
        """计算 params_hash，查找缓存。"""

    def set(agent_name: str, params: dict, result: AgentResult) -> None:
        """写入缓存。"""

    def invalidate(agent_name: str) -> None:
        """主动失效（Agent 定义更新时调用）。"""
```

### 3.4 依赖图自动解析

用户选择 Agent 列表后，系统按 `depends_on` 字段自动分组：

```
输入（用户勾选）:
  [triage, file_analysis, network_analysis, root_cause, reporter]

依赖图:
  triage ──┬── file_analysis ──┐
           └── network_analysis┘── root_cause ── reporter

执行分组:
  Batch 1: [triage]                                   (串行: 1个)
  Batch 2: [file_analysis, network_analysis]           (并行: 2个)
  Batch 3: [root_cause]                                (串行: 1个)
  Batch 4: [reporter]                                  (串行: 1个)

总耗时: T1 + max(T2, T3) + T4 + T5
        (串行约15s + 并行约15s + 根因20s + 报告10s = ~60s)
        相比全串行 (~85s) 节省约 25s
```

---

## 四、API 设计

### 4.1 Agent 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/agent-management/agents` | 列出所有 Agent |
| POST | `/api/agent-management/agents` | 注册新 Agent |
| PUT | `/api/agent-management/agents/{name}` | 更新 Agent 配置 |
| DELETE | `/api/agent-management/agents/{name}` | 删除 Agent |
| GET | `/api/agent-management/agents/deps` | 查询依赖图 |

### 4.2 管道执行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/agent-management/pipeline/validate` | 验证管道配置 |
| POST | `/api/agent-management/pipeline/run` | 按指定 Agent 列表执行 |
| GET | `/api/agent-management/pipeline/presets` | 列出预置管道 |
| POST | `/api/agent-management/pipeline/presets` | 保存预置管道 |

### 4.3 请求/响应示例

```json
POST /api/agent-management/pipeline/run
{
  "event_id": "cm:file_hashes:95",
  "agents": ["triage", "file_analysis", "process_analysis", "network_analysis", "reporter"],
  "use_cache": true
}
→ 202
{
  "run_id": "run_custom_abc123",
  "status": "running",
  "pipeline": [
    {"name": "triage", "stage": 1, "parallel": false, "status": "running"},
    {"name": "file_analysis", "stage": 2, "parallel": true, "status": "pending"},
    {"name": "process_analysis", "stage": 2, "parallel": true, "status": "pending"},
    {"name": "network_analysis", "stage": 2, "parallel": true, "status": "pending"},
    {"name": "reporter", "stage": 3, "parallel": false, "status": "pending"}
  ]
}
```

---

## 五、前端界面功能

### 5.1 Pipeline Builder（管道构建器）

```
┌──────────────────────────────────────────────────────────────┐
│  Agent Orchestration Management                              │
│  ┌──────────┬────────────┬──────────────────┐                │
│  │ Pipeline │ Agent Lib  │  History         │                │
│  │ Builder  │            │                  │                │
│  ├──────────┴────────────┴──────────────────┤                │
│  │                                          │                │
│  │  Available Agents        Pipeline        │                │
│  │  ┌────────────────┐     ┌────────────┐  │                │
│  │  │ ● Triage       │ →   │ 1. Triage  │  │  拖拽排序       │
│  │  │ ● File         │     │ 2. File    │  │                │
│  │  │ ● Process      │     │ 3. Process │  │  每个 Stage：   │
│  │  │ ● Network      │     │ 4. Network │  │  - 名称         │
│  │  │ ● Registry     │     │ 5. Reg(⛔) │  │  - 标签(built-in│
│  │  │ ● Threat Intel │     │ 6. Intel   │  │     /custom)    │
│  │  │ ● Timeline     │     │ 7. Report  │  │  - 状态(active/ │
│  │  │ ● Root Cause   │     └────────────┘  │     cached/no   │
│  │  │ ● Reporter     │     [▶ Start]        │     data)       │
│  │  └────────────────┘     [Save Preset]    │                │
│  └──────────────────────────────────────────┘                │
│  ⓘ 3 个 Agent 无依赖 → 并行执行，预计节省 30s               │
│                                                              │
│  Agent Library (9 total, 8 active)                           │
│  ┌───────┬────────┬────────────┬───────┬──────────┐          │
│  │ Name  │ Type   │ Data Source│ Status│ Actions  │          │
│  ├───────┼────────┼────────────┼───────┼──────────┤          │
│  │Triage │built-in│sec_events  │ active│ edit|dis │          │
│  │File   │custom  │file_create │ active│ edit|dis │          │
│  │...    │...     │...         │ ...   │ ...      │          │
│  │Memory │custom  │—           │no data│ edit|rm  │          │
│  └───────┴────────┴────────────┴───────┴──────────┘          │
│                                               [+ Register]   │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 交互动作

| 操作 | 效果 |
|------|------|
| **从 Available 拖到 Pipeline** | 按插入位置添加，系统自动更新编号 |
| **Pipeline 内拖拽重排** | 实时重排序号 + 检查依赖完整性 |
| **点击 Agent 名称** | 弹出配置面板（数据源/依赖/prompt 模板） |
| **右键 × 移除** | 从管道移除，如被下游依赖则弹警告 |
| **Save Preset** | 保存当前管道配置为模板 |
| **Start Pipeline** | 调用 API 开始执行，跳转详情页 SSE 实时显示 |
| **Register new agent** | 弹出表单：名称/数据源/依赖/LLM prompt 模板 |

---

## 六、预估工作量

| 模块 | 后端 | 前端 | 文件数 | 代码量（估） |
|------|------|------|--------|------------|
| Agent 注册表 + DB 模型 | ~120 行 | — | 3 个文件 | 120 行 |
| 并行执行引擎 | ~250 行 | — | 1 个文件 | 250 行 |
| 缓存管理 | ~80 行 | — | 1 个文件 | 80 行 |
| API 端点 | ~150 行 | — | 1 个文件 | 150 行 |
| 前端 Pipeline Builder | — | ~300 行 | 1 个文件 | 300 行 |
| 前端 Agent Library | — | ~200 行 | 1 个文件 | 200 行 |
| 前端配置弹窗 | — | ~150 行 | 1 个文件 | 150 行 |
| 前端 Store + 路由 | — | ~80 行 | 2 个文件 | 80 行 |
| 预置数据 + 单元测试 | ~100 行 | — | 1 个文件 | 100 行 |
| **合计** | **~700 行** | **~730 行** | **11 个文件** | **~1430 行** |

---

## 七、实施排期建议

| 阶段 | 任务 | 预估工时 |
|------|------|---------|
| **P0** | AgentDefinition 模型 + DB 迁移 | 0.5 天 |
| | AgentRegistry 注册表 + 依赖图解析 | 1 天 |
| | PipelineEngine 并行执行引擎 | 1.5 天 |
| **P1** | Agent 管理 API（CRUD + validate） | 1 天 |
| | 前端 Pipeline Builder + Agent Library | 2 天 |
| | 前端配置表单 + Store | 1 天 |
| **P2** | CacheManager 结果缓存 | 0.5 天 |
| | 可视化依赖图 + 拖拽排序增强 | 1 天 |
| | 预置管道保存/载入 | 0.5 天 |
| **QA** | 全量回归测试 | 1 天 |
| **合计** | | **~10 天** |

---

## 八、风险与注意事项

| 风险 | 等级 | 应对 |
|------|------|------|
| Agent 定义过多导致前端图标/名称混乱 | 低 | 按类型分组（analysis/investigation/action） |
| 依赖环检测遗漏 | 中 | 拓扑排序时 DFS 环检测 + 前端实时验证 |
| `asyncio.gather` 并发过高 | 中 | 限制最大并发数（max_concurrent=5） |
| 缓存命中策略过于激进 | 低 | 相同 params_hash 才命中（含时间窗口） |
| 自定义 Agent 的 prompt_template 安全性 | 中 | 限制字段长度 + 模板变量白名单 |
| 前端拖拽在移动端不可用 | 低 | 添加"上下箭头按钮"操作作为 fallback |
