# AI 事件研判打标 增量 — QA 验收清单

> 模块：生产者 `EventVerdictService` + 端点 `POST /api/security-events/ai-verdict`
> 关联：消费者 `IncidentCorrelator._fetch_suspicious_events`（只读 `json_extract(ai_verdict,'$.label')='suspicious'`）
> 设计：`docs/ai_verdict_increment_design.md`

## 1. 契约一致性（成败点）

| 检查项 | 期望 | 实现对照 |
| --- | --- | --- |
| 写回 JSON 键名 | `label` / `confidence` / `reason` / `attack_type` | `event_verdict_service._normalize` 强制 4 键 |
| `label` 取值范围 | `suspicious` / `false_positive` / `benign` / `unknown` | `ALLOWED_LABELS` 枚举校验，越界强制 `unknown` |
| 消费者读取键 | `json_extract(ai_verdict,'$.label')` | 写回 `json.dumps(verdict)`，`label` 键逐字符一致 |
| 降级兜底值 | `unknown`（非 `benign`，避免污染统计） | `degraded` / 解析失败 → `{label:"unknown",...}` |
| confidence 类型/范围 | float ∈ [0,1] | `_normalize` 浮点钳制 `round(conf,4)` |

## 2. 功能验收

| # | 场景 | 期望结果 | 自测覆盖 |
| --- | --- | --- | --- |
| 1 | 正常 LLM 返回 suspicious | `ai_verdict.label='suspicious'` 落库；`details[].status=processed` | ✅ test_normal_writeback_suspicious |
| 2 | LLM 降级 / 熔断 | `label='unknown'`；整批 2xx，绝不 500 | ✅ test_degraded_to_unknown |
| 3 | 解析失败（非 JSON） | `label='unknown'`；`status=degraded` | ✅ test_parse_failure_to_unknown |
| 4 | 幂等（force=False） | 已研判事件 `status=skipped`，不覆盖 | ✅ test_idempotent_skip_then_force_override |
| 5 | 覆盖重判（force=True） | 重新写回 `processed` | ✅ 同上 |
| 6 | 阈值降级 | `confidence<阈值` 的 suspicious → `benign` | ✅ test_threshold_downgrade_to_benign |
| 7 | 批量上限 200 | 去重后 >200 → 端点 400（非 500） | ✅ test_batch_limit_400 |
| 8 | 空 event_ids | 端点 400 | ✅ test_empty_event_ids_400 |
| 9 | 事件不存在 | 单条 `status=failed`，其余正常 | ✅ test_event_not_found_is_failed |
| 10 | 鉴权 | 无 token → 401 | ✅ test_auth_required_returns_401 |
| 11 | 路由前缀 | `/api/security-events/ai-verdict`；重复前缀 404 | ✅ test_no_duplicate_prefix |
| 12 | 生产者↔消费者契约 | `IncidentCorrelator._fetch_suspicious_events` 能读到写回数据 | ✅ test_consumer_can_read_producer_output |
| 13 | 前端 vite build | 通过 | ✅ QA 套件 test_vite_build_passes（独立运行） |

## 3. 降级与审计

- [x] 逐条 `try/except`，单条失败计入 `failed` 并继续，整批 2xx
- [x] `AgentLLM.call` 内部写 `ai_audit_log`（含 `user_id`），审计可追溯
- [x] `data_masking.apply(evidence)` 构造脱敏 prompt（IP/路径/用户名/域名）
- [x] `ai_analysis` 列缺失（未迁移）不阻断 `ai_verdict` 写回（服务层 try/except）

## 4. 全局一致性审查结论

- [x] 导入可解析（无循环依赖）
- [x] 写回键名与 `incident_correlator.py` 逐字符一致
- [x] 端点鉴权 `Depends(get_current_user)`（与 `events.py` 一致，非 `api/auth.py`）
- [x] 端点路径无重复前缀（`prefix="/api/security-events"` + 装饰器 `/ai-verdict`）

## 5. 自测修复记录

- **问题**：自测首跑 7 失败（含全部正常写回 / 降级 / 幂等 / 阈值 / 消费者读取 / 端点成功用例）。
- **根因**：`_process_one` 将原生 `sqlite3.Row` 直接传入 `_build_prompt`，而 `_build_prompt` 内调用
  `row.get('id')` 等访问方式失败 —— `sqlite3.Row` 没有 `.get()` 方法（仅支持 `row['col']`）。
- **修复**：在 `_process_one` 取到 `row` 后、访问字段前加 `row = dict(row)`，转为普通 dict，
  使 `row["col"]` 与 `row.get("col")` 均可用，且不改变任何写回语义。
- **复测结果**：`pytest tests/test_event_verdict.py` → **12 passed**（全部用例绿）。
- **前端 build**：`vite build` → `✓ built in 33.91s`（仅历史遗留 chunk-size 警告，与本增量无关）。

## 6. 最终裁决

- [x] 后端自测：12/12 通过（隔离 SQLite，绝不触碰生产库 `backend/data/ir_platform.db`）
- [x] 前端 build：`vite build` 通过
- [x] 全局一致性审查：导入可解析、无循环依赖、写回键名逐字符一致、鉴权、路径无重复前缀

**IS_PASS: YES**（详见交付总结）
