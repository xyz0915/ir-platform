# IR 平台日志检索功能优化方案 v2

> 基于应急专家原始分析（2026-07-19，commit 33485a9）修正 + 现状复核后优化
> 复核日期：2026-07-21 | 当前基准 commit：7818afd

---

## 一、原始分析准确性评价

### ✅ 正确的判断（仍然成立）

| 原文观点 | 验证结果 |
|---------|---------|
| 存在三张核心日志表：`agent_imports` / `normalized_logs` / `security_events` | ✅ 仍成立，三表 schema 各自独立 |
| `agent_imports` 字段太薄（仅 9 字段 + raw_json blob），FTS5 搜索精确性差 | ✅ 仍成立，raw_json 中有效字段被埋没 |
| 手工 EVTX 导入的数据不写 `agent_imports` → 在 `/log-search` 搜不到 | ✅ 仍成立，`import_log_service.py` 未写 `agent_imports` |
| 缺少统一跨表检索入口 | ✅ 仍成立，三个页面三套 API |
| `/log-search` 缺少日志类型/严重度/时间筛选器 | ✅ 仍成立 |

### ❌ 已过时或偏差的判断

| 原文观点 | 现状 |
|---------|------|
| "三条平行管线完全不互通" | ⚠️ **部分已修复**：主 JSON 导入（`import_service.py`）已同时写入 `agent_imports` + `security_events` + 数据已归一化关联 |
| "智能检索搜到的数据不对" | ❌ **已修复**：`nl_log_search` 已改为搜索 `security_events`（867 条安全事件），而非 `normalized_logs`（407 条 Windows 日志） |
| "建议建结构化索引视图提取 raw_json 字段" | ⚠️ **已有更好方案**：`security_events.evidence` 已包含 Mapper 解析后的结构化字段，T01 又注入了 `_raw_extra`，无需另建一张索引表 |

### 核心结论

> 原始分析准确指出了"日志检索碎片化"的问题，但其 P0 方案（建 `agent_imports_structured` 索引表）在当前架构下已不是最优解。**`security_events` 表 + `evidence` 字段已经承担了"结构化日志索引"的角色**。优化方向应是：**打通 `/log-search` 与 `security_events` 的检索链路**，而非另造一张新表。

---

## 二、当前架构现状图（修正后）

```
Agent JSON 导入 (import_service.py)
  │
  ├─→ agent_imports (54 条)    ← 原始报文，FTS5 全文检索
  ├─→ event_normalizer
  │     ├─→ security_events (867 条)  ← 结构化安全事件 ✓
  │     │     └─ evidence + _raw_extra  → 字段已丰富 ✓
  │     └─→ normalized_logs (407 条)  ← Windows 日志
  └─→ 服务风险分析 (analysis_service.py)
        └─→ abnormal_processes / 等分析表

手工 EVTX 导入 (import_log_service.py)
  ├─→ normalized_logs           ← 写 normalized_logs
  ├─→ security_events           ← 写 security_events
  ├─→ import_results            ← 写 import_results
  └─→ 不写 agent_imports        ← ❌ 所以 /log-search 搜不到

前端页面                    →    对应表
  /log-search               →    agent_imports (只看到 54 条元数据 + FTS5)
  /analysis-center          →    security_events (867 条安全事件)
  /logs                     →    normalized_logs (407 条 Windows 日志)
  智能检索 (POST /nl-log-search)  →  security_events ✅ 已修复
```

---

## 三、优化方案（基于现状修正后）

### P0-1：让 `/log-search` 展示 security_events 数据

**目标**：日志检索页不再只搜 `agent_imports` 的 54 条原始报文元数据，改为展示 `security_events` 的 867 条结构化安全事件。

#### 后端改动

修改 `log_search.py` API：

```
改前:
  GET /api/log-search/search → log_importer.search() → agent_imports (FTS5)

改后:
  GET /api/log-search/search → search_events() → security_events (SQL 字段匹配)
```

改造 `log_search.py` 中 4 个端点：

| 端点 | 改前 | 改后 |
|------|------|------|
| `GET /search` | FTS5 搜 agent_imports | 搜 security_events（关键词 + 字段筛选） |
| `GET /search/advanced` | _parse_advanced_query → FTS5 | **删除此端点**（死代码） |
| `GET /search/export` | 导出 agent_imports | 导出 security_events |
| `GET /list` | 列 agent_imports | 列 security_events（可保留双表切换） |

复用 `nl_log_search.py` 中新增的 `search_events()` 函数，无需重复造轮。

**涉及文件**：`log_search.py`、`log_importer.py`（删减冗余代码）

**工作量**：约 0.5 天

---

### P0-2：前端 `/log-search` 增加筛选维度

在日志检索页增加已可筛选的维度（security_events 已有这些字段）：

| 筛选维度 | security_events 字段 | 说明 |
|---------|---------------------|------|
| 事件类型 | `event_type` | process_start / network_outbound / registry_modify / file_create 等 |
| 严重级别 | `severity` | critical / high / medium / low |
| 攻击阶段 | `attack_stage` | persistence / defense_evasion / credential_access 等 |
| 引擎来源 | `source_collector` | osquery / cm |
| 事件状态 | `status` | pending / investigating / resolved / dismissed |
| 时间范围 | `timestamp` | 精确起止时间选择器 |

**分类 Tab 视图**：参考分析中心的事件分类标签，在日志检索页复用同一套组件。

**涉及文件**：前端日志检索页面（`frontend/src/views/LogSearchView.vue` 或类似页面）

**工作量**：约 1-2 天

---

### P1-1：手工导入管线统一写入 `agent_imports`

**目标**：手工 EVTX 导入的数据也能在 `/log-search` 搜到。

**改动**：在 `import_log_service.py` 的导入流程末尾，追加写 `agent_imports`：

```python
# 在步骤 5 之后追加（import_log_service.py ≈ L305）
try:
    from app.services.log_importer import import_batch as log_import_batch
    records_to_import = [{
        "collector_type": log_source,  # evtx / syslog
        "raw_json": json.dumps(parsed_items, ensure_ascii=False),
    }]
    log_import_batch(host_id, records_to_import, case_id=case_id)
except Exception as exc:
    logger.warning("agent_imports write failed (non-blocking): %s", exc)
```

**涉及文件**：`import_log_service.py`

**工作量**：约 0.5 天

---

### P1-2：删除死代码（精简臃肿）

原文已指出 `_parse_advanced_query()` 和 `search_advanced()` 是 140 行死代码。当前仍需确认是否有人用过，建议：

1. 审计 `nl_query_audit` 表是否有 `search_advanced` 的调用记录
2. 如无使用记录 → 删除 `_parse_advanced_query()`、`search_advanced()`、`GET /search/advanced` 端点
3. 保留接口返回 `501 Not Implemented` 或重定向到 `search()`

**涉及文件**：`log_importer.py`（-140 行）、`log_search.py`（-10 行）

**工作量**：约 0.5 天

---

### P2：统一跨表检索（长期优化）

**目标**：一个搜索入口查全部日志。

```
统一检索 API: GET /api/logs/unified-search?keyword=xxx&types=all,events,imports
  │
  ├─ 搜索 security_events (关键词 + event_type + severity + time)
  ├─ 搜索 agent_imports (关键词 + collector_type + time，FTS5 兜底)
  ├─ 搜索 normalized_logs (字段匹配 + time)
  │
  └─ 统一分页 + 时间排序 + 来源标记
```

**前端**：在日志检索页加一个"范围"筛选器，可选：
- "仅安全事件"（默认，`security_events`）
- "含原始日志"（`security_events` + `agent_imports`）
- "全量日志"（三表合并）

**工作量**：约 3-5 天（含前后端）

---

## 四、执行路线图

```
第 1 周: P0-1 (日志检索页改查 security_events) + P0-2 (前端筛选)
          效果: /log-search 从 54 条元数据 → 867 条安全事件，可筛选
第 2 周: P1-1 (手工导入写 agent_imports) + P1-2 (删死代码)
          效果: 三表数据基本打通，代码减 150 行
第 3 周: P2 (统一跨表检索)
          效果: 一个搜索入口搜所有
```

---

## 五、与原始方案的差异对照

| 项 | 原始方案 | v2 优化方案 | 差异原因 |
|----|---------|------------|---------|
| P0-1 | 建 `agent_imports_structured` 索引表 | 改为让 `/log-search` 搜索 `security_events` | 原始方案未考虑 `security_events.evidence` 已承担结构化解析角色。已有数据（867 条）无需再造一份。 |
| P0-2 | 前端加分类筛选 | 同原始方案，补充 security_events 可用字段 | 基本一致，补充了攻击阶段/引擎来源/状态等筛选维度 |
| P1-1 | 建统一跨表检索引擎 | 先做手工导入写 agent_imports + 删死代码 | 统一检索引擎改动量大（3-5 天），先做小改打通数据通路 |
| P1-2 | 无 | 删除 `_parse_advanced_query` 等死代码 | 原始方案未审计死代码问题 |
| P2 | 无 | 统一跨表检索 | 原始方案的 P1-1 降级为 P2 |
