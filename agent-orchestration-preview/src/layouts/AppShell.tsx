import { useEffect } from 'react';
import { Box, Drawer, useMediaQuery, useTheme } from '@mui/material';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { useAppStore } from '@/store/useAppStore';
import { useAgentStore } from '@/store/useAgentStore';
import { useHitlStore } from '@/store/useHitlStore';

/** 整体骨架：Sidebar（响应式折叠/抽屉） + TopBar + Outlet */
export function AppShell() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm')); // <768 移动
  const isTablet = useMediaQuery(theme.breakpoints.between('sm', 'md')); // 768–1279 平板

  const userCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const mobileOpen = useAppStore((s) => s.mobileOpen);
  const setMobileOpen = useAppStore((s) => s.setMobileOpen);

  const fetchAgents = useAgentStore((s) => s.fetchAgents);
  const fetchRuns = useAgentStore((s) => s.fetchRuns);
  const fetchTasks = useHitlStore((s) => s.fetchTasks);

  // 全局数据预取，保证各模块与角标有数据
  useEffect(() => {
    void fetchAgents();
    void fetchRuns();
    void fetchTasks();
  }, [fetchAgents, fetchRuns, fetchTasks]);

  // 平板强制图标栏；移动端用抽屉；桌面跟随用户折叠
  const effectiveCollapsed = isMobile ? false : isTablet ? true : userCollapsed;

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* 桌面 / 平板：常驻侧栏 */}
      {!isMobile && (
        <Box
          sx={{
            width: effectiveCollapsed ? 64 : 240,
            flexShrink: 0,
            transition: 'width .2s',
            borderRight: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Sidebar collapsed={effectiveCollapsed} onToggle={toggleSidebar} />
        </Box>
      )}

      {/* 移动端：抽屉侧栏 */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: 'block', sm: 'none' },
          '& .MuiDrawer-paper': { width: 240 },
        }}
      >
        <Sidebar collapsed={false} onNavigate={() => setMobileOpen(false)} />
      </Drawer>

      <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <TopBar />
        <Box
          component="main"
          sx={{ flexGrow: 1, p: { xs: 2, md: 3 }, overflowX: 'hidden' }}
        >
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}
