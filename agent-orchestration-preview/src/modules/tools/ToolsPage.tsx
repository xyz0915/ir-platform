import { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import SchemaIcon from '@mui/icons-material/Schema';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { JsonViewer } from '@/components/shared/JsonViewer';
import { EmptyState } from '@/components/shared/EmptyState';
import { getTools, getMcpServers } from '@/mocks/tools';
import type { McpServer, ToolDef } from '@/types';
import { McpServerList } from './McpServerList';

export function ToolsPage() {
  const [tools, setTools] = useState<ToolDef[]>([]);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getTools(), getMcpServers()]).then(([t, s]) => {
      if (!alive) return;
      setTools(t.data);
      setServers(s.data);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const serverName = useMemo(() => {
    const map = new Map(servers.map((s) => [s.server_id, s.name]));
    return (id?: string) => (id ? map.get(id) ?? id : '内置');
  }, [servers]);

  return (
    <Box>
      <PageHeader
        title="工具与 MCP"
        subtitle="ToolRegistry 工具生态与 MCP 服务器状态（F1 / M2）"
      />

      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        工具注册表（{tools.length}）
      </Typography>
      {loading ? (
        <EmptyState title="加载中…" />
      ) : (
        <Grid container spacing={2}>
          {tools.map((t) => (
            <Grid item xs={12} sm={6} md={4} key={t.tool_id}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, flexGrow: 1 }}>
                      {t.name}
                    </Typography>
                    <StatusBadge status={t.status} />
                  </Stack>
                  <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1, minHeight: 40 }}>
                    {t.description}
                  </Typography>
                  <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5, mb: 1 }}>
                    <Chip size="small" variant="outlined" label={t.category} />
                    <Chip size="small" variant="outlined" label={`MCP: ${serverName(t.mcp_server_id)}`} />
                  </Stack>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    幂等键：<Box component="span" sx={{ fontFamily: 'monospace' }}>{t.idempotency_key}</Box>
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    超时 {t.timeout_ms}ms · 重试 {t.retries}
                  </Typography>
                  <Box sx={{ mt: 1, textAlign: 'right' }}>
                    <IconButton
                      size="small"
                      onClick={() => setExpanded((prev) => (prev === t.tool_id ? null : t.tool_id))}
                      aria-label="预览 schema"
                    >
                      <SchemaIcon fontSize="small" />
                    </IconButton>
                  </Box>
                  {expanded === t.tool_id && (
                    <Box sx={{ mt: 1 }}>
                      <JsonViewer value={t.schema} maxHeight={180} title="JSON Schema" />
                    </Box>
                  )}
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <Divider sx={{ my: 3 }} />

      <McpServerList servers={servers} loading={loading} />
    </Box>
  );
}
