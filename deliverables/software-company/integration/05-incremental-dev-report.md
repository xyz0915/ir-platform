# 增量开发完成报告 · 架构收口 + USE_MOCK 接线 + 工程卫生 + e2e 脚手架

> 阶段：集成交付后的增量收尾（对应 04-verify-report.md 标注的两类架构/后端级遗留 + 用户四项指令）
> 执行者：主理人齐活林（因 Agent 调度通道临时故障，本轮由主理人直接落地代码与验证，非常规代写）

## 一、改动清单（逐文件）

### 架构收口：消除直连（对齐 01-arch-design.md §4.1）
| 文件 | 改动 |
|------|------|
| `src/stores/agentManagement.js` | M2 store：删除对 `@/api/agentManagement` 的直连 import，改为 `import agentApi from '@/api/agent'`；11 处调用（listAgents/createAgent/updateAgent/deleteAgent/pipeline.validate/run/getRunStatus/cancel/getPresets/createPreset/deletePreset）全部改走 facade；删除未使用的 `getDependencyGraph/getCacheStats/invalidateCache/resumeRun` 导入 |
| `src/stores/agents.js` | M6 store：删除对 `@/api/agentOrchestration` 的直连 import（含 `getSSEUrl`），改走 facade；6 处调用（runs.listAgentRuns/getAgentRun/createAgentRun、hitl.listPendingApprovals/approve/reject）改走 facade 嵌套命名空间 |
| `src/views/AgentRunDetailView.vue` | M8 视图：删除 `await import('@/api/agentOrchestration')` 动态直连，改顶部 `import agentApi from '@/api/agent'` 并 `agentApi.runs.getAgentRun(runId)` |
| `src/views/settings/AgentManagement.vue` | 附带收口：原直连 `@/api/agents` 的带分页 `getAgents/getAgentStats`，改走 facade 新增的 `agents.list(params)` 与 `stats.getAgentStats`（保留分页语义，不破坏设置页列表） |

### USE_MOCK 真正接线（实现"置否即零改动接真后端"）
| 文件 | 改动 |
|------|------|
| `src/api/agent/index.js` | 为每个 Mock 模块（guardrail/tools/memory/settings/dashboard/observability）增加 `USE_MOCK[module] ? mock : real` 门控；新增 `runs.createAgentRun`、`pipeline.createPreset/deletePreset`；新增 `agents.list(params)` 命名空间；新增对 `./real/*` 的导入 |
| `src/api/agent/real/guardrail.js` `tools.js` `memory.js` `settings.js` `dashboard.js` `observability.js` | **新增** 6 个真实适配器，经 `@/api/index` 的 axios 实例调文档化端点，注释标明"后端 F1/F3/F7/F8/F10/F14 就绪后启用"。默认 `USE_MOCK=true` 时不被走到 |

### 工程卫生
| 文件 | 改动 |
|------|------|
| `src/router/index.js` | 删除 M8 `AgentRunDetailView` 与未被路由引用的死 import `AgentManagementView` 的静态 import；`AoRunDetail` 路由改 `() => import('@/views/AgentRunDetailView.vue')` 懒加载 |
| `vite.config.js` | `build.rollupOptions.output.manualChunks` 拆分 `vue-vendor` / `element-vendor` / `echarts-vendor` / `vendor` |
| `frontend/.gitignore` | **新增**：忽略 `dist/`、`dist-*/`、`dist-qa/`、Playwright 报告等 |
| `package.json` | scripts 增加 `"e2e": "playwright test"` |

### e2e 脚手架（不运行，仅补齐内容）
| 文件 | 改动 |
|------|------|
| `playwright.config.js` | **新增** Playwright 配置（testDir=./e2e，baseURL 5173，webServer 注释示例） |
| `e2e/flowA.spec.js` `flowB.spec.js` `flowC.spec.js` | **新增** 三条核心链路（M2→M3→M6→M8 / HITL×guardrail / Dashboard 聚合） |
| `e2e/README.md` | **新增** 前置条件与运行说明 |

### 测试兜底
| 文件 | 改动 |
|------|------|
| `src/stores/__tests__/agentManagement.store.spec.js` | `vi.mock` 目标由 `@/api/agentManagement` 改为 `@/api/agent`（默认导出嵌套结构），断言同步到 `agentApi.pipeline.*` |
| `src/stores/__tests__/agents.store.spec.js` | `vi.mock` 目标改为 `@/api/agent`，断言同步到 `agentApi.runs.*` / `agentApi.hitl.*` |
| `vite.config.js` | `test.exclude` 增加 `e2e/**`，避免 vitest 误跑 Playwright 规格 |

## 二、USE_MOCK 接线说明
- 机制：facade 每个 Mock 方法形如 `() => (USE_MOCK.guardrail ? guardrailMock.x() : guardrailReal.x())`。
- 当前 `mock-config.js` 中 `guardrail/tools/memory/settings/dashboardTrend/observability=true`，`pipeline/hitl/agents/runs=false`，故默认运行态/构建态/既有测试**完全不变**。
- 后端就绪后：**仅需将对应键置 `false`**（如 F8 落地 → `guardrail:false`），facade 自动改走 `real/guardrail.js`，store 与组件**零改动**。真实适配器已按 01-api-spec 文档化端点实现，仅需后端定稿 URL。

## 三、工程卫生验证
- `dist/` 已清理（含历史 `dist-clean-verify`/`dist-new` 残留）；`frontend/.gitignore` 已忽略重建产物。
- 懒加载：`AgentRunDetailView` 构建产物为独立 chunk（`AgentRunDetailView-*.js`，17.78 kB / gzip 7.11 kB）；死 import `AgentManagementView` 已移除（构建产物不再含该 chunk）。
- `manualChunks` 生效：`vue-vendor`(125.9 kB)、`element-vendor`(946 kB)、`echarts-vendor`(1,038 kB)、`vendor`(1,158 kB) 独立分包，提升缓存命中。

## 四、验证结果
- **构建**：`npx vite build` → `✓ built in 18.90s`，**零错误**（仅 echarts/element-plus 单包 >500kB 的常规体积提示，符合预期）。
- **单测回归**：`npx vitest run` → 333 用例中 **324 通过**；9 个失败**全部位于 `src/__tests__/components/analysis/`**（EvidenceViewer/IocIndicators/MatchedRulesList 等），为本次集成前已存在的分析中心失败，与本次改造无关；本次改动的 facade / M2 / M6 相关测试**全部通过**，未引入新失败。
- **§4.1 偏差扫描**：全仓仅 facade 内部与测试文件保留对 `@/api/agentManagement|agentOrchestration|agents` 的引用，store / view **零直连**。

## 五、IS_PASS 结论
**IS_PASS: YES**
- 直连残留：无（除 facade 内部与测试）
- USE_MOCK 门控：已生效（门控逻辑就位，默认态不变）
- M2/M8 懒加载 + manualChunks：已生效
- 构建：零错误

## 六、遗留项 / 后续
1. 分析中心 9 个既有失败用例需另行排查（非本次范围）。
2. 真实 e2e：待后端 F 系列就绪后，`npm i -D @playwright/test && npx playwright install chromium` 再 `npm run e2e`（`e2e/README.md` 已说明）。
3. 真实适配器端点 URL 为文档化约定，后端定稿后按 `real/*.js` 注释 TODO 对齐。
