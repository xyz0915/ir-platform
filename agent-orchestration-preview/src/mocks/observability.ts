import type { ObservabilityRun } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/** 可观测性运行记录（trace / 日志 / 续跑点） */
const OBSERVABILITY_RUNS: ObservabilityRun[] = [
  {
    run_id: 'run-002',
    agent_name: '处置响应 Agent',
    trace: [
      { span_id: 'sp-1', name: 'run', started_at: '2026-07-06T15:55:00.000Z', duration_ms: 26000 },
      { span_id: 'sp-2', parent_id: 'sp-1', name: 'locate_host', started_at: '2026-07-06T15:55:01.000Z', duration_ms: 20000 },
      { span_id: 'sp-3', parent_id: 'sp-1', name: 'guardrail_check', started_at: '2026-07-06T15:55:21.000Z', duration_ms: 4000 },
      { span_id: 'sp-4', parent_id: 'sp-1', name: 'hitl_wait', started_at: '2026-07-06T15:55:26.000Z', duration_ms: 0 },
    ],
    logs: [
      { ts: '2026-07-06T15:55:00.000Z', level: 'info', message: 'run started: 处置响应 Agent' },
      { ts: '2026-07-06T15:55:21.000Z', level: 'info', message: 'guardrail: policy gp-host-isolate passed' },
      { ts: '2026-07-06T15:55:26.000Z', level: 'warn', message: 'hitl: 进入人工审核，运行挂起 (resume_point=sp-4)' },
    ],
    resume_point: 'sp-4',
  },
  {
    run_id: 'run-003',
    agent_name: '威胁狩猎 Agent',
    trace: [
      { span_id: 'sp-10', name: 'run', started_at: '2026-07-06T14:10:00.000Z', duration_ms: 900000 },
      { span_id: 'sp-11', parent_id: 'sp-10', name: 'plan_hypothesis', started_at: '2026-07-06T14:10:01.000Z', duration_ms: 9000 },
      { span_id: 'sp-12', parent_id: 'sp-10', name: 'netflow_search', started_at: '2026-07-06T14:10:11.000Z', duration_ms: 470000 },
      { span_id: 'sp-13', parent_id: 'sp-10', name: 'reflect', started_at: '2026-07-06T14:18:01.000Z', duration_ms: 419000 },
    ],
    logs: [
      { ts: '2026-07-06T14:10:00.000Z', level: 'info', message: 'run started: 威胁狩猎 Agent' },
      { ts: '2026-07-06T14:18:01.000Z', level: 'info', message: 'reflect: 发现 2 个 C2 通信迹象' },
    ],
  },
  {
    run_id: 'run-004',
    agent_name: '取证分析 Agent',
    trace: [
      { span_id: 'sp-20', name: 'run', started_at: '2026-07-06T13:00:00.000Z', duration_ms: 540000 },
      { span_id: 'sp-21', parent_id: 'sp-20', name: 'sandbox_detonate', started_at: '2026-07-06T13:00:01.000Z', duration_ms: 539000 },
    ],
    logs: [
      { ts: '2026-07-06T13:00:00.000Z', level: 'info', message: 'run started: 取证分析 Agent' },
      { ts: '2026-07-06T13:09:00.000Z', level: 'error', message: 'sandbox_detonate failed: 沙箱容量不足，任务排队超时' },
    ],
  },
];

/** 读取可观测性运行记录 */
export const getObservabilityRuns = async (): Promise<ApiResponse<ObservabilityRun[]>> => {
  await delay();
  return ok(clone(OBSERVABILITY_RUNS));
};

/** 按 run_id 读取 */
export const getObservabilityRun = (id: string): ObservabilityRun | undefined =>
  OBSERVABILITY_RUNS.find((r) => r.run_id === id);
