import { useEffect, useRef, useState, type DragEvent } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Grid,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import LinkIcon from '@mui/icons-material/Link';
import DeleteIcon from '@mui/icons-material/Delete';
import { PageHeader } from '@/components/shared/PageHeader';
import { StepFlow, type StepItem } from '@/components/shared/StepFlow';
import { usePipelineStore } from '@/store/usePipelineStore';
import { NodePalette } from './NodePalette';
import { NODE_TYPE_LABELS, type NodeType, type RunStatus } from '@/types';

const NODE_W = 170;
const NODE_H = 64;
const CANVAS_W = 1400;
const CANVAS_H = 640;

const NODE_COLOR: Record<NodeType, string> = {
  trigger: '#3B82F6',
  investigate: '#60A5FA',
  forensic: '#10B981',
  remediate: '#F59E0B',
  guardrail: '#EF4444',
  hitl: '#F97316',
  end: '#94A3B8',
};

export function PipelineCanvasPage() {
  const theme = useTheme();
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [snack, setSnack] = useState('');

  const {
    nodes,
    edges,
    status,
    validationMsg,
    nodeStatus,
    isRunning,
    progress,
    seedFromSample,
    addNodeAt,
    removeNode,
    addEdge,
    removeEdge,
    validate,
    run,
    reset,
  } = usePipelineStore();

  useEffect(() => {
    if (usePipelineStore.getState().nodes.length === 0) {
      void seedFromSample();
    }
  }, [seedFromSample]);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/x-node-type') as NodeType;
    if (!type) return;
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = e.clientX - rect.left - NODE_W / 2;
    const y = e.clientY - rect.top - NODE_H / 2;
    addNodeAt(type, Math.max(0, x), Math.max(0, y));
  };

  const handleNodeClick = (id: string) => {
    if (connectFrom && connectFrom !== id) {
      addEdge(connectFrom, id);
      setConnectFrom(null);
    }
  };

  // 流程② 步骤条状态
  const flowSteps: StepItem[] = [
    { label: '拖入节点', state: nodes.length > 0 ? 'done' : 'active' },
    { label: '连线流转', state: edges.length > 0 ? 'done' : 'todo', hint: `${edges.length} 条` },
    { label: '校验', state: status === 'valid' ? 'done' : status === 'invalid' ? 'error' : 'todo' },
    {
      label: '运行',
      state: isRunning ? 'active' : status === 'done' ? 'done' : 'todo',
    },
  ];

  const nodeById = new Map(nodes.map((n) => [n.node_id, n]));

  const edgePath = (s: string, t: string): string => {
    const sn = nodeById.get(s);
    const tn = nodeById.get(t);
    if (!sn || !tn) return '';
    const sx = sn.position.x + NODE_W;
    const sy = sn.position.y + NODE_H / 2;
    const tx = tn.position.x;
    const ty = tn.position.y + NODE_H / 2;
    return `M ${sx} ${sy} C ${sx + 50} ${sy}, ${tx - 50} ${ty}, ${tx} ${ty}`;
  };

  const statusBorder = (id: string): { borderColor: string; boxShadow?: string; anim?: boolean } => {
    const st: RunStatus | undefined = nodeStatus[id];
    if (st === 'running') {
      return { borderColor: theme.palette.primary.main, boxShadow: `0 0 0 3px ${theme.palette.primary.main}55`, anim: true };
    }
    if (st === 'success') return { borderColor: theme.palette.success.main };
    const node = nodeById.get(id);
    return { borderColor: node ? NODE_COLOR[node.type] : theme.palette.divider };
  };

  return (
    <Box>
      <PageHeader
        title="流水线编排（DAG 画布）"
        subtitle="节点=步骤、边=流转；校验闭环与护栏节点后运行（F11 / M1，单底座所见即所得）"
        action={
          <Stack direction="row" spacing={1}>
            <Button variant="outlined" startIcon={<CheckCircleIcon />} onClick={validate}>
              校验
            </Button>
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              disabled={status !== 'valid' || isRunning}
              onClick={() => {
                run();
                setSnack('流水线开始运行（mock SSE 流式步进）');
              }}
            >
              运行
            </Button>
            <Button variant="text" startIcon={<RestartAltIcon />} onClick={reset}>
              重置
            </Button>
          </Stack>
        }
      />

      <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'background.default' }}>
        <StepFlow steps={flowSteps} />
      </Paper>

      {(isRunning || status === 'done') && (
        <Box sx={{ mb: 2 }}>
          <LinearProgress variant="determinate" value={progress} color={status === 'done' ? 'success' : 'primary'} />
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {status === 'done' ? `运行完成（${progress}%）` : `运行进度 ${progress}%`}
          </Typography>
        </Box>
      )}

      {validationMsg && (
        <Alert severity={status === 'valid' ? 'success' : 'error'} sx={{ mb: 2 }}>
          {validationMsg}
        </Alert>
      )}

      {connectFrom && (
        <Alert severity="info" sx={{ mb: 2 }} onClose={() => setConnectFrom(null)}>
          连线模式：点击目标节点完成 {nodeById.get(connectFrom)?.label} → ? 的连线（再次点击连线按钮取消）
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid item xs={12} md={3}>
          <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
            <NodePalette onAdd={(type) => addNodeAt(type, 40 + nodes.length * 12, 40 + nodes.length * 12)} />
            <Divider sx={{ my: 2 }} />
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              操作提示：拖拽节点到画布；点击节点上的连线按钮后点目标节点完成连线；点击连线可删除；节点右上角可删除。
            </Typography>
          </Paper>
        </Grid>

        <Grid item xs={12} md={9}>
          <Paper
            variant="outlined"
            ref={canvasRef}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            sx={{
              position: 'relative',
              width: '100%',
              height: CANVAS_H,
              overflow: 'auto',
              bgcolor: 'background.default',
              backgroundImage:
                'linear-gradient(#ffffff0a 1px, transparent 1px), linear-gradient(90deg, #ffffff0a 1px, transparent 1px)',
              backgroundSize: '24px 24px',
            }}
          >
            <Box sx={{ position: 'relative', width: CANVAS_W, height: CANVAS_H }}>
              {/* 连线层 */}
              <svg width={CANVAS_W} height={CANVAS_H} style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none' }}>
                <defs>
                  <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
                    <path d="M0,0 L8,3 L0,6 Z" fill={theme.palette.text.secondary} />
                  </marker>
                </defs>
                {edges.map((e, i) => {
                  const d = edgePath(e.source, e.target);
                  if (!d) return null;
                  return (
                    <g key={i} style={{ pointerEvents: 'auto', cursor: 'pointer' }} onClick={() => removeEdge(e.source, e.target)}>
                      <path d={d} fill="none" stroke="transparent" strokeWidth={14} />
                      <path
                        d={d}
                        fill="none"
                        stroke={theme.palette.text.secondary}
                        strokeWidth={2}
                        markerEnd="url(#arrow)"
                      />
                    </g>
                  );
                })}
              </svg>

              {/* 节点层 */}
              {nodes.map((n) => {
                const sb = statusBorder(n.node_id);
                const isConnectSource = connectFrom === n.node_id;
                return (
                  <Paper
                    key={n.node_id}
                    onClick={() => handleNodeClick(n.node_id)}
                    sx={{
                      position: 'absolute',
                      left: n.position.x,
                      top: n.position.y,
                      width: NODE_W,
                      minHeight: NODE_H,
                      p: 1,
                      cursor: connectFrom ? 'crosshair' : 'default',
                      border: `2px solid ${sb.borderColor}`,
                      borderColor: isConnectSource ? theme.palette.primary.main : sb.borderColor,
                      boxShadow: sb.boxShadow,
                      animation: sb.anim ? 'pipulse 1s infinite' : undefined,
                      '@keyframes pipulse': {
                        '0%,100%': { boxShadow: `0 0 0 2px ${theme.palette.primary.main}44` },
                        '50%': { boxShadow: `0 0 0 6px ${theme.palette.primary.main}11` },
                      },
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'center',
                    }}
                  >
                    <Typography variant="caption" sx={{ color: NODE_COLOR[n.type], fontWeight: 700 }}>
                      {NODE_TYPE_LABELS[n.type]}
                    </Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
                      {n.label}
                    </Typography>

                    {/* 连线按钮 */}
                    <Tooltip title="从此节点连线">
                      <IconButton
                        size="small"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          setConnectFrom((prev) => (prev === n.node_id ? null : n.node_id));
                        }}
                        sx={{ position: 'absolute', top: -10, right: -10, bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider' }}
                      >
                        <LinkIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    {/* 删除按钮 */}
                    <IconButton
                      size="small"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        removeNode(n.node_id);
                      }}
                      sx={{ position: 'absolute', bottom: -10, right: -10, bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider' }}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Paper>
                );
              })}

              {nodes.length === 0 && (
                <Box sx={{ position: 'absolute', top: '40%', left: 0, right: 0, textAlign: 'center', color: 'text.secondary' }}>
                  <Typography variant="body2">从左侧拖入「调查 / 取证 / 处置」等节点开始编排</Typography>
                </Box>
              )}
            </Box>
          </Paper>
        </Grid>
      </Grid>

      <Chip
        sx={{ mt: 2 }}
        size="small"
        color={status === 'valid' ? 'success' : 'default'}
        label={`画布状态：${status}`}
      />
    </Box>
  );
}
