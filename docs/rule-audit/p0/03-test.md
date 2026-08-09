# P0 阶段测试文档 —— 规则真实性与事件日志桥接

| 项 | 内容 |
| --- | --- |
| 阶段 | P0（阻断级缺陷修复） |
| 环节 | 测试（第 3/4 环节） |
| 上游 | `p0/01-design.md`、`p0/02-dev.md` |
| 测试套件 | `backend/tests/test_p0_rule_authenticity.py` |
| 用例总数 | 68 |
| 执行结果 | **68 passed, 0 failed**（耗时 53.94s） |
| 编写日期 | 2026-08-08 |

---

## 1. 测试目标

P0 阶段修复的是"规则看似存在、实际不可能命中"的**真实性缺陷**，因此测试不能只验证"函数返回 True"，必须验证三件事：

1. **不可造假**：占位 IOC 被移除后，规则在情报库为空时**必须不命中**（不能靠残留常量蒙混）。
2. **真可用**：导入真实 IOC 后，同一条输入**必须立即命中**（不重启、不重载）。
3. **不误伤**：新增能力不得让正常主机产生告警，且不得破坏存量 7 种规则类型的行为。

---

## 2. 测试环境

| 项 | 值 |
| --- | --- |
| OS | Windows |
| Python | 3.13.12（`backend/venv`） |
| 测试框架 | pytest（`pyproject.toml` 内配置 rootdir） |
| 数据库 | 每个端到端用例使用 `tmp_path` 独立 SQLite，通过 `temp_db` fixture 预置 `cases(id=1)` 与 `hosts(id=1,7)` |
| 隔离策略 | IOC 相关用例通过 `global_context` 注入内存态 IOC；依赖扫描用例通过 `inventory` 形参注入，**不读真实 `iocs` 表** |

执行命令：

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/test_p0_rule_authenticity.py -q -p no:warnings
```

---

## 3. 用例设计与结果

### 3.1 P0-1 占位 IOC 清除（3 例）

| # | 用例 | 设计意图 | 结果 |
| --- | --- | --- | --- |
| 1 | `test_no_placeholder_in_matchable_values` | 全规则库（4 个 JSON）grep `example.com` / `attacker.net` / `185.174.137.11`，命中数必须为 0 | PASS |
| 2 | `test_c2_domain_rule_is_ioc_driven` | `suspicious_c2_domain` 的 `values` 为空数组且声明 `ioc_types` | PASS |
| 3 | `test_attack_chain_c2_step_is_ioc_driven` | 攻击链 `attack_chain_default_c2_persistence` step2 同样为 IOC 驱动 | PASS |

> **说明**：用例 1 在首轮执行时曾失败——`values` 已清空，但 `_meta.ioc_note` 注释文本里仍残留 `evil.example.com` 字样。这类残留虽不参与匹配，却会让后续审计 grep 产生假阳性，因此按"零残留"标准改写了注释文案。

### 3.2 P0-1 IOC 类型解析 `resolve_ioc_types`（5 例）

| # | 用例 | 覆盖分支 | 结果 |
| --- | --- | --- | --- |
| 4 | `test_field_mapping_multi_type` | `remote_address` → `["ip","domain"]`（本次新增的多类型映射） | PASS |
| 5 | `test_legacy_string_mapping_still_works` | 旧的 `str` 单值映射自动包装为单元素列表（向后兼容） | PASS |
| 6 | `test_explicit_condition_overrides_field` | `condition.ioc_types` 优先级高于字段映射表 | PASS |
| 7 | `test_unmapped_field_returns_empty` | 未映射字段返回 `[]`，不抛异常 | PASS |
| 8 | `test_dedup_and_order_preserved` | 重复类型去重，且保持声明顺序 | PASS |

### 3.3 P0-1 动态 IOC 匹配（6 例）—— 核心真实性断言

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 9 | `test_empty_ioc_store_never_matches` | IOC 库为空 → 任意 `remote_address` **不命中** | PASS |
| 10 | `test_no_global_context_never_matches` | 完全不传 `global_context` → 不命中（不得回落到硬编码） | PASS |
| 11 | `test_domain_ioc_hits_after_import` | 导入 1 条 `domain` IOC → 同一输入立即命中 | PASS |
| 12 | `test_ip_ioc_hits_on_same_field` | 同一字段的 `ip` 类 IOC 也能命中（验证多类型合并） | PASS |
| 13 | `test_irrelevant_ioc_type_does_not_match` | 导入 `hash` 类 IOC 不影响 `remote_address` 判定 | PASS |
| 14 | `test_static_values_still_work` | 静态 `values` 与动态 IOC 可并存合并 | PASS |

用例 9/10 与 11/12 构成一对**互斥证据**：前者证明"删干净了"，后者证明"还能用"。缺任何一半，改造都不算成立。

### 3.4 P0-2 新规则类型注册（3 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 15 | `test_rule_type_enum_contains_new_type` | `RULE_TYPE_ENUM` 含 `event_log_summary`（共 8 种） | PASS |
| 16 | `test_matcher_registered` | `MatcherRegistry` 可 dispatch 到新匹配器 | PASS |
| 17 | `test_confidence_default_present` | `_CONFIDENCE_DEFAULT["event_log_summary"] == 0.8` | PASS |

### 3.5 P0-2 条件校验（9 例）

| # | 用例 | 输入 | 期望 | 结果 |
| --- | --- | --- | --- | --- |
| 18 | `test_valid_single_event` | `{event_id: "4625", count: 10}` | 通过 | PASS |
| 19 | `test_valid_multi_event` | `{event_ids: ["4625","4771"]}` | 通过 | PASS |
| 20 | `test_defaults_are_accepted` | 省略 `aggregate`/`operator` | 通过（取默认） | PASS |
| 21 | `test_missing_event_id_rejected` | 二者皆缺 | 拒绝 | PASS |
| 22 | `test_empty_event_ids_rejected` | `event_ids: []` | 拒绝 | PASS |
| 23 | `test_bad_operator_rejected` | `operator: "~="` | 拒绝 | PASS |
| 24 | `test_bad_aggregate_rejected` | `aggregate: "avg"` | 拒绝 | PASS |
| 25 | `test_negative_count_rejected` | `count: -1` | 拒绝 | PASS |
| 26 | `test_non_int_count_rejected` | `count: "10"` | 拒绝 | PASS |

### 3.6 P0-2 匹配器行为（14 例）

| # | 用例 | 场景 | 结果 |
| --- | --- | --- | --- |
| 27 | `test_above_threshold_matches` | 37 ≥ 10 → 命中 | PASS |
| 28 | `test_below_threshold_not_match` | 3 ≥ 10 → 不命中 | PASS |
| 29 | `test_boundary_equal_matches_for_gte` | **边界值** 10 ≥ 10 → 命中 | PASS |
| 30 | `test_int_key_normalized` | key 为 `int 4625` 而非 `"4625"` → 归一后命中 | PASS |
| 31 | `test_bare_summary_dict_supported` | 裸计数字典（无 `event_ids_summary` 包裹） | PASS |
| 32 | `test_empty_summary_not_match` | `{}` → 不命中 | PASS |
| 33 | `test_missing_key_counts_as_zero` | 缺失事件 ID 按 0 计，不抛 KeyError | PASS |
| 34 | `test_non_dict_input_not_match` | 传入 `list`/`str`/`None` → 不命中且不异常 | PASS |
| 35 | `test_aggregate_sum` | 多 ID 求和后比较 | PASS |
| 36 | `test_aggregate_any` | 任一 ID 达标即命中 | PASS |
| 37 | `test_aggregate_max` | 取最大值比较 | PASS |
| 38 | `test_less_than_operator` | `<` / `<=` 反向阈值 | PASS |
| 39 | `test_unknown_operator_returns_false` | 非法运算符返回 False（不抛出、不误判） | PASS |
| 40 | `test_dispatch_via_registry` | 经注册表分发路径等价于直调 | PASS |

### 3.7 P0-2 规则文件（5 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 41 | `test_six_rules_defined` | `event_log_rules.json` 定义 6 条 | PASS |
| 42 | `test_expected_event_ids_covered` | 覆盖 4625/4648/4662/4769/4672/4624 | PASS |
| 43 | `test_all_conditions_pass_validation` | 6 条 condition 全部通过 `validate_condition` | PASS |
| 44 | `test_normal_baseline_produces_no_alert` | **真实正常主机快照** `{4672:31, 4624:33, 4648:8, 4776:2, 4625:1}` → 0 命中 | PASS |
| 45 | `test_attack_scenario_triggers_expected_rules` | 构造攻击态快照 → 命中预期规则集合 | PASS |

> 用例 44 是阈值标定的守门用例：6 条规则的阈值全部按这份真实基线上浮设定（如 4624 基线 33 → 阈值 100），确保上线首日不会把正常办公主机刷成告警。

### 3.8 P0-2 载荷解析 `extract_event_summary`（7 例）

| # | 用例 | 输入形态 | 结果 |
| --- | --- | --- | --- |
| 46 | `test_collector_object` | 采集器原生 dict | PASS |
| 47 | `test_list_wrapped` | list 包裹的单元素 | PASS |
| 48 | `test_json_string` | JSON 字符串（Agent 侧序列化场景） | PASS |
| 49 | `test_bare_counter_dict` | 裸计数字典 | PASS |
| 50 | `test_multi_element_merged` | 多元素 list → 按事件 ID 合并求和 | PASS |
| 51 | `test_none_and_garbage` | `None` / 非法类型 → 返回 `{}` 不抛异常 | PASS |
| 52 | `test_non_numeric_values_skipped` | 值非数字 → 跳过该项而非整体失败 | PASS |

### 3.9 P0-2 端到端告警（6 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 53 | `test_alert_created_from_payload` | 调用 `evaluate_and_alert` 后 `alerts` 表新增记录 | PASS |
| 54 | `test_repeat_call_is_idempotent` | 5 分钟窗口内重复调用不新增行（聚合计数 +1） | PASS |
| 55 | `test_normal_payload_creates_no_alert` | 正常基线载荷 → 0 新增 | PASS |
| 56 | `test_empty_payload_is_safe` | 空/缺失 `security` 字段 → 静默返回，不影响导入主流程 | PASS |
| 57 | `test_unknown_host_reports_no_false_success` | **不存在的 host_id → 返回空列表，不报告虚假成功** | PASS |
| 58 | `test_alert_detail_contains_evidence` | 告警 detail 内含 `observed_counts` 证据字段 | PASS |

### 3.10 P0-3 死规则下线（3 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 59 | `test_dead_rules_disabled_with_reason` | 2 条规则 `enabled == false` 且 `_meta.disabled_reason == "no_producer_field"` | PASS |
| 60 | `test_label_marks_offline_state` | `label` 带"（已下线·待采集器补齐）"后缀，界面可辨识 | PASS |
| 61 | `test_rules_not_deleted` | 规则**保留**在文件中（含 `depends_on` 复活线索），未被物理删除 | PASS |

### 3.11 规则加载完整性（3 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 62 | `test_all_rules_load_without_drop` | `loader.load_default_rules()` 加载 4 个 JSON 无丢弃、无 warning | PASS |
| 63 | `test_rule_type_distribution` | 类型分布符合预期（见下表） | PASS |
| 64 | `test_no_duplicate_rule_names` | 规则名唯一（防止新文件与存量撞名） | PASS |

加载后真实清单（共 **147** 条）：

| 类型 | 数量 |
| --- | --- |
| regex | 62 |
| behavior | 40 |
| composite | 13 |
| list | 11 |
| attack_chain | 10 |
| **event_log_summary** | **6（本次新增）** |
| threshold | 3 |
| exists | 2 |

### 3.12 IOC 依赖可观测（4 例）

| # | 用例 | 断言 | 结果 |
| --- | --- | --- | --- |
| 65 | `test_scan_reports_c2_rule_as_dependent` | 扫描结果含 `suspicious_c2_domain` | PASS |
| 66 | `test_unsatisfied_when_ioc_store_empty` | 注入空 `inventory` → `satisfied=false`、`unsatisfied_count>0` | PASS |
| 67 | `test_satisfied_once_ioc_imported` | 注入含 `domain` 的 inventory → `satisfied=true` | PASS |
| 68 | `test_attack_chain_steps_are_scanned` | 攻击链 `ordered_steps[*].match` 也被纳入扫描 | PASS |

---

## 4. 缺陷记录（测试阶段发现并修复）

首轮执行结果为 **63 passed / 3 failed**，发现 2 个真实缺陷，均已修复后复测转绿。

### DEF-P0-01 —— 外键失败被吞，上报虚假成功（严重）

- **发现用例**：`test_alert_created_from_payload`、`test_alert_detail_contains_evidence`
- **现象**：`FOREIGN KEY constraint failed`，但 `evaluate_and_alert` 仍返回"已产生告警"。
- **根因**：`Alert.create_or_aggregate` 内部捕获异常后返回 `(None, False)`，而桥接层未检查 `alert_id` 是否为 `None`，直接把该结果追加进成功列表。生产环境下这会导致**告警丢失却显示成功**。
- **修复**：`security_event_rules.py` 在 `create_or_aggregate` 之后增加空值分支——`alert_id is None` 时记 warning 并 `continue`，不计入返回结果。
- **回归**：新增 `test_unknown_host_reports_no_false_success` 长期锁定该行为。

### DEF-P0-02 —— 依赖扫描读真实库导致用例不可复现（中）

- **发现用例**：`test_unsatisfied_when_ioc_store_empty`
- **现象**：开发环境 `iocs` 表已有数据，"空情报库"场景得到 `unsatisfied_count=0`，与预期相反。
- **根因**：`scan_ioc_dependent_rules()` 直接查真实表，测试无法隔离。
- **修复**：为该函数增加可选 `inventory` 形参（不传时仍走真实表），测试注入 `{}`。副产品是**支持了 dry-run 演练**——运维可预演"若导入某类情报，会激活哪些规则"。
- **回归**：补充 `test_satisfied_once_ioc_imported` 覆盖正向场景。

此外还修正了 `temp_db` fixture 的建表 SQL（`cases` 表字段是 `case_number` 而非 `case_no`），属测试代码自身问题。

---

## 5. 存量回归

### 5.1 结论

P0 改动涉及 `rule_engine.py`、`analysis.py`（schema）、`import_service.py` 三个存量文件，均为**追加式改动**，无接口签名变更。存量规则匹配测试全部通过，详见 `p0/04-verify.md` 的回归执行记录。

### 5.2 环境阻塞说明（重要，非本次引入）

执行 `pytest tests/` 全量收集时进程崩溃：

```
Windows fatal exception: access violation
  File "...\venv\Lib\site-packages\torch\__init__.py", line 445 in <module>
```

**排查结论**：在干净进程中单独执行 `import torch` 即崩溃，与本次改动无任何调用关系。这是本机 torch 二进制/DLL 层面的环境故障（既有问题）。

受影响的是 22 个在模块导入期即引入 `torch → transformers → sentence_transformers` 链的 AI/Agent 相关测试文件（如 `test_knowledge_retriever.py`、`test_batch2_agents.py` 等）。这些文件与规则引擎无耦合。

**处置**：回归时以 `--ignore` 排除上述 22 个文件，其余全部执行。该环境问题应作为独立议题单独跟踪修复，不阻塞 P0 验收。

---

## 6. 测试结论

| 维度 | 结论 |
| --- | --- |
| 用例通过率 | 68/68 = **100%** |
| 真实性双向验证 | 通过（空库不命中 + 导入即命中，两侧证据齐全） |
| 边界与异常覆盖 | 通过（阈值边界、类型异常、空输入、非法运算符、未知主机） |
| 误报防护 | 通过（真实正常主机基线 0 命中） |
| 缺陷收敛 | 2 个（DEF-P0-01 严重 / DEF-P0-02 中）均已修复并补充回归用例 |
| 遗留风险 | torch 环境崩溃（既有，与本阶段无关），已单列跟踪 |

**建议进入验证环节。**
