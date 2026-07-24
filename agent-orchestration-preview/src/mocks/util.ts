import type { ISODateTime } from '@/types';

/** 模拟网络延迟（100–400ms 随机），用于 mock 读取函数贴近真实 API */
export const delay = (min = 100, max = 400): Promise<void> => {
  const ms = Math.floor(min + Math.random() * (max - min));
  return new Promise((resolve) => setTimeout(resolve, ms));
};

/** 深拷贝（避免组件修改污染原始 mock 常量） */
export const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/** 统一响应包装（模拟 API 返回结构） */
export interface ApiResponse<T> {
  code: number;
  data: T;
  message: string;
}

export const ok = <T>(data: T): ApiResponse<T> => ({ code: 0, data, message: 'ok' });

/** 当前时间的 ISO 字符串 */
export const nowISO = (): ISODateTime => new Date().toISOString();

/** 相对当前时间偏移若干分钟，返回 ISO 字符串 */
export const isoMinutesAgo = (minutes: number): ISODateTime =>
  new Date(Date.now() - minutes * 60 * 1000).toISOString();
