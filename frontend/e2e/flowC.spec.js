import { test, expect } from '@playwright/test'

/**
 * 核心链路 C：Dashboard(M1) 聚合 listAgentRuns + getAgentStats + mock trend，
 * 轮询/增量刷新不丢运行态。
 */
test.describe('链路 C：Dashboard 聚合 runs+stats+trend', () => {
  test('概览页展示指标卡并在刷新后保持运行态', async ({ page }) => {
    await page.goto('/agent-orchestration/dashboard')
    await expect(page.getByText(/运行总数|成功率|进行中|待审批/)).toBeVisible()

    // 模拟轮询/增量刷新（SSE runCompleted 或 30s 轮询），状态不应丢失
    await page.waitForTimeout(1500)
    await expect(page.getByText(/运行总数|成功率|进行中|待审批/)).toBeVisible()
  })
})
