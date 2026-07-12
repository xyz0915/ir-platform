import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000
})

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
      if (status === 401) {
        localStorage.removeItem('ir_token')
        localStorage.removeItem('ir_user')
        ElMessage.error('登录已过期，请重新登录')
        router.push('/login')
      } else if (status === 404) {
        // 优先显示后端的具体错误信息
        const msg = error.response.data?.detail || '资源不存在'
        // 采集数据 Tab 端点可能未注册（users/services/usb/remote-control），不弹窗
        const url = error.config?.url || ''
        const isCollectionTab = /\/hosts\/\d+\/(users|services|usb|remote-control)$/.test(url)
        if (!isCollectionTab) {
          ElMessage.error(msg)
        }
      } else if (status >= 500) {
        ElMessage.error('服务器内部错误')
      } else {
        const msg = error.response.data?.detail || error.response.data?.message || '请求失败'
        ElMessage.error(msg)
      }
    } else {
      ElMessage.error('网络连接异常')
    }
    return Promise.reject(error)
  }
)

export default request
