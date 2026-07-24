import { Card, CardContent, Box, Typography, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';
import type { ReactNode } from 'react';
import type { ChipProps } from '@mui/material';

export interface StatCardProps {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  /** 色调：决定图标背景与数值强调色 */
  tone?: ChipProps['color'];
  /** 趋势文本，如 '+12% 周环比' */
  trend?: string;
  onClick?: () => void;
}

/** 指标卡：Dashboard 与模块概览复用 */
export function StatCard({ label, value, icon, tone = 'primary', trend, onClick }: StatCardProps) {
  const theme = useTheme();
  const hex =
    tone === 'primary'
      ? theme.palette.primary.main
      : tone === 'default'
        ? theme.palette.text.secondary
        : (theme.palette[tone as 'info' | 'success' | 'warning' | 'error' | 'secondary']?.main ??
          theme.palette.primary.main);

  return (
    <Card
      sx={{
        height: '100%',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'transform .15s, border-color .15s',
        '&:hover': onClick ? { transform: 'translateY(-2px)', borderColor: 'primary.main' } : {},
      }}
      onClick={onClick}
    >
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            {label}
          </Typography>
          {icon && (
            <Box
              sx={{
                width: 36,
                height: 36,
                borderRadius: 2,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: hex,
                backgroundColor: alpha(hex, 0.12),
              }}
            >
              {icon}
            </Box>
          )}
        </Box>
        <Typography variant="h4" sx={{ mt: 1, fontWeight: 700, color: 'text.primary' }}>
          {value}
        </Typography>
        {trend && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {trend}
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
