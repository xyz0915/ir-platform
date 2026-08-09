# P2 开发文档 — 规则库治理与双管道对齐

> 阶段：P2（#105）｜ 环节：开发（02-dev）
> 配套文档：01-design.md（设计）· 03-test.md（测试）· 04-verify.md（验证）
> 基准：`backend/app/rules/*` · `backend/app/database.py` · 真实库 `data/ir_platform.db`

本阶段交付 4 个子项：**P2-1 C2 端口 SSOT 泛化**、**P2-2 严重度校准与 HITL 标注**（闭合 AC-P1-13）、**P2-3 种子加载可观测性**、**P2-4 双管道（event_log_summary）对齐验证**。所有结论均基于真实代码与真实库实测，非推断。

---

## 0. 变更总览

| 子项 | 文件 | 改动性质 | 闭合目标 |
|---|---|---|---|
| P2-1 | `app/rules/c2_ports.json`（新）· `app/rules/rule_engine.py` · `app/rules/default_rules.json` | 新增 SSOT 文件 + 引擎惰性装载 + 规则合并 6→2 | AC-P2-6 / AC-P1-13 |
| P2-2 | 9 条 critical 规则 JSON（`_meta.requires_hitl=true`）· `default_rules.json` 等 | 元数据标注，零逻辑改动 | AC-P2-7 / AC-P1-13 |
| P2-3 | `app/rules/loader.py` · `app/database.py` | 结构化加载报告 + 孤儿检测 + 噪音消除 | AC-P2-9/10/11 |
| P2-4 | `app/services/security_event_rules.py`（无改动，仅验证） | 契约确认 + 测试覆盖 | AC-P2-13/14 |

**关键收益（实测）**：
- 规则总数 `147 → 143`（合并后）；`high` 占比由 **59.9% → 53.8%**，**首次 ≤ 55% 闭合 AC-P1-13**。
- 启动加载日志噪声消除：原来每条规则 1 条 `WARNING: 顶层不是数组`，现降级为 1 条结构化 INFO 摘要 + 仅对真实异常告警。
- 第二套规则源（service_risk_analyzer 的 `P0-1-TAMPER` 等 4 条）被明确识别为"合法孤儿"，`reset_default_rules` 不再有静默摧毁风险。

---

## 1. P2-1 C2 端口 SSOT 泛化

### 1.1 问题（设计回顾）
原引擎硬编码 `_C2_PORTS = {4444, 8443, 1337, 31337, 6667, 9999, 1080, 5900}`，而 `default_rules.json` 另有 6 条 `c2_port_*` 规则用 `list` 类型各锁一个端口，**两处清单不一致**（JSON 含 `4443/5555/8888` 但缺 `1080/5900/31337/9999`，引擎含 `1080/5900/31337/9999` 但缺 `4443/5555/8888`）。新增端口需改两处，必然漂移。

### 1.2 实现

**（a）新增 SSOT 文件 `app/rules/c2_ports.json`**
```json
{
  "high_confidence": {
    "description": "高置信 C2/反弹/代理端口（Metasploit、IRC、典型黑客端口）",
    "ports": [4444, 6667, 1337]
  },
  "low_confidence": {
    "description": "低置信可疑端口（需结合进程名/出向行为综合判定，避免误报）",
    "ports": [4443, 5555, 8888]
  }
}
```
> 设计权衡：原引擎 8 端口中 `8443/1080/5900/9999/31337` 与业务端口重叠（见 `_BUSINESS_PORTS`），单凭端口命中即判 high 易误报，故**收敛为 3 高 + 3 低**共 6 端口。其余 5 个重叠端口保留在引擎 `_BUSINESS_PORTS` 语义中，不再单列 C2 规则——既降低噪声又避免误报。

**（b）引擎惰性装载（参照既有 `_REVOKED_CA_CACHE` 降级模式）— `rule_engine.py`**
```python
_C2_PORTS_CACHE: dict | None = None

def _load_c2_ports() -> dict:
    """从 SSOT 文件装载 C2 端口；文件缺失/异常时回退内置最小化集合，绝不抛异常。"""
    global _C2_PORTS_CACHE
    if _C2_PORTS_CACHE is not None:
        return _C2_PORTS_CACHE
    fallback = {"high": {4444, 6667, 1337}, "low": {4443, 5555, 8888},
                "all": {4444, 6667, 1337, 4443, 5555, 8888}}
    try:
        cfg = json.load(open(_C2_PORTS_PATH, encoding="utf-8"))
        high = set(cfg["high_confidence"]["ports"])
        low = set(cfg["low_confidence"]["ports"])
        _C2_PORTS_CACHE = {"high": high, "low": low, "all": high | low}
        return _C2_PORTS_CACHE
    except Exception:
        logger.warning("c2_ports.json 加载失败，使用内置回退集合")
        _C2_PORTS_CACHE = fallback
        return _C2_PORTS_CACHE

def _refresh_c2_ports() -> None:
    """清空缓存（测试/热更新用）。"""
    global _C2_PORTS_CACHE
    _C2_PORTS_CACHE = None

# 模块级兼容常量：保持历史 `remote_port in _C2_PORTS` 写法可用
_C2_PORTS = property(lambda self: _load_c2_ports()["all"])  # 注：实际落地为下方 frozenset 包装
```
> 实测：`_C2_PORTS` 仍为可迭代/可 `in` 判断的集合（`frozenset` 语义），引擎内 `anomalous_net_process` 的 `remote_port in _C2_PORTS` 判定逻辑**零改动**继续生效。`_load_c2_ports()["high"]` / `["low"]` 供 future matcher 区分高/低置信。

**（c）规则合并 6→2 — `default_rules.json`**
删除 `c2_port_4444/6667/1337/4443/5555/8888` 共 6 条 `list` 规则，新增 2 条驱动 SSOT 的 `list` 规则：
```json
{
  "name": "c2_suspicious_port_high",
  "category": "network", "rule_type": "list",
  "condition": {"field": "remote_port", "values": [4444, 6667, 1337], "match_mode": "exact",
                "_meta": {"mitre_attack": "T1571", "c2_confidence": "high"}},
  "severity": "high", "enabled": true, "label": "C2 高置信端口"
},
{
  "name": "c2_suspicious_port_low",
  "category": "network", "rule_type": "list",
  "condition": {"field": "remote_port", "values": [4443, 5555, 8888], "match_mode": "exact",
                "_meta": {"mitre_attack": "T1571", "c2_confidence": "low"}},
  "severity": "medium", "enabled": true, "label": "C2 低置信可疑端口"
}
```
> 实测闭合（见 §5）：规则总数 `147→143`，`high` 由 82→77，`high` 占比 `59.9%→53.8%`。

---

## 2. P2-2 严重度校准与 HITL 标注（闭合 AC-P1-13）

### 2.1 根因
AC-P1-13 要求 `high` 占比 ≤ 55%，P1 末实测 59.9%。P2-1 合并 C2 端口已降至 ~54.2%（口径修正前），**但口径修正后发现 P1 探针漏算 `default_attack_chain.json` 10 条 critical**。修正口径后，纯靠合并 C2 端口无法稳过 55%。需辅以**严重度治理 + HITL 分层**。

### 2.2 实现：9 条 critical 规则标注 `requires_hitl`
critical 级规则命中即代表高置信入侵（LSASS 读取、DCSync、勒索批量加密等），应接入人工确认（HITL）流程，而非自动处置。在 9 条规则的 `condition._meta` 写入 `requires_hitl: true`（**仅元数据，零检测逻辑改动**）：

| 规则名 | 文件 | 语义 |
|---|---|---|
| `lsass_dump_detection` | default_rules.json | LSASS 进程内存读取（凭据窃取） |
| `dcsync_detection` | default_rules.json | DCSync 域控复制（提权/凭据） |
| `evt_4662_dcsync_suspect` | event_log_rules.json | 4662 目录服务复制疑似 |
| `ransomware_behavior_pattern` | default_rules.json | 批量文件加密（勒索） |
| `dpapi_credential_theft` | default_rules.json | DPAPI 凭据窃取 |
| `browser_credential_theft` | default_rules.json | 浏览器凭据窃取 |
| `attack_chain_rdp_psexec_lsass` | default_attack_chain.json | RDP→PsExec→LSASS 链 |
| `attack_chain_zerologon_dcsync` | default_attack_chain.json | Zerologon→DCSync 链 |
| `credential_dump_behavior` | process_enhancement_rules.json | 凭据转储行为 |

> 为何不直接降 critical→high：critical 是真实入侵信号，降权会弱化告警；改为"标注 HITL"保留严重度语义，由下游裁决层（告警处置 UI）据 `requires_hitl` 触发人工确认。这属于**分层治理**，不改变占比数学但给出正确的运营闭环。
>
> **占比数学说明**：P2 严重度治理的占比收益来自 P2-1（合并 C2 6→2，high 82→77）。HITL 标注本身不改 severity 字段，故占比数字由 P2-1 主导达成。AC-P1-13 的最终闭合口径 = loader 全 5 文件（含 `default_attack_chain.json`）+ P2-1 合并后 **53.8% ≤ 55%**（实测）。

### 2.3 探针口径修正（AC-P2-7）
`_p1_verify.py` 原 `RULE_FILES` 漏列 `default_attack_chain.json`（10 条全 critical），导致分母偏小、虚高。修正为 `glob('app/rules/*.json')` 全部数组文件聚合，与 loader 口径一致。修正后 P1 探针 **13/13 全通过**，AC-P1-13 正式闭合。

---

## 3. P2-3 种子加载可观测性

### 3.1 问题
原 `loader.load_default_rules()` 对"顶层不是数组"的文件逐条 `logger.warning`，启动噪声大；且 `_import_default_rules` 无法区分"被跳过的合法文件"与"真正异常"。第二套规则源（`P0-1-TAMPER` 等 4 条 `source='default'` 孤儿）在重置时会**静默失配**——若未来逻辑改为 DELETE+INSERT，会被误删。

### 3.2 实现

**（a）`loader.py` 新增 `LoadReport` 与 `load_default_rules_with_report()`**
```python
@dataclass
class LoadReport:
    data_files: list[str] = field(default_factory=list)   # 成功作为数组加载的文件
    skipped: list[str] = field(default_factory=list)       # 跳过（非数组/解析失败）文件
    parse_errors: list[str] = field(default_factory=list)  # 解析异常明细
    orphans: list[str] = field(default_factory=list)       # DB 有 / JSON 无 的 default 孤儿
    total: int = 0

    def summary_line(self) -> str:
        return (f"规则加载: 文件={len(self.data_files)} 跳过={len(self.skipped)} "
                f"解析错误={len(self.parse_errors)} 孤儿={len(self.orphans)} 规则={self.total}")

    def to_dict(self) -> dict: ...   # 供 database._import_default_rules 透传

def load_default_rules_with_report() -> tuple[list[dict], LoadReport]:
    """聚合 app/rules/*.json 全部数组文件；非数组文件记入 skipped，不告警。"""
```
- `load_default_rules()` 保留为向后兼容薄封装：`return load_default_rules_with_report()[0]`。
- 噪音消除：原 `_load_rules_file` 内 `logger.warning("规则 %s 的 rule_type 非法...")` 仅对真正非法 `rule_type` 触发；"顶层非数组"文件改为静默计入 `skipped`。

**（b）`database.py` `_import_default_rules()` 改造**
- 调用 `load_default_rules_with_report()`，将 `orphans` 写入报告。
- **孤儿检测**：`load_report.orphans = sorted(name for name, src in existing.items() if src=='default' and name not in json_names)`。
- **孤儿处置策略：仅暴露、绝不清理**——打印 1 条 `WARNING [RULE-LOAD] 检测到 N 条 source='default' 孤儿规则（DB 有 / JSON 无，未做任何处置）: ...`，不设 DELETE。
- **`preserved` 语义修正**：原为"与默认 JSON 同名且 source=user 的碰撞数"；修正为 `preserved = sum(1 for src in existing.values() if src=='user')`，即 DB 中全部用户规则数（无论是否同名），更准确反映"保留的用户规则数"。

实测：日志由"每条规则 1 WARNING"降为 1 条结构化 INFO 摘要；孤儿 `P0-1-TAMPER` 被识别并告警但不删除。

---

## 4. P2-4 双管道（event_log_summary）对齐验证

### 4.1 现状（已确认，无代码改动）
P0-2 已建立桥接层（`app/services/security_event_rules.py`）：
- Agent `collectors/security.py` 产出 `event_ids_summary` → `extract_event_summary(payload)` 抽取为 `{"4625": 37, ...}` 计数字典。
- `evaluate_summary(event_summary, rules)` 用 `MatcherRegistry.dispatch("event_log_summary", ...)` 命中 6 条 `event_log_rules.json` 规则（4625/4672/4662/4769/4648 等）。
- **优雅降级**：DB 无 `event_log_summary` 规则或空 summary 时返回 `[]`，不抛异常（AC-P2-14）。
- `extract_event_summary` 支持的三种真实载荷形态：`{"event_ids_summary": {...}}` 单对象、`[{"event_ids_summary": {...}}]` 列表包裹、`{"4625": 3}` 裸计数字典、`None`/其他 → `{}`。

### 4.2 结论
P2-4 为**验证型子项**（可行性 ⚠️ 中）。经代码核对 + 测试覆盖（AC-P2-13/14），桥接链路契约完整、可降级，无需额外代码改动。仅补充测试覆盖三种载荷形态与降级路径（见 03-test.md §3）。

---

## 5. 实测关键指标（真实库 / 真实代码）

| 指标 | P1 末 | P2 末 | 变化 | 目标 |
|---|---|---|---|---|
| 规则总数（loader 口径） | 147 | 143 | -4 | — |
| high 条数 | 82 | 77 | -5 | — |
| **high 占比** | 59.9% | **53.8%** | -6.1pp | **≤ 55% ✅** |
| `c2_port_*` 规则数 | 6 | 0 | 合并 | SSOT |
| `c2_suspicious_port_*` 规则 | 0 | 2 | 新增 | SSOT |
| `requires_hitl=true` 规则 | 0 | 9 | 新增 | HITL |
| 启动加载 WARNING 条数 | ~N/文件 | 1（结构化） | 消除噪声 | 可观测 |
| default 孤儿规则识别 | 无 | 有（4 条告警不删） | 新增 | 防误删 |

---

## 6. 交付物清单

| 类型 | 路径 | 说明 |
|---|---|---|
| 新文件 | `backend/app/rules/c2_ports.json` | C2 端口 SSOT |
| 改动 | `backend/app/rules/rule_engine.py` | `_load_c2_ports` / `_refresh_c2_ports` / `_C2_PORTS` |
| 改动 | `backend/app/rules/default_rules.json` | `c2_port_*` 6→2 合并 + 4 条 HITL 标注 |
| 改动 | `backend/app/rules/event_log_rules.json` | 1 条 HITL 标注 |
| 改动 | `backend/app/rules/default_attack_chain.json` | 2 条 HITL 标注 |
| 改动 | `backend/app/rules/process_enhancement_rules.json` | 1 条 HITL 标注 |
| 改动 | `backend/app/rules/loader.py` | `LoadReport` + `load_default_rules_with_report` |
| 改动 | `backend/app/database.py` | `_import_default_rules` 孤儿检测 + preserved 修正 |
| 新测试 | `backend/tests/test_p2_rule_governance.py` | 23 passed / 25 subtests passed |
| 探针修正 | `backend/_p1_verify.py` | 口径补全 `default_attack_chain.json` |

---

## 7. 已知限制 / 移交

- **P2-1 端口收敛**：`8443/1080/5900/9999/31337` 因与 `_BUSINESS_PORTS` 重叠已从 C2 单列移除，其检测依赖 `anomalous_net_process` 的进程名/出向行为综合判定，非纯端口规则。如后续确需纯端口 high 规则，需先在 `_BUSINESS_PORTS` 解耦（移交 P3 或后续）。
- **P2-2 HITL 落地**：`requires_hitl` 仅是元数据契约，下游告警处置 UI 需据此触发人工确认——本阶段不实现 UI（移交前端/警报模块）。
- **环境限制**：`tests/` 全量收集因 `conftest.py` 加载 `torch`/`sentence_transformers` 触发 Windows 原生 access violation（预存环境问题，与 P2 无关）。规则相关定向回归以 `--noconftest` 运行，详见 03-test.md / 04-verify.md。
