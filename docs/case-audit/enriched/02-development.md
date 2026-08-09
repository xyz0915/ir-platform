# 案件详情数据扩充（P0+P1）— 开发文档

| 字段 | 内容 |
| --- | --- |
| **阶段** | 开发阶段（Development） |
| **负责人** | 应急研判组（WorkBuddy 代理执行） |
| **日期** | 2026-08-10 |
| **版本号** | v1.0.0 |
| **关联设计** | `docs/case-audit/enriched/01-design.md` (v1.0.0) |

---

## 1. 代码结构说明

```
backend/app/
├── services/
│   └── case_summary.py         # 新增：案件详情聚合服务（单连接内 9 段聚合）
└── api/
    └── cases.py                # 在 GET /{case_id} 之前新增 GET /{case_id}/summary

backend/tests/
└── test_case_summary.py        # 新增：9 例隔离单元测试

frontend/src/
├── api/
│   └── cases.js                # 新增 summary(id) 调 GET /cases/{id}/summary
└── views/
    └── CaseDetailView.vue      # 重写：保留主机列表+批量AI对比，新增 9 张卡片
```

> 未改动任何数据库表结构；未改动 `main.py` 路由注册逻辑（仅依赖既有注册顺序）。

---

## 2. 实现记录（按 AC 映射）

### AC-1 聚合接口 `GET /api/cases/{id}/summary`
- `app/api/cases.py:90-105` 新增路由。函数内局部 `import` `get_case_summary`（延迟导入，避免循环依赖与 torch 全量导入）。
- 先 `CaseService.get_case(case_id)` 判空 → 404；否则调 `build_summary(case_id)`，返回 `{"code":0,"data":...,"message":"success"}`。

### AC-2 派生严重度 `derived_severity`
- `case_summary._derived_severity(conn, host_ids)`：`SELECT severity FROM alerts WHERE host_id IN (...) AND status != 'dismissed'`，取 `SEVERITY_RANK` 最大值反查等级名。
- 无主机或无告警返回 `'none'`。

### AC-3 告警态势（P0）
- `_alert_section`：返回 `alert_stats`（total / by_severity / by_status）+ `top_alerts`（按 `SEVERITY_RANK` 与 `count` 倒序取前 8，字段含 `rule_label/severity/status/source_process/source_ip/count/时间`）。

### AC-4 受影响资产态势（P0）
- `_host_section`：主机总数、状态分布；在线 Agent 经 `agents JOIN hosts WHERE case_id=? AND status='online'`（去重计数）；风险 Top5 主机以 `ioc_hits` 计数作 `risk_score` 代理。

### AC-5 响应时间线（P0）
- `_timeline`：自构建案件里程碑——创建（`cases.created_at`）、首批主机接入（`MIN(hosts.collection_time)`）、首次告警（`MIN(alerts.first_seen_at)`）、取证启动（`MIN(triage_tasks.started_at)`）、取证完成（`MAX(triage_tasks.finished_at)`）、处置更新（`MAX(remediation_checklist.updated_at)`）、最近更新（`cases.updated_at`）；按时间排序。

### AC-6 处置闭环进度（P1）
- `_remediation_section`：遍历 `remediation_checklist.items` JSON（每个 case 一行，`_safe_json` 解析为列表），逐条计 `checked`，算 done/total/percent，取前 12 条作样本。

### AC-7 动态取证进度（P1）
- `_triage_section`：`triage_tasks` 按 `status` 分组计数 → pending/running/done/failed/total。

### AC-8 威胁指标 IOC（P1）
- `_ioc_section`：`ioc_hits` 按 `(ioc_type,ioc_value,host_id)` 聚合；VALUE 集合去重后 `(ioc_type,ioc_value) IN (...)` 关联 `iocs` 取 `ioc_id`；再用 `ioc_id IN (...)` 关联 `threat_intel`（经 `ThreatIntel._row_to_dict`），把 `provider/risk_score/judgments/threat_level/attck` 回灌每条 IOC（`intel` 字段，无情报则 `None`）。
- 函数同时返回 `intel_by_ioc` 供 TTP 聚合复用。

### AC-9 攻击链/TTP（P1）
- `_ttp_section`：`kill_chain` 来自 `security_events.attack_stage` 分组计数（标签经 `ATTACK_STAGE_LABELS` 翻译）；`techniques` 聚合自 `intel_by_ioc` 中每条情报的 `attck`（JSON 列表，支持 dict/字符串），按出现次数倒序。

### AC-10 AI 分析结论（P2 顺带）
- `_ai_section`：`security_events.ai_analysis` 非空者按 `timestamp` 倒序取前 10，解析 JSON，取 `risk_score`（兼容 `riskScore`）最高者，返回 `risk_score/attack_chain/attackChain/recommendation/summary/latest_at`。

### AC-11 前端多卡片重做
- `cases.js` 新增 `summary(id)`。
- `CaseDetailView.vue`：
  - `onMounted` 调 `loadCase()` + `loadHosts()` + `loadSummary()`；`loadSummary` 调 `casesApi.summary(route.params.id)` 写入 `summary.value`。
  - 卡片：①基础信息（优先级/派生严重度/资产数）；②告警态势（by_severity 彩色分布 + by_status + Top8 表格）；③受影响资产态势（总数/状态/在线 Agent + 风险 Top5）；④响应时间线（el-timeline，按 `timelineType` 着色）；⑤处置闭环进度（el-progress + 明细）；⑥动态取证进度（pending/running/done/failed 统计）；⑦威胁指标 IOC（表格含情报回灌）；⑧攻击链/TTP（kill_chain 标签 + techniques 列表）；⑨AI 分析结论（risk_score 标签 + attack_chain + recommendation）。
  - 辅助函数：`sevLabel/sevType/sevColor`、`priorityLabel/priorityType`、`alertStatusLabel/alertStatusType`、`hostStatusLabel`、`triageLabel`、`timelineType`、`aiRiskType`；枚举 `SEVERITY_ORDER`、`ALERT_STATUS_ORDER`。
  - 保留：原主机列表表格 + 添加主机对话框 + 批量 AI 对比分析对话框（风险评估/威胁模式/攻击路径对比）。

---

## 3. 关键决策与偏离说明
- **延迟导入聚合服务**：`cases.py` 内 `from app.services.case_summary import ...` 置于函数体内，避免与 `case_service`/`auth_service` 等模块的潜在环形依赖，并规避模块级导入触发 torch 全量收集（既有 `--noconftest` 环境限制，详见测试文档 §5）。
- **IN 子句参数化**：`_in_clause(ids)` 统一生成占位符，所有 `IN (...)` 查询均显式传参，修复了早期漏传 `host_ids` 导致的 `ProgrammingError`。
- **未新增表/列**：全部为查询期派生，零表结构变更，保证既有套件与运行库兼容。

---

## 4. 未变更项（回归安全）
- 数据库表结构（cases/hosts/alerts/triage_tasks/ioc_hits/iocs/threat_intel/security_events/remediation_checklist/agents）均不变。
- `main.py` 路由注册顺序不变，summary 路由为静态前缀不冲突。
- `CaseDetailView.vue` 的主机列表与批量 AI 对比对话框交互保持不变。
