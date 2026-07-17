# 自然语言指挥台 v3.0 — 10项功能增强

## 修改文件
- `backend/app/api/ai_advanced.py` — SSE性能指标 + 报表生成端点
- `backend/app/schemas/ai_advanced.py` — QueryEndEvent增加exec_time_ms/results_count
- `frontend/src/api/ai_advanced.js` — SSE回调传extra数据 + generateReport API
- `frontend/src/views/AiAdvancedView.vue` — 全部10项功能实现

## 功能清单
| # | 功能 | 状态 | 关键实现 |
|---|------|------|---------|
| 1 | 消息操作菜单 | ✅ | 每轮AI消息hover出现···，支持复制/引用/有用/没用/意图修正 |
| 2 | 时间范围Pill | ✅ | 输入框下方蓝色tag显示解析的时间范围，可关闭 |
| 3 | 输入区智能补全 | ✅ | el-autocomplete，/或@触发模板下拉+历史匹配 |
| 4 | 告警批量处置 | ✅ | alert每行checkbox+底部浮起批量操作栏 |
| 5 | 意图修正反馈 | ✅ | 菜单"这不是我要的"，自动重查 |
| 6 | 多轮复合查询 | ✅ | chatContext.workingSet追踪中间结果 |
| 7 | 对话导出 | ✅ | 页面头部按钮，导出Markdown |
| 8 | 查询性能洞察 | ✅ | SSE query_end带回exec_time_ms/results_count，文本尾部显示⚡ |
| 9 | 报表生成 | ✅ | /ai/generate-report后端端点+前端按钮 |
| 10 | ECharts仪表盘 | ✅ | stats卡片加小型饼图渲染 |
