import { Box, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Typography, Chip, Badge, Button } from '@mui/material';
import type { ReactNode } from 'react';
import { useLocation, NavLink } from 'react-router-dom';
import DashboardIcon from '@mui/icons-material/Dashboard';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ExtensionIcon from '@mui/icons-material/Extension';
import StorageIcon from '@mui/icons-material/Storage';
import GppGoodIcon from '@mui/icons-material/GppGood';
import ShieldIcon from '@mui/icons-material/Shield';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import SettingsIcon from '@mui/icons-material/Settings';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import { useHitlStore } from '@/store/useHitlStore';

interface NavItem {
  path: string;
  label: string;
  icon: ReactNode;
  badge?: boolean;
}

const NAV: NavItem[] = [
  { path: '/dashboard', label: '概览 Dashboard', icon: <DashboardIcon /> },
  { path: '/agents', label: '智能体管理', icon: <SmartToyIcon /> },
  { path: '/pipeline', label: '流水线编排', icon: <AccountTreeIcon /> },
  { path: '/tools', label: '工具与 MCP', icon: <ExtensionIcon /> },
  { path: '/memory', label: '记忆与 RAG', icon: <StorageIcon /> },
  { path: '/hitl', label: '人工审核台', icon: <GppGoodIcon />, badge: true },
  { path: '/guardrail', label: '护栏与安全', icon: <ShieldIcon /> },
  { path: '/observability', label: '可观测性', icon: <MonitorHeartIcon /> },
  { path: '/settings', label: '设置', icon: <SettingsIcon /> },
];

export interface SidebarProps {
  collapsed: boolean;
  onNavigate?: () => void;
  onToggle?: () => void;
}

/** 左侧可折叠侧边栏（9 模块导航） */
export function Sidebar({ collapsed, onNavigate, onToggle }: SidebarProps) {
  const { pathname } = useLocation();
  const pending = useHitlStore((s) => s.tasks.filter((t) => t.status === 'pending').length);

  return (
    <Box
      sx={{
        width: collapsed ? 64 : 240,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: '100vh',
        transition: 'width .2s',
        overflowX: 'hidden',
        bgcolor: 'background.paper',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          px: collapsed ? 0 : 2,
          justifyContent: collapsed ? 'center' : 'flex-start',
          height: 64,
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
      >
        <ShieldIcon color="primary" />
        {!collapsed && (
          <Typography variant="subtitle1" sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
            智能体编排
          </Typography>
        )}
      </Box>

      <List sx={{ flexGrow: 1, py: 1 }}>
        {NAV.map((item) => {
          const active = pathname === item.path || pathname.startsWith(item.path + '/');
          return (
            <ListItem key={item.path} disablePadding sx={{ px: 1 }}>
              <ListItemButton
                component={NavLink}
                to={item.path}
                onClick={onNavigate}
                selected={active}
                sx={{
                  borderRadius: 2,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  minHeight: 44,
                  '&.Mui-selected': {
                    bgcolor: 'primary.main',
                    color: '#fff',
                    '&:hover': { bgcolor: 'primary.dark' },
                    '& .MuiListItemIcon-root': { color: '#fff' },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: collapsed ? 0 : 40, justifyContent: 'center' }}>
                  {item.badge && pending > 0 && collapsed ? (
                    <Badge color="error" badgeContent={pending}>
                      {item.icon}
                    </Badge>
                  ) : (
                    item.icon
                  )}
                </ListItemIcon>
                {!collapsed && <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: 14, fontWeight: active ? 700 : 500 }} />}
                {!collapsed && item.badge && pending > 0 && (
                  <Chip size="small" color="error" label={pending} />
                )}
              </ListItemButton>
            </ListItem>
          );
        })}
      </List>

      {onToggle && (
        <Box sx={{ p: 1.5, borderTop: '1px solid', borderColor: 'divider' }}>
          <Button
            fullWidth
            onClick={onToggle}
            startIcon={collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
            sx={{ justifyContent: collapsed ? 'center' : 'flex-start', color: 'text.secondary' }}
          >
            {!collapsed && '收起侧栏'}
          </Button>
        </Box>
      )}
    </Box>
  );
}
