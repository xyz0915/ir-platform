/**
 * M9 设置 真实适配器（F10 / F14 后端就绪后启用）。
 *
 * - listModelProfiles：F10 重定向到 /api/ai/profiles（跨前缀绝对路径），
 *   并把后端 items[]（id/profile_name/model_name/is_active）映射为前端
 *   ModelProfile（profile_id/name/model/enabled），使 store 零改动（07 §4.3 / §5.3）。
 * - getDeploymentConfig：由 USE_MOCK.settingsDeployment 门控，B 档默认仍走 Mock；
 *   后端 F14 就绪后翻 false 即直连 /api/settings/deployment（形状同构，直接透传）。
 *
 * 设计依据：07-arch-decomposition.md §4.3 / §4.4 / §5.3 / §5.5。
 */
import request from '@/api/index'

const BASE = '/settings' // F14 deployment 端点前缀（07 §4.4）

/**
 * 后端 AiConfigProfile（脱敏后）字段 → 前端 ModelProfile 字段映射。
 * @param {Object} p 后端 profile 记录
 * @returns {{profile_id:any,name:string,provider:string,model:string,enabled:boolean}}
 */
function mapProfile(p) {
  return {
    profile_id: p.id,
    name: p.profile_name,
    provider: p.provider,
    model: p.model_name,
    enabled: !!p.is_active,
  }
}

export function listModelProfiles() {
  // F10 重定向：跨命名空间端点。axios baseURL='/api'，故 url 用相对路径即可。
  return request({ url: '/ai/profiles', method: 'GET' }).then((res) => {
    const items = (res && res.data && res.data.items) || []
    const mapped = items.map(mapProfile)
    return { code: 0, data: mapped, message: 'success' }
  })
}

export function getDeploymentConfig() {
  // F14 后端聚合端点：返回 DeploymentConfig，与 Mock 同构，直接透传。
  return request({ url: `${BASE}/deployment`, method: 'GET' })
}
