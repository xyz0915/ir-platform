import { lazy, Suspense, type ReactNode } from 'react';
import { Box, CircularProgress } from '@mui/material';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './layouts/AppShell';

/** 路由级懒加载的加载占位 */
const RouteFallback = () => (
  <Box
    sx={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '60vh',
    }}
  >
    <CircularProgress size={28} />
  </Box>
);

const wrap = (node: ReactNode) => <Suspense fallback={<RouteFallback />}>{node}</Suspense>;

// 9 模块路由级懒加载（页面以具名导出，故用 .then 映射到 default）
const DashboardPage = lazy(() => import('./modules/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const AgentListPage = lazy(() => import('./modules/agents/AgentListPage').then((m) => ({ default: m.AgentListPage })));
const PipelineCanvasPage = lazy(() => import('./modules/pipeline/PipelineCanvasPage').then((m) => ({ default: m.PipelineCanvasPage })));
const ToolsPage = lazy(() => import('./modules/tools/ToolsPage').then((m) => ({ default: m.ToolsPage })));
const MemoryPage = lazy(() => import('./modules/memory/MemoryPage').then((m) => ({ default: m.MemoryPage })));
const HitlQueuePage = lazy(() => import('./modules/hitl/HitlQueuePage').then((m) => ({ default: m.HitlQueuePage })));
const GuardrailPage = lazy(() => import('./modules/guardrail/GuardrailPage').then((m) => ({ default: m.GuardrailPage })));
const ObservabilityPage = lazy(() => import('./modules/observability/ObservabilityPage').then((m) => ({ default: m.ObservabilityPage })));
const SettingsPage = lazy(() => import('./modules/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })));

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', element: wrap(<DashboardPage />) },
      { path: 'agents', element: wrap(<AgentListPage />) },
      { path: 'pipeline', element: wrap(<PipelineCanvasPage />) },
      { path: 'tools', element: wrap(<ToolsPage />) },
      { path: 'memory', element: wrap(<MemoryPage />) },
      { path: 'hitl', element: wrap(<HitlQueuePage />) },
      { path: 'guardrail', element: wrap(<GuardrailPage />) },
      { path: 'observability', element: wrap(<ObservabilityPage />) },
      { path: 'settings', element: wrap(<SettingsPage />) },
    ],
  },
  { path: '*', element: <Navigate to="/dashboard" replace /> },
]);
