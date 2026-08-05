# 智能体编排 — RAG / 记忆增强开关操作文档（A10）

> 适用范围：IR Platform 智能体编排模块（`backend/app/services/agents/pipeline_engine.py`）
> 状态：**默认全部关闭**（存量流水线 prompt 零变化）；本文档说明如何渐进启用。
> 关联：A12（记忆向量化扩展位，本期未实现，见 §4）。

---

## 1. 总原则：默认关，按节点 opt-in 渐进启用

- 全局开关（`IR_RAG_AUTO_ENHANCE` / `IR_MEMORY_AUTO_ENHANCE`）**默认 `False`**，
  这是刻意设计——保证存量流水线的 Prompt 与运行行为完全不变。
- 推荐启用路径：**先按节点 `input_params` 逐节点 opt-in 验证效果**，再决定是否全局打开。
- 任一开关打开后，仅在 **LLM 类节点**执行前注入知识/记忆；非 LLM 节点不受影响。

---

## 2. 全局开关（环境变量）

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `IR_RAG_AUTO_ENHANCE` | `false` | 自动 RAG 知识注入总开关（`1/true/yes/on` 视为开启） |
| `IR_RAG_AUTO_ENHANCE_K` | `3` | RAG 注入 Top-K（夹取 `[1,10]`） |
| `IR_RAG_RETRIEVE_TIMEOUT` | `5.0` | RAG 检索超时（秒）；超时按未命中处理，不阻断节点 |
| `IR_RAG_INJECT_HEADER` | `[知识增强] …` | RAG 注入块头文案 |
| `IR_MEMORY_AUTO_WRITE` | `true` | **自动沉淀**总开关：关键节点执行成功后自动写长期记忆（纯追加，不改 prompt；与“增强”是两件事） |
| `IR_MEMORY_AUTO_ENHANCE` | `false` | 记忆增强总开关（LLM 节点执行前注入历史记忆 Top-K） |
| `IR_MEMORY_ENHANCE_K` | `3` | 记忆注入 Top-K（夹取 `[1,10]`） |
| `IR_MEMORY_RETRIEVE_TIMEOUT` | `3.0` | 记忆检索超时（秒） |
| `IR_MEMORY_MAX_CONTENT` | `4000` | 单条记忆正文最大长度（字符） |
| `IR_MEMORY_INJECT_HEADER` | `[记忆增强] …` | 记忆注入块头文案 |

> 沉淀（write）与增强（enhance）的区别：
> - **沉淀**（`IR_MEMORY_AUTO_WRITE=True`）：执行后把结论/摘要/处置记录追加进 `agent_memories` 表，供后续事件参考；不读取、不改变当前 Prompt。
> - **增强**（`IR_MEMORY_AUTO_ENHANCE=True`）：执行前检索历史记忆并注入当前 Prompt。

---

## 3. 节点级 opt-in / opt-out（`input_params`）

在画布节点的高级配置（`input_params`）中设置，优先级高于全局开关：

| 参数 | 作用 |
|---|---|
| `rag_enhance` | `true` → 该节点强制启用 RAG 注入（opt-in）；`false` → 强制跳过（opt-out）；缺省回退全局 |
| `rag_top_k` | 该节点 RAG Top-K（覆盖全局 `IR_RAG_AUTO_ENHANCE_K`，夹取 `[1,10]`） |
| `memory_enhance` | `true` → 强制启用记忆注入；`false` → 强制跳过；缺省回退全局 |
| `memory_top_k` | 该节点记忆 Top-K（覆盖全局 `IR_MEMORY_ENHANCE_K`，夹取 `[1,10]`） |
| `remember` | 该节点是否自动沉淀记忆（覆盖全局 `IR_MEMORY_AUTO_WRITE`） |

实现位置：`pipeline_engine.py` `_rag_enabled`（约 L1530）、`_rag_top_k`（L1548）、
`_memory_enabled`（L1723）、`_memory_top_k`（L1741）、`_enhance_with_memory`（L1823）。

---

## 4. A12 记忆向量化扩展位（本期未实现）

当前记忆检索为 SQLite 关键词 `LIKE`（`AgentMemory.search`），无语义检索。
已在 `knowledge_retriever.py` `COLLECTION_NAMES` 预留常量：

```python
"memory": "ir_memory",   # 768 维，与 EMBEDDING_MODEL_NAME（bge-base-zh-v1.5）同模型
```

后续实现路径（供排期参考）：
1. `AgentMemory.create`（或 `_sediment_memory`）写库时同步向量化（fail-safe：向量化失败不阻断写库）；
2. `_enhance_with_memory` 检索改为向量 Top-K + `LIKE` 兜底；
3. 与 `ir_seed / ir_rules` 命名隔离、维度一致（768），避免维度漂移。

---

## 5. 兼容性说明

- 默认关闭 → 存量流水线 Prompt 零变化，`test_p2_memory_enhance.py`（默认关不注入 / opt-in / opt-out / Top-K 夹取）全量回归通过。
- 全局打开会改变所有 LLM 节点 Prompt（多出注入块），**上线前请评估对存量流水线的影响**。
- 建议先在测试环境按节点 `rag_enhance/memory_enhance` 验证，再灰度全局开关。
