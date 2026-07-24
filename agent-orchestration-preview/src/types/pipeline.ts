import type { ID, ISODateTime } from './common';

/** DAG 节点类型 */
export type NodeType =
  | 'trigger'
  | 'investigate'
  | 'forensic'
  | 'remediate'
  | 'guardrail'
  | 'hitl'
  | 'end';

/** 节点类型中文标签 */
export const NODE_TYPE_LABELS: Record<NodeType, string> = {
  trigger: '触发',
  investigate: '调查',
  forensic: '取证',
  remediate: '处置',
  guardrail: '护栏',
  hitl: '人工审核',
  end: '结束',
};

/** 流水线节点（步骤的物化） */
export interface PipelineNode {
  node_id: ID;
  type: NodeType;
  label: string;
  position: { x: number; y: number };
  config?: Record<string, unknown>;
}

/** 流水线边（步骤流转） */
export interface PipelineEdge {
  source: ID;
  target: ID;
}

/**
 * 流水线定义 —— 仅"配置 / DAG 定义层"，执行统一走 Orchestrator（单底座策略）。
 */
export interface PipelineDef {
  pipeline_id: ID;
  name: string;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  status: 'draft' | 'validated' | 'running';
  requires_guardrail: boolean;
  requires_hitl: boolean;
  created_at: ISODateTime;
}
