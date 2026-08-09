# P0 阶段 · 设计文档（需求与架构说明）

- 文档编号：RA-P0-01
- 阶段：P0 — 必须修复（真实性缺陷）
- 依据：`docs/rule-audit/optimized-feasibility-v2.md` 第 P0 章
- 状态：已评审 / 进入开发
- 关联任务：#101 / #102 / #103

---

## 1. 背景与问题陈述

规则库审计（v2）在代码层确认了三类**"检测能力真实性"缺陷**：规则在库内计数、在 UI 上显示为 `enabled=true`，
但在真实数据流中**永远不可能命中**，形成"账面覆盖"而非"实际覆盖"。

| 编号 | 缺陷 | 代码证据 | 危害 |
|------|------|----------|------|
| P0-1 | 占位/虚构 IOC | `default_rules.json::suspicious_c2_domain` 的 3 个 `*.example.*` 值；`default_attack_chain.json::attack_chain_default_c2_persistence` step2 的 `evil.example.com` / `c2.attacker.net` / `185.174.137.11` | 规则永不命中真实 C2；攻击链第 2 步必断，整条 critical 攻击链失效 |
| P0-2 | Security 事件日志未接入规则引擎 | `agent/collectors/security.py` 产出 `event_ids_summary`，但 `backend` 侧仅落 `agent_imports.raw_json`，无任何规则消费 | 4625/4648/4662/4769/4672/4624 等**Windows 核心安全审计事件全部漏报** |
| P0-3 | 2 条 `exists` 死规则 | `suspicious_service_reg_exists`(field=`service_image_path`)、`suspicious_scheduled_task_xml_exists`(field=`scheduled_task_xml`)，无任何采集器产出该字段，且 `enabled=true` | 虚假覆盖；分析员误以为已覆盖 T1543/003、T1053/005 |

---

## 2. 设计目标

| 目标 | 可度量验收口径 |
|------|----------------|
| G1 | 规则库中不存在 `example.com` / `attacker.net` 类虚构 IOC 字面量 |
| G2 | C2 类规则改为**动态情报驱动**：`iocs` 表为空时零命中（不误报），导入情报后**立即**生效（无需重启） |
| G3 | 攻击链 C2 步骤与 G2 同源，不再因占位值必断 |
| G4 | 新增 `event_log_summary` 规则类型，端到端把 `event_ids_summary` 转成告警 |
| G5 | 死规则显式 `enabled:false` 并标注失效原因，UI/文档可追溯 |
| G6 | 全部改动**向后兼容**：存量 141 条规则语义不变，存量测试全绿 |

## 3. 非目标（明确排除）

- **不**内置任何"看起来像真的"的假 IOC 种子数据。审计的核心批评就是虚构指标；用另一批无法验证的
  硬编码 IP/域名替换，只是把问题从"明显假"变成"隐蔽假"。IOC 必须由用户/情报源导入。
- 不在 P0 做误报治理（属 P2）、不新增检测点（属 P3）、不做行为基线（属 P1-5）。
- 不改动 `attack_chain` 在 `MatcherRegistry` 中的 stub 注册语义（攻击链走 `_match_attack_chain`
  主机级关联通道，非逐条 dispatch 通道，现状正确）。

---

## 4. 方案设计

### 4.1 P0-1 · 占位 IOC → 动态情报引用

#### 4.1.1 现状机制

引擎已具备动态 IOC 能力，无需从零造轮子：

```
evaluate() ──► global_context["iocs_by_type"] = RuleEngine._load_iocs_by_type()
                                                    │
                                                    ▼
                                       Ioc.list() → {ip:{...}, domain:{...}, ...}
                                                    │
_match_list(item, condition, global_context) ───────┘
   merged_values = condition.values ∪ iocs_by_type[FIELD_TO_IOC_TYPE[field]]
```

#### 4.1.2 现状缺口

`FIELD_TO_IOC_TYPE` 的值是**单个字符串**，`remote_address → "ip"`。而 `suspicious_c2_domain`
的语义是"连接恶意 **C2 域名**"，字段同样是 `remote_address`。结果：即使用户导入了 domain 类 IOC，
该规则也永远取不到。**这是把占位值删掉后规则会彻底哑掉的根因**，必须一并修。

#### 4.1.3 设计决策

| 决策 | 内容 | 理由 |
|------|------|------|
| D1 | `FIELD_TO_IOC_TYPE` 的值支持 `str` 或 `list[str]`，`remote_address` 改为 `["ip", "domain"]` | 出站连接字段天然可承载 IP 与域名两种形态；保持 `str` 兼容存量映射 |
| D2 | `condition` 新增可选键 `ioc_types: list[str]`，**显式覆盖**字段推导 | 规则作者可精确声明依赖的情报类型，不受字段名歧义影响 |
| D3 | `condition._meta.requires_ioc: true` 标记"该规则依赖外部情报" | 供 UI/巡检展示"待接入情报源"，把隐性依赖显性化 |
| D4 | 目标规则 `values` 置为 `[]`，规则保持 `enabled:true` | `values=[]` + `iocs` 空 ⇒ `merged_values` 为空 ⇒ `_match_list` 直接 `return False`，零误报；导入情报后立即生效 |
| D5 | 新增 `app/rules/ioc_dependency.py` 巡检模块 + `GET /api/rules/ioc-dependency` | 让"规则依赖情报但情报库为空"这一风险**可观测**，而非埋在 JSON 里 |

优先级：`condition.ioc_types` > `FIELD_TO_IOC_TYPE[field]` > 无动态引用。

#### 4.1.4 改动清单

| 文件 | 改动 |
|------|------|
| `backend/app/rules/rule_engine.py` | `FIELD_TO_IOC_TYPE` 支持 list；新增 `_resolve_ioc_types(field, condition)`；`_match_list` 改为遍历多类型合并 |
| `backend/app/rules/default_rules.json` | `suspicious_c2_domain`：`values → []`，加 `ioc_types:["domain","ip"]`、`_meta.requires_ioc:true` |
| `backend/app/rules/default_attack_chain.json` | step2 `match`：`values → []`，加 `ioc_types:["domain","ip"]` |
| `backend/app/rules/ioc_dependency.py`（新增） | `scan_ioc_dependent_rules()` → 依赖情报的规则清单 + 各类型 IOC 存量 + `satisfied` 布尔 |
| `backend/app/api/rules.py` | 新增 `GET /ioc-dependency` |

### 4.2 P0-2 · Security 事件日志桥接（核心工作量）

#### 4.2.1 数据流现状与目标

```
现状：agent/collectors/security.py
        └─ {"event_ids_summary": {"4625": 37, ...}, "event_records":[...]}
             └─► import_service.py → log_importer → agent_imports.raw_json
                    └─► ❌ 断点：无任何规则消费，永不产生告警

目标：                                  ┌─► agent_imports（保留，全文检索用）
      security payload ─► import_service ┤
                                         └─► security_event_rules.evaluate_and_alert()
                                                └─► RuleEngine(event_log_summary 规则)
                                                       └─► Alert.create_or_aggregate()
```

#### 4.2.2 新规则类型 `event_log_summary`

选择"**新增规则类型**"而非"展开成逐条 canonical event"的理由：
`event_ids_summary` 本质是**窗口内计数聚合**（`{"4625": 37}`），没有逐条时间戳。强行展开成 37 条
伪事件会污染时间线、破坏 `security_events` 的时间语义。计数型数据用计数型规则表达，语义直达。

**condition schema：**

```jsonc
{
  "event_id": "4625",            // 单事件 ID（与 event_ids 二选一）
  "event_ids": ["4648", "4624"], // 多事件 ID（与 aggregate 配合）
  "aggregate": "sum",            // sum(默认) | max | any —— 仅 event_ids 时生效
  "operator": ">=",              // >= (默认) | > | == | <= | <
  "count": 10,                   // 阈值，默认 1
  "_meta": {"mitre_attack": "T1110"}
}
```

**匹配语义：** 从 `data_item` 取 `event_ids_summary`（兼容 `data_item` 本身即 summary 的裸字典形态），
按 `event_id`/`event_ids` + `aggregate` 求出实测值 `actual`，与 `count` 按 `operator` 比较。
键统一按字符串归一（`4625` 与 `"4625"` 等价）。

**校验规则（`validate_condition`）：** `event_id` 与 `event_ids` 至少有一；`event_ids` 必须为非空列表；
`operator` 必须在白名单；`count` 必须可转 `int` 且 ≥ 0；`aggregate` 必须在 `{sum,max,any}`。

#### 4.2.3 首批规则（`event_log_rules.json`，6 条）

| 规则名 | 事件 | 条件 | 严重度 | ATT&CK |
|--------|------|------|--------|--------|
| `evt_4625_failed_logon_burst` | 4625 登录失败 | `>= 10` | high | T1110 |
| `evt_4648_explicit_cred_burst` | 4648 显式凭据登录 | `>= 15` | medium | T1078 |
| `evt_4662_dcsync_suspect` | 4662 目录服务对象访问 | `>= 1` | critical | T1003/006 |
| `evt_4769_kerberoasting_suspect` | 4769 Kerberos 服务票据 | `>= 30` | high | T1558/003 |
| `evt_4672_special_privilege_anomaly` | 4672 特权登录 | `>= 50` | medium | T1078/002 |
| `evt_4624_logon_volume_anomaly` | 4624 成功登录 | `>= 100` | low | T1078 |

阈值设定原则：以**真实快照数据**为基线校准，避免上线即刷屏。
观测样本（`purge_snapshots/33`）：`4672:31, 4624:33, 4648:8, 4776:2, 4625:1`。
上表阈值均高于该正常基线，保证"正常主机不产生告警"。

> 说明：`4662`/`4769` 在非域环境样本中为 0，阈值取 `>=1`/`>=30` 属保守起步值，
> P1-5 引入行为基线后转为动态阈值。

#### 4.2.4 服务层 `services/security_event_rules.py`

```python
evaluate_and_alert(host_id, security_payload, case_id=None) -> list[dict]
  1. 抽取 event_ids_summary（兼容 dict / [dict] / 缺失）
  2. Rule.list(rule_type="event_log_summary", enabled=True)  # DB 优先
     └─ DB 无记录时回退 loader 内置 JSON（保证未 seed 环境也可用）
  3. 逐条 MatcherRegistry.dispatch("event_log_summary", item, condition)
  4. 命中 → Alert.create_or_aggregate(host_id, rule_name, ...)  # 5 分钟窗口天然去重
  5. 全程 try/except 包裹，任何异常仅告警日志，不阻塞导入主流程
```

**幂等性：** 复用 `Alert.create_or_aggregate` 的 `(host_id, rule_name, 5min)` 聚合窗口。
同一主机重复上报同一采集批次不会产生重复告警，只递增 `count`。

#### 4.2.5 接入点

`import_service.py` 在 `agent_imports` 写入之后、事件归一化之前插入调用，**非阻塞**（`try/except`）。
选择此处的理由：该函数是所有 Agent 数据落库的唯一收敛点，无需新增 API、无需改 Agent 端、无需处理鉴权。

### 4.3 P0-3 · 死 `exists` 规则下线

`suspicious_service_reg_exists` / `suspicious_scheduled_task_xml_exists` 置 `enabled:false`，
并在 `description` 追加失效原因与复活条件，`_meta` 增加 `disabled_reason` / `depends_on` 结构化字段。

> 不删除规则：保留条目可让 P3-2 的采集器补齐后直接 `enabled:true` 复活，且保留 ATT&CK 映射的可追溯性。

---

## 5. 架构影响与风险

| 风险 | 影响面 | 缓解 |
|------|--------|------|
| 新增 `event_log_summary` 破坏 `RULE_TYPE_ENUM` 长度断言 | 存量测试 | 全量回归；若有硬编码长度断言则同步更新 |
| `_match_list` 多类型合并引入性能回退 | 热路径 | 类型数 ≤ 3，集合合并 O(n)，且 `iocs_by_type` 每次 evaluate 只加载一次 |
| 导入流程新增同步调用拖慢导入 | 导入耗时 | 规则数 6 条、纯内存比较，量级 μs；且全链路 try/except 非阻塞 |
| `values:[]` 规则被误判为"配置错误" | 校验层 | `validate_condition` 已显式允许 `list` 的空 `values`（仅 `None` 非法），无需改动 |

## 6. 验收标准（供 04-verify 逐条核对）

- **AC-1** 全规则库 grep `example.com|attacker.net|185.174.137.11` 命中数 = 0
- **AC-2** `iocs` 表为空时 `suspicious_c2_domain` 对任意 `remote_address` 均不命中
- **AC-3** 导入一条 `domain` 类 IOC 后，同一输入立即命中（无需重启）
- **AC-4** 攻击链 step2 在导入 IOC 后可命中，整链可达成
- **AC-5** `RULE_TYPE_ENUM` 含 `event_log_summary` 且 `MatcherRegistry` 已注册
- **AC-6** 给定 `{"4625": 37}` 触发 `evt_4625_failed_logon_burst`，`{"4625": 3}` 不触发
- **AC-7** 端到端：调用 `evaluate_and_alert` 后 `alerts` 表新增对应记录，重复调用不新增行
- **AC-8** 2 条死规则 `enabled == false` 且含 `disabled_reason`
- **AC-9** 4 个规则 JSON 全部通过 `loader.load_default_rules()` 校验，无 warning 丢弃
- **AC-10** 后端存量测试套件全绿
