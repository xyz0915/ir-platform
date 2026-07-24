import { Box, Skeleton, Stack } from '@mui/material';

export interface ContentSkeletonProps {
  /** 卡片数量 */
  count?: number;
}

/** 加载骨架占位 */
export function ContentSkeleton({ count = 6 }: ContentSkeletonProps) {
  return (
    <Box
      sx={{
        display: 'grid',
        gap: 2,
        gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: 'repeat(3, 1fr)' },
      }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <Stack key={i} spacing={1} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
          <Skeleton variant="text" width="40%" />
          <Skeleton variant="rectangular" height={24} />
          <Skeleton variant="text" width="80%" />
        </Stack>
      ))}
    </Box>
  );
}
