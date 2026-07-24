import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  build: {
    emptyOutDir: false,
    rollupOptions: {
      output: {
        // 工程卫生：按包归类拆 vendor chunk，避免单包过大、提升缓存命中
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('element-plus') || id.includes('@element-plus')) return 'element-vendor'
            if (id.includes('echarts') || id.includes('zrender') || id.includes('vue-echarts')) return 'echarts-vendor'
            if (id.includes('vue') || id.includes('pinia') || id.includes('vue-router') || id.includes('@vue')) return 'vue-vendor'
            return 'vendor'
          }
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  test: {
    env: { TZ: "Asia/Shanghai" },
    environment: 'happy-dom',
    globals: true,
    // e2e 目录为 Playwright 浏览器级测试，不纳入 vitest 单测
    exclude: ['**/node_modules/**', '**/dist/**', 'e2e/**', 'tests-e2e/**'],
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
