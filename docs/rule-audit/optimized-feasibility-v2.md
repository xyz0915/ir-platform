# 规则库审计报告 · 真实性审计与优化方案 V2（代码实证版）

> 本文基于 `rule_audit_authenticity_and_optimization.md`（下称"原报告"）做**代码级真实性核验**，并据真实代码现状输出修正后的优化方案。
>
> 核验方式：直接 `load_default_rules()` 路径读取 `backend/app/rules/*.json` 全部规则文件 + 精确计数；读取 `rule_engine.py` / `detection_policy.py` / `loader.py` / `agent/collectors/security.py` 真实实现；用脚本对每条断言做命中验证（非人工读报告）。
>
> 核验代码根：`backend/app/rules/`、`agent/collectors/security.py`（当前工作区实际代码）。

---

## 一、真实性核验结论

### 1.1 ✅ 经代码实证属实（原报告正确，可直接采信）

| # | 原报告结论 | 代码实证 |
|---|---|---|
| 1 | `suspicious_c2_domain` 用 `example.*` 占位域名 = 零覆盖 | `default_rules.json` 该规则 condition 含 `malware-c2.example.com` 等；脚本命中 `example.*` 占位 ✅ |
| 2 | 威胁情报为 0（仅静态清单，无动态 IOC 接入） | `FIELD_TO_IOC_TYPE` + `_load_iocs_by_type()` 动态 IOC 机制**已存在**，但默认库 `known_bad_*` 全为硬编码值，`iocs` 表默认空 → 真实零命中 ✅ |
| 3 | `behavior` 默认规则是 `command_line/name/path` 子串匹配 | 引擎 `_match_behavior` 对 `credential_dump`/`uac_bypass` 等均为 `kw in name/cmd` 子串判定 ✅ |
| 4 | C2 端口规则是 6 个固定端口 | `c2_port_4444/6667/1337/4443/5555/8888` 精确等于 4444/6667/1337/4443/5555/8888 ✅ |
| 5 | `credential_dump_behavior` 与 `lsass_dump_detection` 重复 | 二者均在 `default_rules.json` 且 `pattern=credential_dump` ✅ |
| 6 | `exists` 规则依赖采集器未产出字段 → 死规则 | `suspicious_service_reg_exists`(field=`service_image_path`) / `suspicious_scheduled_task_xml_exists`(field=`scheduled_task_xml`) 全后端零采集器产出；且二者**仍 `enabled=true`** ✅ |
| 7 | "仅判进程名"规则误报高 | `msbuild_inline_task_execution`/`msiexec_remote_lolbin`/`cmd_powershell_chain`/`bitsadmin_download` 均 `field=name` 且 pattern 为进程名；`remote_desktop_suspicious` 同 `field=name` ✅ |
| 8 | `attack_chain` 已实现并默认启用（纠正原报告"未使用"） | `default_attack_chain.json` 10 条 `attack_chain` 全部 `enabled=true`；`detection_policy.py:23 enable_attack_chain: bool = True`；`rule_engine.evaluate()` 有 `_match_attack_chain` 分支 ✅ |
| 9 | 引擎行为检测能力已进化（40+ 模式，含结构化检测） | `BEHAVIOR_PATTERNS` 实际 ~42 个（含 `process_name_spoof`/Levenshtein+同形、`unsigned_exe`/JOIN `file_hashes`、`ancestry_chain`、`memory_injection`、`etw_amsi_tamper` 等）✅ |
| 10 | `security.py` 安全事件日志采集器存在（缺口在桥接） | `agent/collectors/security.py:_get_windows_event_summary()` 用 `wevtutil` 查 Security 通道，产出 `event_ids_summary` ✅（根因：采集在 `agent/` 框架，与 `backend/app/rules` 管道未接） |
| 11 | `known_bad_ip` 仅 7 个静态 IP | 3 条 list 规则合计 7 个 IP（185.220.101.1/2/3、104.244.72.115、104.244.74.211、91.219.236.166、192.42.116.14）✅ |
| 12 | 种子加载有"静默丢弃"安全网 | `loader.load_default_rules()` 对非法 `rule_type`/`severity`/`condition`（含 `validate_condition`/`validate_behavior_pattern` 失败）`logger.warning + continue` ✅ |
| 13 | 占位 IOC 从 `list` 蔓延到 `attack_chain` 层 | `default_attack_chain.json` 的 `attack_chain_default_c2_persistence` step 用 `evil.example.com`/`c2.attacker.net`/`185.174.137.11` ✅ |

### 1.2 ❌ 经代码实证失真的项（必须纠正）

| # | 原报告陈述 | 真实代码现状 | 纠正 |
|---|---|---|---|
| **A** | **§3.2：regex≈49 / behavior≈47（合计 134）** | 真实全量分布：**regex=62 / behavior=40 / composite=13 / list=11 / attack_chain=10 / threshold=3 / exists=2 = 141** | ❌ 报告自相矛盾（134≠141），且把"regex 主导"错画成"behavior 近半"。**真实是 regex 主导（44%）** |
| **B** | **§3.2："behavior ≈ 47（default 23 + enhancement 24）"** | `default_rules.json` behavior=**22**；`process_enhancement_rules.json` 是 **24 条总数**（behavior=13/regex=9/list=1/threshold=1），**不是 24 条 behavior** | ❌ 把"文件 24 条"误读为"24 条 behavior"。enhancement behavior 实为 13 |
| **C** | **§3.1 漏列 `revoked_ca.json`** | 该文件是 `{"revoked_signers":[...]}` **对象而非数组**，`load_default_rules()` 因"非数组"跳过；它是 `revoked_sig` 行为模式的数据源，不计入规则 | ⚠️ 报告"141 条"总数**结论正确**（revoked_ca.json 不进规则集），但目录里确有第 5 个 JSON 未说明用途，易误导 |
| **D** | **P0-3：将 2 条死 `exists` 规则"置 enabled:false"**（暗示当前生效或待办） | 全库仅 **2 条 disabled**：`dns_c2_beaconing`(threshold)、`domain_fronting_detection`(regex)；两条 `exists` 死规则**仍是 `enabled=true`** | ⚠️ 报告方向对（P0-3 仍是有效待办），但需明确：死 `exists` 规则**当前仍启用**，会误导运维以为"已生效"，优先级不应降 |
| **E** | **§2.2 称 `BEHAVIOR_PATTERNS` "白名单已扩至 40+"** | 引擎 docstring 仍写"20 种"，实际集合已扩到 ~42 | ✅ 报告结论对，仅 docstring 未同步（无害） |

> 说明：A/B 是**数字硬错**，直接影响"命令行依赖比例"的画像——原报告对默认库"regex/behavior 主体依赖 command_line"的方向仍成立，但**真实占比需按 regex=62(44%) 重算**，而非报告暗示的近半。

### 1.3 修正后的真实规则清单（141 条，loader 实测）

| 文件 | 条数 | rule_type 构成 | 是否经原报告审计 |
|---|---|---|---|
| `default_rules.json` | 102 | regex 53 / behavior 22 / composite 13 / list 10 / exists 2 / threshold 2 | ✅（主体） |
| `default_attack_chain.json` | 10 | attack_chain 10（全 enabled） | ❌ 原报告误称"未使用" |
| `process_enhancement_rules.json` | 24 | behavior 13 / regex 9 / list 1 / threshold 1 | ❌ 漏审（非"24 条 behavior"） |
| `seed_rules_process.json` | 5 | behavior 5 | ❌ 漏审 |
| `revoked_ca.json` | — | 数据文件（revoked_signers），**不进规则集** | ❌ 未说明 |
| **合计** | **141** | regex 62 / behavior 40 / composite 13 / list 11 / attack_chain 10 / threshold 3 / exists 2 | 原报告覆盖 102（72%） |

---

## 二、优化方案 V2（可行性校正版）

> 优先级沿用 P0–P3，但：① 剔除被代码证伪的项（无）；② **据 A/B 修正类型画像**；③ **据 D 明确死 exists 规则仍启用、P0-3 不改降级**；④ 每项标注**可行性评级**（引擎已具备机制 / 需新增 / 需外部依赖）。

### P0 — 阻断实战可用性（必须立即处理）

**P0-1 消除占位/静态 IOC** — 可行性：🔥 高（管道已就绪）
- 问题：`suspicious_c2_domain` 3 个 `example.*` + `attack_chain_default_c2_persistence` 的 `evil.example.com`/`c2.attacker.net`/`185.174.137.11` 全是占位 → 真实 C2 零命中。
- 动作：引擎 `_load_iocs_by_type()` + `FIELD_TO_IOC_TYPE` **已具备动态 IOC 引用能力**，只需①向 `iocs` 表灌入实时源（OTX/微步/云镜）并置 `enabled=1`；②把占位规则的 `condition.values` 改为空、依赖动态 IOC，或上线前临时 `enabled:false`。红队样本命中回归。

**P0-2 桥接 Security 事件日志到规则引擎** — 可行性：⚠️ 中（需新增 matcher + 管道对接，最高价值）
- 问题：`agent/collectors/security.py` 已产出 `event_ids_summary`（4625/4662/4648…），但 `backend` 规则引擎只吃单条 canonical 事件，无消费层。
- 动作：① 新增 `rule_type: "event_log_summary"`（或把 `event_ids_summary` 展开为 canonical 事件流）；② 新增规则集：4625 突发/4648→暴力破解·密码喷洒；4662→DCSync；4769 RC4→Kerberoasting；4624(登录类型9+显式凭据)→PtH；4672 特殊权限异常。这是 AD 域检测的**真正入口**。

**P0-3 修复 2 条死 `exists` 规则** — 可行性：🔥 高（配置级）
- 问题：`service_image_path` / `scheduled_task_xml` **后端零采集器产出**，且二者**当前仍 `enabled=true`**（全库仅 `dns_c2_beaconing`/`domain_fronting_detection` 2 条 disabled，不含它们）。
- 动作：二选一——(a) 补齐采集器字段并在 canonical 事件产出；(b) 短期置 `enabled:false` + UI 标注"待采集接线"，避免误导为已生效。**据 D，此项错误优先级不应降**（运维会误判覆盖）。

### P1 — 重大漏报 / 能力短板

**P1-1 审计 29 条漏审规则**（enhancement 24 + seed 5）— 可行性：🔥 高（分析工作）
- 按真实构成：enhancement 实际 behavior 13 / regex 9 / list 1 / threshold 1。重点：`process_name_spoof` 的 Levenshtein 阈值（编辑距离==1 是否过严/过松）、`unsigned_exe` 对 `file_hashes` 缺失时的降级是否为 False 漏报、`revoked_sig` 空库降级。

**P1-2 消冗余 `credential_dump`** — 可行性：🔥 高（配置级）
- `credential_dump_behavior` 与 `lsass_dump_detection` 同 `pattern=credential_dump` → 合并或去重，避免严重度虚高+重复告警。

**P1-3 攻击链 `registry` step 对齐** — 可行性：⚠️ 中
- `attack_chain` 依赖 `process`/`connection`/`registry` 三维 step；确认 `registry` 维采集器是否产出 `key_path`，否则对应 step 永不命中。

**P1-4 "仅判进程名"规则降权/复合化** — 可行性：🔥 高（配置级）
- 5 条 `field=name` 的 regex（msbuild/msiexec/cmd/bitsadmin/remote_desktop）+ `unsigned_process`(behavior) 改 `composite`(进程名+参数特征) 或降 severity + 资产/白名单基线。

**P1-5 资产/账号行为基线** — 可行性：⚠️ 中–高（需历史基线存储）
- `high_connection_count`/`network_scan_behavior`/`time_cluster_burst`/`data_compression_exfil`/`dns_c2_beaconing`(已 disabled) 用历史基线替代固定阈值，否则生产误报淹没真警。需确认基线存储是否已具备。

### P2 — 误报治理 / 工程

**P2-1 C2 端口泛化** — 可行性：🔥 高（引擎已有 `_C2_PORTS`/`_BUSINESS_PORTS` 常量 + `anomalous_net_process` pattern）。
**P2-2 严重度校准** — 可行性：🔥 高（配置级）；把"仅看进程名"规则降权，把 LSASS 读取/DCSync/勒索批量加密提 critical 并接 HITL。
**P2-3 种子加载可观测性** — 可行性：🔥 高（小）；启动时把"被跳过规则名+原因"写入运维日志/RuleHistory。
**P2-4 双管道对齐** — 可行性：⚠️ 中；确认 `agent/collectors/security.py` 的 `event_ids_summary` 是否回流 `backend`（P0-2 前置）。

### P3 — 增强与演进

**P3-1 新增检测点（Top 20）** — 可行性：🔥 高（新增规则）；Kerberos 4769 / DCSync 4662 / PtH 4624 / 暴力破解 4625 / 实时 TI / C2 JA3·信标·DGA / Sysmon·ETW / 黄金票据 / MFA 疲劳·不可能旅行 / Linux systemd·cron·SSH / 容器·K8s 逃逸 / 云身份·Exchange·OAuth / 勒索批量加密 / 卷影删除 / 数据外发云存储 / RMM 滥用 / 钓鱼 URL·附件 / 蜜罐诱饵——除 attack_chain 与部分结构化行为外仍为真缺口。
**P3-2 `exists` 类扩展** — 可行性：⚠️ 中（依赖 P0-3a 采集器补齐）；新增 `wmi_subscription_exists`/`scheduled_task_exists` 等持久化兜底。

---

## 三、可行性总体评估

| 维度 | 评估 |
|---|---|
| **引擎能力** | 远超原报告刻画：`attack_chain` 已落地默认启用；`BEHAVIOR_PATTERNS` ~42 个含结构化检测；动态 IOC 引用机制已就绪。**原报告"行为=子串"对默认规则成立、对引擎能力不成立**——此纠正属实。 |
| **最大缺口** | `agent/collectors/security.py`(Security 事件) → `backend/app/rules` 的**管道桥接**（P0-2）。引擎吃单条 canonical 事件，`event_ids_summary` 无消费层。这是 AD 域检测的真正入口，工作量中但价值最高。 |
| **最大低风险收益** | P0-1(占位 IOC 替换动态源，管道已备)、P0-3(exists 死规则置 disabled，配置级)、P1-2(credential_dump 去重)——均 **🔥 高可行性、低工作量**，应首批落地。 |
| **需外部依赖** | P1-5 历史基线存储、P0-2 管道对接、实时 TI 源接入——需确认基础设施是否已具备，否则工作量升档。 |

---

## 四、落地行动清单（按性价比 + 可行性排序）

| 序 | 行动 | 对应项 | 可行性 | 工作量 |
|---|---|---|---|---|
| 1 | 把 3+3 个占位/示例 IOC 改引用 `iocs` 动态集合（或临时 `enabled:false`） | P0-1 | 🔥 高（管道已备） | 小 |
| 2 | 2 条死 `exists` 规则置 `enabled:false` + UI 标注"待采集" | P0-3 | 🔥 高 | 小 |
| 3 | 合并 `credential_dump_behavior` / `lsass_dump_detection` | P1-2 | 🔥 高 | 小 |
| 4 | 新增 `event_log_summary` 规则集（4625/4662/4769/4624/4672/4648）并桥接 `security.py` | P0-2 | ⚠️ 中 | 中 |
| 5 | 补审 enhancement(24) + seed(5) 逐条 FP/FN（按真实行为 13/regex 9 构成） | P1-1 | 🔥 高 | 中 |
| 6 | 5 条"仅判进程名"规则降权/复合化 | P1-4 | 🔥 高 | 中 |
| 7 | 攻击链 `registry` step 的 `key_path` 采集对齐 | P1-3 | ⚠️ 中 | 中 |
| 8 | 资产/账号行为基线替换固定阈值 | P1-5 | ⚠️ 中–高 | 大 |

---

## 五、与原报告的关键差异（务必知悉）

1. **类型分布纠正**：原报告 §3.2（regex≈49 / behavior≈47，合计 134）**错误且自相矛盾**；真实为 **regex=62 / behavior=40**，regex 主导（44%）。原报告"behavior 近半"画像不成立。
2. **enhancement 文件误读**：原报告把 `process_enhancement_rules.json` 的"24 条总数"当作"24 条 behavior"；真实 behavior=13。
3. **死规则状态**：两条 `exists` 死规则**当前仍 `enabled=true`**（全库仅 `dns_c2_beaconing`/`domain_fronting_detection` 2 条 disabled），P0-3 优先级不应降。
4. **`revoked_ca.json`**：非规则数组（revoked_signers 数据源），不进 `load_default_rules`，故"141 条"总数正确；但目录确有第 5 个 JSON，原报告未说明其用途（供 `revoked_sig` 行为模式使用）。
5. **13 项核心结论**（`#1–#13`）经代码实证全部属实，原报告主体可信，可直接用于治理。

> 建议：下一步把 `process_enhancement_rules.json`(真实 behavior 13 / regex 9 / list 1 / threshold 1) 与 `seed_rules_process.json`(behavior 5) 按"检测原理/误报/漏报"格式补做逐条分析，使 141 条审计完整闭环。
