# 测试报告 · 第④批 P0-B（AI 检测工程：规则自生成 + 自动调优）

> 验证人：software-qa-engineer-4（独立验证，严过关）
> 交付方：software-engineer-6（实现 + 自测 IS_PASS=YES 12/12）
> 验证日期：2026-07-18
> 红线：**全程使用临时 SQLite 隔离库（IsolatedDBTestCase），未触碰 `backend/data/ir.db` 一行**

---

## 1. 概述

对 P0-B 三模块（T-B1 规则草稿/影子运行、T-B2 自动调优/人审启用、T-B3 前端草稿视图）做独立验证，覆盖 8 项验证清单。后端以 FastAPI `TestClient` + `FakeLLM` mock 运行；前端做静态契约比对 + `vite build` 真构建。

**环境**：Python 3.13.12（venv）/ pytest 9.1.1；Node（vite 已安装 `node_modules`）。
**新增/复用测试**：`tests/test_batch4_rule_drafts.py`（工程师 12 例）、`tests/test_batch4_qa_independent.py`（本次独立 29 例）。

---

## 2. 验证清单逐项结果（8/8 通过）

| # | 验证项 | 结果 | 关键断言 |
|---|--------|------|----------|
| 1 | **鉴权闸门** | ✅ | 7 端点全部 `Depends(get_current_user)`；`enable`/`reject` 仅 admin（非 admin→403）；无 token→401；端点解析于 `/api/rules/...`（重复前缀 `/api/rules/rules/...`→404，无歧义） |
| 2 | **rule_dsl 安全校验** | ✅ | 拒绝代码注入（`__import__`/`eval`/`subprocess`）、DDL（`DROP`/`SELECT`/`; `/`--`）、全表扫描正则（`.*`/`.+`/`^.*$`）、笛卡尔积（list>1000 / composite>50 / 嵌套>3）；非白名单字段/键/类型拒绝；AST 静态扫描确认 `rule_dsl/rule_engine/rule_shadow/rule_generator/rule_tuner` 中**无 `eval()`/`exec()`/`compile()`/`__import__()` 实际调用** |
| 3 | **rule_generator 降级** | ✅ | `AgentLLM` 返回 `degraded=True`（无 Profile / 熔断）→ 确定性启发式生成可用草稿（rule_type 合法、condition 通过 DSL、`generate` 不 500）；空样本日志回退 `exists` 占位 |
| 4 | **影子分支安全红线** | ✅ | 对匹配数据的 `is_shadow` 规则 `RuleEngine.evaluate` 返回 `len(matches)==0`（绝不产生告警）；`shadow_hit_count` 正确递增并落库（`rule_drafts.shadow_hit_count` + `rules` 镜像行 `is_shadow=1, shadow_hit_count` 同步） |
| 5 | **rule_tuner 调优** | ✅ | 生成新版本草稿：`parent_draft_id` 指向原草稿、`tuned_version+1`、`tuning_history_json` 追加且保留 `llm_degraded` 标记；原草稿置 `pending_review`；启发式路径对 list 规则移除误报值、对非 list 规则降严重度（high→medium） |
| 6 | **模型 + CRUD + 状态机** | ✅ | `RuleDraft.create/list/get_by_id/get_by_name/update/delete` 正常；状态机 `draft→shadow→enabled/rejected` 自洽；已驳回草稿被 `enable` 正确拒绝（400） |
| 7 | **前端契约** | ✅ | `RuleDraftView.vue` 消费真实字段（`shadow_hit_count`/`tuned_version`/`rationale`/`dsl`/`sample_hits`/`status`/`condition`）；`api/ruleDrafts.js` 7 条路径与后端一致（base `/api` + `/rules/...`）；`vite build` 通过（38.6s，仅 chunk 体积提示，无错误） |
| 8 | **端到端冒烟** | ✅ | generate→draft→shadow(命中→2)→stats→tune→enable(admin)：生效规则落库 `rules.enabled=1, is_shadow=0`、草稿状态 `enabled`；reject 路径：草稿 `rejected` 且 `rules` 镜像行 `is_shadow=0, enabled=0` |

---

## 3. 逐模块结果

### T-B1 · DSL 校验 + 规则草稿 + 影子运行
- 涉及：`rule_dsl.py`、`rule_generator.py`、`rule_shadow.py`、`models/rule_draft.py`、`rules/rule_engine.py`（影子分支）、`api/rules.py`（generate/drafts/shadow/shadow-stats）、`database.py`（rule_drafts 表 + rules 的 is_shadow/shadow_hit_count）
- 结果：**全部通过**。DSL 三条安全红线（不执行任意代码 / 拒笛卡尔积全表扫描 / 拒 DDL 注入）均有断言覆盖且通过；影子运行计数与落库一致。

### T-B2 · 自动调优 + 人审启用
- 涉及：`rule_tuner.py`、`api/rules.py`（tune/enable/reject）
- 结果：**全部通过**。调优产出新版本草稿并保留历史；admin 闸门（enable/reject 403 for 非 admin）生效；状态机转换自洽。

### T-B3 · 前端规则草稿视图
- 涉及：`RuleDraftView.vue`、`api/ruleDrafts.js`、`router/index.js`、`AppLayout.vue`（菜单）、`vite build`
- 结果：**全部通过**。字段契约、路径契约静态校验通过；`vite build` 成功产出 `dist/`。

---

## 4. 测试统计与覆盖率

| 套件 | 用例数 | 结果 |
|------|--------|------|
| `tests/test_batch4_rule_drafts.py`（工程师） | 12 | 12 passed |
| `tests/test_batch4_qa_independent.py`（独立） | 29 | 29 passed |
| **合计** | **41** | **41 passed, 0 failed** |

- **鉴权**：7 端点 ×（401 无 token / 200 鉴权通过 / 403 非 admin 限权）全覆盖。
- **DSL**：6 类合法规则 + 8 类拒绝场景 + 静态无-eval 扫描。
- **影子安全红线**：`len(matches)==0` 直接断言 + 计数落库双写断言。
- **调优/Bug 回归**：LLM 成功路径 + 降级路径（list 移除值 / 非 list 降严重度）+ 历史保留。
- **E2E**：生成→影子→统计→调优→启用 / 驳回 两条主链路。
- **覆盖率说明**：核心公共服务与 API 主链路、状态机、安全红线均被覆盖；未追求 100% 行覆盖（如 `_mirror_to_rules` 的 INSERT/UPDATE 分支、攻击链影子分支需 host 上下文，属次要路径），关键契约与红线已充分验证。

---

## 5. 发现的 Bug 与修复建议

### 5.1 源码 Bug
**无。** 经独立验证，交付代码在 8 项清单、状态机、安全红线上均符合 `docs/ai_features_design.md` 与 PRD 约定，未发现功能或安全缺陷。

### 5.2 验证过程中发现并自修的「测试代码」问题（Round 1 自检修复，不计入源码缺陷）
1. `test_reject_code_injection` 第 3 条用例结构不合法（缺 `values`，被 `;` 触发 DDL 拦截而非代码注入拦截）→ 改为结构合法且不含 `;`、`--` 的代码字符串（如 `subprocess.check_output('id')`），使其命中代码注入分支。
2. `test_valid_types_pass` 的 composite 子规则误用非白名单字段 `remote_address`（DSL 正确拒绝）→ 改为白名单字段 `source_ip`。
3. `test_tune_creates_new_version_and_preserves_history` 误将 `tuner_tune`（内部已 `asyncio.run`）再包一层 `asyncio.run` → 去掉外层包装。

> 上述 3 项均为测试侧问题，已在同一轮内修复并复跑通过，源码无需改动。

---

## 6. 智能路由判定

- 源码有 Bug → 否
- 测试代码有 Bug → 是（3 项，已在 Round 1 全部自修）
- 全部通过 → 是

**最终判定：`NoOne`（无需回退工程师修改）。**

交付代码质量达标，独立验证 41/41 通过，前端 `vite build` 通过，安全红线（无 token→401、admin 限权、影子 0 告警、DSL 拒注入/全表扫描/DDL、绝不 eval 任意代码）全部成立。建议直接进入合并/发布评审。

---

## 7. 交付物
- 测试：`backend/tests/test_batch4_qa_independent.py`（29 例，独立验证）
- 复用：`backend/tests/test_batch4_rule_drafts.py`（12 例，工程师）
- 报告：`backend/qa_report_batch4.md`（本文件）
- 构建产物：`frontend/dist/`（vite build 通过）
- 红线证据：所有用例经 `tests/_qa_batch1_common.IsolatedDBTestCase` 使用临时 SQLite，未读写 `backend/data/ir.db`。
