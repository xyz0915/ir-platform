# P0 阶段 · 开发文档（实现细节与代码说明）

- 文档编号：RA-P0-02
- 上游：`01-design.md`
- 状态：开发完成，待测试

---

## 1. 变更总览

| # | 文件 | 类型 | 说明 |
|---|------|------|------|
| 1 | `backend/app/rules/rule_engine.py` | 修改 | `FIELD_TO_IOC_TYPE` 支持多类型；新增 `resolve_ioc_types()`；`_match_list` 多类型合并；新增 `_extract_event_summary()` / `_match_event_log_summary()`；`_CONFIDENCE_DEFAULT` 与 `MatcherRegistry` 注册扩展 |
| 2 | `backend/app/schemas/analysis.py` | 修改 | `RULE_TYPE_ENUM` +`event_log_summary`；新增 `EVENT_LOG_OPERATORS` / `EVENT_LOG_AGGREGATES`；`validate_condition` 新增分支 |
| 3 | `backend/app/rules/default_rules.json` | 修改 | `suspicious_c2_domain` 去占位化；2 条死 `exists` 规则下线 |
| 4 | `backend/app/rules/default_attack_chain.json` | 修改 | 攻击链 step2 去占位化 |
| 5 | `backend/app/rules/event_log_rules.json` | **新增** | 6 条 Windows 安全事件规则 |
| 6 | `backend/app/services/security_event_rules.py` | **新增** | 事件日志 → 规则 → 告警 桥接服务 |
| 7 | `backend/app/rules/ioc_dependency.py` | **新增** | 情报依赖巡检模块 |
| 8 | `backend/app/services/import_service.py` | 修改 | 导入主链路挂载 P0-2 桥接（非阻塞） |
| 9 | `backend/app/api/rules.py` | 修改 | 新增 `GET /api/rules/ioc-dependency` |

净增规则数：**141 → 147**（+6 条 `event_log_summary`）。

---

## 2. P0-1 实现细节

### 2.1 `FIELD_TO_IOC_TYPE` 支持多类型

```python
FIELD_TO_IOC_TYPE: dict = {
    # IP / 域名混合类（出站连接目标既可能是 IP 也可能是域名）
    "remote_address": ["ip", "domain"],   # ← 原为 "ip"
    "remote_ip": "ip",
    ...
}
```

**为什么必须改这里：** 若只把 `suspicious_c2_domain` 的假值删掉而不改映射，
该规则字段是 `remote_address`（旧映射 → 仅 `ip`），用户导入 **domain 类情报后规则依然取不到**，
等于把"假覆盖"换成了"零覆盖"。这是本次修复最容易被忽略的隐藏依赖。

### 2.2 `resolve_ioc_types()` — 统一解析入口

```python
def resolve_ioc_types(field: str, condition: Optional[dict] = None) -> list:
    # 优先级：condition["ioc_types"] > FIELD_TO_IOC_TYPE[field] > []
```

- 显式声明 `ioc_types` 时**完全覆盖**字段推导，规则作者拥有最终控制权；
- 兼容 `str` 与 `list` 两种映射写法，存量条目零改动；
- 去重且保序，返回值可直接迭代。

### 2.3 `_match_list` 多类型合并

```python
merged_values: list = list(base_values)
if global_context:
    iocs_by_type = global_context.get("iocs_by_type") or {}
    if iocs_by_type:
        for ioc_type in resolve_ioc_types(field, condition):
            dyn = iocs_by_type.get(ioc_type)
            if dyn:
                merged_values.extend(dyn)
```

原逻辑只取单一类型且用 `merged_values = merged_values + list(dyn)` 生成新列表；
改为 `extend` 原地追加，避免多类型时的重复列表拷贝。

**零命中保证：** 函数下方原有短路 `if not value or not merged_values: return False`。
当 `values=[]` 且情报库为空时，`merged_values` 为空 → 直接返回 `False`，**不会产生任何误报**。

**即时生效保证：** `_load_iocs_by_type()` 在**每次 `evaluate()` 入口实时查库**（无内存缓存），
因此情报导入后下一次分析立即生效，无需重启服务。

### 2.4 规则 JSON 改动

`suspicious_c2_domain`：

```jsonc
"condition": {
  "field": "remote_address",
  "values": [],                       // 原 3 条占位域名 → 清空
  "ioc_types": ["domain", "ip"],      // 显式声明依赖类型
  "match_mode": "contains",
  "_meta": { "mitre_attack": "T1571", "requires_ioc": true, "ioc_note": "..." }
}
```

攻击链 step2 同样处理，并把 `match_mode` 由 `exact` 改为 `contains`——
`remote_address` 实际值常带端口（`1.2.3.4:443`），`exact` 会漏匹配。

### 2.5 情报依赖巡检 `ioc_dependency.py`

`scan_ioc_dependent_rules()` 递归提取三处 list 条件：
`list` 规则本体、`attack_chain.ordered_steps[*].match`、`composite.sub_rules[*]`，
对每处解析 `ioc_types`，对照 `iocs` 表存量给出 `satisfied` 判定。

判定口径：`satisfied = 有静态 values 兜底 OR 情报库中该类型至少有 1 条可用指标`。

对外暴露 `GET /api/rules/ioc-dependency`，返回情报存量、依赖规则清单与未满足清单。

---

## 3. P0-2 实现细节

### 3.1 类型注册链路（4 处，缺一不可）

| 环节 | 位置 | 内容 |
|------|------|------|
| 枚举 | `schemas/analysis.py::RULE_TYPE_ENUM` | 加入 `event_log_summary`，否则 `loader` 会以"rule_type 非法"静默丢弃整个规则文件 |
| 校验 | `schemas/analysis.py::validate_condition` | 新增分支，校验 `event_id`/`event_ids`/`operator`/`count`/`aggregate` |
| 匹配 | `rule_engine.py::_match_event_log_summary` | 计数比较实现 |
| 分发 | `rule_engine.py` 末尾 `MatcherRegistry.register` | 注册为第 8 类 matcher |
| 置信度 | `rule_engine.py::_CONFIDENCE_DEFAULT` | `0.8`（高于 behavior 0.7，低于 list 1.0） |

### 3.2 `_extract_event_summary()` — 输入形态归一

真实链路上同一份数据会以三种形态出现，全部兼容：

| 形态 | 来源 | 处理 |
|------|------|------|
| `{"event_ids_summary": {...}, "antivirus": [...]}` | 采集器原始对象 | 取 `event_ids_summary` |
| `{"4625": 3}` | 已剥离外层的裸计数 | 全部值为数字才认定，避免误吞普通业务字典 |
| 其它 / 缺失 | — | 返回 `{}` → 不命中 |

键统一 `str(k).strip()`，值统一 `int(v)`，因此 `{4625: 37}`（int 键）与 `{"4625": 37}` 等价。
无法转 int 的值直接跳过而非抛异常。

### 3.3 `_match_event_log_summary()` 语义

```python
counts = [summary.get(eid, 0) for eid in target_ids]
aggregate = condition.get("aggregate", "sum")
if aggregate == "any":  return any(_cmp(c) for c in counts)
if aggregate == "max":  return _cmp(max(counts) if counts else 0)
return _cmp(sum(counts))          # 默认 sum
```

- 缺失的事件 ID 计为 `0`（而非跳过），保证 `<`/`<=` 语义正确；
- `operator` 不在白名单 → 记 warning 并返回 `False`（防御式，不抛异常打断整批评估）。

### 3.4 桥接服务 `security_event_rules.py`

三个可独立测试的层次：

| 函数 | 职责 | 是否触库 |
|------|------|----------|
| `extract_event_summary(payload)` | 载荷归一（含 `list` 包裹、JSON 字符串），多元素按 ID 累加 | 否（纯函数） |
| `evaluate_summary(summary, rules=None)` | 规则匹配，返回命中项 + `observed_counts` | 仅读规则 |
| `evaluate_and_alert(host_id, payload, case_id)` | 端到端写告警 | 是 |

**规则来源策略：** `load_event_log_rules()` 先查 DB（用户可能在 UI 调过阈值），
DB 中一条都没有时回退内置 JSON，保证未 seed 环境开箱即用。

**幂等：** 直接复用 `Alert.create_or_aggregate` 的 `(host_id, rule_name, status='open', 5 分钟)`
聚合窗口——命中已有告警则 `count+1` 并返回 `is_new=False`，不新增行。

**告警内容：** `title` 形如 `登录失败爆发（疑似爆破）（4625×37）`；
`detail` 为结构化 dict，含 `observed_counts` / `threshold` / `operator` / `mitre_attack`。

### 3.5 接入点选择

挂在 `import_service.import_from_content()` 中 `agent_imports` 写入之后：

```python
try:
    from app.services.security_event_rules import evaluate_and_alert
    security_payload = data.get("security")
    if security_payload:
        host_case_id = host_info.get("case_id") if host_info else None
        alerts_made = evaluate_and_alert(host_id, security_payload, case_id=host_case_id)
        ...
except Exception as exc:
    logger.warning("security event log rule eval failed (non-blocking): %s", exc)
```

理由：该函数是**所有 Agent 数据落库的唯一收敛点**，因此
① 无需新增 API 端点；② 无需改动 Agent 端；③ 无需额外处理鉴权；④ 文件导入与 Agent 上报两条路径同时覆盖。

---

## 4. P0-3 实现细节

两条规则改为 `enabled: false`，并在 `condition._meta` 增加结构化下线信息：

```jsonc
"_meta": {
  "mitre_attack": "T1543/003",
  "disabled_reason": "no_producer_field",
  "disabled_detail": "backend/agent 采集链路中不存在产出 service_image_path 字段的采集器，exists 规则恒为 False",
  "depends_on": "P3-2：服务注册项采集器补齐 service_image_path 后可复活",
  "disabled_at": "P0-3"
}
```

`label` 追加"（已下线·待采集器补齐）"后缀，UI 列表可直接看出状态。
**保留条目不删除**：便于 P3-2 采集器补齐后一键复活，且保留 ATT&CK 映射的可追溯性。

---

## 5. 向后兼容性说明

| 关注点 | 结论 | 依据 |
|--------|------|------|
| 存量 `list` 规则语义 | 不变 | `resolve_ioc_types` 对 `str` 映射行为与旧代码完全一致 |
| 存量 `values` 非空规则 | 不变 | 静态值仍在 `merged_values` 中优先保留 |
| `validate_condition("list", ...)` | 不变 | 原本就允许空 `values`（仅 `None` 非法），无需改动 |
| 未 seed 的 DB | 正常 | 桥接服务回退内置 JSON |
| 缺 `iocs` 表的环境 | 正常 | `_load_iocs_by_type()` 异常吞掉返回 `{}` |
| 导入性能 | 影响可忽略 | 6 条规则纯内存整数比较，且全链路 try/except 非阻塞 |

## 6. 冒烟结果（开发自测）

```
registered: ['attack_chain','behavior','composite','event_log_summary','exists','list','regex','threshold']
remote_address           -> ['ip','domain']
explicit override        -> ['domain']
empty ioc store hit      = False     ← 情报库为空零命中
after import (hit)       = True      ← 导入后即时命中
ip via same field        = True      ← 同字段 IP 类同样生效
4625=37 / 4625=3         -> True / False
int key / bare dict      -> True / True
sum 8+15=23 (>=20)       -> True
any 8|15 (>=20)          -> False
loader TOTAL             = 147  (regex 62 / behavior 40 / composite 13 / list 11 /
                                 attack_chain 10 / event_log_summary 6 / threshold 3 / exists 2)
占位 IOC grep            = 0 命中
```
