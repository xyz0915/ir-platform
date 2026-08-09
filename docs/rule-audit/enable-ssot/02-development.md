# 启用状态单一真值（Enable-SSOT）改造 — 开发文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 开发阶段（Development） |
| **负责人** | 规则治理组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联设计** | `docs/rule-audit/enable-ssot/01-design.md` (v1.0.0) |

---

## 1. 代码结构说明

```
backend/app/
├── models/
│   ├── rule.py          # + effective_active_of() / annotate_effective()
│   └── policy.py        # activate() 改为部署事务；+ get_active_rule_ids() / ensure_active_policy()
├── services/
│   └── analysis_service.py   # 去掉静默回退，改用 ensure_active_policy()
├── analysis/
│   └── service_risk_analyzer.py  # 行为引擎纳入激活策略门控
└── api/
    └── rules.py         # list_rules / selector / stats 附加 effective_active 字段

frontend/src/
├── views/
│   ├── RulesView.vue          # 生效态筛选 + 行内生效徽标 + 详情生效态
│   └── PolicyConfigView.vue   # 行内生效徽标 + 一键对齐已启用高危 + 部署提示修正
└── api/policies.js            # 不变（复用现有接口）
```

---

## 2. 实现记录（按 AC 映射）

### AC-1 单一可计算真值 `effective_active`
- `rule.py:effective_active_of(rule, active_ids, policy_active)` → `(bool, reason)`。
  - `reason ∈ {生效中, 未选入激活策略, 已禁用, 无激活策略}`。
- `rule.py:annotate_effective(rules, active_ids, policy_active)` → 批量附加
  `in_active_policy / effective_active / effective_reason`。
- 引擎口径仍是 `rules.enabled`（`load_rules`/`load_rules_by_ids` 的 `AND enabled=1`），
  `effective_active` 为**展示/审计用单一真值**，与引擎读取保持一致。

### AC-2 激活策略 = 受控部署事务
- `policy.py:activate(pid)` 重写为部署事务：
  1. 记录原激活策略 `prev_ids`，本策略选中集 `selected`；
  2. 反激活其他 + 本策略 `is_active=1`；
  3. 全量对账 `rules.enabled`：选中且非 `deprecated` → `1`；当前 `enabled=1` 且未选中且非 `deprecated` → `0`；
  4. 对每条被改写的规则调 `Rule._write_audit(action="policy_deploy", ...)`，
     含 `old_val={"effective_active": before}`、`new_val={"effective_active": after, "enabled": ..., "policy_id": ...}`。
- `set_rules()` 仍只更新蓝图 `policy_rules`（不改变 `enabled`），符合"激活才部署"。

### AC-3 取消静默回退
- `policy.py:ensure_active_policy()`：已存在激活策略直接返回（**不做部署，保留手工 override**）；
  不存在则自动激活基线（默认策略 / id 最小）并 `logger.warning`。
- `analysis_service.py:163-176`：原 `else` 静默全量分支删除，改为
  `active_policy = DetectionPolicy.ensure_active_policy()`；若仍无激活策略，返回空规则集并 `logger.error`（绝不静默全量）。

### AC-4 双页可见真实生效态
- `api/rules.py:list_rules` 与 `list_rules_for_selector`：返回项统一 `annotate_effective`。
- `api/rules.py:get_rule_stats`：`data` 新增 `effective_active` 计数。
- `policy.py:get_by_id`：策略详情的 `rules` 也 `annotate_effective`（以"本策略是否激活"为上下文）。
- `RulesView.vue`：新增"真实生效中/未生效"快捷芯片、生效态下拉筛选、表格行内徽标、详情弹窗生效态。
- `PolicyConfigView.vue`：规则行内显示 `effState(r)` 徽标（生效中 / 已禁用 / 策略未激活 / 未选入本策略）。

### AC-5 行为引擎同策略门控
- `service_risk_analyzer.py:_load_behavior_rules`：存在激活策略时用
  `Rule.list_by_ids(active_ids)` 并过滤 `engine_type='behavior_engine'`；否则回退全部 `enabled` 行为规则。

### AC-6 审计可追溯
- 部署事务对每条被改写规则写 `rule_audit_log`，含变更前后 `effective_active`。
- `/rules` 启用手动开关（`bulk-enable` / `PUT /{id}`）经 `Rule.update` 已写审计（含 `enabled` 变更）。

### AC-7 一键对齐
- `PolicyConfigView.vue:alignEnabledHighRisk()` + 计算属性 `hasEnabledHighRiskGap`：
  把"已启用但未被本策略选中"的 critical/high 规则批量补选（消除静默空洞），保存并激活后生效。

---

## 3. 关键决策与偏离说明
- **保留 `load_rules_by_ids` 的 `AND enabled=1`**：部署事务已把选中集写入 `enabled`，
  该过滤作为"实时只跑启用规则"的安全网，保证 `/rules` 手工禁用可即时覆盖（手动 override 仍生效），
  不造成"选中却不生效"的幽灵态。与设计文档 3.2 一致。
- **`deprecated` 规则不被部署改写**：安全护栏，避免误启用已废弃规则。
- **`ensure_active_policy` 命中已有激活策略时不重新部署**：避免每次分析覆盖人工启停结果。

---

## 4. 未变更项（回归安全）
- `rules` 表结构不变（无新增列）；`policy_rules` / `detection_policies` 结构不变。
- 引擎读取口径不变（仍只读 `rules.enabled`），仅增加展示层 `effective_active` 与部署写入逻辑。
- 默认策略（main.py 启动初始化）仍创建并激活，保证生产环境必有激活策略。
