import { Box } from '@mui/material';
import type { Theme } from '@mui/material/styles';

export type RuntimeState = 'healthy' | 'degraded' | 'critical';

const COLOR: Record<RuntimeState, string> = {
  healthy: '#22C55E',
  degraded: '#F59E0B',
  critical: '#EF4444',
};

const LABEL: Record<RuntimeState, string> = {
  healthy: '运行正常',
  degraded: '部分降级',
  critical: '异常',
};

export interface RunStateDotProps {
  state: RuntimeState;
  /** 是否显示文字标签 */
  withLabel?: boolean;
  size?: number;
}

/** 运行态指示灯（绿/橙/红），带呼吸动画 */
export function RunStateDot({ state, withLabel = false, size = 10 }: RunStateDotProps) {
  const color = COLOR[state];
  return (
    <Box
      sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}
      title={LABEL[state]}
    >
      <Box
        sx={{
          width: size,
          height: size,
          borderRadius: '50%',
          backgroundColor: color,
          boxShadow: `0 0 0 0 ${color}`,
          animation: 'aop-pulse 1.8s infinite',
          '@keyframes aop-pulse': {
            '0%': { boxShadow: `0 0 0 0 ${hexToRgba(color, 0.5)}` },
            '70%': { boxShadow: `0 0 0 6px ${hexToRgba(color, 0)}` },
            '100%': { boxShadow: `0 0 0 0 ${hexToRgba(color, 0)}` },
          },
        }}
      />
      {withLabel && (
        <Box component="span" sx={(t: Theme) => ({ fontSize: 13, color: t.palette.text.secondary })}>
          {LABEL[state]}
        </Box>
      )}
    </Box>
  );
}

/** 将 hex 颜色转为带透明度的 rgba 字符串 */
function hexToRgba(hex: string, alpha: number): string {
  const v = hex.replace('#', '');
  const r = parseInt(v.substring(0, 2), 16);
  const g = parseInt(v.substring(2, 4), 16);
  const b = parseInt(v.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
