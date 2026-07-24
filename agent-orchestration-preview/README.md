# 智能体编排管理 · 前端功能预览

> 基于《智能体编排管理 — 优化后方案》的**前端功能预览（原型）**。用 mock 数据驱动、不接真实后端，目的是在产品上线前，让安全分析师 / SOC 主管 / 编排管理员直观审核功能结构、SecOps 交互与视觉风格。

## 简介

本预览覆盖方案定义的「单底座」架构在 UI 层的落点：以已验证可用的 **Orchestrator** 为唯一执行引擎视角，将 ToolRegistry、MemoryLayer(RAG)、Planner/Reflector、统一 HITL、Guardrails、多模型 AgentLLM、Observability、DAG 配置层等组件映射为 9 大功能模块，并以 3 条核心用户操作流程串联交互。

**它不是生产实现**，所有数据来自 `src/mocks/`，但 store 层刻意与未来真实 API 同形，便于平滑替换。

## 技术栈

- 构建：Vite 5 + React 18 + TypeScript 5.6
- UI：MUI v5.16 + Emotion + @mui/x-charts 7（图表）
- 样式：Tailwind CSS 3（仅作原子类辅助，已关闭 preflight 避免与 MUI 冲突）
- 路由：react-router-dom 6（嵌套路由 + 路由级懒加载）
- 状态：Zustand 4（切片：app / agent / hitl / pipeline）

## 快速开始

```bash
npm install
npm run dev        # 默认 http://localhost:5173
npm run build      # tsc 类型检查 + vite 生产构建（输出 dist/）
npm run preview    # 预览生产构建
```

> 排错提示：若 `npm run build` 在既有 `dist/` 被 dev server 占用时报 `EPERM: operation not permitted`，先停止占用进程，或构建到干净目录：`npx vite build --outDir dist-qa`。
> 本仓库 `.npmrc` 已指向 npmmirror 镜像以加速安装。

## 项目结构

```
agent-orchestration-preview/
├── package.json            # 依赖与脚本
├── vite.config.ts          # Vite 配置（build.emptyOutDir:false 规避沙箱守卫）
├── tsconfig.json           # TS 配置（strict 开启）
├── tailwind.config.js      # Tailwind（扩展 MUI 同色板，关闭 preflight）
├── postcss.config.js
├── index.html
├── .npmrc                  # 指向 npmmirror 镜像
├── .gitignore
├── docs/                   # 需求与设计文档
│   ├── prd.md              # 产品需求文档（简单 PRD）
│   ├── arch.md             # 系统架构设计 + 任务分解
│   ├── class-diagram.mermaid
│   └── sequence-diagram.mermaid
└── src/
    ├── main.tsx            # 入口
    ├── App.tsx             # 根组件（Theme + Router 装配）
    ├── theme.ts            # 暗色/亮色主题 token（对齐方案色板）
    ├── router.tsx          # 9 条懒加载路由 + index→/dashboard
    ├── types/              # 11 个类型定义（agent/pipeline/tool/hitl/...）
    ├── mocks/              # 10 个 mock 数据（字段语义对齐方案）
    ├── store/              # 4 个 Zustand store（app/agent/hitl/pipeline）
    ├── components/shared/  # 共享组件（StatusBadge/StepFlow/StatCard/DataTable/...）
    ├── layouts/            # AppShell / TopBar / Sidebar
    └── modules/            # 9 大功能模块
        ├── dashboard/      # M1 概览 Dashboard
        ├── agents/         # M2 智能体管理（列表/新建表单/详情抽屉）
        ├── pipeline/       # M3 流水线编排（DAG 画布 + 节点面板）
        ├── tools/          # M4 工具与 MCP
        ├── memory/         # M5 记忆与 RAG
        ├── hitl/           # M6 人工审核台（队列 + 上下文面板）
        ├── guardrail/      # M7 护栏与安全
        ├── observability/  # M8 可观测性
        └── settings/       # M9 设置（多模型 + 无状态部署）
```

## 模块说明（9 大功能模块）

| 路由 | 模块 | 对应方案 | 优先级 |
|---|---|---|---|
| `/dashboard` | 概览 Dashboard | Observability / M0 | P0 |
| `/agents` | 智能体管理 | F2 / M0 修空壳 | P0 |
| `/pipeline` | 流水线编排（DAG 画布） | PipelineEngine 配置层 / F11 | P1 |
| `/tools` | 工具与 MCP | ToolRegistry / F1 | P1 |
| `/memory` | 记忆与 RAG | MemoryLayer / F3 | P2 |
| `/hitl` | 人工审核台 | 统一 HITL / F6 / M0 | P0 |
| `/guardrail` | 护栏与安全 | Guardrails / F8(P0) | P0 |
| `/observability` | 可观测性 | F7 / F9 续跑 | P1 |
| `/settings` | 设置 | AgentLLM / F10 / F14 | P1 |

## 三条核心用户操作流程（可视化呈现）

1. **新建自定义 Agent**：`AgentForm` 用步骤条（基础信息 → 选择工具/模型 → 确认）提交 → `useAgentStore.addAgent` → 新卡片即时出现在列表，详情抽屉用 `JsonViewer` 预览配置。
2. **DAG 编排与运行**：`PipelineCanvasPage` + `NodePalette` 拖拽/连线建模 DAG → 校验（闭环 + 含护栏节点）→ `usePipelineStore.run` 用 Kahn 拓扑排序逐步高亮节点（步骤条状态切换 + spin 动画），顶部显示流式整体进度。
3. **HITL 审批**：`HitlQueuePage` 队列 → `HitlContextPanel` 展开「待审 → 上下文 → 护栏校验 → 通过/拒绝」→ 通过调 `approve→resumeRun`、拒绝调 `reject→cancelRun`，状态实时变更，侧栏/顶栏待审角标同步 −1。

## 视觉风格

暗色为默认主题（SecOps 惯例，可切亮色并持久化），关键 token：

- primary `#3B82F6`、secondary `#10B981`、success `#22C55E`、warning `#F59E0B`、error `#EF4444`
- 暗底 `background.default #0F172A`、卡片 `background.paper #1E293B`、分割线 `divider #334155`
- 圆角 8px、8 倍数间距、trace/日志用等宽字体

## 响应式

自定义断点 `xs:0 / sm:768 / md:1280 / lg:1536 / xl:1920`：

- `<768`（移动）：`Drawer` 临时抽屉 + 汉堡按钮
- `768–1279`（平板）：强制图标栏（宽 64）
- `≥1280`（桌面）：完整侧栏，可手动折叠

图表经 `ResizeObserver`（`useElementWidth`）自适应宽度。

## Mock 数据与后端替换

数据流为 `mocks → store → modules` 单向。store 暴露与未来 API 同形的异步方法（如 `listAgents()`、`approveHitl(id, decision)`，返回 `Promise` 并带 100–400ms 模拟延迟）。后端就绪后**仅需替换 `src/mocks/` 的实现**，业务组件零改动。

## 文档索引

- `docs/prd.md` — 产品需求文档
- `docs/arch.md` — 系统架构设计 + 任务分解（T1–T14）
- `docs/class-diagram.mermaid` / `docs/sequence-diagram.mermaid` — 类图与时序图

## 与方案的关系

本预览依据《智能体编排管理 — 优化后方案》（单底座：以 Orchestrator 为唯一执行引擎，PipelineEngine 降级为配置 / DAG 定义层；F8 护栏升 P0、F14 无状态化进 M0）实现其 UI 原型，便于在上线前评审交互与视觉。
