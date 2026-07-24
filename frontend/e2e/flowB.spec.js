import { test, expect } from '@playwright/test'

/**
 * 核心链路 B：HITL 上下文面板渲染 guardrail_result（M6 × M7 协同）。
 * 审批面板点击某待审任务后，上下文面板应展示 useGuardrail().evaluate 计算的
 * GuardrailResult（whitelist_hit / requires_confirm / requires_rollback_plan / passed）。
 */
test.describe('链路 B：HITL 上下文面板渲染 guardrail_result', () => {
  test('审批面板展示护栏计算结果', async ({ page }) => {
    await page.goto('/agent-orchestration/hitl')
    await page.getByText(/待审批|pending|waiting_hitl/).first().click()

    // 上下文面板渲染护栏结果（热插拔：Mock 或后端 F8 真实评估）
    await expect(
      page.getByText(/护栏|guardrail|whitelist_hit|requires_confirm|requires_rollback_plan|passed/),
    ).toBeVisible()
  })
})
