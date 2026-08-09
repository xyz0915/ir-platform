# 启用状态单一真值（Enable-SSOT）改造 — 验证文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 验证阶段（Validation） |
| **负责人** | 规则治理组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联测试** | `docs/rule-audit/enable-ssot/03-testing.md` (v1.0.0) |
| **验收基线** | `docs/rule-audit/enable-ssot/01-design.md` AC-1~AC-7 |

---

## 1. 验证方法

以设计文档定义的 **AC-1~AC-7 验收标准**为基线，逐项比对开发文档的实现记录与测试文档的执行结果，确认：

1. 每条 AC 均有对应的代码变更（开发文档映射）；
2. 每条 AC 均有对应的测试覆盖或编译/评审证据（测试文档结果）；
3. 既有能力未被破坏（回归套件全绿）。

---

## 2. 验收标准比对表

| 编号 | 验收标准 | 开发映射 | 测试/验证证据 | 结论 |
| --- | --- | --- | --- | --- |
| **AC-1** | 检测生效存在**单一可计算真值** `effective_active` | `rule.py:effective_active_of` / `annotate_effective`；公式 `enabled AND (no_active_policy OR in_active_policy)` | TC-01（4 分支全绿）、TC-02（批量注解全绿） | ✅ **达成** |
| **AC-2** | 激活策略是**受控部署事务**，将选中集写入 `rules.enabled` | `policy.py:activate` 重写为部署事务；选中→1、未选→0、`deprecated` 不改写 | TC-03（选中/未选部署正确）、TC-04（`deprecated` 不被启用）、TC-05（写 `policy_deploy` 审计且含 `effective_active`） | ✅ **达成** |
| **AC-3** | **取消静默回退**：无激活策略时自动激活基线，而非全量运行 | `policy.py:ensure_active_policy`；`analysis_service.py` 删除静默全量分支，改调 `ensure`；极端无策略返回空集并告警 | TC-06（自动激活基线 + 再次调用保留 override） | ✅ **达成** |
| **AC-4** | **双页可见真实生效态**：`/rules` 与 `/policies` 均展示 `effective_active` 徽标 + 原因 | `api/rules.py` 三个接口附加字段；`RulesView.vue` 芯片/筛选/行内徽标/详情；`PolicyConfigView.vue` 行内 `effState` 徽标 | `vite build --logLevel warn` 编译通过（§4）；代码评审确认双页均渲染 | ✅ **达成** |
| **AC-5** | **行为引擎纳入同策略门控** | `service_risk_analyzer._load_behavior_rules` 随激活策略选中集纳入/排除 | TC-07（无策略回退全量；激活不选→排除；激活选中→纳入，全绿） | ✅ **达成** |
| **AC-6** | **审计可追溯**：改变 `effective_active` 的操作写 `rule_audit_log` 含前后 `effective_active` | 部署事务对每条改写规则写审计；手工开关经既有 `Rule.update` 审计 | TC-05（`policy_deploy` 记录含 `effective_active` 前后值） | ✅ **达成** |
| **AC-7** | **一键对齐**：已启用但未选入激活策略的高危规则可批量补选 | `PolicyConfigView.vue:alignEnabledHighRisk` + `hasEnabledHighRiskGap` | TC-08（critical/high 补选、low 不补选，语义全绿） | ✅ **达成** |

---

## 3. 回归与质量门禁

| 检查项 | 结果 |
| --- | --- |
| 新增测试 `test_enable_ssot.py` | 8 passed（28.99s） |
| 回归 `test_rules_import.py` | 15 passed |
| 回归 `test_p2_rule_governance.py` | 23 passed，25 subtests passed |
| 前端编译 `vite build` | 通过，无错误/告警 |
| 表结构变更 | 无（`rules` / `policy_rules` / `detection_policies` 列不变） |
| 已知环境限制（torch 导入 segfault，非本次引入） | 📌 记录备案，不影响交付 |

**质量门禁判定**：全部 AC 达成 + 新增与回归测试全绿 + 前端编译通过 + 无表结构变更 → **质量门禁通过**。

---

## 4. 结论

启用状态单一真值（Enable-SSOT）改造已按"设计 → 开发 → 测试 → 验证"四阶段闭环完成：

- **根因消除**：原 `/rules` 与 `/policies` 双开关"与"关系、无单一真值、静默全量回退、行为引擎绕过策略等问题，已通过"策略激活=受控部署事务写 `rules.enabled` + 展示层 `effective_active` 单一真值"模型根治；
- **可观测性**：双页均可见"真实是否告警"及原因，消除静默检测空洞；
- **可追溯**：部署与手工改写均写审计含 `effective_active` 前后值；
- **安全性**：`deprecated` 规则不被部署改写；`ensure_active_policy` 命中已有激活策略不重新部署，保留人工启停结果；
- **可回归**：既有规则导入与治理套件全部通过，无破坏。

**最终结论：验收通过（PASS）。** 建议后续将 `test_enable_ssot.py` 纳入 CI 主测试流，并将已知 torch 导入 segfault 作为独立环境问题跟踪排查。

---

## 5. 阶段衔接与交付物清单

| 阶段 | 文档 | 状态 |
| --- | --- | --- |
| 设计 | `docs/rule-audit/enable-ssot/01-design.md` (v1.0.0) | ✅ 已交付 |
| 开发 | `docs/rule-audit/enable-ssot/02-development.md` (v1.0.0) | ✅ 已交付 |
| 测试 | `docs/rule-audit/enable-ssot/03-testing.md` (v1.0.0) | ✅ 已交付 |
| 验证 | `docs/rule-audit/enable-ssot/04-validation.md` (v1.0.0) | ✅ 已交付 |

代码改动（`policy.py` / `rule.py` / `analysis_service.py` / `service_risk_analyzer.py` / `api/rules.py` / `RulesView.vue` / `PolicyConfigView.vue` + 新增 `test_enable_ssot.py`）均已在开发、测试阶段落盘并验证通过。
