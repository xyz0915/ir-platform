# 案件详情数据扩充（P0+P1）— 设计文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 设计阶段（Design） |
| **负责人** | 应急研判组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联方案** | 应急专家视角的「案件详情数据补充方案」：P0=告警态势/受影响资产态势/响应时间线/基础信息扩充；P1=处置闭环进度/动态取证进度/威胁指标 IOC/攻击链 TTP；P2（顺带）=AI 分析结论 |

---

## 1. 背景与问题陈述

### 1.1 现状（代码实证）
- 原 `CaseDetailView.vue` 仅展示案件基础字段 + 主机列表，研判所需的关键态势数据缺失：看不到**派生严重度**、**告警分布**、**受影响资产风险排名**、**处置/取证进度**、**IOC/TTP**、**时间线**。
- 案件严重度在 `cases` 表中无独立字段，需由关联告警推导；原前端无从获取。
- 告警（`alerts`）、取证（`triage_tasks`）、IOC 命中（`ioc_hits`）等数据分属不同表，且 `triage_tasks`/`ioc_hits` 仅带 `host_id`，需经 `hosts` 关联回案件（`case_id`），前端逐接口拉取会产生多次往返且需自行 JOIN。

### 1.2 应急专家研判缺口
应急人员打开案件详情时必须一眼回答 5 个问题：
1. 这事多严重？（`derived_severity`）
2. 发生了什么？（`alert_stats` / `top_alerts`）
3. 影响了哪些资产？（`host_stats` / `ioc_summary` / `ttp_summary`）
4. 处置到哪一步了？（`remediation_progress` / `triage_progress`）
5. 时间线怎么走的？（`timeline`）

---

## 2. 设计目标与验收标准（AC）

| 编号 | 验收标准 | 优先级 | 说明 |
| --- | --- | --- | --- |
| AC-1 | 新增后端聚合接口 `GET /api/cases/{id}/summary`，单连接内一次性返回全部卡片数据 | P0 | 避免前端 N 次往返 |
| AC-2 | **派生严重度** `derived_severity` = 关联告警最高严重度，忽略 `status='dismissed'` | P0 | 无告警时为 `none` |
| AC-3 | **告警态势**：告警总数 / 按严重度分布 / 按状态分布 + Top 8 告警（按严重度+次数排序） | P0 | 覆盖 P0「告警态势卡」 |
| AC-4 | **受影响资产态势**：主机总数 / 状态分布 / 在线 Agent 数 / 风险 Top5 主机（以 IOC 命中数为风险代理） | P0 | 覆盖 P0「受影响资产态势」 |
| AC-5 | **响应时间线**：案件级里程碑（创建/首批主机接入/首次告警/取证启动/取证完成/处置更新/最近更新）按时序排列 | P0 | 覆盖 P0「响应时间线」 |
| AC-6 | **处置闭环进度**：解析 `remediation_checklist.items` JSON，计算 done/total/percent + 明细样本 | P1 | 覆盖 P1「处置闭环进度」 |
| AC-7 | **动态取证进度**：`triage_tasks` 状态分布（pending/running/done/failed/total） | P1 | 覆盖 P1「动态取证进度」 |
| AC-8 | **威胁指标 IOC**：`ioc_hits` 关联 `iocs` 与 `threat_intel`，回灌情报（provider/risk_score/judgments/threat_level/attck） | P1 | 覆盖 P1「威胁指标 IOC」 |
| AC-9 | **攻击链/TTP**：`kill_chain` 来自 `security_events.attack_stage`；`techniques` 聚合自 `threat_intel.attck` JSON | P1 | 覆盖 P1「攻击链 TTP」 |
| AC-10 | **AI 分析结论**（P2 顺带）：解析 `security_events.ai_analysis` JSON，取最高 `risk_score` 结论（risk_score/attack_chain/recommendation/latest_at） | P2 | 覆盖 P2「AI 分析结论」 |
| AC-11 | **前端 `CaseDetailView.vue` 多卡片重做**：保留主机列表 + 批量 AI 对比对话框，新增基础信息/告警/资产/时间线/处置/取证/IOC/TTP/AI 卡片，调用 summary 接口渲染 | P0+P1 | 前端落地 |

---

## 3. 架构设计

### 3.1 聚合服务（SSOT for 案件态势）
```
GET /api/cases/{id}/summary
   │
   ▼
app.services.case_summary.get_case_summary(case_id)
   │  单 DB 连接（with get_connection() as conn）
   │
   ├─ _case_host_ids()          hosts WHERE case_id=?  → 案件内主机 id 列表
   ├─ _derived_severity()       alerts 最高严重度（忽略 dismissed）
   ├─ _alert_section()          alert_stats + top_alerts（Top8）
   ├─ _host_section()           主机总数/状态/在线 Agent/风险 Top5
   ├─ _remediation_section()    处置进度（解析 items JSON）
   ├─ _triage_section()         取证进度（状态计数）
   ├─ _ioc_section()            ioc_hits → iocs → threat_intel（回灌 intel）
   ├─ _ttp_section()            kill_chain(attack_stage) + techniques(attck)
   ├─ _ai_section()             security_events.ai_analysis 最高分结论
   └─ _timeline()               案件里程碑（自构建，非 TimelineBuilder）
```

设计要点：
- **单连接一致性**：所有聚合在 `with get_connection() as conn` 内完成，避免多连接下数据漂移。
- **参数化 IN 子句**：`_in_clause(ids)` 生成 `?,?...` 占位符，彻底规避 SQL 注入与绑定数不匹配（`_derived_severity` 曾因漏传 `host_ids` 触发 `ProgrammingError`，详见测试文档 D-1）。
- **案件级时间线自建**：`TimelineBuilder.build` 面向单主机原始 JSON，不适用案件级聚合，故 `_timeline()` 自行查询里程碑时间并排序。

### 3.2 关系链（数据来源实证）
| 数据 | 主表 | 关联键 | 经由 |
| --- | --- | --- | --- |
| 案件 | `cases` | `id` | 直接 |
| 主机 | `hosts` | `case_id` | 直接 |
| 告警 | `alerts` | `host_id` | `hosts` → `case_id` |
| 处置清单 | `remediation_checklist` | `case_id` | 直接 |
| 取证任务 | `triage_tasks` | `host_id` | `hosts` → `case_id` |
| IOC 命中 | `ioc_hits` | `host_id` | `hosts` → `case_id` |
| 威胁情报 | `threat_intel` | `ioc_id` | `iocs` → `ioc_hits` |
| 攻击阶段/AI | `security_events` | `host_id` | `hosts` → `case_id` |

### 3.3 派生严重度算法
```
SEVERITY_RANK = {critical:4, high:3, medium:2, low:1, info:0, none:0}
derived_severity = max(SEVERITY_RANK[a.severity] for a in alerts WHERE status != 'dismissed')
                 → 反查等级名；无主机/无告警 → 'none'
```

---

## 4. 接口定义

### `GET /api/cases/{id}/summary`
- **鉴权**：`Depends(get_current_user)`
- **成功**：`{"code":0,"data":{...},"message":"success"}`，`data` 结构见 §3.1 各 section。
- **404**：案件不存在 → `{"detail":"案件不存在"}`。
- **路由顺序**：`main.py` 中 `case_hosts.router`(prefix `/api`) 注册于 `cases.router`(prefix `/api/cases`) 之前；summary 路由用 `{case_id}/summary` 静态前缀，不与 `/{case_id}` 冲突。

### 响应 `data` 关键字段
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `case.derived_severity` | str | 派生严重度 |
| `case.priority` | str | 案件优先级（原表已有列） |
| `alert_stats.{total,by_severity,by_status}` | obj | 告警态势 |
| `top_alerts[]` | list | Top8 告警 |
| `host_stats.{total,by_status,online_agents,risk_top}` | obj | 资产态势 |
| `timeline[]` | list | 里程碑事件 |
| `remediation_progress.{done,total,percent,items}` | obj | 处置进度 |
| `triage_progress.{pending,running,done,failed,total}` | obj | 取证进度 |
| `ioc_summary[]` | list | IOC + 情报回灌 |
| `ttp_summary.{kill_chain,techniques}` | obj | 攻击链/TTP |
| `ai_summary.{risk_score,attack_chain,recommendation,latest_at}` | obj | AI 结论（P2） |

---

## 5. 关键决策与偏离说明
- **不新增数据库列**：`derived_severity` 与全部统计均为查询期派生，不改动 `cases`/`hosts`/`alerts` 等任何表结构，回归安全。
- **风险 Top 主机以 IOC 命中数为代理**：无独立风险分模型时，用 `ioc_hits` 计数作为主机风险排序代理指标（可解释、可追溯）。
- **AI 结论取最高分样本**：`security_events.ai_analysis` 可能有多条，取 `risk_score` 最高者作为卡片结论，避免信息过载。
- **P2 顺带实现**：AI 分析结论改动与 P0+P1 同链路，成本极低，故一并实现（AC-10）。
