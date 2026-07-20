"""第②批 T-A3 前端静态/集成校验（不起 dev server）。

逐文件校验前端接线正确性：
- agentOrchestration.js 含 6 个 API 封装且复用既有 axios 拦截器（自动带 token）。
- stores/agents.js 接入 6 个 API 并暴露动作。
- AgentRunView.vue 内嵌 HitlApprovalPanel。
- router/index.js 注册 agent-orchestration 路由 → AgentRunView。
- AppLayout.vue 加入「智能体编排」菜单。
- api/index.js 的 axios 拦截器自动注入 ir_token。

结论：前端接线正确（仅静态校验，人工联调建议见报告）。
"""

import os
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
# 前端位于 backend/ 的同级目录（项目根/frontend/src），而非 backend/frontend/src
_FRONTEND = os.path.normpath(os.path.join(_BACKEND, "..", "frontend", "src"))


def _read(rel):
    with open(os.path.join(_FRONTEND, rel), "r", encoding="utf-8") as f:
        return f.read()


class TestFrontendWiring(unittest.TestCase):
    def test_agent_orchestration_api_calls(self):
        src = _read("api/agentOrchestration.js")
        for fn in ("createAgentRun", "listAgentRuns", "getAgentRun",
                   "approveAgentRun", "rejectAgentRun", "listPendingApprovals"):
            self.assertIn(f"export function {fn}", src,
                           f"缺少封装函数 {fn}")
        # 复用既有 axios 实例（自动带 token）
        self.assertIn("import request from './index'", src)
        # 路径前缀统一 /agents
        for path in ("/agents/run", "/agents/runs", "/agents/approvals"):
            self.assertIn(path, src)

    def test_agent_store_actions(self):
        src = _read("stores/agents.js")
        for fn in ("createAgentRun", "listAgentRuns", "getAgentRun",
                   "approveAgentRun", "rejectAgentRun", "listPendingApprovals"):
            self.assertIn(fn, src, f"store 未接入 {fn}")
        for action in ("fetchRuns", "fetchRunDetail", "startRun",
                      "fetchApprovals", "approve", "reject"):
            self.assertIn(action, src, f"store 未暴露动作 {action}")

    def test_agent_run_view_embeds_hitl_panel(self):
        src = _read("views/AgentRunView.vue")
        self.assertIn(
            "import HitlApprovalPanel from '@/components/agents/HitlApprovalPanel.vue'",
            src)
        self.assertIn("<HitlApprovalPanel", src)

    def test_router_registers_agent_orchestration(self):
        src = _read("router/index.js")
        self.assertIn("path: 'agent-orchestration'", src)
        self.assertIn("AgentRunView", src)

    def test_applayout_has_menu_item(self):
        src = _read("components/AppLayout.vue")
        self.assertIn("智能体编排", src)
        self.assertIn("/agent-orchestration", src)

    def test_axios_interceptor_injects_token(self):
        src = _read("api/index.js")
        self.assertIn("interceptors.request.use", src)
        self.assertIn("ir_token", src)
        self.assertIn("Bearer", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
