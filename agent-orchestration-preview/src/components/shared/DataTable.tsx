import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Paper } from '@mui/material';
import type { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  label: string;
  align?: 'left' | 'center' | 'right';
  /** 自定义单元格渲染；缺省直接取 row[key] */
  render?: (row: T) => ReactNode;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
}

/** 通用表格封装（自动斑马纹 + 圆角容器） */
export function DataTable<T>({ columns, rows, rowKey, empty }: DataTableProps<T>) {
  if (rows.length === 0 && empty) {
    return <>{empty}</>;
  }
  return (
    <TableContainer component={Paper} sx={{ border: '1px solid', borderColor: 'divider' }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            {columns.map((c) => (
              <TableCell key={c.key} align={c.align ?? 'left'} sx={{ fontWeight: 700 }}>
                {c.label}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, i) => (
            <TableRow
              key={rowKey(row)}
              sx={{ '&:nth-of-type(even)': { backgroundColor: (t) => t.palette.action.hover } }}
            >
              {columns.map((c) => (
                <TableCell key={c.key} align={c.align ?? 'left'}>
                  {c.render ? c.render(row) : ((row as Record<string, ReactNode>)[c.key] ?? '—')}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
