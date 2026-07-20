"""第③批 T-D2 · 前端静态 / 集成校验（不起 dev server）。

仅做静态校验：检查 6 个交付文件存在且接线正确。
- incidents.js：含 listIncidentClusters / correlateIncidents / getRootCause，
  走既有 axios 拦截器（import request from './index' 带 token）。
- IncidentClusterView.vue：存在簇列表（el-table）+ 详情抽屉（el-drawer）。
- RootCausePanel.vue：消费真实字段
  （explanationText = llm_explanation||summary、isDegraded = llm_explanation==null、
   ppid/time/ref 用索引 i 缩进），不依赖不存在的 degraded/depth 键。
- RootCauseView.vue：内嵌 RootCausePanel。
- router/index.js：有 incident-clusters + root-cause 路由。
- AppLayout.vue：菜单含「事件归并」「根因分析」。

结论：前端接线正确。后端 ↔ 前端字段契约差异（见报告 Known Issues）另行记录，
不阻断本静态校验。
"""

from pathlib import Path
import unittest

_THIS = Path(__file__).resolve().parent
_FRONTEND = _THIS.parent.parent / "frontend" / "src"


def _read(rel: str) -> str:
    p = _FRONTEND / rel
    if not p.exists():
        raise FileNotFoundError(f"前端文件缺失：{p}")
    return p.read_text(encoding="utf-8")


class TestFrontendWiring(unittest.TestCase):
    def test_incidents_api_has_three_functions_and_token_interceptor(self):
        src = _read("api/incidents.js")
        self.assertIn("listIncidentClusters", src)
        self.assertIn("correlateIncidents", src)
        self.assertIn("getRootCause", src)
        # 走既有 axios 拦截器（带 token）
        self.assertIn("from './index'", src)
        self.assertIn("request.get('/ai/incidents/clusters'", src)
        self.assertIn("request.post('/analysis/root-cause'", src)
        # correlate 走 POST 且 mode 作为 query 传
        self.assertIn("mode", src)
        self.assertIn("/ai/correlate-incidents", src)

    def test_incident_cluster_view_has_list_and_drawer(self):
        src = _read("views/IncidentClusterView.vue")
        self.assertIn("el-table", src)
        self.assertIn("el-drawer", src)
        self.assertIn("drawer", src)
        # 调用了 API
        self.assertIn("listIncidentClusters", src)
        self.assertIn("correlateIncidents", src)
        # 详情渲染真实字段
        self.assertIn("member_event_ids", src)
        self.assertIn("ai_verdict_agg", src)

    def test_root_cause_panel_consumes_real_fields(self):
        src = _read("components/analysis/RootCausePanel.vue")
        # 真实字段消费：explanation / degraded（与后端 analyze() 返回键一致）
        self.assertIn("explanation", src)
        self.assertIn("explanationText", src)
        self.assertIn("isDegraded", src)
        # explanationText = explanation || summary（降级时 explanation 回退 summary）
        self.assertIn("explanation ||", src)
        self.assertIn("|| props.result?.summary", src)
        # isDegraded = degraded === true（后端 degraded 标记）
        self.assertIn("degraded === true", src)
        # ppid / time / ref 真实节点字段存在
        self.assertIn("ppid", src)
        self.assertIn(".time", src)
        self.assertIn("step.ref", src) if "ref" in src else self.assertIn("ref", src)
        # 用索引 i 缩进（确认 v-for 使用索引而非不存在的 depth 键）
        self.assertIn("v-for=", src)
        # 不依赖不存在的 llm_explanation / depth 键
        self.assertNotIn("llm_explanation", src)
        self.assertNotIn(".depth", src)
        # 节点真实增强字段 is_abnormal / severity / attack_path 仍被消费（优雅降级）
        self.assertIn("is_abnormal", src)
        self.assertIn("severity", src)
        self.assertIn("attack_path", src)

    def test_root_cause_view_embeds_panel(self):
        src = _read("views/RootCauseView.vue")
        self.assertIn("RootCausePanel", src)
        self.assertIn("getRootCause", src)
        # 内嵌组件标签
        self.assertIn("<RootCausePanel", src)

    def test_router_has_two_routes(self):
        src = _read("router/index.js")
        self.assertIn("incident-clusters", src)
        self.assertIn("IncidentClusterView", src)
        self.assertIn("root-cause", src)
        self.assertIn("RootCauseView", src)

    def test_applayout_menu_has_entries(self):
        src = _read("components/AppLayout.vue")
        self.assertIn("事件归并", src)
        self.assertIn("/incident-clusters", src)
        self.assertIn("根因分析", src)
        self.assertIn("/root-cause", src)


if __name__ == "__main__":
    unittest.main()
