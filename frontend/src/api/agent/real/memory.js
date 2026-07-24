/**
 * M5 记忆与 RAG 真实适配器（F3 后端就绪后启用）。
 * USE_MOCK.memory=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §5）。
 */
import request from '@/api/index'

const BASE = '/knowledge-bases' // TODO: 对齐后端 F3 真实路由

export function listKnowledgeBases() {
  return request({ url: BASE, method: 'GET' })
}
