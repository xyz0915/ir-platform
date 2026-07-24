import { create } from 'zustand';
import type { AgentRun, AgentRunStep, ID, NodeType, PipelineEdge, PipelineNode, RunStatus } from '@/types';
import { getPipelineSample } from '@/mocks/pipelines';
import { nowISO } from '@/mocks/util';
import { useAgentStore } from './useAgentStore';

/** DAG 画布运行态 */
export type PipelineStatus = 'idle' | 'valid' | 'invalid' | 'running' | 'done';

const NODE_STEP_KIND: Record<NodeType, AgentRunStep['kind']> = {
  trigger: 'plan',
  investigate: 'tool',
  forensic: 'tool',
  remediate: 'tool',
  guardrail: 'guardrail',
  hitl: 'hitl',
  end: 'reflect',
};

/** 拓扑排序（Kahn）：返回节点执行顺序；若存在环则追加剩余节点 */
const topoSort = (nodes: PipelineNode[], edges: PipelineEdge[]): ID[] => {
  const indeg = new Map<ID, number>();
  const adj = new Map<ID, ID[]>();
  nodes.forEach((n) => {
    indeg.set(n.node_id, 0);
    adj.set(n.node_id, []);
  });
  edges.forEach((e) => {
    if (!indeg.has(e.source) || !indeg.has(e.target)) return;
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1);
    adj.get(e.source)!.push(e.target);
  });
  const queue = nodes.filter((n) => (indeg.get(n.node_id) ?? 0) === 0).map((n) => n.node_id);
  const order: ID[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    order.push(id);
    (adj.get(id) ?? []).forEach((nxt) => {
      indeg.set(nxt, (indeg.get(nxt) ?? 1) - 1);
      if ((indeg.get(nxt) ?? 0) === 0) queue.push(nxt);
    });
  }
  if (order.length < nodes.length) {
    nodes.forEach((n) => {
      if (!order.includes(n.node_id)) order.push(n.node_id);
    });
  }
  return order;
};

/** 检测有向图是否存在环 */
const hasCycle = (nodes: PipelineNode[], edges: PipelineEdge[]): boolean => {
  const order = topoSort(nodes, edges);
  return order.length < nodes.length;
};

const NODE_TYPE_CN: Record<NodeType, string> = {
  trigger: '触发',
  investigate: '调查',
  forensic: '取证',
  remediate: '处置',
  guardrail: '护栏',
  hitl: '人工审核',
  end: '结束',
};

interface PipelineState {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  status: PipelineStatus;
  validationMsg: string;
  /** 各节点运行态高亮 */
  nodeStatus: Record<ID, RunStatus>;
  runningNodeId: ID | null;
  isRunning: boolean;
  progress: number;

  seedFromSample: () => Promise<void>;
  addNodeAt: (type: NodeType, x: number, y: number) => void;
  removeNode: (id: ID) => void;
  addEdge: (source: ID, target: ID) => void;
  removeEdge: (source: ID, target: ID) => void;
  validate: () => void;
  run: () => void;
  reset: () => void;
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  nodes: [],
  edges: [],
  status: 'idle',
  validationMsg: '',
  nodeStatus: {},
  runningNodeId: null,
  isRunning: false,
  progress: 0,

  seedFromSample: async () => {
    const res = await getPipelineSample();
    set({ nodes: res.data.nodes, edges: res.data.edges, status: 'idle', validationMsg: '' });
  },

  addNodeAt: (type, x, y) => {
    const id = `n-${type}-${Date.now()}`;
    const node: PipelineNode = {
      node_id: id,
      type,
      label: `${NODE_TYPE_CN[type]} ${get().nodes.filter((n) => n.type === type).length + 1}`,
      position: { x, y },
    };
    set((s) => ({ nodes: [...s.nodes, node], status: 'idle', validationMsg: '' }));
  },

  removeNode: (id) => {
    set((s) => ({
      nodes: s.nodes.filter((n) => n.node_id !== id),
      edges: s.edges.filter((e) => e.source !== id && e.target !== id),
      status: 'idle',
      validationMsg: '',
    }));
  },

  addEdge: (source, target) => {
    if (source === target) return;
    const exists = get().edges.some((e) => e.source === source && e.target === target);
    if (exists) return;
    set((s) => ({ edges: [...s.edges, { source, target }], status: 'idle', validationMsg: '' }));
  },

  removeEdge: (source, target) => {
    set((s) => ({
      edges: s.edges.filter((e) => !(e.source === source && e.target === target)),
      status: 'idle',
      validationMsg: '',
    }));
  },

  validate: () => {
    const { nodes, edges } = get();
    if (nodes.length === 0) {
      set({ status: 'invalid', validationMsg: '请先从左侧拖入节点。' });
      return;
    }
    if (hasCycle(nodes, edges)) {
      set({ status: 'invalid', validationMsg: '校验未通过：检测到环路，DAG 不允许闭环。' });
      return;
    }
    const hasGuardrail = nodes.some((n) => n.type === 'guardrail' || n.type === 'hitl');
    if (!hasGuardrail) {
      set({
        status: 'invalid',
        validationMsg: '校验未通过：缺少护栏/审核节点（安全主线要求每条处置链路必经护栏）。',
      });
      return;
    }
    set({ status: 'valid', validationMsg: '校验通过：DAG 无环且含护栏节点。' });
  },

  run: () => {
    const { status, nodes, edges } = get();
    if (status !== 'valid') return;
    const order = topoSort(nodes, edges);
    set({
      status: 'running',
      isRunning: true,
      progress: 0,
      nodeStatus: {},
      runningNodeId: null,
    });

    let i = 0;
    const stepOnce = (): void => {
      if (i >= order.length) {
        // 构建一条运行记录并写入 AgentRun 集合
        const run = buildRun(order, nodes);
        useAgentStore.getState().addRun(run);
        const done: Record<ID, RunStatus> = {};
        order.forEach((id) => (done[id] = 'success'));
        set({ status: 'done', isRunning: false, progress: 100, runningNodeId: null, nodeStatus: done });
        return;
      }
      const nodeId = order[i];
      set((s) => ({
        nodeStatus: { ...s.nodeStatus, [nodeId]: 'running' },
        runningNodeId: nodeId,
        progress: Math.round((i / order.length) * 100),
      }));
      i += 1;
      setTimeout(() => {
        set((s) => ({ nodeStatus: { ...s.nodeStatus, [nodeId]: 'success' } }));
        stepOnce();
      }, 750);
    };
    stepOnce();
  },

  reset: () => {
    set({
      nodes: [],
      edges: [],
      status: 'idle',
      validationMsg: '',
      nodeStatus: {},
      runningNodeId: null,
      isRunning: false,
      progress: 0,
    });
  },
}));

/** 由节点执行顺序构造一条 AgentRun（供可观测性/Dashboard 联动） */
const buildRun = (order: ID[], nodes: PipelineNode[]): AgentRun => {
  const ts = nowISO();
  const runId = `run-pipe-${Date.now()}`;
  const byId = new Map(nodes.map((n) => [n.node_id, n]));
  const steps: AgentRunStep[] = order.map((id, idx) => {
    const node = byId.get(id)!;
    return {
      step_id: `ps-${id}-${idx}`,
      run_id: runId,
      name: node.label,
      kind: NODE_STEP_KIND[node.type],
      status: 'success',
      started_at: ts,
      finished_at: ts,
    };
  });
  return {
    run_id: runId,
    agent_id: 'pipe-incident-response',
    agent_name: '流水线编排',
    status: 'success',
    trigger: 'manual',
    started_at: ts,
    finished_at: ts,
    steps,
    guardrail_hits: [],
    hitl_tasks: [],
    summary: 'DAG 编排运行完成，所有节点成功。',
  };
};
