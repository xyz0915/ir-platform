import { defineConfig } from '@playwright/test'

/**
 * 智能体编排模块 — 浏览器级端到端测试配置。
 *
 * ⚠️ 当前仅作规格留存：后端（F1/F3/F7/F8/F10/F14）尚未就绪，且本沙箱未安装
 * Playwright 浏览器，请勿直接 `npm run e2e`。待后端就绪后：
 *   1) npm i -D @playwright/test
 *   2) npx playwright install chromium
 *   3) 另开终端 npm run dev（或放开下方 webServer）
 *   4) npm run e2e
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL: 'http://localhost:5173',
    headless: true,
    trace: 'on-first-retry',
  },
  // 如需 playwright 自管 dev server，取消注释：
  // webServer: {
  //   command: 'npm run dev',
  //   url: 'http://localhost:5173',
  //   reuseExistingServer: true,
  // },
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
})
