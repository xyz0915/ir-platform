import { test, expect } from '@playwright/test'

/**
 * 核心链路 A：创建智能体(M2) → 编排执行(M3 runPipeline 返回 run_id)
 *            → 产生 HITL 任务(M6) → 批准 → 可观测(M8) 出现 trace/日志。
 * 依赖真实/ Mock 后端运行（见 e2e/README.md）。
 */
test.describe('链路 A：智能体创建 → 编排执行 → HITL 批准 → 可观测', () => {
  test('端到端走通编排闭环', async ({ page }) => {
    // ── M2 智能体管理：新建智能体 ──
    await page.goto('/agent-orchestration/agents')
    await page.getByRole('button', { name: /新建|新增|创建/ }).click()
    await page.getByLabel(/名称|name/i).fill('e2e-agent')
    await page.getByRole('button', { name: /保存|创建|确定/ }).click()
    await expect(page.getByText('e2e-agent')).toBeVisible()

    // ── M3 流水线 DAG：进入画布并启动，得到 run_id ──
    await page.goto('/agent-orchestration/pipeline')
    await page.getByRole('button', { name: /启动|执行|运行/ }).click()
    await page.goto('/agent-orchestration/runs')
    await expect(page.getByText(/run-/)).toBeVisible()

    // ── M6 人工审核台：出现待审任务并批准 ──
    await page.goto('/agent-orchestration/hitl')
    const pending = page.getByText(/待审批|pending|waiting_hitl/).first()
    await expect(pending).toBeVisible()
    await page.getByRole('button', { name: /批准|通过|approve/i }).click()

    // ── M8 可观测性：运行详情出现 trace/日志 ──
    await page.goto('/agent-orchestration/runs')
    await page.getByText(/run-/).first().click()
    await page.getByRole('button', { name: '可观测性' }).click()
    await expect(page.getByText(/trace|日志|步骤|step/)).toBeVisible()
  })
})
