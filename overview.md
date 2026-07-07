# AI 分析执行 BugFix 概览

## 本次完成
- 修复了 AI 分析执行时报错的问题。
- 完成了真实主机数据的 AI 分析调用测试，确认能够成功生成 AI 报告。
- 调整了前端开发代理，使页面请求连到已修复的后端实例。

## 根因
- 当前接入的 AI 网关/模型在 `chat/completions` 调用中，不接受代码原先发送的 token 参数格式，返回：`Unsupported parameter: max_output_tokens`。
- 这说明不同 OpenAI-compatible 网关在 token 限制字段上存在兼容性差异，原实现只支持单一参数写法，导致 AI 分析请求被 400 拒绝。

## 关键改动
- `backend/app/services/ai_service.py`
  - 为 LLM 调用增加参数兼容重试逻辑：
    - 默认先按 `max_tokens` 请求
    - 若网关返回 `Unsupported parameter: max_tokens` 或 `Unsupported parameter: max_output_tokens`，则自动切换为 `max_output_tokens` 重试
- `frontend/vite.config.js`
  - 将开发代理目标切换到本次验证用的后端实例端口 `8012`

## 验证结果
- 真实主机 `host_id=1`，状态 `analyzed`：AI 分析成功
- `POST /api/ai/analyze/1` 返回 `code: 0`
- 返回内容包含：
  - `risk_assessment`
  - `threat_analysis`
  - `timeline_analysis`
  - `recommendations`
  - `raw_response`
  - `model_used`
  - `tokens_used`
- 本次实测模型：`gpt-5.4`
- 本次实测 token 消耗：`12266`

## 备注
- 当前工作区里存在多个后端实例并行运行；本次修复验证使用的是 `8012` 端口实例。
- 若浏览器页面仍报旧错，通常不是代码没修，而是前端还连着旧后端实例。