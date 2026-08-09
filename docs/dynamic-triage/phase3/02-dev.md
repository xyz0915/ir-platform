# 阶段三 开发文档 — 聚合稳定性（告警→聚类→events 幂等/去重）

> 隶属：应急动态取证方案 · Phase 3 / 3 · 开发环节
> 记录本阶段实际落地代码改动与实现要点。

## 1. 根因定位（实测）

- daemon 推流 `event_type='process_start'`（`agent/agent.py` 阶段一保留原始 event_type）。
- `AlertEngine.evaluate_events`（`services/alert_engine.py`）仅按 `_EVENT_RULES` 匹配
  `process_create/process_term/network_connect/...`，**不含 `process_start`** → 返回 `None` → 零告警。
- `evaluate_process_event` / `evaluate_batch_process_events` 全局无调用方（死代码）。

## 2. 改动（backend/app/services/alert_engine.py）

`evaluate_events` 重构为「按事件类型分流」的统一入口：

```python
_PROCESS_TYPES = {"process_start", "process_create", "process_term"}

def evaluate_events(self, host_id, events):
    new_alerts = []
    for event in (events or []):
        if not isinstance(event, dict):
            continue
        try:
            et = event.get("event_type", "")
            if et in _PROCESS_TYPES:
                result = self.evaluate_process_event(host_id, event)   # 命令级检测 + 去重
            else:
                result = self.process_event(host_id, event)            # 通用规则评估
            if result:
                new_alerts.append(result)
        except Exception as e:
            logger.warning("Event evaluation error: %s", e)
    return new_alerts
```

- 进程类事件 → `evaluate_process_event`：
  - 命令含 `certutil -urlcache/-split` → `EVENT-CERTUTIL-DOWNLOAD` / critical；
  - `powershell -enc` → `EVENT-PS-ENCODED` / critical；
  - `whoami/net user/ipconfig/systeminfo` → `EVENT-RECON` / medium；
  - `procdump/mimikatz` → `EVENT-CRED-DUMP` / critical；
  - 其余 → `EVENT-PROCESS-ROUTINE` / low。
  - 每条均经 `Alert.create_or_aggregate`（5 分钟窗、按 host+rule 聚合）。
- 非进程类事件 → `process_event`（通用 `_EVENT_RULES`，行为不变）。

## 3. 去重/幂等机制（既有，本阶段验证）

- `Alert.create_or_aggregate`（`models/alert.py:42`）：
  ```sql
  SELECT id, count FROM alerts
  WHERE host_id=? AND rule_name=? AND status='open'
    AND last_seen_at > datetime('now','-5 minutes')
  ```
  命中 → `UPDATE count=count+1, last_seen_at=now`；未命中 → `Alert.create(...)`。
- 这是防告警风暴的核心：同一 (host, rule) 在 5 分钟内无论来多少事件，都归一到单条告警。

## 4. 聚类（既有，本阶段验证）

- `IncidentCorrelator._cluster_keyword(alerts)`：纯函数，按 `rule_name` 分组 + 攻击链阶段映射，
  相同输入产出确定性分组（测试 T8 验证）。
- semantic 模式（`_cluster_semantic`）按需触发，产出 `incident_clusters`，非 daemon 流持续写入。

## 5. 未改动项（明确标注）

- `Alert` 模型 / `create_or_aggregate`：逻辑已正确，仅验证，未改动。
- `IncidentCorrelator`：聚类逻辑已确定，仅验证，未改动。
- `evaluate_batch_process_events`：与 `evaluate_events` 新逻辑重叠，标记为冗余保留（无外部调用方）。

## 6. 影响面评估

- `process_events.py:70` 仍调用 `engine.evaluate_events(host_id, payload)`（未改），但因其内部已分流，
  daemon 进程事件现可正确告警——**无需改动端点即可修复管道断点**。
- 导入包中的 `process_create` 事件现同样走命令级评估，行为一致、无回归。
