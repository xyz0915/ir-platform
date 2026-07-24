/**
 * M9 设置 真实适配器（F10/F14 后端就绪后启用）。
 * USE_MOCK.settings=false 时由 facade 切换至此，调用方零改动。
 * 端点 URL 为文档化约定（对齐 01-api-spec.md §9）。
 */
import request from '@/api/index'

const BASE = '/settings' // TODO: 对齐后端 F10/F14 真实路由

export function listModelProfiles() {
  return request({ url: `${BASE}/model-profiles`, method: 'GET' })
}
export function getDeploymentConfig() {
  return request({ url: `${BASE}/deployment`, method: 'GET' })
}
