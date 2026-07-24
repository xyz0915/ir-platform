import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Box, Card, CardContent, Chip, Divider, Grid, Paper, Stack, Typography, useTheme } from '@mui/material';
import type { Theme } from '@mui/material/styles';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import { useAgentStore } from '@/store/useAgentStore';
import { getObservabilityRuns } from '@/mocks/observability';
import type { AgentRun, ObservabilityRun, RunStatus, TraceSpan } from '@/types';
import dayjs from 'dayjs';

const STEP_COLOR: Record<RunStatus, string> = {
  pending: '#94A3B8',
  running: '#3B82F6',
  success: '#22C55E',
  failed: '#EF4444',
  waiting_hitl: '#F59E0B',
  cancelled: '#64748B',
};

interface RunEntry {
  run_id: string;
  agent_name: string;
  hasTrace: boolean;
}

export function ObservabilityPage() {
  const theme = useTheme();
  const [searchParams, setSearchParams] = useSearchParams();
  const agentRuns = useAgentStore((s) => s.runs);

  const [obsRuns, setObsRuns] = useState<ObservabilityRun[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getObservabilityRuns().then((res) => {
      if (alive) {
        setObsRuns(res.data);
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const runList: RunEntry[] = useMemo(() => {
    const fromObs = obsRuns.map((r) => ({ run_id: r.run_id, agent_name: r.agent_name, hasTrace: true }));
    const obsIds = new Set(obsRuns.map((r) => r.run_id));
    const fromAgent = agentRuns
      .filter((r) => !obsIds.has(r.run_id))
      .map((r) => ({ run_id: r.run_id, agent_name: r.agent_name, hasTrace: false }));
    return [...fromObs, ...fromAgent];
  }, [obsRuns, agentRuns]);

  const runId = searchParams.get('run') ?? runList[0]?.run_id ?? null;
  const obsRun = obsRuns.find((r) => r.run_id === runId) as ObservabilityRun | undefined;
  const agentRun = agentRuns.find((r) => r.run_id === runId) as AgentRun | undefined;

  const selectRun = (id: string) => setSearchParams({ run: id });

  const traceTree = useMemo(() => (obsRun ? buildTraceTree(obsRun.trace) : []), [obsRun]);

  if (loading) return <EmptyState title="加载中…" />;

  return (
    <Box>
      <PageHeader title="可观测性" subtitle="运行时间线 / trace span / 结构化日志 / 续跑点（F7 / F9）" />

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Stack spacing={1.5}>
            {runList.map((r) => (
              <Paper
                key={r.run_id}
                variant="outlined"
                sx={{
                  p: 1.5,
                  cursor: 'pointer',
                  borderColor: r.run_id === runId ? 'primary.main' : 'divider',
                  borderWidth: r.run_id === runId ? 2 : 1,
                }}
                onClick={() => selectRun(r.run_id)}
              >
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {r.agent_name}
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'monospace' }}>
                  {r.run_id}
                </Typography>
                <Box sx={{ mt: 0.5 }}>
                  <Chip size="small" color={r.hasTrace ? 'secondary' : 'default'} variant="outlined" label={r.hasTrace ? '含 trace' : '仅步骤'} />
                </Box>
              </Paper>
            ))}
            {runList.length === 0 && <EmptyState title="暂无运行记录" />}
          </Stack>
        </Grid>

        <Grid item xs={12} md={8}>
          {!runId || (!obsRun && !agentRun) ? (
            <EmptyState title="选择左侧运行" description="查看时间线、trace 与日志。" />
          ) : (
            <Stack spacing={2}>
              {/* 概览 */}
              <Card>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="h6" sx={{ flexGrow: 1 }}>
                      {agentRun?.agent_name ?? obsRun?.agent_name}
                    </Typography>
                    {agentRun && <StatusBadge status={agentRun.status} />}
                  </Stack>
                  <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'monospace' }}>
                    {runId}
                  </Typography>
                  {agentRun && (
                    <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
                      {agentRun.summary}
                    </Typography>
                  )}
                </CardContent>
              </Card>

              {/* 步骤时间线（来自 AgentRun.steps） */}
              {agentRun?.steps && agentRun.steps.length > 0 && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
                      运行步骤时间线
                    </Typography>
                    <Stack spacing={0}>
                      {agentRun.steps.map((s, i) => (
                        <Stack key={s.step_id} direction="row" spacing={1.5} sx={{ position: 'relative' }}>
                          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                            <Box
                              sx={{
                                width: 12,
                                height: 12,
                                borderRadius: '50%',
                                bgcolor: STEP_COLOR[s.status],
                                mt: 0.5,
                              }}
                            />
                            {i < agentRun.steps.length - 1 && (
                              <Box sx={{ width: 2, flexGrow: 1, bgcolor: 'divider' }} />
                            )}
                          </Box>
                          <Box sx={{ pb: 1.5 }}>
                            <Typography variant="body2" sx={{ fontWeight: 600 }}>
                              {s.name}
                            </Typography>
                            <Stack direction="row" spacing={0.5} sx={{ mt: 0.25 }}>
                              <Chip size="small" variant="outlined" label={s.kind} />
                              <StatusBadge status={s.status} />
                              {s.started_at && (
                                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                                  {dayjs(s.started_at).format('HH:mm:ss')}
                                </Typography>
                              )}
                            </Stack>
                          </Box>
                        </Stack>
                      ))}
                    </Stack>
                  </CardContent>
                </Card>
              )}

              {/* Trace 树 */}
              {traceTree.length > 0 && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>
                      Trace 树
                    </Typography>
                    {traceTree.map((node) => (
                      <TraceNode key={node.span_id} node={node} depth={0} />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* 续跑点 */}
              {obsRun?.resume_point && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                      续跑点（F9 持久化续跑）
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                      运行中断时可从 <Box component="span" sx={{ fontFamily: 'monospace', color: theme.palette.secondary.main }}>{obsRun.resume_point}</Box> 恢复，无需重跑。
                    </Typography>
                  </CardContent>
                </Card>
              )}

              {/* 日志 */}
              {obsRun?.logs && obsRun.logs.length > 0 && (
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" sx={{ mb: 1 }}>
                      结构化日志
                    </Typography>
                    <Paper variant="outlined" sx={{ bgcolor: 'background.default', p: 1.5, maxHeight: 260, overflow: 'auto' }}>
                      {obsRun.logs.map((l, i) => (
                        <Box
                          key={i}
                          sx={{ fontFamily: theme.typography.mono, fontSize: 12, lineHeight: 1.7 }}
                        >
                          <span style={{ color: theme.palette.text.secondary }}>
                            [{dayjs(l.ts).format('HH:mm:ss')}]
                          </span>{' '}
                          <span style={{ color: logColor(l.level, theme) }}>[{l.level.toUpperCase()}]</span>{' '}
                          <span style={{ color: theme.palette.text.primary }}>{l.message}</span>
                        </Box>
                      ))}
                    </Paper>
                  </CardContent>
                </Card>
              )}
            </Stack>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}

interface TraceNodeT extends TraceSpan {
  children: TraceNodeT[];
}

function buildTraceTree(spans: TraceSpan[]): TraceNodeT[] {
  const map = new Map<string, TraceNodeT>();
  spans.forEach((s) => map.set(s.span_id, { ...s, children: [] }));
  const roots: TraceNodeT[] = [];
  map.forEach((node) => {
    if (node.parent_id && map.has(node.parent_id)) {
      map.get(node.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function TraceNode({ node, depth }: { node: TraceNodeT; depth: number }) {
  return (
    <Box sx={{ ml: depth * 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.25 }}>
        <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: 'secondary.main' }} />
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {node.name}
        </Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {node.duration_ms}ms
        </Typography>
      </Box>
      {node.children.map((c) => (
        <TraceNode key={c.span_id} node={c} depth={depth + 1} />
      ))}
    </Box>
  );
}

function logColor(level: string, theme: Theme): string {
  switch (level) {
    case 'error':
      return theme.palette.error.main;
    case 'warn':
      return theme.palette.warning.main;
    case 'info':
      return theme.palette.info.main;
    default:
      return theme.palette.text.secondary;
  }
}
