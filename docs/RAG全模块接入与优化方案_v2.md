# RAG 语义检测 — 全模块接入 + 优化方案 v2

> 2026-07-12 | 基于 v1 方案 + 6 项优化

## 一、优化项总览

| # | 优化 | 效果 | 改动量 |
|---|------|------|--------|
| 1 | 硬编码→动态 query | 查询文本反应真实主机数据 | 删除 1 行硬编码 |
| 2 | 子串匹配→结构化 ID 关联 | 前端精准跳转，不再模糊匹配 | 约 40 行 |
| 3 | 单次检索→三维并行检索 | 进程/外连/webshell-ms 各自独立语义 | 约 50 行 |
| 4 | 相似度阈值分模块差异化 | 进程 0.75 / 外连 0.70 / webshell 0.65 | 约 15 行 |
| 5 | 查询文本去冗余 distinct | 减少重复编码，提升精度 | 约 10 行 |
| 6 | ChromaDB 三 collection 分拆 | 种子/规则/草稿分别检索后加权合并 | 约 60 行 |

## 二、改动清单

### 2.1 优化 1+5：动态查询 + 去冗余（`knowledge_retriever.py::_build_query_text`）

- 删除 `analysis_service.py` 中硬编码的 `"svch0st c0balt-str1ke ..."`
- `_build_query_text` 对进程名/外连 IP/web目录做 `distinct` 去重后再拼接
- 新增 webshell / memory_shell / persistence 三段文本

### 2.2 优化 2：结构化 evidence（`knowledge_retriever.py` + `analysis_service.py`）

每条 `knowledge_hit` 扩展为：

```python
{
    "title": "powershell_download_cradle",
    "confidence": "high",
    "evidence_type": "process",      # process|connection|webshell|memory_shell|persistence
    "evidence_key": "powershell.exe", # 前端点击跳转的锚点值
    "entry_ref": "rule_*",           # 知识库跳转 ID
    ...
}
```

`_cross_validate` 不再只匹配 process_name，而是对每个语义 hit：
1. 匹配进程 → evidence_type=process, evidence_key=process_name
2. 匹配外连 → evidence_type=connection, evidence_key=remote_addr
3. 匹配 webshell → evidence_type=webshell, evidence_key=path
4. 匹配 ms → evidence_type=memory_shell, evidence_key=class_name
5. 匹配持久化 → evidence_type=persistence, evidence_key=name

### 2.3 优化 3：三维并行检索（`analysis_service.py`）

```
raw_data
  ├─→ _build_dim_query("process")     → model.encode → ChromaDB query → top-3
  ├─→ _build_dim_query("connection")  → model.encode → ChromaDB query → top-3
  └─→ _build_dim_query("webshell_ms") → model.encode → ChromaDB query → top-3
                                                                          ↓
                                                            interleave + dedup → 5 hits
```

新增 `_build_dim_query(dim, raw_data)` 函数，按维度提取文本：
- process: 进程名 + 命令行（取 top-10 distinct）
- connection: 远程 IP + 端口 + 协议（取 top-10 distinct IPs）
- webshell_ms: path + funcs + class_name + agent_jar

三次 `model.encode` 并行调用（同一模型实例），结果按 score 降序 interleave 去重取 top-5。

### 2.4 优化 4：分模块阈值（`knowledge_retriever.py`）

```python
DIM_THRESHOLDS = {
    "process": 0.75,      # 进程名变种容忍度高
    "connection": 0.70,   # IP/端口 语义弱，标准阈值
    "webshell_ms": 0.65,  # 危险函数名精度要求高
}
```

`_vector_retrieve` 新增 `dim` 参数，按维度选阈值。

### 2.5 优化 6：ChromaDB 三 collection（`knowledge_retriever.py`）

```
ir_rules (144 records)
  → 拆为:
  ├── ir_seed    (11 records) — 种子知识 + 已批准草稿
  ├── ir_rules   (133 records) — 检测规则
  └── ir_draft   (动态) — 待审核草稿
```

三 collection 分别检索，结果加权合并：
- seed 命中 weight=1.5（种子知识精准度最高）
- rule 命中 weight=1.0
- draft 命中 weight=0.5（草稿未经审核，降权）

### 2.6 前端：点击跳转知识库（改动约 80 行）

- `KnowledgeDetailPopup.vue` 新建 — 知识条目详情弹窗
  - 显示：标题 / 描述 / ATT&CK 映射 / severity / 来源 / entry_type
  - 底部 "在知识库中查看" 按钮 → 路由跳转 `/knowledge?ref=xxx`
- 知识卡片 + 📚 badge → 点击 → 弹出 popup
- 后端 API：`GET /api/knowledge/entry?ref=rule_5_cmd_powershell_chain`
  - 从 ChromaDB metadata + rules 缓存查找
  - 返回 `{name, description, severity, category, mitre_attack, source, entry_type}`

### 2.7 后端：各模块 get_* 注入 knowledge_hit（`analysis_service.py`）

注入模式同 `get_abnormal_processes`：

| 方法 | 注入字段 | 匹配 key |
|------|---------|---------|
| `get_abnormal_processes` ✅ 已实现 | `row.knowledge_hit` | process_name |
| `get_suspicious_connections` | `row.knowledge_hit` | remote_addr |
| `get_webshells` (分析结果透传) | `row.knowledge_hit` | path |
| `get_memory_shells` (透传) | `row.knowledge_hit` | class_name |
| `get_persistence_items` | `row.knowledge_hit` | name |

## 三、文件改动总览

| 文件 | 内容 | 行数 |
|------|------|------|
| `knowledge_retriever.py` | `_build_query_text` 扩展 + 三维并行检索 + 分阈值 + 三 collection | ~120 |
| `analysis_service.py` | 删硬编码 + `_build_dim_query` + `_cross_validate` 多模块 + 5 个注入 | ~100 |
| `knowledge_draft.py` | `GET /api/knowledge/entry` | ~20 |
| `HostDetailView.vue` | 卡片点击→popup + 跳转 | ~25 |
| `KnowledgeDetailPopup.vue` 新建 | 知识详情弹窗 | ~60 |
| `SuspiciousConnectionTable.vue` 等 3 组件 | 📚 badge | 各 ~10 |

总计约 355 行，净增。
