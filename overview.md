# 本次处理概览

## 完成内容
- 修复 AI 分析卡在 0% 不动的问题：后端 RAG 向量模型加载改为仅使用本地缓存，不再因首次联网下载 Hugging Face 模型而阻塞整个分析链路。
- 修复取消分析后界面恢复异常的问题：前端取消后会真正重置状态并回到确认阶段，可直接重新发起分析。
- 保持关键词回退链路可用：本地无向量模型缓存时，自动快速降级为关键词检索，而不是长时间卡死。

## 关键改动
- `backend/app/services/knowledge_retriever.py`
  - `_get_embedding_model()` 改为 `local_files_only=True`
  - 本地无模型缓存时记录 warning，并禁用 embedding，快速回退关键词检索
- `frontend/src/components/AiAnalysisDialog.vue`
  - `handleCancelAnalysis()` 改为取消后 `resetState()` 并回到 `confirm`
- 之前已兼容 `content` SSE 文本事件，保证黑色终端区能显示流式输出

## 验证结果
- 后端语法校验通过：`knowledge_retriever.py`
- 前端构建通过：`npm --prefix frontend run build`
- 后端 AI API 定向回归通过：`backend/tests/test_ai_api.py` -> 25/25 通过

## 说明
- 用户日志中的真正阻塞点是 `sentence-transformers/all-MiniLM-L6-v2` 首次联网访问 Hugging Face 超时重试，导致任务长时间停在早期阶段。
- 修复后，在离线或网络受限环境下，AI 分析不会再因为模型下载卡住；若本地没有向量模型缓存，将直接走关键词回退。
