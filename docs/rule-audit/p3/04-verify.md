# P3 验证文档 — 检测点增强与 exists 扩展

> 阶段：P3（#106）｜ 环节：验证（04-verify）
> 配套文档：01-design.md（设计）· 02-dev.md（开发）· 03-test.md（测试）
> 验收口径：真实库 `data/ir_platform.db` + 真实代码实测

---

## 1. 验收结论

**P3 阶段四环节全部完成，验收通过，可交付。至此 P0–P3 四阶段全部完毕。**

核心交付：P3-1 新增 16 条 active 检测点（卷影删除/RMM/LOLBin/PowerShell 混淆/账户创建/日志清除/NTDS/持久化/云外发/反向 Shell/WebShell 等），覆盖既有采集器能力缺口；P3-2 新增 4 条 `exists` 持久化兜底（disabled + pending_collector 标注），待采集接线即激活。AC-P1-13 严重度占比保持 54.6% 不回归。

---

## 2. AC 逐条核对（P3 共 9 项）

| AC | 需求 | 实测证据 | 结果 |
|---|---|---|---|
| AC-P3-1 | `advanced_detections.json` 装载，总数 +20 | loader 总数 163，adv/pki 共 20 条 | ✅ |
| AC-P3-2 | 16 条 active 合法 `rule_type` | 16 条 active；类型 ∈ {regex,list,composite} | ✅ |
| AC-P3-3 | active 字段对应 canonical 模型 | active 字段 ⊆ {command_line,name,path,domain} | ✅ |
| **AC-P3-4** | 抽样规则真实命中 | 8 项 matcher dispatch 命中 + 负向不命中 | ✅ |
| **AC-P3-5** | 无新增死规则 | active 规则不引用未采集字段；JA3/ETW/K8s/MFA 等无采集器项**未实现** | ✅ |
| **AC-P3-6** | P3-2 4 条 exists 兜底 `enabled:false`+标注 | 4 条 pki_* `enabled:false` + `_meta.pending_collector`；matcher 惰性正确 | ✅ |
| AC-P3-7 | 装载无非法类型/异常 | loader 无非法 `rule_type` | ✅ |
| **AC-P3-8** | 整体 high 占比 ≤55% | 54.6%（89/163）≤55% | ✅ |
| AC-P3-9 | 四篇文档齐备 | 01/02/03/04 均在 `docs/rule-audit/p3/` | ✅ |

**P3 验收：9/9 全 PASS。**

---

## 3. 跨阶段闭环确认

| 阶段 | 规则总数 | high 占比 | 说明 |
|---|---|---|---|
| P0 末 | 141 | — | 初始 |
| P1 末 | 147 | 59.9% | AC-P1-13 FAIL（移交 P2） |
| P2 末 | 143 | 53.8% | AC-P1-13 闭合 |
| **P3 末** | **163** | **54.6%** | **AC-P1-13 仍闭合 ✅** |

P3 新增 20 条（+16 active +4 disabled），经降权校准（2 条 high→medium）后整体 high 占比仅微升 0.8pp，仍稳定 ≤55%。

---

## 4. 回归兼容性

| 范围 | 结果 |
|---|---|
| 规则相关 11 文件定向回归（`--noconftest`） | 182 passed / 53 subtests passed（修复 1 例后） |
| P3 专项套件 `test_p3_detection_enhancement.py` | 19 passed |
| P0-2 event_log_summary 规则（6 条） | 仍在 + DCSync 仍 HITL ✅ |
| P1 探针 `_p1_verify.py` | 13/13 PASS（不受影响） |

> 修复项：`test_rules_import.test_07_rule_severity_update` 原硬编码 `default_rules.json`，
> 在 P3 新增 `advanced_detections.json` 后，被选中的规则可能位于新文件而断言失败。
> 已改为"按规则名定位真实源文件并就地修改+恢复"，兼容规则分布于任意 JSON，且不破坏真实文件。
>
> 全量 `tests/` 因 `conftest.py` 加载 torch 触发 Windows 原生 access violation（预存环境，与 P3 无关），规则相关验证已通过 `--noconftest` 定向回归充分覆盖。

---

## 5. 已知限制与移交

1. **P3-2 为"待激活模板"**：4 条 `exists` 兜底因后端零采集器产出对应字段（`P0-3` 已确认），维持 `enabled:false`。采集器（wmi_subscribe/scheduled_task/service_operation/registry_modify）接线后，运维将其改 `enabled=true` 即生效，无需改规则逻辑。
2. **未实现项（明确边界）**：受采集器缺失限制，C2 JA3/信标/DGA、Sysmon/ETW、黄金票据、MFA 疲劳/不可能旅行、Linux cron/SSH、K8s/云身份/Exchange/OAuth、钓鱼 URL/附件、蜜罐诱饵——本阶段**不写 active 规则**（避免死规则），已在 01-design.md 登记为"已识别缺口 + 阻塞依赖"。
3. **阈值基线**：部分规则阈值（如 4625/4769）为静态估算，生产环境应据 P1-5 历史基线替换（移交后续）。

---

## 6. 交付物清单

| 类型 | 路径 |
|---|---|
| 设计文档 | `docs/rule-audit/p3/01-design.md` |
| 开发文档 | `docs/rule-audit/p3/02-dev.md` |
| 测试文档 | `docs/rule-audit/p3/03-test.md` |
| 验证文档 | `docs/rule-audit/p3/04-verify.md` |
| 新文件 | `backend/app/rules/advanced_detections.json`（20 条） |
| 新测试 | `backend/tests/test_p3_detection_enhancement.py`（19 passed） |
| 测试修正 | `backend/tests/test_rules_import.py`（test_07 兼容多文件源） |
| 生成脚本 | `backend/_gen_p3.py`（规则生成器，可复跑） |

---

## 7. P0–P3 总交付汇总

| 阶段 | 文档 | 关键交付 |
|---|---|---|
| P0 | 01-04 | 占位 IOC 替换动态源、Security 事件桥接（event_log_summary 6 条） |
| P1 | 01-04 | 29 条漏审修正、credential_dump 去重、进程名规则降权/复合化、三态语义 |
| P2 | 01-04 | C2 端口 SSOT、严重度校准+HITL、加载可观测性、双管道验证 |
| P3 | 01-04 | 16 条检测点增强 + 4 条 exists 持久化兜底 |

**全部四阶段、四环节完成，可追溯文档 16 篇齐备。**
