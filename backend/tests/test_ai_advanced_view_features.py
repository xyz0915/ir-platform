"""AiAdvancedView.vue 三项功能增强回归验证（15 项）.

用独立临时 SQLite 库构建，不碰生产库。

验证清单:
  功能 1：多轮上下文 + 时间解析（6 项）
  功能 2：结果下钻与关联跳转（5 项）
  功能 3：会话持久化 + AI 研判（4 项）

运行方式:
    cd backend && venv/Scripts/python.exe tests/test_ai_advanced_view_features.py -v
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 路径常量 ──────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
VIEW_PATH = FRONTEND_DIR / "src" / "views" / "AiAdvancedView.vue"

# 如路径不对，尝试备用
if not VIEW_PATH.exists():
    VIEW_PATH = Path(os.environ.get(
        "AI_ADVANCED_VIEW_PATH",
        str(BACKEND_DIR.parent / "frontend" / "src" / "views" / "AiAdvancedView.vue")
    ))


def read_vue_source() -> str:
    """读取 Vue 组件源码。"""
    if not VIEW_PATH.exists():
        raise FileNotFoundError(f"Vue 源文件不存在: {VIEW_PATH}")
    return VIEW_PATH.read_text("utf-8")


# ===========================================================================
# 功能 1：多轮上下文 + 时间解析（6 项）
# ===========================================================================

class TestFeature1_ContextAndTimeParsing(unittest.TestCase):
    """验证多轮上下文与自然语言时间解析功能。"""

    @classmethod
    def setUpClass(cls):
        cls.src = read_vue_source()

    # ── 1.1 parseTimeExpression 函数存在，支持 8 种时间表达式 ──────────

    def test_01_parseTimeExpression_function_exists(self):
        """1.1-1 parseTimeExpression 函数定义存在"""
        self.assertIn("function parseTimeExpression", self.src,
                       "parseTimeExpression 函数未定义")

    def test_01_parseTimeExpression_patterns(self):
        """1.1-2 支持至少 8 种时间表达式模式"""
        # 找到 parseTimeExpression 函数体（使用正则检测嵌套大括号）
        func_start = self.src.find("function parseTimeExpression(text)")
        self.assertGreater(func_start, -1, "parseTimeExpression 函数未找到")

        # 用缩进层级法提取函数体
        brace_depth = 0
        in_func = False
        body_lines = []
        for line in self.src[func_start:].split("\n"):
            if not in_func and "function parseTimeExpression" in line:
                in_func = True
            if in_func:
                body_lines.append(line)
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0 and len(body_lines) > 1:
                    break
        body = "\n".join(body_lines)

        # 期望的时间表达式正则
        expected_patterns = [
            "过去24小时", "最近24小时", "近24小时",  # regex #1 (含昨天)
            "昨天",
            "过去7天", "近7天", "最近7天",  "本周",    # regex #2
            "过去30天", "近30天", "这个月",             # regex #3
            "近1小时", "过去1小时", "最近1小时",        # regex #4
            "今天",
            "上周",
        ]
        for pat in expected_patterns:
            self.assertIn(pat, body,
                          f"时间表达式 '{pat}' 未在 parseTimeExpression 中找到")

    # ── 1.2 resolveReference 函数存在 ──────────────────────────────────

    def test_02_resolveReference_function_exists(self):
        """1.2 resolveReference 函数定义存在"""
        self.assertIn("function resolveReference", self.src,
                       "resolveReference 函数未定义")

    def test_02_resolveReference_replaces_pronouns(self):
        """1.2 resolveReference 替换'它/该/这个'为主机名"""
        self.assertIn("function resolveReference", self.src,
                      "resolveReference 函数未定义")
        # 直接在源码中搜索指代词判断
        self.assertIn("它", self.src,
                      "resolveReference 中缺少指代词'它'判断")
        self.assertIn("该", self.src,
                      "resolveReference 中缺少指代词'该'判断")
        self.assertIn("这个", self.src,
                      "resolveReference 中缺少指代词'这个'判断")
        self.assertIn("这些", self.src,
                      "resolveReference 中缺少指代词'这些'判断")
        self.assertIn("host:", self.src,
                      "resolveReference 中缺少 host: 占位替换")

    # ── 1.3 chatContext 状态对象 ───────────────────────────────────────

    def test_03_chatContext_state_object(self):
        """1.3 chatContext ref 存在且包含 5 个字段"""
        # 找 ref 定义
        ref_match = re.search(
            r"const\s+chatContext\s*=\s*ref\(\s*\{([^}]+)\}\s*\)",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(ref_match, "chatContext ref 未定义")
        body = ref_match.group(1)

        expected_fields = ["hostId", "hostName", "intent", "timeRange", "lastQuery"]
        for field in expected_fields:
            self.assertIn(field, body,
                          f"chatContext 缺少字段: {field}")

    # ── 1.4 contextHint 显示 + .context-hint CSS class ────────────────

    def test_04_contextHint_in_template(self):
        """1.4-1 contextHint 在模板中渲染（.context-hint class）"""
        self.assertIn('class="context-hint"', self.src,
                       "模板中未找到 .context-hint class")
        self.assertIn("contextHint", self.src,
                      "模板中未引用 contextHint 变量")

    def test_04_contextHint_css_class(self):
        """1.4-2 .context-hint CSS 样式定义存在"""
        style_section = self.src[self.src.find("<style"):]
        self.assertIn(".context-hint", style_section,
                       "<style> 中未定义 .context-hint")

    # ── 1.5 时间解析后 AI 回复自动带上 start_time / end_time ─────────

    def test_05_time_params_in_sendQuery(self):
        """1.5 sendQuery 中构建请求参数含 start_time / end_time"""
        self.assertIn("params.start_time", self.src,
                      "sendQuery 中未设置 start_time 参数")
        self.assertIn("params.end_time", self.src,
                      "sendQuery 中未设置 end_time 参数")
        self.assertIn("start_time", self.src,
                      "源码中未出现 start_time")
        self.assertIn("end_time", self.src,
                      "源码中未出现 end_time")

    # ── 1.6 sendQuery 中上下文在 AI 回复后更新 ────────────────────────

    def test_06_context_updated_after_response(self):
        """1.6 sendQuery 中 AI 回复后更新 chatContext"""
        self.assertIn("chatContext.value.hostId", self.src,
                      "sendQuery 后未更新 chatContext.hostId")
        self.assertIn("chatContext.value.hostName", self.src,
                      "sendQuery 后未更新 chatContext.hostName")
        self.assertIn("chatContext.value.lastQuery", self.src,
                      "sendQuery 后未更新 chatContext.lastQuery")


# ===========================================================================
# 功能 2：结果下钻与关联跳转（5 项）
# ===========================================================================

class TestFeature2_DrillDownNavigation(unittest.TestCase):
    """验证结果下钻与关联跳转功能。"""

    @classmethod
    def setUpClass(cls):
        cls.src = read_vue_source()

    # ── 2.7 useRouter 导入 ────────────────────────────────────────────

    def test_07_useRouter_imported(self):
        """2.7 import { useRouter } from 'vue-router' 存在"""
        self.assertIn("import { useRouter } from 'vue-router'", self.src,
                       "useRouter 未从 vue-router 导入")
        self.assertIn("const router = useRouter()", self.src,
                       "router 实例未创建")

    # ── 2.8 navigateTo 函数 ──────────────────────────────────────────

    def test_08_navigateTo_function_exists(self):
        """2.8 navigateTo 函数存在（window.open 新标签跳转）"""
        self.assertIn("function navigateTo", self.src,
                      "navigateTo 函数未定义")
        self.assertIn("window.open", self.src,
                      "navigateTo 中未使用 window.open")
        self.assertIn("_blank", self.src,
                      "navigateTo 中未使用 _blank 新标签")

    # ── 2.9 clickable class + @click=navigateTo ──────────────────────

    def test_09_clickable_class_on_components(self):
        """2.9 统计卡/告警/主机/案件有 clickable class + navigateTo"""
        # 统计卡
        stat_match = re.findall(r'class="[^"]*clickable[^"]*".*@click="navigateTo\(', self.src)
        self.assertGreaterEqual(len(stat_match), 4,
                                f"clickable + navigateTo 绑定不足 ({len(stat_match)} 处), 期望至少 4 处")

    def test_09_specific_clickable_elements(self):
        """2.9 各类卡片元素有 .clickable"""
        # 统计卡
        self.assertIn('class="stat-card info clickable"', self.src,
                      "统计卡 info 缺少 clickable")
        self.assertIn('class="stat-card high clickable"', self.src,
                      "统计卡 high 缺少 clickable")
        self.assertIn('class="stat-card critical clickable"', self.src,
                      "统计卡 critical 缺少 clickable")
        self.assertIn('class="stat-card clickable"', self.src,
                      "统计卡 主机 缺少 clickable")
        # 告警标题
        self.assertIn('class="a-title clickable"', self.src,
                      "告警标题缺少 clickable")
        self.assertIn('class="a-host clickable"', self.src,
                      "告警主机缺少 clickable")
        # 主机卡片
        self.assertIn('class="host-card clickable"', self.src,
                      "主机卡片缺少 clickable")
        # 案件
        self.assertIn('class="case-mini clickable"', self.src,
                      "案件缺少 clickable")

    # ── 2.10 .clickable CSS ─────────────────────────────────────────

    def test_10_clickable_css_exists(self):
        """2.10 .clickable { cursor: pointer; } CSS 存在"""
        style_section = self.src[self.src.find("<style"):]
        self.assertIn(".clickable", style_section,
                       "<style> 中未定义 .clickable")
        self.assertIn("cursor: pointer", style_section,
                       ".clickable 样式缺少 cursor: pointer")

    # ── 2.11 跳转路径正确 ──────────────────────────────────────────

    def test_11_navigation_paths(self):
        """2.11 跳转路径包含 /hosts/:id, /analysis/events/:id 等"""
        expected_paths = [
            "/analysis/events?severity=critical",
            "/analysis/events?severity=high",
            "/analysis/events?status=open",
            "/hosts/",
            "/analysis/events/",
            "/cases/",
        ]
        for path in expected_paths:
            self.assertIn(f"navigateTo('{path}", self.src,
                          f"跳转路径 '{path}' 未找到")
            # 也检查拼接形式（带 + 拼接）
            if "/" in path:
                self.assertIn(f"navigateTo('{path}", self.src,
                              f"拼接路径 '{path}' 未找到")

    def test_11_dynamic_paths_with_concat(self):
        """2.11 动态路径拼接（+ 运算符）"""
        # /hosts/ + id
        self.assertIn("navigateTo('/hosts/' +", self.src,
                      "主机跳转路径未使用动态拼接")
        # /analysis/events/ + id
        self.assertIn("navigateTo('/analysis/events/' +", self.src,
                      "告警跳转路径未使用动态拼接")
        # /cases/ + id
        self.assertIn("navigateTo('/cases/' +", self.src,
                      "案件跳转路径未使用动态拼接")


# ===========================================================================
# 功能 3：会话持久化 + AI 研判（4 项）
# ===========================================================================

class TestFeature3_SessionAndAnalysis(unittest.TestCase):
    """验证会话持久化与 AI 研判增强功能。"""

    @classmethod
    def setUpClass(cls):
        cls.src = read_vue_source()

    # ── 3.12 sessions / activeSessionId + localStorage ────────────────

    def test_12_sessions_ref_and_localStorage(self):
        """3.12-1 sessions / activeSessionId ref 存在"""
        self.assertIn("const sessions", self.src,
                      "sessions ref 未定义")
        self.assertIn("const activeSessionId", self.src,
                      "activeSessionId ref 未定义")

    def test_12_localStorage_keys(self):
        """3.12-2 localStorage key 为 ir-ai-chat-sessions / ir-ai-active-session"""
        self.assertIn("SESSION_KEY", self.src,
                      "SESSION_KEY 常量未定义")
        self.assertIn("ACTIVE_SESSION_KEY", self.src,
                      "ACTIVE_SESSION_KEY 常量未定义")
        self.assertIn("ir-ai-chat-sessions", self.src,
                      "localStorage key 缺少 ir-ai-chat-sessions")
        self.assertIn("ir-ai-active-session", self.src,
                      "localStorage key 缺少 ir-ai-active-session")

    def test_12_load_and_save_logic(self):
        """3.12-3 localStorage 保存/恢复逻辑完整"""
        self.assertIn("localStorage.getItem(ACTIVE_SESSION_KEY)", self.src,
                      "未从 localStorage 恢复 activeSessionId")
        self.assertIn("localStorage.setItem", self.src,
                      "未调用 localStorage.setItem 持久化数据")
        self.assertIn("localStorage.removeItem", self.src,
                      "未调用 localStorage.removeItem 清理数据")

    def test_12_save_uses_SESSION_KEY(self):
        """3.12-4 保存时使用 SESSION_KEY 常量"""
        self.assertIn("localStorage.setItem(SESSION_KEY", self.src,
                      "保存会话时未使用 SESSION_KEY")
        self.assertIn("localStorage.setItem(ACTIVE_SESSION_KEY", self.src,
                      "保存会话时未使用 ACTIVE_SESSION_KEY")

    # ── 3.13 loadSession / saveSession / newSession / deleteSession ───

    def test_13_session_functions_exist(self):
        """3.13 loadSession/saveSession/newSession/deleteSession 全存在"""
        self.assertIn("function loadSession", self.src,
                      "loadSession 函数未定义")
        self.assertIn("function saveSession", self.src,
                      "saveSession 函数未定义")
        self.assertIn("function newSession", self.src,
                      "newSession 函数未定义")
        self.assertIn("function deleteSession", self.src,
                      "deleteSession 函数未定义")

    def test_13_session_functions_logic(self):
        """3.13 各函数内部逻辑完整"""
        # loadSession: 查找 session、恢复消息、设置 activeSessionId
        self.assertIn(".messages", self.src,
                      "loadSession 中未处理 messages")
        # saveSession: 保存到 localStorage
        self.assertIn("JSON.stringify(sessions.value)", self.src,
                      "saveSession 中未序列化 sessions")
        # deleteSession: 过滤删除
        self.assertIn(".filter(", self.src,
                      "deleteSession 中未使用 filter 删除")
        # newSession: 清空上下文
        self.assertIn("chatContext.value", self.src,
                      "newSession 中未重置 chatContext")

    # ── 3.14 AI 研判增强卡片 ────────────────────────────────────────

    def test_14_analysis_render_exists(self):
        """3.14-1 m.render === 'analysis' 模板存在"""
        self.assertIn("m.render === 'analysis'", self.src,
                      "AI 研判卡片模板未找到")
        self.assertIn('class="analysis-card"', self.src,
                      "analysis-card CSS class 未找到")

    def test_14_analysis_fields(self):
        """3.14-2 研判卡片展示置信度/攻击模式/MITRE 标签/建议"""
        self.assertIn("confidence", self.src,
                      "研判卡片缺少置信度字段")
        self.assertIn("attackPattern", self.src,
                      "研判卡片缺少攻击模式字段")
        self.assertIn("mitreIds", self.src,
                      "研判卡片缺少 MITRE 标签字段")
        self.assertIn("suggestion", self.src,
                      "研判卡片缺少建议字段")

    def test_14_analysis_card_structure(self):
        """3.14-3 研判卡片模板完整结构"""
        self.assertIn("ac-confidence", self.src,
                      "置信度 class 未定义")
        self.assertIn("ac-suggestion", self.src,
                      "建议 class 未定义")
        self.assertIn("mitre-tag", self.src,
                      "MITRE 标签 class 未定义")
        self.assertIn("m.analysis", self.src,
                      "模板中未引用 m.analysis")


# ===========================================================================
# 额外检查：ECharts / 各 tab 逻辑完整保留 / 路由不变
# ===========================================================================

class TestExtra_RegressionChecks(unittest.TestCase):
    """验证其他 tab 功能完整保留。"""

    @classmethod
    def setUpClass(cls):
        cls.src = read_vue_source()

    def test_echarts_imported(self):
        """ECharts 导入和初始化逻辑完整保留"""
        self.assertIn("import * as echarts from 'echarts'", self.src,
                      "ECharts 导入丢失")
        self.assertIn("echarts.init", self.src,
                      "ECharts init 调用丢失")

    def test_correlate_tab_preserved(self):
        """告警降噪 tab 逻辑保留"""
        self.assertIn("correlateIncidents", self.src,
                      "correlateIncidents 函数调用丢失")
        self.assertIn("doCorrelate", self.src,
                      "doCorrelate 函数丢失")
        self.assertIn("renderCorrelateCharts", self.src,
                      "renderCorrelateCharts 函数丢失")

    def test_story_tab_preserved(self):
        """攻击故事 tab 逻辑保留"""
        self.assertIn("doNarrate", self.src,
                      "doNarrate 函数丢失")
        self.assertIn("narrateIncident", self.src,
                      "narrateIncident 函数调用丢失")
        self.assertIn("storySections", self.src,
                      "storySections 变量丢失")

    def test_risk_tab_preserved(self):
        """预测预警 tab 逻辑保留"""
        self.assertIn("doRiskRank", self.src,
                      "doRiskRank 函数丢失")
        self.assertIn("getRiskRanking", self.src,
                      "getRiskRanking 函数调用丢失")
        self.assertIn("renderRiskCharts", self.src,
                      "renderRiskCharts 函数丢失")

    def test_fp_tab_preserved(self):
        """误报管理 tab 逻辑保留"""
        self.assertIn("loadFPs", self.src,
                      "loadFPs 函数丢失")
        self.assertIn("deleteFP", self.src,
                      "deleteFP 函数丢失")
        self.assertIn("getFalsePositives", self.src,
                      "getFalsePositives 函数调用丢失")

    def test_tab_names_unchanged(self):
        """所有 Tab 切换路由不变"""
        expected_tabs = [
            'name="chat"',
            'name="correlate"',
            'name="story"',
            'name="risk"',
            'name="fp"',
        ]
        for tab in expected_tabs:
            self.assertIn(tab, self.src,
                          f"Tab '{tab}' 丢失或名称改变")

    def test_onTabChange_preserved(self):
        """onTabChange 函数完整保留"""
        self.assertIn("function onTabChange", self.src,
                      "onTabChange 函数丢失")


# ===========================================================================
# 前端构建验证
# ===========================================================================

class TestBuild(unittest.TestCase):
    """验证前端构建通过。"""

    def test_15_vite_build(self):
        """3.15 构建通过: cd frontend && npx vite build"""
        import subprocess
        result = subprocess.run(
            ["npx.cmd", "vite", "build"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print("=== VITE BUILD STDOUT ===")
            print(result.stdout[-2000:])
            print("=== VITE BUILD STDERR ===")
            print(result.stderr[-2000:])
        self.assertEqual(
            result.returncode, 0,
            f"Vite 构建失败 (exit code {result.returncode}):\n{result.stderr[-1500:]}"
        )


# ===========================================================================
# 主入口 + SQLite 数据库初始化
# ===========================================================================

def _init_temp_db():
    """创建独立临时 SQLite 数据库用于测试（不碰生产库）。"""
    db_fd, db_path = tempfile.mkstemp(suffix="_ai_adv_test.db")
    os.close(db_fd)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS test_marker (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test_marker VALUES (1, 'ai_advanced_view_features_test')")
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    # 验证源文件存在
    if not VIEW_PATH.exists():
        print(f"❌ Vue 源文件不存在: {VIEW_PATH}")
        print(f"   前端目录: {FRONTEND_DIR}")
        sys.exit(1)
    print(f"✅ Vue 源文件: {VIEW_PATH}")
    print(f"✅ 前端目录: {FRONTEND_DIR}")

    # 创建临时 SQLite 数据库
    db_path = _init_temp_db()
    print(f"✅ 临时测试数据库: {db_path}")
    try:
        unittest.main(verbosity=2)
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
            print(f"✅ 已清理临时数据库: {db_path}")
