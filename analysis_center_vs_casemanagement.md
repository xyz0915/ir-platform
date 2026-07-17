# 分析中心 vs 案例管理：case 8 事件数量差异根因分析

## TL;DR
分析中心（AC）与案例管理（CM）是**两条完全独立的数据链路**，数据源、算法、输出表都不同。
CM 侧通过行为/语义分析引擎直接读原始采集数据，命中 18 异常进程 / 10 持久化 / 8 启动项 / 4 文件 hash（host 29 共 36 项）并生成融合检测与时间线；
AC 侧只对归一化后的 `security_events` 跑规则匹配，且**行为类规则因 category-map 缺口从未被执行**，最终只命中 12 条（process×2 + persistence_register×10）。

## 已核实的关键事实（来自真实数据库 `data/ir_platform.db`）

### 案例管理（CM）— `AnalysisService.analyze(host_id)`
- 数据来源：Agent 原始采集 JSON（`ImportService.read_raw_json`），**不经过 security_events**。
- 引擎：`AnomalyDetector` / `PersistenceFinder` / `TimelineBuilder` / `ProcessTreeBuilder` / `RiskAssessor` 等 `app/analysis/*` 模块。
- 输出表（host 29 = case 8 主机的 `analysis_results` 原文）：
  - "异常进程 **18** 项，可疑启动项 **8** 项，可疑持久化 **10** 项，knowledge_hits **4** 项。共发现 **36** 项"
  - host 28 为 16 / 8 / 10 / 4 = 34 项。
- 融合检测：`incident_correlations` 表（534 条通用告警），标题含 `suspicious_service_path` / `orphan_process` / `short_lived_shell` / `unsigned_process`，均包含 host 28/29。这正是 CM 侧行为检测的产物。
- 时间线：`timeline_events` 表（host 29 有记录）。

### 分析中心（AC）— `rule_matcher.match_event()`
- 数据来源：`security_events` 表（经 `event_normalizer` 归一化），case 8 共 **1637 条**，全部 `severity=medium`。
- 规则匹配：`_load_rules_by_categories()` 只加载「该 event_type 在 `_EVENT_TYPE_CATEGORY_MAP` 中可达的 category」对应的启用规则。
- 命中结果：**仅 12 条**有非空 `matched_rules`（1625 条为 `[]`）：
  - `process_start` × 2（rule 9 `cmd_powershell_chain`）
  - `persistence_register` × 10（rule 24/25/27/30 等 run_key / startup_folder / service_path）

### 根因：为什么行为类检测在 AC 侧完全缺失
- `_EVENT_TYPE_CATEGORY_MAP`（rule_matcher.py）把 event_type 映射到候选 category，**没有任何 event_type 映射到 `behavior` category**（已用代码确认：`event_types mapping to 'behavior': []`）。
- 因此所有 `category='behavior'` 的规则（包含 `orphan_process` / `short_lived_shell` / `unsigned_process` —— 也就是 CM 融合检测里那些告警）**永远不会被 `_load_rules_by_categories` 加载**，AC 侧对它们零覆盖。
- 附带缺陷：`orphan_process` 规则内 `parent_name=None` → `str(None)="none"` → `"explorer" not in "none"` 恒为 True，即使放开 category 网关也会大量误报（此前审计实测放开后 1637 条全部命中，且全部来自该规则）。

## 关于「22 条」的澄清
当前数据库里 AC 对 case 8 的真实数字是 **12 条命中 / 1637 条总量**，**不是 22**。
「22」最可能的来源（按可能性排序）：
1. 某个带筛选条件的 UI 视图（如按 case 8 + 特定 host / 时间窗 / severity 过滤后的计数），而非全量匹配数；
2. 先前审计中「扩展 `high_value_path` 规则后可多命中约 22 条可疑目录文件（a.exe / mm.exe / sw.exe / f.exe / ir_agent.exe）」的**改进估算值**，并非 AC 当前显示值；
3. 记忆或截图中的近似数字。

如果你能告诉我具体是哪个界面/筛选条件下看到的「22」，我可以精确定位是哪条查询产生的。

## 结论
- 数量差异**不是 bug**，而是架构使然：CM 是语义/行为分析引擎（吃原始数据），AC 是规则匹配引擎（吃归一化事件）。两者的"事件"根本不是同一批。
- CM 找到的丰富行为线索（异常进程、孤儿进程、无签名进程、融合告警、时间线）**天然不会出现在 AC**，因为 AC 的规则网关把 behavior 类规则整个排除在外。
- 若希望 AC 也能体现这些行为发现，需：① 在 `_EVENT_TYPE_CATEGORY_MAP` 为相关 event_type 增加 `behavior` 类别；② 修复 `orphan_process` 的 `None` 父进程误判；③ 把 CM 的融合检测结果回写到 `security_events` 或建立双向同步。

## 涉及文件
- `backend/app/services/rule_matcher.py` — `_EVENT_TYPE_CATEGORY_MAP`、`_load_rules_by_categories()`、`_match_behavior()`（orphan_process 缺陷）
- `backend/app/services/event_normalizer.py` — Agent JSON → security_events
- `backend/app/services/analysis_service.py` — `AnalysisService.analyze(host_id)`
- `backend/app/analysis/anomaly_detector.py` / `persistence_finder.py` / `process_tree_builder.py` / `timeline_builder.py`
- `backend/app/analysis/scene_aggregator.py` — 融合检测场景汇聚
- `backend/app/api/events.py`（AC 接口）/ `backend/app/api/analysis.py`（CM 接口）
