# 启用状态单一真值（Enable-SSOT）改造 — 设计文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 设计阶段（Design） |
| **负责人** | 规则治理组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联方案** | 审计结论：规则管理（/rules）与策略配置（/policies）的"启用"实为两个独立开关的"与"，当前无单一真值 |

---

## 1. 背景与问题陈述

### 1.1 现状（代码实证）
- `/rules` 的"启用"开关写 `rules.enabled` 列（`app/models/rule.py`）。
- `/policies` 的"已选"开关写 `policy_rules` 关联表（`app/models/policy.py`），仅当该策略 `is_active=1` 时生效。
- 真实检测口径在 `app/services/analysis_service.py:163-176`：
  - 存在激活策略 → `RuleEngine.load_rules_by_ids(active_policy["rule_ids"])`，而 `Rule.list_by_ids`（`rule.py:240`）内部带 `AND enabled=1`；
  - **无激活策略 → 静默回退**到 `RuleEngine.load_rules()`（全部 `enabled=1` 规则）。
- 行为引擎规则在 `service_risk_analyzer.py:52` 用 `Rule.list(engine_type="behavior_engine", enabled=True)`，**完全绕过策略**。

### 1.2 冲突根因
两个开关任一关闭规则都不告警，但"被选中 ≠ 一定生效"（还需 `enabled=1`），"`/rules` 启用 ≠ 一定生效"（还需被激活策略选中）。两个页面各自只展示自己那半边状态，**谁都看不到"真实是否告警"**，形成双控歧义与静默检测空洞。

---

## 2. 设计目标与验收标准（AC）

| 编号 | 验收标准 | 说明 |
| --- | --- | --- |
| AC-1 | 检测生效存在**单一可计算真值** `effective_active` | `effective_active = enabled AND (no_active_policy OR in_active_policy)` |
| AC-2 | 激活策略是**受控部署事务**，将选中集写入 `rules.enabled` | 选中→`enabled=1`；未选→`enabled=0`；`deprecated` 规则不被改写 |
| AC-3 | **取消静默回退**：无激活策略时自动激活基线策略，而非全量运行 | `ensure_active_policy()` 保证恰好一个激活策略 |
| AC-4 | **双页可见真实生效态**：`/rules` 与 `/policies` 均展示 `effective_active` 徽标 | 含原因：未选入激活策略 / 已禁用 / 无激活策略 |
| AC-5 | **行为引擎纳入同策略门控** | `service_risk_analyzer` 与主流一致 |
| AC-6 | **审计可追溯**：任何改变 `effective_active` 的操作写 `rule_audit_log`，含变更前后 `effective_active` | 设计→开发→测试→验证全链路可追 |
| AC-7 | **一键对齐**：可将"已启用但未选入激活策略"的高危规则批量补选 | 消除静默空洞 |

---

## 3. 架构设计

### 3.1 单一真值模型（SSOT）
```
rules.enabled  ── 唯一检测口径（引擎只读此列）
   ▲
   │ policy.activate() 作为"部署事务"把策略选中集写入此处
policy_rules   ── 策略蓝图（intended config，不实时参与判定）
detection_policies.is_active ── 标记哪个蓝图当前已部署
effective_active（计算字段，仅用于展示/告警）=
   enabled AND ( 无激活策略 ? True : rule_id ∈ 激活策略.rule_ids )
```

### 3.2 部署语义（关键决策）
- `DetectionPolicy.set_rules(pid, ids)`：**仅更新蓝图** `policy_rules`，不改 `enabled`。
- `DetectionPolicy.activate(pid)`：**部署事务**——
  1. 反激活其他策略（`is_active=0`），本策略 `is_active=1`；
  2. 对当前库内规则做全量对账：
     - 选中且 `status != 'deprecated'` → `enabled = 1`；
     - 当前 `enabled=1` 且**未选中**且 `status != 'deprecated'` → `enabled = 0`；
     - `status = 'deprecated'`（及显式死规则）→ **不改动**（安全护栏）；
  3. 对每条被改写的规则写 `rule_audit_log`，含变更前后 `effective_active`。
- 切换/激活策略即"重新部署"，以最后一次激活的蓝图为准；`/rules` 的手工开关视为对"已部署态"的即时覆盖（仍写审计）。

### 3.3 去静默回退
- `analysis_service` 增加 `DetectionPolicy.ensure_active_policy()`：若无激活策略，自动激活基线（名称含"默认"且非"副本"的策略；若不存在则取 id 最小者），并 `logger.warning` 记录。
- 删除 `analysis_service.py:172` 的"全量 enabled"静默分支；若 `ensure` 后仍无激活策略（极端异常），返回空规则集并告警，**绝不全量运行**。

### 3.4 行为引擎同门控
- `service_risk_analyzer._load_behavior_rules()`：若激活策略存在，加载 `engine_type='behavior_engine' AND id IN active_rule_ids AND enabled=1`；否则加载全部 `enabled` 行为规则（保持无策略时的向后兼容）。

### 3.5 计算字段 `effective_active`
- 新增 `Rule.annotate_effective(rules, active_ids: set, policy_active: bool)`：为每条规则补充：
  - `in_active_policy: bool`
  - `effective_active: bool`
  - `effective_reason: str`（"生效中" / "未选入激活策略" / "已禁用" / "无激活策略"）
- 在 `GET /api/rules`、`GET /api/rules/selector`、`DetectionPolicy.get_by_id` 返回的规则中统一附加。
- `GET /api/rules/stats` 增加 `effective_active` 计数，便于运营看板。

---

## 4. 接口定义

### 4.1 后端模型（`app/models/policy.py`）
```python
@staticmethod
def get_active_rule_ids() -> set[int]:
    """返回当前激活策略选中规则 id 集合；无激活策略返回空集合。"""

@staticmethod
def ensure_active_policy() -> Optional[dict]:
    """保证恰好一个激活策略：无则激活基线（默认策略 / id 最小），返回激活策略 dict。"""

@staticmethod
def activate(policy_id: int) -> bool:
    """【部署事务】反激活其他策略 + 本策略 is_active=1 + 对账写入 rules.enabled
       + 对每条被改写的规则写 rule_audit_log（含前后 effective_active）。"""
```

### 4.2 后端模型（`app/models/rule.py`）
```python
@staticmethod
def annotate_effective(rules: list, active_ids: set, policy_active: bool) -> list:
    """为规则列表附加 in_active_policy / effective_active / effective_reason。"""

@staticmethod
def effective_active_of(rule: dict, active_ids: set, policy_active: bool) -> tuple[bool, str]:
    """计算单条规则的 (effective_active, reason)。"""
```

### 4.3 后端 API（`app/api/rules.py`）
- `GET /api/rules` 与 `GET /api/rules/selector`：返回项附加 `effective_active` / `in_active_policy` / `effective_reason`。
- `GET /api/rules/stats`：data 增加 `effective_active` 计数。
- `PUT /api/rules/bulk-enable`：仍为即时覆盖，但每次改写写审计含 `effective_active`。
- `PUT /api/rules/{id}`：更新后若 `enabled` 变化，审计含 `effective_active`。

### 4.4 前端
- `RulesView.vue`：规则行增加 `effective_active` 徽标 + 按 `effective_active/原因` 筛选 Chip。
- `PolicyConfigView.vue`：
  - 选择器每行显示 `effective_active` 徽标（= 本策略为激活策略 ? `enabled && 已选` : `false`）；
  - `dirty`（改动未部署）显式提示"选择已变更，需点击激活以生效"；
  - 新增"一键对齐高危"：把"已启用但未选入本策略"的高危（critical/high）规则批量补选。

---

## 5. 数据模型与状态机

### 5.1 `rules` 表（不变，复用现有列）
`enabled INTEGER`、`status TEXT(active|pending_approval|deprecated)`、`engine_type`、`rule_type`。

### 5.2 状态机（单条规则）
```
            set_rules(选中)            activate(部署)
  [未选/禁用] ───────────────► [已选,蓝图] ──────────► [enabled=1, 生效中]
        ▲                          │  activate          │
        │   activate(未选→禁用)     │ (本策略非激活)      │ /rules 手工禁用
        └──────────────────────────┘                   ▼
                                              [enabled=0, 不生效]
  deprecated 规则：任何部署/激活均不改动 enabled（安全护栏）
```

---

## 6. 风险与回滚

| 风险 | 缓解 |
| --- | --- |
| 激活策略误将大量规则禁用，造成检测空洞 | 部署前在事务内计算 diff；仅改写非 deprecated 规则；审计可追溯；提供"一键回滚到默认策略" |
| `/rules` 手工开关与策略蓝图漂移 | 激活即重新部署以蓝图为准；手工开关写审计并标注"手动覆盖" |
| 无激活策略时极端异常 | `ensure_active_policy` 兜底 + 空规则集告警，绝不静默全量 |
| 行为引擎规则被策略误关 | 同主流门控逻辑，且 `deprecated` 不被改写 |

**回滚方案**：本改造不删列、不改表结构，仅调整写入与读取逻辑；如须回退，还原 `policy.py`/`analysis_service.py`/`service_risk_analyzer.py` 与前端两文件即可，数据层面 `rules.enabled` 仍为有效口径。

---

## 7. 阶段衔接说明
- 本文档为**设计阶段**交付物，定义 AC-1~AC-7 与接口契约。
- **开发阶段**须逐条映射 AC 到代码变更，输出 `02-development.md`（代码结构 + 实现记录）。
- **测试阶段**须覆盖 AC-1~AC-7，输出 `03-testing.md`（用例/结果/缺陷）。
- **验证阶段**须比对 AC 达成情况，输出 `04-validation.md`（验收比对 + 结论）。
