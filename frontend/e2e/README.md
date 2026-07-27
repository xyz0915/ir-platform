# 智能体编排模块 — 端到端测试（Playwright）

本目录为**浏览器级端到端（e2e）**测试规格，覆盖三条核心用户链路，与单测（Vitest）互补：

| 规格 | 链路 | 对应模块 |
|------|------|----------|
| `flowA.spec.js` | 创建智能体 → 编排执行 → HITL 批准 → 可观测 | M2 → M3 → M6 → M8 |
| `flowB.spec.js` | HITL 上下文面板渲染 `guardrail_result` | M6 × M7（useGuardrail 热插拔） |
| `flowC.spec.js` | Dashboard 聚合 runs+stats+trend，刷新不丢态 | M1 |

## 前置条件

1. 安装依赖：`npm i -D @playwright/test`
2. 安装浏览器：`npx playwright install chromium`
3. 启动前端：`npx vite`（默认 http://localhost:5173）
4. 启动后端：`cd backend && ../venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`

## 后端状态（2026-07-24 实际验证）

全部后端端点已就绪并通过真实链路验证：

- ✅ F1 聚合看板：`GET /api/agents/dashboard` — 真实
- ✅ F3 知识库：`GET /api/knowledge/bases` — 真实
- ✅ F7 MCP 工具：`GET /api/mcp/servers` `/api/mcp/tools` — 真实
- ✅ F8 护拦：`POST /api/agent-guardrails/evaluate` — 真实
- ✅ F10 模型配置：`GET /api/ai/profiles` — 真实
- ✅ F14 部署配置：`GET /api/settings/deployment` — 真实

详见 `deliverables/software-company/integration/15-verify-report.md`。

## 运行

```bash
npm run e2e          # 等价于 npx playwright test
npm run e2e -- --headed   # 可视化调试
```

> 注意：当前沙箱未安装 Playwright 浏览器（npm registry 网络不可达），
> 在本地环境执行上述前置条件后即可运行。
