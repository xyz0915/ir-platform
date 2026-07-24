import { create } from 'zustand';
import type { Role } from '@/types';

type ThemeMode = 'light' | 'dark';

interface PersistShape {
  mode: ThemeMode;
  role: Role;
}

const STORAGE_KEY = 'aop:app-prefs';

const readPersist = (): Partial<PersistShape> => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Partial<PersistShape>) : {};
  } catch {
    return {};
  }
};

const writePersist = (data: PersistShape): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    /* 忽略持久化失败（预览态） */
  }
};

interface AppState {
  /** 主题模式，默认暗色（SecOps 惯例） */
  mode: ThemeMode;
  /** 顶部角色切换器 */
  role: Role;
  /** 侧边栏是否折叠为图标栏（桌面） */
  sidebarCollapsed: boolean;
  /** 移动端抽屉是否打开 */
  mobileOpen: boolean;
  toggleMode: () => void;
  setMode: (mode: ThemeMode) => void;
  setRole: (role: Role) => void;
  toggleSidebar: () => void;
  setMobileOpen: (open: boolean) => void;
}

const initial = readPersist();

export const useAppStore = create<AppState>((set, get) => ({
  mode: initial.mode ?? 'dark',
  role: initial.role ?? 'analyst',
  sidebarCollapsed: false,
  mobileOpen: false,

  toggleMode: () => {
    const next: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
    set({ mode: next });
    writePersist({ mode: next, role: get().role });
  },

  setMode: (mode) => {
    set({ mode });
    writePersist({ mode, role: get().role });
  },

  setRole: (role) => {
    set({ role });
    writePersist({ mode: get().mode, role });
  },

  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  setMobileOpen: (open) => set({ mobileOpen: open }),
}));
