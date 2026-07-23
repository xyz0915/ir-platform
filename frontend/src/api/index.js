import axios from 'axios'
import { ElMessage, ElNotification } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000
})

/**
 * 判断 URL 是否为分析中心事件详情相关的端点.
 * 对这些端点的错误做特殊处理（避免在事件详情页弹出多个冗余通知）.
 */
function isEventDetailEndpoint(url) {
  return /\/analysis\/events\/[^/]+(\/|$)/.test(url)
}

/**
 * 判断是否为"采集数据 Tab"端点（可能未注册，静默处理）.
 */
function isCollectionTabEndpoint(url) {
  return /\/hosts\/\d+\/(users|services|usb|remote-control)$/.test(url)
}

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('ir_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

request.interceptors.response.use(
  (response) => {
    const res = response.data
    if (res.code !== undefined && res.code !== 0) {
      ElMessage.error(res.message || '请求失败')
      return Promise.reject(new Error(res.message || 'Error'))
    }
    return res
  },
  (error) => {
    if (error.response) {
      const status = error.response.status
      const url = error.config?.url || ''
      const detail = error.response.data?.detail || ''

      if (status === 401) {
        localStorage.removeItem('ir_token')
        localStorage.removeItem('ir_user')
        ElMessage.error('登录已过期，请重新登录')
        router.push('/login')
        return Promise.reject(error)
      }

      // 采集数据 Tab 端点静默忽略
      if (isCollectionTabEndpoint(url)) {
        return Promise.reject(error)
      }

      // ── 业务错误（4xx）：友好的业务提示，非中文后端消息则使用通用文案 ──
      if (status >= 400 && status < 500) {
        let msg = detail || ''
        // 如果是事件详情端点的 404（事件不存在），使用更友好的提示
        if (status === 404 && isEventDetailEndpoint(url)) {
          msg = '事件不存在或已被删除'
        } else if (!msg) {
          // 后端未返回具体错误信息时，按状态码给出通用文案
          const statusMessages = {
            400: '请求参数错误',
            403: '权限不足，无法访问',
            404: '请求的资源不存在',
            405: '请求方法不允许',
            409: '资源冲突',
            422: '请求数据格式有误',
          }
          msg = statusMessages[status] || '请求失败'
        }
        ElNotification({
          title: '提示',
          message: msg,
          type: 'warning',
          duration: 4000,
          position: 'top-right',
        })
        return Promise.reject(error)
      }

      // ── 系统错误（5xx）：服务端内部错误 ──
      if (status >= 500) {
        ElNotification({
          title: '系统错误',
          message: '服务端内部错误，请稍后重试',
          type: 'error',
          duration: 6000,
          position: 'top-right',
        })
        return Promise.reject(error)
      }
    } else {
      ElMessage.error('网络连接异常')
    }
    return Promise.reject(error)
  }
)

export default request
