# P2 阶段设计文档 —— 误报治理与工程可观测性

| 项 | 内容 |
| --- | --- |
| 阶段 | P2（误报治理 / 工程） |
| 依据 | `docs/rule-audit/optimized-feasibility-v2.md` §二 P2、§四 落地行动清单 |
| 前置 | P0（占位 IOC / Security 事件桥接 / 死 exists 规则）、P1（漏报治理）均已交付 |
| 覆盖子项 | P2-1 C2 端口泛化、P2-2 严重度校准、P2-3 种子加载可观测性、P2-4 双管道对齐 |
| 证据来源 | `backend/app/rules/*.json`、`backend/app/rules/rule_engine.py`、`backend/app/rules/loader.py`、`backend/app/database.py`、真实库 `backend/data/ir_platform.db` |
| 采集脚本 | `backend/_p2_evidence.py`、`backend/_p2_evidence2.py`（只读） |

---

## 1. 背景与本阶段定位

P0/P1 解决的是**漏报**（检测不到）与**误报根因**（三态语义、宽泛 regex、重复 pattern）。
P2 转向另外两类问题：

1. **配置层的结构性冗余与割裂** —— 同一个安全语义（"可疑 C2 端口"）在代码常量与规则 JSON 中各存一份，且内容不一致；
2. **工程可观测性缺失** —— 规则装载过程对运维完全是黑盒，跳过了什么、库里多了什么，无人可知。

这两类问题不直接产生告警，但会**持续制造误报/漏报并让人无法察觉**，属于典型的技术债。

### 1.1 实测基线（P2 起点）

以下数据由 `_p2_evidence.py` / `_p2_evidence2.py` 对真实库与规则文件实测得出。

**规则装载**

```
loader.load_default_rules() 返回 = 147 条（enabled=136 / disabled=11）
文件对账：
  default_attack_chain.json         10 条  → 加载 10
  default_rules.json               102 条  → 加载 102
  event_log_rules.json               6 条  → 加载 6
  process_enhancement_rules.json    24 条  → 加载 24
  seed_rules_process.json            5 条  → 加载 5
  revoked_ca.json                   非数组 → 整文件跳过（仅一行 warning）
合计文件内条目 147 = loader 返回 147（0 条校验失败）
```

**严重度分布（两种口径）**

| 口径 | 规则数 | critical | high | medium | low |
| --- | ---: | ---: | ---: | ---: | ---: |
| JSON 全量（loader 5 文件） | 147 | 36 (24.5%) | **82 (55.8%)** | 25 (17.0%) | 4 (2.7%) |
| JSON 仅 enabled | 136 | 33 (24.3%) | 74 (54.4%) | 25 (18.4%) | 4 (2.9%) |
| DB 全量（含 user/ai/import） | 158 | 38 (24.1%) | 85 (53.8%) | 29 (18.4%) | 6 (3.8%) |
| DB 仅 enabled | 145 | 35 (24.1%) | 76 (52.4%) | 28 (19.3%) | 6 (4.1%) |

**DB 来源构成**：`default=151`、`user=4`、`import=2`、`ai=1`。

---

## 2. 问题清单（实测确认）

### 2.1 【P2-1】C2 端口"双清单割裂"+"一端口一规则"—— 结构性缺陷

#### 2.1.1 现状

系统中存在**两套互不相通的 C2 端口清单**。

**清单 A：规则 JSON**（6 条独立 `list` 规则，`backend/app/rules/default_rules.json`）

```
c2_port_4444   sev=high  field=remote_port  match_mode=exact  values=[4444]
c2_port_6667   sev=high  field=remote_port  match_mode=exact  values=[6667]
c2_port_1337   sev=high  field=remote_port  match_mode=exact  values=[1337]
c2_port_4443   sev=high  field=remote_port  match_mode=exact  values=[4443]
c2_port_5555   sev=high  field=remote_port  match_mode=exact  values=[5555]
c2_port_8888   sev=high  field=remote_port  match_mode=exact  values=[8888]
```

**清单 B：引擎硬编码常量**（`rule_engine.py:187`，供 `anomalous_net_process` 行为模式使用）

```python
_C2_PORTS = {4444, 8443, 1337, 31337, 6667, 9999, 1080, 5900}
```

#### 2.1.2 实测差异

| 集合 | 端口 | 后果 |
| --- | --- | --- |
| 交集 | `1337, 4444, 6667` | 仅 3 个端口两条链路都覆盖 |
| **仅 JSON 有** | `4443, 5555, 8888` | 引擎 `anomalous_net_process` **不认这 3 个端口**，行为链路漏判 |
| **仅引擎有** | `1080, 5900, 8443, 9999, 31337` | 这 5 个端口**没有独立告警规则**，list 链路漏判 |

#### 2.1.3 缺陷分析

| # | 缺陷 | 说明 |
| --- | --- | --- |
| D1 | **无单一事实来源（SSOT）** | 同一安全语义两份定义，任何一侧更新另一侧不同步，已实测出 8 个端口的不一致 |
| D2 | **不可扩展** | 新增 1 个 C2 端口需新建 1 条完整规则（name/description/category/severity/condition 全套），维护成本随端口数线性增长 |
| D3 | **严重度一刀切** | 6 条全部 `high`。但 `1080`(SOCKS 代理)、`5900`(VNC)、`8443`(HTTPS-alt) 在企业环境存在大量**合法用途**，统一 high 是明确的误报源 |
| D4 | **注释与代码不符** | `rule_engine.py:186` 注释称"8443 同列于业务与 C2 清单，优先按 C2 判定"，但实测 `_C2_PORTS ∩ _BUSINESS_PORTS = ∅`（`_BUSINESS_PORTS` 内并无 8443）。注释陈腐，误导后续维护者 |
| D5 | **贡献 6 条 high** | 6 条弱条件（单字段精确匹配）规则占据 high 配额，直接推高 high 占比（见 §2.2） |

#### 2.1.4 设计方案

**核心思路：建立 SSOT + 按置信度分层。**

**(1) 新增数据文件 `backend/app/rules/c2_ports.json`（单一事实来源）**

```json
{
  "_comment": "C2/代理/反弹端口单一事实来源（P2-1）。引擎与规则均从此文件取值。",
  "high_confidence": {
    "ports": [1337, 4443, 4444, 5555, 6667, 8888, 31337],
    "severity": "high",
    "rationale": "无公认合法服务占用，出现即高度可疑（Metasploit/IRC C2/常见反弹壳默认端口）"
  },
  "low_confidence": {
    "ports": [1080, 5900, 8443, 9999],
    "severity": "medium",
    "rationale": "存在合法用途（SOCKS 代理/VNC 远程支持/HTTPS 备用端口），需结合进程与路径判定"
  }
}
```

端口全集 = 清单 A ∪ 清单 B = 11 个，**两侧漏判同时消除**。

**(2) 规则侧：6 条合并为 2 条**

| 新规则 | 类型 | values | severity | 取代 |
| --- | --- | --- | --- | --- |
| `c2_suspicious_port_high` | list | high_confidence.ports（7 个） | high | `c2_port_4444/6667/1337/4443/5555/8888` |
| `c2_suspicious_port_low` | list | low_confidence.ports（4 个） | medium | （新增覆盖，此前无规则） |

原 6 条规则名保留在 `_meta.superseded_by` 中，便于历史告警追溯。

**(3) 引擎侧：`_C2_PORTS` 改为从 `c2_ports.json` 装载**

沿用 `_REVOKED_CA_CACHE`（`rule_engine.py:200`）已验证的**懒加载 + 优雅降级**模式：

```python
_C2_PORTS_CACHE: Optional[dict] = None

def _load_c2_ports() -> dict:
    """从 c2_ports.json 装载端口分层清单；文件缺失/损坏时回落内置默认值。"""
```

**降级原则**：文件缺失或解析失败 → 回落到当前硬编码全集，**绝不抛异常、绝不使检测能力归零**（与 `revoked_ca.json` 同策略）。

**(4) 严重度分层进入引擎判定**

`_match_anomalous_net_process` 中 `remote_port in _C2_PORTS` 的布尔判定保持不变（行为模式返回 bool），但**新增分层信息写入命中原因**，供下游 `anomaly_detector` 加权时区分。

#### 2.1.5 附带收益（对 AC-P1-13 的闭合作用）

见 §2.2.3 —— 该合并使 high 占比降至 **53.8%**，闭合 P1 遗留的 AC-P1-13。

---

### 2.2 【P2-2】严重度校准 —— 含 P1 遗留 AC 的口径缺陷修正

#### 2.2.1 P1 遗留问题回顾

P1 验证阶段 AC-P1-13（`high 占比 ≤ 55%`）判定 **FAIL**，实测值 **59.9%**，当时移交 P2 处理。

#### 2.2.2 根因：探针口径缺陷（本阶段新发现）

复核 `backend/_p1_verify.py:19-24` 发现，探针的 `RULE_FILES` 白名单为：

```python
RULE_FILES = [
    "default_rules.json",
    "process_enhancement_rules.json",
    "event_log_rules.json",
    "seed_rules_process.json",
]
```

**漏掉了 `default_attack_chain.json`**（10 条，全部 `critical`），而 `loader.load_default_rules()` 是 `glob("*.json")` 全量装载。分母偏小且被剔除的全是 critical，人为抬高了 high 占比：

| 口径 | 规则数 | high | 占比 |
| --- | ---: | ---: | ---: |
| P1 探针（4 文件） | 137 | 82 | **59.9%** ← AC-P1-13 的 FAIL 值 |
| loader 全口径（5 文件） | 147 | 82 | **55.8%** |

**结论**：59.9% 是**度量错误**，真实基线为 55.8%，与目标 55% 的真实差距是 **0.8pp**（约 2 条 high），而非原以为的 4.9pp。

> 说明：这不是"改口径让 AC 通过"。判定 AC 的口径必须与**生产实际装载行为**（loader）一致，探针使用与生产不一致的子集本身即为缺陷。修正后 55.8% 仍未达标，仍需实质治理。

#### 2.2.3 治理动作与量化预测

| 动作 | 来源 | high 变化 | 总数变化 |
| --- | --- | ---: | ---: |
| A. 修正探针口径为 loader 全量 | P2-2 | — | 137 → 147 |
| B. c2_port 6 条 → 2 条（1 high + 1 medium） | P2-1 | −5 | −4 |

**合并后预测**：

```
总数 = 147 − 6 + 2 = 143
high = 82 − 6 + 1 = 77
high 占比 = 77 / 143 = 53.8%  ≤ 55%  ✅ 闭合 AC-P1-13
```

（若仅按"6 合 1"简化计算：142 条 / high 77 → 54.2%，同样达标。分层方案更优。）

#### 2.2.4 关键高危检测点严重度核查（实测）

可行性文档建议"把 LSASS 读取 / DCSync / 勒索批量加密提 critical"。**实测核查发现这些规则已经是 critical**，无需再提：

| 规则 | rule_type | severity | enabled |
| --- | --- | --- | --- |
| `lsass_dump_detection` | behavior | critical | ✅ |
| `dcsync_detection` | regex | critical | ✅ |
| `evt_4662_dcsync_suspect` | event_log_summary | critical | ✅ |
| `ransomware_behavior_pattern` | behavior | critical | ✅ |
| `dpapi_credential_theft` | regex | critical | ✅ |
| `browser_credential_theft` | regex | critical | ✅ |
| `attack_chain_rdp_psexec_lsass` | attack_chain | critical | ✅ |
| `attack_chain_zerologon_dcsync` | attack_chain | critical | ✅ |
| `credential_dump_behavior` | behavior | critical | ⛔ disabled（P1-2 去重下线，语义并入 `lsass_dump_detection`） |

**设计决策**：P2-2 **不做重复的提权动作**，如实记录"该项在 P0/P1 阶段已达成"。本阶段仅补齐**HITL 挂钩标注**（见下）。

#### 2.2.5 HITL 挂钩

系统已具备 HITL 审批基础设施（`app/api/agents.py` + `app/models/hitl_approval.py`，含 `waiting_hitl` 状态与管理员批准/拒绝端点）。

本阶段动作：为上述 critical 规则统一补 `_meta.requires_hitl: true` 标注，使 Responder 智能体在执行自动处置前**强制走人工审批**，避免 critical 规则误报直接触发隔离/阻断等高影响动作。此为**元数据标注**，不改变引擎判定逻辑。

---

### 2.3 【P2-3】种子加载零可观测性

#### 2.3.1 现状

`loader.load_default_rules()`（`loader.py:25-73`）对每一类校验失败仅调用 `logger.warning(...)` 后 `continue`，**不做任何汇总**，返回值只有 `List[dict]`。调用方 `_import_default_rules()`（`database.py:1375`）返回的 stats 为：

```python
{"updated": ..., "inserted": ..., "preserved": ..., "total": len(rules_data)}
```

`total` 是**装载成功数**，而非文件内条目总数 —— **被跳过的条目在统计中不留任何痕迹**。

#### 2.3.2 缺陷 1：跳过静默

loader 有 7 处 `continue` 分支（文件解析失败 / 顶层非数组 / 条目非对象 / 缺 name / rule_type 非法 / severity 非法 / condition 非对象 / 条件校验失败）。任一分支命中时：

- 运维在 API 返回中看不到（stats 无 skipped 字段）；
- 日志中虽有 warning，但**混在启动日志洪流里**，且无聚合计数；
- 结果：**一条规则因拼写错误被静默丢弃，可能数月无人发现**（P1 阶段已因类似机制踩坑）。

当前实测跳过数为 0（147/147 全部装载成功），但**机制缺陷客观存在**，属于"现在没暴雷不代表安全"。

#### 2.3.3 缺陷 2：数据文件与规则文件混淆

`loader` 对 `app/rules/*.json` 无差别 glob，导致纯数据文件被当作规则文件处理并产生噪音告警：

```
规则文件 revoked_ca.json 顶层不是数组，跳过
```

`revoked_ca.json` 是 `revoked_sig` 行为模式的数据源（`_REVOKED_CA_CACHE`），**本就不该是规则数组**。这条 warning 每次启动都出现，属于**假阳性告警**——而它恰好训练运维忽略此类 warning，从而掩盖真正的规则丢失。P2-1 若新增 `c2_ports.json`，问题会加剧（2 条噪音）。

#### 2.3.4 缺陷 3：DB 孤儿规则不可见（实测发现）

实测 DB 中 `source='default'` 共 **151** 条，而 JSON 仅 **147** 条，多出 **4 条**：

| name | rule_type | severity | condition.detector |
| --- | --- | --- | --- |
| `P0-1-TAMPER` | behavior | critical | `tamper` |
| `P0-2-SHADOW` | behavior | critical | `shadow` |
| `P1-PRIVESC` | behavior | high | `priv_esc` |
| `P1-REGISTRY` | behavior | medium | `registry` |

**溯源结论（重要，避免误判为脏数据）**：这 4 条**并非测试残留或数据污染**，而是**服务风险分析子系统**的配置化规则——由 `app/analysis/service_risk_analyzer.py:87-91` 通过 `condition.detector` 字段派发到 4 个专用检测器（tamper/shadow/priv_esc/registry），权重定义在 `app/analysis/service_constants.py:17-19`。它们是**第二套合法规则源**，只是不由 `app/rules/*.json` 管理。

**风险评估**：

- `_import_default_rules` 采用 **upsert by name**（不含 `DELETE`），因此这 4 条**不会被 reset 误删** —— 经代码核查确认安全；
- 但 import 过程对它们**既不 update 也不 insert，完全静默**。运维无从得知"DB 中存在 4 条 JSON 之外的 default 规则"；
- `source='default'` 语义因此变得**二义**（既指"JSON 种子规则"又指"服务风险内置规则"），未来若有人为 reset 加上 `DELETE FROM rules WHERE source='default'`，这 4 条将被静默删除，服务风险分析能力**整体失效且无告警**。

#### 2.3.5 设计方案

**(1) loader 返回结构化装载报告**

新增 `load_default_rules_with_report()`，返回 `(rules, report)`：

```python
@dataclass
class LoadReport:
    total_files: int          # 扫描到的 json 文件数
    rule_files: int           # 判定为规则文件的数量
    data_files: list[str]     # 已知数据文件（白名单，不计入跳过）
    total_entries: int        # 规则文件内条目总数
    loaded: int               # 成功装载数
    skipped: list[SkipRecord] # 每条跳过的 {file, index, name, reason}
```

`load_default_rules()` 保留为薄封装（只返回 rules），**保证既有调用方与测试零改动**。

**(2) 数据文件白名单**

```python
DATA_FILES = {"revoked_ca.json", "c2_ports.json"}
```

命中白名单的文件跳过规则解析且**不产生 warning**，改为 `logger.debug` 记录为"数据文件"。消除噪音告警。

**(3) stats 扩展 + 孤儿检测**

`_import_default_rules` 的返回值扩展为：

```python
{
  "updated": n, "inserted": n, "preserved": n,
  "total": n,                    # 语义不变（装载成功数），兼容既有调用方
  "total_entries": n,            # 新增：文件内条目总数
  "skipped": n,                  # 新增：被跳过条目数
  "skipped_detail": [...],       # 新增：跳过明细
  "orphans": ["P0-1-TAMPER", ...]  # 新增：DB 有 / JSON 无的 default 规则
}
```

**孤儿不做任何自动清理**——仅暴露。这是刻意的保守设计：孤儿可能是合法的第二套规则源（如本例的服务风险规则），自动删除会造成能力静默丢失。

**(4) 启动摘要日志**

以单条结构化 INFO 输出，便于 grep 与告警：

```
[RULE-LOAD] files=6(rule=5,data=1) entries=147 loaded=147 skipped=0 orphans=4 [P0-1-TAMPER,P0-2-SHADOW,P1-PRIVESC,P1-REGISTRY]
```

`skipped > 0` 时升级为 `WARNING` 并逐条列出原因。

---

### 2.4 【P2-4】双管道对齐 —— 现状核查与残余缺口

#### 2.4.1 可行性文档的判断已过时

可行性文档记载：

> **P2-4 双管道对齐** — 可行性：⚠️ 中；确认 `agent/collectors/security.py` 的 `event_ids_summary` 是否回流 `backend`（P0-2 前置）。

**实测核查：桥接已在 P0-2 阶段建成并投产。** 完整链路如下：

```
agent/collectors/security.py:157   产出 {"event_ids_summary": {"4625": 37, ...}}
        │
        ▼
backend/app/services/import_service.py:228   从 agent_imports.raw_json 提取
        │
        ▼
backend/app/services/security_event_rules.py:41  _extract_event_summary()
        │    （兼容 3 种载荷形态：单对象 / 列表包裹 / 嵌套）
        ▼
MatcherRegistry.dispatch("event_log_summary", ...)   rule_engine.py:3206
        │
        ▼
RuleEngine._match_event_log_summary()   rule_engine.py:1204
```

因此 P2-4 **不需要新建桥接**，转为**覆盖率核查 + 契约文档化**。

#### 2.4.2 覆盖率核查（实测）

**采集侧**（`agent/collectors/security.py:135-136`）：

```python
event_id = parts[-1].strip()
summary[event_id] = summary.get(event_id, 0) + 1
```

**无 event_id 白名单过滤**，全量计数。即采集侧不构成瓶颈。

**规则侧**（`event_log_rules.json`，6 条）：

| 规则 | event_id | 阈值 | severity |
| --- | ---: | --- | --- |
| `evt_4625_failed_logon_burst` | 4625 | `>= 10` | high |
| `evt_4648_explicit_cred_burst` | 4648 | `>= 15` | medium |
| `evt_4662_dcsync_suspect` | 4662 | `>= 1` | critical |
| `evt_4769_kerberoasting_suspect` | 4769 | `>= 30` | high |
| `evt_4672_special_privilege_anomaly` | 4672 | `>= 50` | medium |
| `evt_4624_logon_volume_anomaly` | 4624 | `>= 100` | low |

覆盖 P0-2 设计目标的全部 6 个事件 ID，**无缺口**。

#### 2.4.3 残余缺口（本阶段处理）

| # | 缺口 | 处置 |
| --- | --- | --- |
| G1 | **契约无文档** | 三层载荷形态兼容逻辑仅存在于代码注释，无正式契约文档。新增 §"双管道数据契约"章节写入 `02-dev.md` |
| G2 | **`event_records` 上限 100 条** | `security.py:118` 限制明细最多 100 条，但 `event_ids_summary` 计数**不受此限**（先计数后截断）。需在契约中显式声明"summary 全量、records 采样"，避免后续误用 records 做统计 |
| G3 | **降级路径未验证** | `security_event_rules.py:23` 声明"DB 中无 event_log_summary 规则时优雅降级"，需补测试用例固化 |

**Non-Goal**：不扩展新的 event_id 检测点——那属于 P3-1（Kerberos/PtH/黄金票据等 Top20）。

---

## 3. 影响面与兼容性

| 变更 | 影响面 | 兼容性风险 | 缓解措施 |
| --- | --- | --- | --- |
| c2_port 6 条 → 2 条 | 规则总数 147→143；历史告警的 `rule_name` 引用旧名 | 中 | 旧名写入 `_meta.superseded_by`；历史告警数据不做迁移（保留原名，仅新告警用新名） |
| `_C2_PORTS` 改为文件装载 | `anomalous_net_process` 行为模式 | 低 | 懒加载 + 文件缺失回落硬编码默认值，能力不归零 |
| 端口 `1080/5900/8443/9999` 新增覆盖 | 可能产生新告警 | 中 | 定为 `medium` 而非 high；`_meta` 标注需结合进程判定 |
| loader 新增报告 API | 既有 6 处调用方 | 无 | 原函数签名与返回值完全不变，新增独立函数 |
| stats 字段扩展 | `/api/rules/reset` 响应体 | 低 | 仅新增字段，原字段语义不变（`total` 仍为装载成功数） |
| `_meta.requires_hitl` 标注 | Responder 自动处置 | 低 | 纯元数据，引擎判定逻辑不变 |

**数据库迁移**：无。本阶段不涉及 schema 变更。

---

## 4. 验收标准

| AC | 描述 | 判定方法 |
| --- | --- | --- |
| **AC-P2-1** | `c2_ports.json` 存在且端口全集 = 原 JSON 6 端口 ∪ 原 `_C2_PORTS` 8 端口 = 11 个 | 集合比对 |
| **AC-P2-2** | 引擎 `_C2_PORTS` 与 `c2_ports.json` 完全一致（SSOT 成立） | 装载后集合相等断言 |
| **AC-P2-3** | 旧 6 条 `c2_port_*` 规则已下线，新 2 条规则装载成功且严重度分层正确 | 规则名集合 + severity 比对 |
| **AC-P2-4** | `c2_ports.json` 删除时引擎回落默认值且不抛异常 | 临时改名后调用 `_load_c2_ports()` |
| **AC-P2-5** | `anomalous_net_process` 对 `4443/5555/8888`（原引擎漏判）能命中 | matcher 层直接构造用例 |
| **AC-P2-6** | high 占比（loader 全口径）≤ 55% —— **闭合 P1 遗留 AC-P1-13** | 全量统计 |
| **AC-P2-7** | `_p1_verify.py` 探针口径修正为 loader 全量，重跑 AC-P1-13 通过 | 重跑探针 |
| **AC-P2-8** | 9 条关键 critical 规则（LSASS/DCSync/勒索等）severity 保持 critical 且带 `requires_hitl` 标注 | 逐条核对 |
| **AC-P2-9** | `LoadReport` 能正确报告故意注入的非法规则（rule_type 非法 / 缺 name / condition 校验失败） | 临时文件注入测试 |
| **AC-P2-10** | `revoked_ca.json` / `c2_ports.json` 不再产生"顶层不是数组"warning | 日志捕获断言 |
| **AC-P2-11** | stats 正确报告 4 条孤儿规则且**不删除**它们 | 对真实库快照比对 |
| **AC-P2-12** | `load_default_rules()` 原签名与返回值不变，既有测试全绿 | 回归 5 个规则测试文件 |
| **AC-P2-13** | 双管道契约文档化，`event_ids_summary` 三种载荷形态均有测试覆盖 | 文档 + 测试 |
| **AC-P2-14** | 无 event_log_summary 规则时降级不报错 | 空规则集测试 |
| **AC-P2-15** | 全量回归无新增失败 | pytest 全量 |

---

## 5. 不做的事（Non-Goals）

| 项 | 原因 |
| --- | --- |
| 自动清理 DB 孤儿规则 | 孤儿可能是合法第二套规则源（本例即是），自动删除会静默摧毁服务风险分析能力。**仅暴露，不处置** |
| 统一 `source` 字段语义（拆分 `default` / `builtin`） | 涉及 schema 迁移与前端筛选逻辑，影响面超出 P2 范围，登记为技术债 |
| 新增 event_id 检测点 | 属 P3-1 范围 |
| 端口范围匹配（如 `49152-65535` 高位端口） | 需先有基线数据支撑，否则误报不可控；依赖 P1-5 基线能力成熟后评估 |
| 历史告警的 `rule_name` 迁移 | 破坏审计可追溯性，历史告警应保留其产生时的规则名 |
| 修改 `anomalous_net_process` 的 `non_system` 宽泛分支 | 该分支（非系统目录进程连任意非业务端口即命中）确为误报源，但收敛它需要资产基线，归 P3 |

---

## 6. 实施顺序

```
P2-3（loader 可观测性）    ← 先做，为后续变更提供装载校验能力
      ↓
P2-1（C2 端口 SSOT）       ← 依赖 P2-3 的数据文件白名单机制
      ↓
P2-2（严重度校准）         ← 依赖 P2-1 的规则合并结果
      ↓
P2-4（双管道文档化 + 测试补齐）  ← 独立，可并行
```

---

*本文档所有数据均来自对真实代码与真实库的实测，无推测性结论。采集脚本见 `backend/_p2_evidence.py` / `backend/_p2_evidence2.py`。*
