# 案件详情数据扩充（P0+P1）— 验证文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 验证阶段（Validation） |
| **负责人** | 应急研判组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联测试** | `docs/case-audit/enriched/03-testing.md` (v1.0.0) |
| **验收基线** | `docs/case-audit/enriched/01-design.md` AC-1~AC-11 |

---

## 1. 验证方法

以设计文档定义的 **AC-1~AC-11 验收标准**为基线，逐项比对开发文档的实现记录与测试文档的执行结果，确认：

1. 每条 AC 均有对应的代码变更（开发文档映射）；
2. 每条 AC 均有对应的测试覆盖或编译/评审证据（测试文档结果）；
3. 既有能力未被破坏（回归套件全绿）。

---

## 2. 验收标准比对表

| 编号 | 验收标准 | 优先级 | 开发映射 | 测试/验证证据 | 结论 |
| --- | --- | --- | --- | --- | --- |
| **AC-1** | 聚合接口 `GET /api/cases/{id}/summary` 单连接内返回全部卡片数据 | P0 | `cases.py:90-105`；`case_summary.get_case_summary` 单连接 9 段聚合 | 路由冒烟通过；回归套件全绿（55 passed） | ✅ **达成** |
| **AC-2** | 派生严重度取关联告警最高严重度（忽略 dismissed） | P0 | `_derived_severity`：`status != 'dismissed'` + `SEVERITY_RANK` 取最大 | TC-01（critical+high+medium(dismissed)→high；无主机→none，全绿） | ✅ **达成** |
| **AC-3** | 告警态势：总数/严重度分布/状态分布 + Top8 | P0 | `_alert_section` | TC-02（total/by_severity/by_status + 排序 Top8，全绿） | ✅ **达成** |
| **AC-4** | 受影响资产态势：总数/状态/在线 Agent/风险 Top5 | P0 | `_host_section` | TC-03（online_agents=1；风险 Top5 以 IOC 命中数排序，全绿） | ✅ **达成** |
| **AC-5** | 响应时间线：案件级里程碑按时序 | P0 | `_timeline` 自建里程碑 | TC-09（含创建/首批主机接入/其余里程碑，按时序，全绿） | ✅ **达成** |
| **AC-6** | 处置闭环进度：done/total/percent + 明细 | P1 | `_remediation_section` 解析 items JSON | TC-04（2 项 1 完成 → 50%，全绿） | ✅ **达成** |
| **AC-7** | 动态取证进度：pending/running/done/failed/total | P1 | `_triage_section` 状态计数 | TC-05（三态计数正确，全绿） | ✅ **达成** |
| **AC-8** | 威胁指标 IOC：关联威胁情报并回灌 | P1 | `_ioc_section` ioc_hits→iocs→threat_intel | TC-06（`intel` 回灌 provider/risk_score，全绿） | ✅ **达成** |
| **AC-9** | 攻击链/TTP：kill_chain + techniques 聚合 | P1 | `_ttp_section` | TC-07（attack_stage + attck 聚合，全绿） | ✅ **达成** |
| **AC-10** | AI 分析结论（P2 顺带）：解析 ai_analysis 取最高分 | P2 | `_ai_section` | TC-08（JSON 解析 + 最高 risk_score，全绿） | ✅ **达成** |
| **AC-11** | 前端多卡片重做：9 卡片 + 保留主机列表/批量AI | P0+P1 | `cases.js:summary` + `CaseDetailView.vue` 重写 | `vite build --logLevel warn` 编译通过；代码评审确认卡片齐全 | ✅ **达成** |

---

## 3. 回归与质量门禁

| 检查项 | 结果 |
| --- | --- |
| 新增测试 `test_case_summary.py` | 9 passed（9.26s） |
| 回归 `test_enable_ssot.py` | 8 passed |
| 回归 `test_rules_import.py` | 15 passed |
| 回归 `test_p2_rule_governance.py` | 23 passed，25 subtests passed |
| 合并回归（4 文件同跑） | **55 passed，25 subtests passed（42.70s）** |
| 前端编译 `vite build` | 通过，无错误 |
| 表结构变更 | 无（全部为查询期派生） |
| 已知环境限制（torch 导入 segfault，非本次引入） | 📌 记录备案，不影响交付 |

**质量门禁判定**：全部 AC 达成 + 新增与回归测试全绿 + 前端编译通过 + 无表结构变更 → **质量门禁通过**。

---

## 4. 结论

案件详情数据扩充（P0+P1，P2 顺带）已按「设计 → 开发 → 测试 → 验证」四阶段闭环完成：

- **研判效率提升**：应急人员打开案件详情即可一眼获得派生严重度、告警分布、受影响资产风险排名、处置/取证进度、IOC/TTP 与响应时间线，无需多接口拼装；
- **派生严重度根因化**：由关联告警最高严重度推导且忽略 dismissed，真实反映当前风险水位；
- **IOC/TTP 闭环**：`ioc_hits` 经 `iocs` 关联 `threat_intel`，回灌情报并聚合 MITRE ATT&CK 技战术，支撑攻击链还原；
- **时间线自建**：案件级里程碑（创建→接入→告警→取证→处置→更新）按序呈现，还原事件演进；
- **零表结构变更**：全部为查询期派生，既有规则治理/取证/策略套件全部通过，无破坏；
- **可回归**：纳入 `test_case_summary.py` 共 9 例隔离测试，连同 3 个回归套件全绿。

**最终结论：验收通过（PASS）。** 建议将 `test_case_summary.py` 纳入 CI 主测试流，并将已知 torch 导入 segfault 作为独立环境问题跟踪排查。

---

## 5. 阶段衔接与交付物清单

| 阶段 | 文档 | 状态 |
| --- | --- | --- |
| 设计 | `docs/case-audit/enriched/01-design.md` (v1.0.0) | ✅ 已交付 |
| 开发 | `docs/case-audit/enriched/02-development.md` (v1.0.0) | ✅ 已交付 |
| 测试 | `docs/case-audit/enriched/03-testing.md` (v1.0.0) | ✅ 已交付 |
| 验证 | `docs/case-audit/enriched/04-validation.md` (v1.0.0) | ✅ 已交付 |

代码改动（`app/services/case_summary.py`【新增】、`app/api/cases.py`、`frontend/src/api/cases.js`、`frontend/src/views/CaseDetailView.vue`、`backend/tests/test_case_summary.py`【新增】、`.gitignore`）均已在开发、测试阶段落盘并验证通过。
