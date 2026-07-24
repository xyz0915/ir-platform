import type { PipelineDef } from '@/types';
import { clone, delay, ok, type ApiResponse } from './util';

/**
 * 示例流水线定义（DAG 配置层）。
 * 仅用于画布初始种子；运行态由 usePipelineStore 管理。
 */
const SAMPLE_PIPELINE: PipelineDef = {
  pipeline_id: 'pipe-incident-response',
  name: '事件响应编排（示例）',
  status: 'draft',
  requires_guardrail: true,
  requires_hitl: true,
  created_at: '2026-07-01T09:00:00.000Z',
  nodes: [
    { node_id: 'n-trigger', type: 'trigger', label: '告警触发', position: { x: 80, y: 200 } },
    { node_id: 'n-investigate', type: 'investigate', label: '初步调查', position: { x: 320, y: 200 } },
    { node_id: 'n-forensic', type: 'forensic', label: '取证实录', position: { x: 560, y: 120 } },
    { node_id: 'n-guardrail', type: 'guardrail', label: '护栏校验', position: { x: 560, y: 300 } },
    { node_id: 'n-remediate', type: 'remediate', label: '处置响应', position: { x: 800, y: 300 } },
    { node_id: 'n-end', type: 'end', label: '结束', position: { x: 1040, y: 300 } },
  ],
  edges: [
    { source: 'n-trigger', target: 'n-investigate' },
    { source: 'n-investigate', target: 'n-forensic' },
    { source: 'n-investigate', target: 'n-guardrail' },
    { source: 'n-guardrail', target: 'n-remediate' },
    { source: 'n-remediate', target: 'n-end' },
  ],
};

/** 读取示例流水线 */
export const getPipelineSample = async (): Promise<ApiResponse<PipelineDef>> => {
  await delay();
  return ok(clone(SAMPLE_PIPELINE));
};
