# 服务检测引擎统一到规则管理 — 架构设计方案

> 作者：高见远（架构师）
> 日期：2026-07-12
> 版本：v1.0

---

## 1. 需求摘要

当前 IR 平台的服务检测模块（`ServiceRiskAnalyzer`）是一个完全独立的硬编码孤岛，仅内置 4 条检测规则，不走 `RuleEngine` 统一评估流程。用户要求将服务检测统一到规则引擎中，实现规则的可配置、可扩展、可审计；同时从应急专家视角大幅扩展检测维度，覆盖从急救必检（P0）到深度排查（P1）再到高级威胁（P2）的多层级攻击面。

核心目标：
1. 将服务检测逻辑从硬编码迁移到 `RuleEngine.evaluate()` 驱动的规则体系
2. 新增 `backend/app/rules/service_detection_rules.json`，category=`service`，≥18 条规则
3. `AnomalyDetector` 新增 `detect_services()` 方法，遵循与 `detect_processes()`/`detect_connections()` 一致的模式
4. 旧 `ServiceRiskAnalyzer` 保留但标记为废弃，核心防护能力通过 behavior patterns 迁移到引擎侧

---

## 2. 架构方案

### 2.1 规则文件设计

新建文件：`backend/app/rules/service_detection_rules.json`

规则 JSON 遵循既有 schema（name/category/rule_type/condition/severity/enabled/label/description），category 统一为 `service`，支持 `behavior`、`list`、`composite`、`regex`、`threshold`、`exists` 六种类型。以下为 3 条代表性示例，完整规则清单见第 3 节。

#### 示例 1：behavior 类型 — 无签名驱动检测（P0）

```json
{
  "name": "unsigned_service_driver",
  "description": "检测未签名的内核驱动服务（非 Microsoft 签名），应急场景首要排查指标",
  "category": "service",
  "rule_type": "behavior",
  "condition": {
    "pattern": "unsigned_service_driver",
    "description": "内核驱动服务无有效数字签名或签名为非 Microsoft"
  },
  "severity": "critical",
  "enabled": true,
  "label": "无签名驱动服务",
  "mitre_attack": "T1543.003"
}
```

#### 示例 2：list 类型 — 异常 ImagePath 扩展名（P0）

```json
{
  "name": "suspicious_imagepath_extension",
  "description": "检测服务 ImagePath 使用脚本/非标准可执行扩展名（.bat/.ps1/.vbs/.js/.hta/.py），典型的持久化/提权手法",
  "category": "service",
  "rule_type": "list",
  "condition": {
    "field": "imagepath_ext",
    "values": [".bat", ".ps1", ".vbs", ".js", ".hta", ".py", ".cmd", ".wsf", ".vbe", ".jse"],
    "match_mode": "exact"
  },
  "severity": "critical",
  "enabled": true,
  "label": "异常 ImagePath 扩展名",
  "mitre_attack": "T1543.003"
}
```

#### 示例 3：composite 类型 — 交互式桌面服务（P0）

```json
{
  "name": "interactive_desktop_service",
  "description": "检测同时满足 SERVICE_INTERACTIVE_PROCESS 标志且以 SYSTEM 权限运行的高风险服务",
  "category": "service",
  "rule_type": "composite",
  "condition": {
    "logic": "AND",
    "sub_rules": [
      {
        "type": "list",
        "field": "service_type",
        "values": ["interactive", "SERVICE_INTERACTIVE_PROCESS"],
        "match_mode": "contains"
      },
      {
        "type": "list",
        "field": "user",
        "values": ["LocalSystem", "NT AUTHORITY\\SYSTEM", "SYSTEM"],
        "match_mode": "contains"
      }
    ]
  },
  "severity": "critical",
  "enabled": true,
  "label": "交互式桌面服务（SYSTEM 权限）",
  "mitre_attack": "T1543.003"
}
```

### 2.2 新增 behavior pattern 清单

在 `rule_engine.py` 的 `BEHAVIOR_PATTERNS` 集合（第 39-80 行）中注册以下 11 个全新服务检测行为模式，并在 `_match_behavior()` 的 if-elif 链中追加对应的 `_match_*()` 静态方法：

| # | pattern 名称 | 说明 | 优先级 |
|---|-------------|------|--------|
| 1 | `unsigned_service_driver` | 内核驱动服务无有效数字签名 | P0 |
| 2 | `binary_missing_service` | 服务 ImagePath 指向的可执行文件不存在 | P0 |
| 3 | `error_recovery_suspicious` | 失败恢复命令指向 Temp/AppData/脚本解释器 | P0 |
| 4 | `dllhost_hijack` | DllHost.exe 注册为服务宿主（COM 劫持变种） | P1 |
| 5 | `service_description_spoof` | 服务描述与已知系统服务混淆（伪装可信描述） | P1 |
| 6 | `multi_service_same_binary` | ≥3 个不同服务名指向同一 ImagePath | P1 |
| 7 | `registry_hidden_service` | 服务注册表键安全描述符异常（SDDL 权限过高或隐藏） | P1 |
| 8 | `start_type_anomaly` | 安全服务启动类型从自动变为禁用/手动（时间线变更检测） | P1 |
| 9 | `driver_impersonation` | 设备驱动伪装为用户态服务/已知良性驱动名 | P1 |
| 10 | `dependency_hijack` | 服务依赖项指向缺失/可疑 DLL 或驱动 | P2 |
| 11 | `svchost_injection` | SVCHOST 托管服务 DLL 路径不在 `%SystemRoot%\System32` 或 `ServiceDll` 值异常 | P2 |

> **注**：`new_service_timeline`（新增服务时间线）、`wmi_event_subscription`（WMI 事件订阅）、`binary_replacement`（二进制替换）三条 P1/P2 方向因依赖进程快照间 diff 或 WMI 事件日志采集，当前 Agent 采集中无对应字段。本次暂以 `regex`/`list`/`composite` 规则先行覆盖其核心特征（如通过 service_timeline_diff 字段检测新增服务，见规则清单 SRV-012）；完整实现待 Agent 采集补齐后升级为 behavior 模式。

### 2.3 detect_services() 签名和流程

在 `AnomalyDetector`（`backend/app/analysis/anomaly_detector.py`）中新增方法，与 `detect_processes()` 保持同构：

```python
@staticmethod
def detect_services(raw_data: dict, rules: list) -> list:
    """检测异常系统服务（统一规则引擎驱动）.

    从 raw_data 提取服务列表，筛选 category='service' 规则，
    通过 RuleEngine.evaluate 执行匹配，使用累加评分聚合。

    Args:
        raw_data: Agent JSON 数据.
        rules: 全量规则列表（调用方提前通过 RuleEngine.load_rules 加载并过滤）.

    Returns:
        异常服务列表（含 severity/risk_score/matched_rules 字段）.
        老 Agent 无 services 键时返回空列表（向后兼容）.
    """
    # 1. 提取服务数据 — 复用 ServiceRiskAnalyzer._extract_services() 的标准化逻辑
    services = ServiceRiskAnalyzer._extract_services(raw_data)
    if not services:
        return []

    # 2. 预计算衍生字段（供 rule condition.field 引用）
    for svc in services:
        # imagepath_ext: 从 path 提取扩展名
        path = svc.get("path", "")
        _, ext = os.path.splitext(path.split(" ")[0])  # 取第一个空格前的路径扩展名
        svc["imagepath_ext"] = ext.lower()
        # service_dll: 从 path 提取 SVCHOST -k 参数对应的实际 DLL
        svc["service_dll"] = _extract_service_dll(path, svc.get("name", ""))

    # 3. 筛选 category='service' 规则
    service_rules = [r for r in rules if r.get("category") == "service"]

    # 4. 规则引擎评估
    global_context = {
        "all_services": services,           # 供多服务关联规则（如 multi_service_same_binary）
        "service_name_index": _build_service_name_index(services),  # name → index
    }
    matches = RuleEngine.evaluate(services, service_rules, global_context=global_context)

    # 5. 累加评分聚合（复用 AnomalyDetector._apply_category_scoring 或新建聚合函数）
    return AnomalyDetector._apply_category_scoring(matches, group_key="name")
```

**流程对照**：

| 步骤 | detect_processes | detect_services（新增） |
|------|------------------|------------------------|
| 数据提取 | raw_data.get("processes") | ServiceRiskAnalyzer._extract_services(raw_data) |
| 规则过滤 | category in ("process","behavior","execution") | category == "service" |
| 全局上下文 | process_map, all_items, ancestor_map, connections | all_services, service_name_index |
| 规则匹配 | RuleEngine.evaluate(processes, process_rules, ctx) | RuleEngine.evaluate(services, service_rules, ctx) |
| 结果聚合 | _apply_accumulated_scoring() | _apply_category_scoring(group_key="name") |

### 2.4 analysis_service.py 改动点

文件：`backend/app/services/analysis_service.py`

**改动 1**（第 205-214 行区域）：将 `Step 5.5` 替换为调用 `AnomalyDetector.detect_services()`：

```python
# 旧代码 (当前):
# 5.5 系统服务风险检测
try:
    from app.analysis.service_risk_analyzer import ServiceRiskAnalyzer
    service_risks = ServiceRiskAnalyzer.analyze(raw_data, host_id)
    ...
except Exception:
    service_risks = {...}

# 新代码:
# 5.5 系统服务风险检测（规则引擎驱动）
try:
    svc_anomalies = AnomalyDetector.detect_services(raw_data, rules)
    # 转换 outputs 为 findings.service_risks 兼容格式
    service_risks = _convert_service_anomalies_to_findings(svc_anomalies)
    logger.info("Service risk analysis: %d services, %d anomalies",
                len(svc_anomalies), ...")
except Exception as exc:
    logger.warning("服务风险检测失败: %s", exc)
    service_risks = {"services": [], "aggregate_score": 0, "summary": {"total": 0, "high_risk_count": 0}}
```

> 注：`_convert_service_anomalies_to_findings()` 需要将 `AnomalyDetector.detect_services()` 返回的 `{severity, risk_score, matched_rules}` 结构转换为 `findings.service_risks` 期望的 `{services: [{风险详情}], aggregate_score, summary}` 格式，保持与 `RiskAssessor`（`risk_assessor.py:108-115`）的兼容。

**改动 2**（第 864-877 行）：`get_service_risk()` 方法同步切换到规则引擎路径，或保留旧版作为回退。

### 2.5 兼容性策略

| 级别 | 措施 | 触发条件 |
|------|------|---------|
| **L1 规则驱动优先** | `AnomalyDetector.detect_services()` 走 RuleEngine | 默认路径 |
| **L2 旧版回退** | `ServiceRiskAnalyzer.analyze()` 保留，`@deprecated` 标记 | 配置开关 `USE_LEGACY_SERVICE_DETECTION=true` 或规则引擎初始化失败 |
| **L3 硬编码兜底** | 与旧版逻辑完全一致 | L2 本身也失败时（二次 try/except） |
| **配置开关** | 新增 `settings.SERVICE_DETECTION_MODE` 环境变量：`"engine"`(默认) / `"legacy"` | 灰度切换/回滚 |

**旧版保留策略**：
- `service_risk_analyzer.py`：顶部添加 `warnings.warn("...", DeprecationWarning)`，`analyze()` 方法保留原逻辑不变
- `service_constants.py`：保留不动（`SECURITY_SERVICES`、`TRUSTED_PATHS` 等常量供 behavior 模式内联引用；`SCORING_WEIGHTS` 在旧版路径下继续有效）

---

## 3. 完整规则清单

> **严重度统一**：SEVERITY_SCORES 沿用 `AnomalyDetector` 的 `critical=35 / high=20 / medium=10 / low=5 / info=1`。

### P0 — 急救必检（8 条）

| ID | 规则名 | 类型 | 严重度 | MITRE ATT&CK | 检测逻辑简述 |
|----|--------|------|--------|-------------|-------------|
| SRV-001 | `unsigned_service_driver` | behavior | critical | T1543.003 | 内核驱动服务（path 含 `.sys` / `\\drivers\\`）无有效数字签名或签名证书非 Microsoft |
| SRV-002 | `interactive_desktop_service` | composite | critical | T1543.003 | 服务属性含 `SERVICE_INTERACTIVE_PROCESS` 且以 LocalSystem/SYSTEM 身份运行（Session 0 隔离绕过的典型后门） |
| SRV-003 | `suspicious_imagepath_extension` | list | critical | T1543.003 | ImagePath 扩展名 ∈ {.bat, .ps1, .vbs, .js, .hta, .py, .cmd, .wsf, .vbe, .jse} |
| SRV-004 | `binary_missing_service` | behavior | critical | T1574.002 | ImagePath 指向的文件不存在（二进制已被删除的残留服务，常见 webshell 提权/持久化后清理痕迹） |
| SRV-005 | `error_recovery_suspicious` | behavior | critical | T1543.003 | 服务失败恢复命令（FailureCommand）指向 Temp/AppData/脚本解释器路径 |
| SRV-006 | `svchost_untrusted_dll` | behavior | critical | T1543.003 | SVCHOST 托管服务的 `ServiceDll` 值指向 `%SystemRoot%\System32` 以外的路径（DLL 劫持） |
| SRV-007 | `security_service_disabled` | behavior | critical | T1562.001 | 安全软件服务（14 个白名单内）status≠running 或 start_type∈{disabled, manual} |
| SRV-008 | `shadow_service_name` | behavior | high | T1036.004 | 服务名与 `KNOWN_LEGIT_SERVICES`(80+) 编辑距离 ≤2 且不在已知集合中（名称伪装） |

### P1 — 深度排查（7 条）

| ID | 规则名 | 类型 | 严重度 | MITRE ATT&CK | 检测逻辑简述 |
|----|--------|------|--------|-------------|-------------|
| SRV-009 | `dllhost_hijack` | behavior | high | T1543.003 | ImagePath 指向 dllhost.exe 但不在 `%SystemRoot%\System32`（COM 服务劫持） |
| SRV-010 | `service_description_spoof` | behavior | high | T1036.003 | 服务描述（display_name）与已知系统服务描述相似度 ≥0.90，但服务名不在白名单中 |
| SRV-011 | `multi_service_same_binary` | behavior | high | T1543.003 | ≥3 个不同服务名指向同一个非系统目录 ImagePath（批量注册恶意服务） |
| SRV-012 | `new_service_timeline` | threshold | high | T1543.003 | 服务安装时间晚于系统最近一次启动且不在已知合法新增服务列表中（需 `install_date` 字段） |
| SRV-013 | `start_type_anomaly` | composite | high | T1562.001 | 安全服务 start_type=disabled 或从 auto→disabled/manual 发生了变更（需 `prev_start_type` 字段） |
| SRV-014 | `registry_permission_anomaly` | behavior | high | T1574.011 | 服务注册表键 SDDL 权限允许非管理员写入（Authenticated Users / Everyone 拥有修改权限） |
| SRV-015 | `driver_impersonation` | behavior | medium | T1543.003 | 驱动服务（type=kernel）display_name 模仿已知良性驱动名称 |

### P2 — 高级威胁（4 条）

| ID | 规则名 | 类型 | 严重度 | MITRE ATT&CK | 检测逻辑简述 |
|----|--------|------|--------|-------------|-------------|
| SRV-016 | `dependency_hijack` | behavior | medium | T1574.002 | 服务依赖（DependOnService）项对应的服务不存在或状态为 disabled/absent |
| SRV-017 | `privileged_service_anomaly` | composite | medium | T1543.003 | 服务以 SYSTEM 权限运行且 ImagePath 不在可信系统目录（`C:\Windows\System32`, `C:\Windows\SysWOW64`, `C:\Program Files`） |
| SRV-018 | `service_binary_outdated` | behavior | low | T1543.003 | 服务二进制版本号低于已知最新版本（存在可利用漏洞），需 `version_info` 字段 |
| SRV-019 | `auto_start_service_suspicious` | composite | medium | T1547.001 | start_type=auto + ImagePath 不在可信目录 + 服务名不在 `KNOWN_LEGIT_SERVICES` 中 |

> **合计**：19 条规则（P0: 8, P1: 7, P2: 4），覆盖 6 种 rule_type（behavior: 12, composite: 3, list: 2, threshold: 1, regex: 1）。

---

## 4. 任务列表

任务按依赖关系排序，有明确文件:行号。

| # | 任务 | 依赖 | 落地点 | 说明 |
|---|------|------|--------|------|
| **T1** | 新增 `service_detection_rules.json` | 无 | `backend/app/rules/service_detection_rules.json` (新文件) | 写入 19 条规则 JSON，含完整 condition/severity/mitre_attack |
| **T2** | 注册 11 个新 behavior pattern 到 `BEHAVIOR_PATTERNS` | 无 | `rule_engine.py:39-80` | 追加 `unsigned_service_driver` 等 11 个 pattern 到集合 |
| **T3** | 追加 behavior pattern 匹配分支到 `_match_behavior()` | T2 | `rule_engine.py:1354-1397` | 在 if-elif 链末尾（`vanished_process` 之后）追加 11 个 `elif pattern == "xxx": return RuleEngine._match_xxx(...)` |
| **T4** | 实现 11 个 `_match_*()` 静态方法 | T2, T3 | `rule_engine.py` (新方法) | 各 pattern 的独立检测逻辑，可引用 `all_services`/`service_name_index` 等全局上下文 |
| **T5** | `AnomalyDetector` 新增 `detect_services()` | T1 | `anomaly_detector.py:401` (after `detect_startup_items`) | 遵循 `detect_processes` 同构模式，提取 services→过滤 rules→evaluate→聚合评分 |
| **T6** | `analysis_service.py` Step 5.5 切换到 `detect_services()` | T5 | `analysis_service.py:205-214` | 替换 ServiceRiskAnalyzer 调用为 AnomalyDetector.detect_services，保持 findings.service_risks 格式兼容 |
| **T7** | `analysis_service.py` `get_service_risk()` 同步切换 | T5 | `analysis_service.py:864-877` | API 端点 `/hosts/{host_id}/service-risk` 切换到新引擎 |
| **T8** | 标记 `ServiceRiskAnalyzer` 为废弃 | T5 | `service_risk_analyzer.py:1` (文件头) | 添加 `warnings.warn(DeprecationWarning)` 和 `@deprecated` 标记，保留原逻辑 |
| **T9** | 新增配置开关 `SERVICE_DETECTION_MODE` | T5 | `config.py` / `settings.py` | 新增环境变量，默认 "engine"，支持 "legacy" 回退 |
| **T10** | 编写 `detect_services()` 单元测试 | T1, T4, T5 | `tests/test_service_detection.py` (新文件) | 覆盖：正常命中、无数据降级、异常 ImagePath、多服务同二进制、svchost 注入等 |
| **T11** | 集成测试：端到端服务检测流程 | T6, T7, T9 | `tests/test_integration_service.py` | 使用完整 Agent JSON payload 验证从 raw_data→findings.service_risks 的完整链路 |
| **T12** | 更新 IR 平台用户手册 服务检测章节 | T1-T7 | `docs/IR平台用户手册.md` | 描述新规则体系、P0/P1/P2 分级、用户如何启用/禁用特定服务规则 |

### 依赖图

```
T1 ─┬─ T5 ─┬─ T6 ─┬─ T11
    │       │       │
T2 ─┤       ├─ T7 ──┤
T3 ─┤       │       │
T4 ─┘       ├─ T8 ──┘
            ├─ T9
            ├─ T10
            └─ T12
```

---

## 5. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/rules/service_detection_rules.json` | **新建** | 19 条 service 类别规则定义 |
| `backend/app/rules/rule_engine.py` | **修改** | BEHAVIOR_PATTERNS 追加 11 个 pattern（行 80）；`_match_behavior()` 追加 11 个 elif 分支（行 1397 之后）；新增 ~350 行 `_match_*()` 方法 |
| `backend/app/analysis/anomaly_detector.py` | **修改** | 新增 `detect_services()` 方法（~60 行，在 `detect_startup_items` 之后）；可选新增 `_build_service_name_index()` 辅助函数 |
| `backend/app/services/analysis_service.py` | **修改** | Step 5.5 区域（行 205-214）替换 ServiceRiskAnalyzer 调用；`get_service_risk()` 方法（行 864-877）同步切换 |
| `backend/app/analysis/service_risk_analyzer.py` | **修改** | 文件头添加 DeprecationWarning 标记（无需修改内部逻辑） |
| `backend/app/config.py` | **修改** | 新增 `SERVICE_DETECTION_MODE` 配置项（默认 "engine"） |
| `tests/test_service_detection.py` | **新建** | detect_services 单元测试 |
| `tests/test_integration_service.py` | **新建** | 端到端集成测试 |
| `docs/IR平台用户手册.md` | **修改** | 服务检测章节更新 |

**不修改的文件**：
- `backend/app/analysis/service_constants.py` — 常量继续被 behavior 模式和旧版共同引用
- `backend/app/api/analysis.py` — `get_service_risk` API 端点签名不变
- `backend/app/analysis/risk_assessor.py` — `findings.service_risks` 兼容格式不变

---

## 6. 风险与待确认

### 6.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| **Agent 采集字段缺失** | `install_date`/`prev_start_type`/`version_info`/`sddl` 等字段当前 Agent 可能未采集 | 对应规则以 `exists` 子条件守卫（字段不存在时跳过，不抛异常），缺数据时优雅降级（SRV-012/013/014/018 自动跳过） |
| **误报率** | 多服务同二进制、svchost 注入等在大规模企业环境可能触发大量告警 | 规则启用白名单机制：`condition.whitelist_services` 排除已知合法场景；P2 规则默认 severity=medium/low，不产生 critical 噪音 |
| **兼容性** | `findings.service_risks` 数据结构变更后下游消费方（前端仪表盘/报告生成）可能受影响 | `_convert_service_anomalies_to_findings()` 确保输出格式与旧版 `{services, aggregate_score, summary}` 完全一致 |
| **规则引擎热路径性能** | 19 条规则对每台主机的全部服务（通常 200-500 个）执行全量匹配，O(n×m) | 服务数量远小于进程（200-500 vs 1000+），且大部分规则为 O(1) 字段检查；`multi_service_same_binary` 通过 `service_name_index` 索引加速 |

### 6.2 待确认

1. **Agent 采集字段清单** — 当前 Agent JSON 中 `services` 的实际字段集合是什么？需要与 `ServiceRiskAnalyzer._extract_services()` 的字段映射对照确认
2. **SDDL 权限字段** — 注册表安全描述符是否在当前采集范围内？如暂无，SRV-014（registry_permission_anomaly）需降级或延迟上线
3. **二进制签名验证** — 引擎侧 `unsigned_exe` pattern 的签名信息来自 `file_hashes` 表 JOIN，服务检测的二进制完整性校验是否可复用同一数据源？
4. **多语言服务名称** — `KNOWN_LEGIT_SERVICES` 仅覆盖英文服务名，中文 Windows 环境下服务名可能不同；SRV-008/010 的名称伪装比对是否需要支持非 ASCII？
5. **report 模块的输出格式** — `findings.service_risks` 的 `{services, aggregate_score, summary}` 结构是否在所有下游模块中一致使用？需确认报告生成/POST API 的消费方格式预期
