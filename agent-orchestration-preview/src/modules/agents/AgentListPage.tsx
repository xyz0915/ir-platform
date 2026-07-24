import { useState } from 'react';
import { Box, Button, Card, CardContent, Chip, Grid, Stack, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { ContentSkeleton } from '@/components/shared/ContentSkeleton';
import { EmptyState } from '@/components/shared/EmptyState';
import { useAgentStore } from '@/store/useAgentStore';
import { listToolsSync } from '@/mocks/tools';
import { listModelProfilesSync } from '@/mocks/settings';
import type { AgentConfig } from '@/types';
import { AgentDetailDrawer } from './AgentDetailDrawer';
import { AgentForm } from './AgentForm';

export function AgentListPage() {
  const agents = useAgentStore((s) => s.agents);
  const loading = useAgentStore((s) => s.loadingAgents);
  const profiles = listModelProfilesSync();
  const tools = listToolsSync();

  const [detail, setDetail] = useState<AgentConfig | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(false);

  const openDetail = (a: AgentConfig) => {
    setDetail(a);
    setDetailOpen(true);
  };

  return (
    <Box>
      <PageHeader
        title="智能体管理"
        subtitle="内置 + 自定义 Agent 列表、详情与配置（F2 修空壳 / M0）"
        action={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setFormOpen(true)}>
            新建自定义 Agent
          </Button>
        }
      />

      {loading && agents.length === 0 ? (
        <ContentSkeleton count={6} />
      ) : agents.length === 0 ? (
        <EmptyState
          icon={<SmartToyIcon />}
          title="暂无 Agent"
          description="点击「新建自定义 Agent」创建一个。"
          action={<Button variant="contained" onClick={() => setFormOpen(true)}>新建</Button>}
        />
      ) : (
        <Grid container spacing={2}>
          {agents.map((a) => {
            const profileName = profiles.find((p) => p.profile_id === a.model_profile)?.name ?? a.model_profile;
            return (
              <Grid item xs={12} sm={6} md={4} key={a.agent_id}>
                <Card
                  sx={{ height: '100%', cursor: 'pointer', '&:hover': { borderColor: 'primary.main' } }}
                  onClick={() => openDetail(a)}
                >
                  <CardContent>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                      <SmartToyIcon color={a.kind === 'builtin' ? 'primary' : 'secondary'} />
                      <Typography variant="subtitle1" sx={{ fontWeight: 700, flexGrow: 1 }}>
                        {a.display_name}
                      </Typography>
                      <StatusBadge status={a.kind} label={a.kind === 'builtin' ? '内置' : '自定义'} />
                    </Stack>
                    <Typography
                      variant="body2"
                      sx={{ color: 'text.secondary', mb: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                    >
                      {a.description}
                    </Typography>
                    <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
                      {a.data_sources.slice(0, 3).map((d) => (
                        <Chip key={d} size="small" variant="outlined" label={d} />
                      ))}
                      {a.data_sources.length > 3 && (
                        <Chip size="small" label={`+${a.data_sources.length - 3}`} />
                      )}
                    </Stack>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        工具 {a.tools.length} · {profileName}
                      </Typography>
                      <StatusBadge status={a.status} />
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      <AgentDetailDrawer agent={detail} open={detailOpen} onClose={() => setDetailOpen(false)} />
      <AgentForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  );
}
