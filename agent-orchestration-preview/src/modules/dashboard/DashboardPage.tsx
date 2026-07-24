import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Card, CardContent, CardHeader, Divider, Grid, Stack, Typography } from '@mui/material';
import { LineChart, PieChart } from '@mui/x-charts';
import dayjs from 'dayjs';
import PlayCircleOutlineIcon from '@mui/icons-material/PlayCircleOutline';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import GppGoodIcon from '@mui/icons-material/GppGood';
import ShieldIcon from '@mui/icons-material/Shield';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { DataTable, type Column } from '@/components/shared/DataTable';
import { useElementWidth } from '@/components/shared/useElementWidth';
import { EmptyState } from '@/components/shared/EmptyState';
import { useTheme } from '@mui/material';
import { useHitlStore } from '@/store/useHitlStore';
import { useAgentStore } from '@/store/useAgentStore';
import { getDashboardStats } from '@/mocks/dashboard';
import type { AgentRun, DashboardStats } from '@/types';

const RUN_STATUS_COLORS = ['#22C55E', '#EF4444', '#F59E0B', '#3B82F6', '#94A3B8'];

export function DashboardPage() {
  const theme = useTheme();
  const navigate = useNavigate();

  const pending = useHitlStore((s) => s.tasks.filter((t) => t.status === 'pending').length);
  const runs = useAgentStore((s) => s.runs);

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  const { ref: lineRef, width: lineWidth } = useElementWidth<HTMLDivElement>();
  const { ref: pieRef, width: pieWidth } = useElementWidth<HTMLDivElement>();

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getDashboardStats().then((res) => {
      if (alive) {
        setStats(res.data);
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  // 运行中智能体：优先用 store（含流水线运行时），否则用聚合值
  const runningAgents = useMemo(() => {
    const storeRunning = runs.filter((r) => r.status === 'running').length;
    return storeRunning || stats?.running_agents || 0;
  }, [runs, stats]);

  const pieData = useMemo(() => {
    const base = stats?.recent_runs ?? runs;
    const counts: Record<string, number> = {};
    base.forEach((r) => {
      counts[r.status] = (counts[r.status] ?? 0) + 1;
    });
    return Object.entries(counts).map(([k, v]) => ({ id: k, value: v, label: labelOf(k) }));
  }, [stats, runs]);

  const columns: Column<AgentRun>[] = [
    {
      key: 'run_id',
      label: '运行 ID',
      render: (r) => <Typography variant="body2" sx={{ fontFamily: theme.typography.mono }}>{r.run_id}</Typography>,
    },
    { key: 'agent_name', label: '智能体' },
    { key: 'status', label: '状态', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'trigger', label: '触发' },
    {
      key: 'started_at',
      label: '开始时间',
      render: (r) => dayjs(r.started_at).format('MM-DD HH:mm'),
    },
    {
      key: 'op',
      label: '操作',
      render: (r) => (
        <Typography
          variant="body2"
          sx={{ color: 'primary.main', cursor: 'pointer' }}
          onClick={() => navigate(`/observability?run=${r.run_id}`)}
        >
          查看详情
        </Typography>
      ),
    },
  ];

  return (
    <Box>
      <PageHeader title="概览 Dashboard" subtitle="团队运行态势、成功率与待审任务一览（SecOps 安全主线）" />

      <Grid container spacing={2}>
        <Grid item xs={6} md={3}>
          <StatCard
            label="运行中智能体"
            value={loading ? '—' : runningAgents}
            icon={<PlayCircleOutlineIcon />}
            tone="info"
            trend="实时运行态"
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            label="运行成功率"
            value={loading ? '—' : `${stats?.success_rate ?? 0}%`}
            icon={<CheckCircleOutlineIcon />}
            tone="success"
            trend="近 7 日均值"
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            label="待审 HITL"
            value={pending}
            icon={<GppGoodIcon />}
            tone="warning"
            trend="需人工确认"
            onClick={() => navigate('/hitl')}
          />
        </Grid>
        <Grid item xs={6} md={3}>
          <StatCard
            label="护栏拦截"
            value={loading ? '—' : stats?.guardrail_blocks ?? 0}
            icon={<ShieldIcon />}
            tone="error"
            trend="未通过护栏"
            onClick={() => navigate('/guardrail')}
          />
        </Grid>

        {/* 趋势图 */}
        <Grid item xs={12} md={8}>
          <Card>
            <CardHeader title="运行成功率趋势（近 7 日）" />
            <Divider />
            <CardContent>
              <Box ref={lineRef} sx={{ width: '100%' }}>
                {lineWidth > 0 && stats && (
                  <LineChart
                    width={lineWidth}
                    height={260}
                    series={[{ data: stats.trend.map((t) => t.success_rate), label: '成功率(%)', area: true, color: '#3B82F6' }]}
                    xAxis={[{ scaleType: 'point', data: stats.trend.map((t) => dayjs(t.ts).format('MM-DD')) }]}
                    sx={{
                      '& .MuiChartsAxis-tickLabel': { fill: theme.palette.text.secondary },
                      '& .MuiChartsAxis-line': { stroke: theme.palette.divider },
                      '& .MuiChartsGrid-line': { stroke: theme.palette.divider },
                    }}
                  />
                )}
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* 运行分布 */}
        <Grid item xs={12} md={4}>
          <Card sx={{ height: '100%' }}>
            <CardHeader title="近期运行状态分布" />
            <Divider />
            <CardContent>
              <Box ref={pieRef} sx={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
                {pieWidth > 0 && pieData.length > 0 ? (
                  <PieChart
                    width={Math.min(pieWidth, 320)}
                    height={240}
                    series={[
                      {
                        data: pieData,
                        innerRadius: 40,
                        outerRadius: 90,
                        paddingAngle: 2,
                        cornerRadius: 4,
                      },
                    ]}
                    colors={RUN_STATUS_COLORS}
                    sx={{ '& .MuiChartsLegend-root': { display: 'none' } }}
                  />
                ) : (
                  <EmptyState title="暂无运行数据" />
                )}
              </Box>
              <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', justifyContent: 'center', mt: 1 }}>
                {pieData.map((d, i) => (
                  <Box key={d.id} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: RUN_STATUS_COLORS[i % RUN_STATUS_COLORS.length] }} />
                    <Typography variant="caption">{d.label} {d.value}</Typography>
                  </Box>
                ))}
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        {/* 近期运行 */}
        <Grid item xs={12}>
          <Card>
            <CardHeader title="近期运行" subheader="点击查看运行 timeline / trace / 日志" />
            <Divider />
            <CardContent>
              <DataTable
                columns={columns}
                rows={stats?.recent_runs ?? []}
                rowKey={(r) => r.run_id}
                empty={<EmptyState title="暂无运行记录" />}
              />
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}

function labelOf(status: string): string {
  const map: Record<string, string> = {
    running: '运行中',
    success: '成功',
    failed: '失败',
    waiting_hitl: '等待审核',
    pending: '排队中',
    cancelled: '已取消',
  };
  return map[status] ?? status;
}
