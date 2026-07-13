import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: '0.0.0.0',  // 允许通过 IP 访问
    proxy: {
      // AI 分析 SSE 专用代理 — 强制关闭缓冲，让 complete 事件实时到达
      '/api/ai/': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: false,
        // 不缓存任何内容
        selfHandleResponse: false,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            // 关闭 nginx 风格的反向代理缓冲
            proxyReq.setHeader('X-Accel-Buffering', 'no')
            proxyReq.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
            proxyReq.setHeader('Pragma', 'no-cache')
          })
          proxy.on('proxyRes', (proxyRes, req) => {
            // 后端返回的是 SSE，代理层不要缓存
            proxyRes.headers['X-Accel-Buffering'] = 'no'
            proxyRes.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
          })
        }
      },
      // 其他 API 走通用代理
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
