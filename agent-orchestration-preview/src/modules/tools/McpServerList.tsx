import { Box, Card, CardContent, Chip, Stack, Typography } from '@mui/material';
import DnsIcon from '@mui/icons-material/Dns';
import dayjs from 'dayjs';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { EmptyState } from '@/components/shared/EmptyState';
import type { McpServer } from '@/types';

export interface McpServerListProps {
  servers: McpServer[];
  loading: boolean;
}

/** MCP 服务器状态列表 */
export function McpServerList({ servers, loading }: McpServerListProps) {
  return (
    <Box>
      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        MCP 服务器（{servers.length}）
      </Typography>
      {loading ? (
        <EmptyState title="加载中…" />
      ) : (
        <Stack spacing={1.5}>
          {servers.map((s) => (
            <Card key={s.server_id}>
              <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <DnsIcon color={s.status === 'online' ? 'success' : s.status === 'degraded' ? 'warning' : 'error'} />
                <Box sx={{ flexGrow: 1 }}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                    {s.name}
                  </Typography>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    传输 {s.transport} · 工具 {s.tools_count} · 心跳 {dayjs(s.last_heartbeat).format('HH:mm:ss')}
                  </Typography>
                </Box>
                <Chip size="small" variant="outlined" label={s.server_id} sx={{ fontFamily: 'monospace' }} />
                <StatusBadge status={s.status} />
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Box>
  );
}
