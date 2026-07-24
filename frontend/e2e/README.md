# 智能体编排模块 — 端到端测试（Playwright）

本目录为**浏览器级端到端（e2e）**测试规格，覆盖三条核心用户链路，与单测（Vitest）互补：

| 规格 | 链路 | 对应模块 |
|------|------|----------|
| `flowA.spec.js` | 创建智能体 → 编排执行 → HITL 批准 → 可观测 | M2 → M3 → M6 → M8 |
| `flowB.spec.js` | HITL 上下文面板渲染 `guardrail_result` | M6 × M7（useGuardrail 热插拔） |
| `flowC.spec.js` | Dashboard 聚合 runs+stats+trend，刷新不丢态 | M1 |

## 前置条件（当前未满足）

1. 安装依赖：`npm i -D @playwright/test`
2. 安装浏览器：`npx playwright install chromium`
3. 启动前端：`npm run dev`（默认 http://localhost:5173）
4. 启动后端：真实/ Mock 后端（端口 8000，对应 `vite.config.js` 的 `/api` 代理）。
   后端就绪前，Mock 模块（M4/M5/M7/M9/M1 trend/M8 trace）由 `src/api/agent/mock/*` 提供，
   真实模块（M2/M3 接口层/M6/M1 runs+stats）需后端 F 系列接口（F1/F3/F7/F8/F10/F14）。

## 运行

```bash
npm run e2e          # 等价于 npx playwright test
npm run e2e -- --headed   # 可视化调试
```

> 配置见 `playwright.config.js`。当前仓库沙箱未安装 Playwright 浏览器，且后端未就绪，
> **请勿直接执行**，待上述条件满足后作为回归验证使用。
