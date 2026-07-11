# IR Platform 知识库功能 · 架构评审报告

> 评审对象：IR Platform（FastAPI + Vue3）的「知识库 / RAG 检索增强」子系统
> 评审方式：只读源码走查（未改任何代码）
> 关键文件：`backend/app/services/knowledge_retriever.py`、`prompt_builder.py`、`ai_task_service.py`、`ai_service.py`、`api/knowledge_draft.py`、`models/knowledge_draft.py`、`data/knowledge_seed.py`、`services/explainability_service.py`、`models/ai_analysis.py`、`main.py`、`config.py`；前端 `KnowledgeView.vue`、`HostKnowledgeTab.vue`、`EvidenceTracePanel.vue`、`api/knowledge.js`、`router/index.js`

---

## 1. 功能定位与边界

知识库功能是一个 **「管理员/AI 维护的参考知识条目 + RAG 检索增强」双轨制** 能力，主要服务于 AI 安全分析的可解释性与命中规则联动，而非独立的攻防情报库。

- **知识条目来源（三元）**
  1. **内置种子知识**（`data/knowledge_seed.py:170` `ALL_SEED_KNOWLEDGE`，共 10 条：MITRE_TECHNIQUES 5 + C2_FRAMEWORKS 3 + MALWARE_PATTERNS 2）。
  2. **AI 自动建议**：AI 分析时若发现知识库未覆盖的威胁模式，在 JSON 顶层返回 `knowledge_suggestions`，由 `ai_task_service.py:367-403` 写入 `knowledge_drafts`（`source='ai_suggest'`）。
  3. **人工导入 / 第三方同步**：`api/knowledge_draft.py:204` 手动导入、`api/knowledge_draft.py:289` 从 VirusTotal/AbuseIPDB/OTX 同步（`source='manual'`/`external`）。
- **审核闭环**：草稿经管理员 `approve`（批准入库）/ `reject`（拒绝）/ `recall`（撤回）后，状态流转（`models/knowledge_draft.py`）。只有 `status='approved'` 的草稿才会成为检索语料（`models/knowledge_draft.py:311-337 get_as_seed_entries`）。
- **如何增强 AI（RAG 拼接，非微调）**：在 `PromptBuilder.build()` 阶段（`prompt_builder.py:1583-1638 _build_knowledge_section`）调用 `KnowledgeRetriever.retrieve()`，把命中的知识条目以纯文本形式拼进 user prompt 的「## 参考知识」段落。属于 **检索即拼接（retrieval-augmented prompting）**，无重排/无 query 改写。
- **边界澄清**：知识库 **不是**「自动从攻击技战术库实时检索」——`default_rules.json` 规则库与种子知识都是**静态/已审核**语料；真正的「规则命中联动」是另一条路径 `prompt_builder.py:1640-1706 _build_actual_matches`（读 `default_rules.json` 解释本地引擎已触发的规则原因），与 RAG 检索并行但相互独立。

---

## 2. 整体架构与模块划分

```
┌─────────────────────────┐   ┌──────────────────────────┐
│ 前端 KnowledgeView.vue   │   │ HostKnowledgeTab.vue     │
│ (知识库管理: 4 Tab)      │   │ (主机维度审核 Tab)       │
└───────────┬─────────────┘   └───────────┬──────────────┘
            │                              │
            ▼                              ▼
┌────────────────────────────────────────────────────────┐
│ frontend/src/api/knowledge.js (axios 封装)               │
└───────────┬────────────────────────────────────────────┘
            │  /api/knowledge/*  (main.py:68  prefix=/api/knowledge)
            ▼
┌────────────────────────────────────────────────────────┐
│ api/knowledge_draft.py  (REST: drafts/approve/reject/    │
│   recall/batch/import/sync/seeds)                        │
└───────────┬────────────────────────────────────────────┘
            │ 写 status
            ▼                              ▲ 触发 rebuild
┌──────────────────────┐      ┌──────────────────────────┐
│ models/knowledge_     │      │ services/knowledge_       │
│ draft.py (SQLite 表)  │      │ retriever.py (RAG 核心)   │
└──────────────────────┘      └───┬───────────────┬───────┘
                                   │               │
                    ┌──────────────▼───┐     ┌──────▼──────────────┐
                    │ ChromaDB 集合     │     │ sentence-transformers │
                    │ ir_rules (持久化) │     │ all-MiniLM-L6-v2     │
                    └──────────────────┘     └─────────────────────┘
                                   ▲
            ┌──────────────────────┴───────────────────────┐
            │ AI 分析调用链（检索在组装 prompt 时触发）       │
            │ ai_task_service._execute_task → PromptBuilder  │
            │   .build(include_knowledge=True)               │
            │     → KnowledgeRetriever.retrieve()            │
            │   → ExplainabilityService.build_evidence_trace │
            │   → AiAnalysisReport.create (evidence 落库)    │
            └───────────────────────────────────────────────┘
```

**关键结论**：知识库的「写入面」（前端→api→SQLite→触发 chroma 重建）与「读取面」（AI 分析→PromptBuilder→retriever→chroma）通过 **SQLite 状态 + Chroma 派生索引** 解耦，二者靠 `rebuild_seed_index()` 事件驱动同步——这正是一致性风险的根源（见 §3、§8）。

---

## 3. 数据模型与存储

### 3.1 `knowledge_drafts` 关系表（来源 `models/knowledge_draft.py:55-60`）
| 字段 | 用途 |
|---|---|
| `host_id` / `analysis_report_id` | 溯源：来源主机 / 分析报告 |
| `title` / `description` | 知识条目标题与正文（**被拼进 prompt**） |
| `category` | mitre_attack / c2_framework / malware_behavior / auto |
| `severity` | low/medium/high/critical |
| `mitre_attack` / `pattern` | ATT&CK 编号 / 检测关键词（逗号分隔） |
| `status` | pending / approved / rejected（审核状态机） |
| `source` | ai_suggest / manual / external |
| `raw_ioc` | 原始 IOC JSON（第三方同步用） |
| `created_at` / `reviewed_at` | 时间戳 |

**要点**：表 **不存任何向量**；向量仅存在于 Chroma。关系表是「已批准语料」的唯一事实源，Chroma 是派生索引。去重按三元组 `(title, category, mitre_attack)`（`models/knowledge_draft.py:281-309`）。

### 3.2 ChromaDB 集合
- **集合名** `ir_rules`（`knowledge_retriever.py:51`），**持久化**到 `backend/data/chroma/`（`settings.DATA_DIR/"chroma"`，`knowledge_retriever.py:52`，`config.py:35`）。
- **距离度量** `cosine`（`knowledge_retriever.py:124` `metadata={"hnsw:space":"cosine"}`）。
- **文档内容** = `"{name}: {description}"`；**metadata** = `{rule_name, severity, category}`（`knowledge_retriever.py:267-275` 规则索引、`353-362` 种子索引）。
- **embedding 模型** `sentence-transformers` 的 **`all-MiniLM-L6-v2`**（384 维，`knowledge_retriever.py:50`），加载用 `local_files_only=True`（`knowledge_retriever.py:89-92`）。

### 3.3 同步机制与不一致风险（**重点**）
写入 Chroma 仅发生在两处：`_build_index()`（规则）、`_build_seed_index()`（种子+已批准草稿），且都通过 `KnowledgeRetriever.rebuild_seed_index()` 在 **approve 时触发**（`api/knowledge_draft.py:142`、`197`）。

存在 **三类一致性缺陷**：

1. **【严重 Bug】种子知识（真正的攻防 KB）从未被向量化**。`_build_seed_index()` 的早退守卫：
   ```python
   # knowledge_retriever.py:327-331
   if _SEED_INDEXED:
       return True
   if collection.count() > 0:      # ← 只要集合非空就直接返回
       _SEED_INDEXED = True
       return True
   ```
   `_ensure_index()`（`knowledge_retriever.py:592-615`）先调 `_build_index()` 把 `rule_*` 写入集合使 `count>0`，随后 `_build_seed_index()` 立即命中 `count>0` 早退，**10 条种子知识永不入向量库**。结论：**向量库实际只含 `default_rules.json` 的规则名+描述，不含 MITRE/C2/Malware 种子**。
2. **【严重 Bug】reject / recall 不触发重建 → 向量残留**。`reject_draft`（`api/knowledge_draft.py:149`）、`recall_draft`（`163`）只改 SQLite `status`，**不调 `rebuild_seed_index()`**（仅 approve/batch-approve 调）。一旦某草稿被批准（向量入 chroma），后续即使被 reject/recall 回 pending，其向量仍留在 chroma，且 `retrieve()` 检索时**只看 chroma 不看 DB status**，导致**已被拒绝/撤回的知识仍会出现在 RAG 结果中**。
3. **【中】approve 触发重建仍有残留种子 Bug**：`rebuild_seed_index()`（`knowledge_retriever.py:617-663`）只 `delete` `seed_`/`draft_` 前缀（`641-651`），但 `rule_*` 仍在，于是 `_build_seed_index()` 再次因 `count>0` 早退——**即使管理员批准了草稿，种子/草稿向量依然大概率未被成功加入**（取决于当时集合是否恰好为空，而正常情况下非空）。

> 综合：向量检索路径（`_vector_retrieve`）在 chroma+模型可用时**几乎只返回规则名匹配**；高价值的 MITRE/C2/Malware 与已批准草稿，仅能通过**关键词回退路径**（`_keyword_retrieve` 直接读 SQLite `get_as_seed_entries()`）命中。换句话说，RAG 的「语义向量」部分与「安全知识点」部分被上述 bug 割裂了。

---

## 4. RAG 检索流程（核心，`knowledge_retriever.py`）

### 4.1 检索入口与分支（`retrieve()` `knowledge_retriever.py:669-708`）
```python
if collection is not None and model is not None and collection.count() > 0:
    results = KnowledgeRetriever._vector_retrieve(...)   # 优先向量
else:
    results = KnowledgeRetriever._keyword_retrieve(...)   # 回退关键词
```
- **向量检索** `_vector_retrieve`（`714-836`）：`_build_query_text`（`402-531`，从分层数据抽取进程/外连/IOC/持久化/时间线拼成查询串）→ `model.encode` → `collection.query(n_results=min(limit*3, count))`（多取 3 倍过滤，`756`）→ **余弦距离阈值 `0.7` 过滤**（`789`，`VECTOR_DISTANCE_THRESHOLD`）→ 结构化 dict。
- **相似度阈值**：`distance > 0.7` 丢弃（约 similarity<0.3）；`distance<=0.35` 标 `confidence=high`（`806`）。
- **关键词回退** `_keyword_retrieve`（`842-1010`）：规则名精确命中 + 描述关键词≥2 + C2 签名 + 种子（含 `pattern` 关键词），按分数排序。
- **metadata 过滤**：**无任何 host/tag/severity 维度过滤**；检索是全局的，不区分主机上下文。

### 4.2 与 prompt 的关系
`PromptBuilder._build_knowledge_section`（`prompt_builder.py:1583-1638`）把结果拼为：
```python
sections.append("## 参考知识\n以下是根据当前主机数据匹配的安全规则知识，请参考这些规则进行分析：")
for item in knowledge_items:
    sections.append(f"- [{confidence}] {title}: {summary}")   # :1617
```
并在 token 预算内注入（`prompt_builder.py:625-638`，预算 `AI_INPUT_BUDGET=80000`，`config.py:71`）。

### 4.3 重排 / 改写 / 压缩
**均无**。纯 Top-K + 距离阈值；无 query 改写、无交叉编码器重排、无上下文压缩。

### 4.4 降级策略（健壮性较好）
- 查询编码失败 → 关键词回退（`:752-753`）；
- chroma query 异常 → 关键词回退（`:763-765`）；
- model/chroma 不可用或集合空 → 关键词回退；
- `PromptBuilder._build_knowledge_section` 整体 try/except，检索异常时**静默跳过知识段**、分析照常进行（`:1619-1620`）。

### 4.5 性能与并发
- **embedding 缓存**：模型进程级单例（`_EMBEDDING_MODEL`，`:62`）+ 规则/种子/C2 进程级缓存（`:64-66`），合理。
- **持久化**：`PersistentClient`，合理（非内存）。
- **⚠ 阻塞事件循环**：`model.encode()` 与 `collection.query()` 均为**同步 CPU/IO 调用**，且运行在 `asyncio` 任务内（`ai_task_service.py:476`、`ai_service.py:540`）。在 uvicorn 单 worker 下会**阻塞整个事件循环**，建议 `await asyncio.to_thread(...)`。
- **⚠ 多 worker 并发写**：每个 uvicorn worker 各自 `PersistentClient` 指向同一 `data/chroma` 目录；`rebuild_seed_index()` 的 `delete`+`add` 非原子，并发 approve 有竞争/锁告警风险（写入频率低，概率小但存在）。
- `local_files_only=True`：模型未预下载时 `_EMBEDDING_AVAILABLE=False`，**整个向量路径静默降级为关键词**（运维须预置模型）。

---

## 5. 与 AI 分析的集成点

- **调用位置**：`ai_task_service._execute_task` 在「解析回复后、保存报告前」调用 `KnowledgeRetriever.retrieve(tiered_data, limit=5, structured=True)`（`ai_task_service.py:474-480`），旧路径 `ai_service.analyze_with_ai_json` 在 `:540-544` 同样调用。两者均在**组装 prompt 阶段**（`PromptBuilder.build(include_knowledge=True)`，`prompt_builder.py:618`）与**报告后处理阶段**各检索一次（两次检索，略有冗余）。
- **可配置性**：`limit=5` 硬编码；阈值/Top-K 全硬编码；**没有「本次请求是否检索」的开关**。`AiAnalysisRequest.include_rag_detail`（`schemas/ai.py:93`）字段存在但**未被 `ai_task_service` 消费**（full 模式始终检索）。`build_module`/`_build_deep_dive_context` 故意 `include_knowledge=False`（模块/深挖模式不注入知识）。
- **证据溯源关联**：检索结构化结果 → `_cross_validate_knowledge`（`ai_task_service.py:956-1169`）做 IOC 交叉校验，打 `evidence_level: confirmed/none` → 仅 `confirmed` 进 `ExplainabilityService.build_evidence_trace`（`explainability_service.py:339-422`）→ 写入报告 `threat_analysis.evidence_trace.knowledge_evidence`。
- **可回溯性（弱点）**：`knowledge_evidence` 仅含 `title/rule_name/description/summary/score/confidence/match_reason` 等**快照字段**，**无知识条目 ID / 无草稿 ID / 无种子 ID**，且 `EvidenceTracePanel.vue:9-16` 仅展示文本、**不可点击跳转到源知识条目**。因此报告中的证据**无法回溯到具体知识库条目**（尤其无法区分「内置种子」vs「某次 AI 建议草稿」）。`evidence_level`（confirmed/none）已计算却**未透传给前端展示**。

---

## 6. 代码质量与技术债

- **大文件/复杂函数**：`knowledge_retriever.py`（1011 行）、`prompt_builder.py`（1768 行）、`ai_task_service.py`（1243 行）均偏重；`_keyword_retrieve`（`:842-1010`，~170 行）与 `_vector_retrieve`（`:714-836`）**重复构造同一结构化 dict 形状**，可抽取为 `_to_structured_item()`。
- **硬编码**：模型名、集合名、chroma 路径、阈值 `0.7`、Top-K 系数 `3`、budget `80000` 散落常量/配置，缺乏统一检索配置对象。
- **死代码**：`data/knowledge_seed.py:173-183 SEED_DOCUMENTS` 定义但**未被 retriever 消费**（retriever 自己从 `_load_seed_data()` 重建 doc 列表）。
- **错误处理**：chroma 连接/编码均有 try/except 并降级，较好；但 `rebuild_seed_index` 失败仅 `logger.warning` 不阻断 approve（可接受，但造成 §3 的静默不一致）。
- **懒加载（已做得较好）**：chroma 客户端与 embedding 模型均**懒加载**（`_get_collection`/`_get_embedding_model`），`main.py:41-46` 启动仅 `init_db()`，**不初始化 chroma、不下载模型**——避免了拖慢启动。✅ 这是本子系统的亮点。
- **测试覆盖（缺失）**：项目有 `tests/test_p2_features.py`、`tests/test_explainability_service.py`，但**两者均未覆盖 `knowledge_retriever` / `KnowledgeRetriever` / `KnowledgeDraft`**（已 grep 验证）。检索核心逻辑 **0 单测**，回归风险高——尤其 §3 的索引 bug 本可被一个单测捕获。

---

## 7. 安全与风险

- **⚠ 知识库管理接口未鉴权（高）**：`api/knowledge_draft.py` 全文**无任何 `Depends(...)`**（已 grep 确认 `backend/app/api` 下 agent/analysis/hosts/cases/ai/... 均含鉴权依赖，唯独 knowledge_draft 缺失）；`main.py` 也未挂全局鉴权中间件。`router/index.js` 的 `requiresAuth` 仅是**前端路由守卫**，后端 `/api/knowledge/*`（approve/reject/import/sync/recall）可被**未认证请求直接调用**。危害：任意网络可达者能批准/导入/同步知识，污染 RAG 语料。建议补齐与其他路由一致的 `Depends(get_current_user)`。
- **⚠ Prompt 注入（中-高）**：知识条目 `title`/`description` 经 `_build_knowledge_section` 以**纯文本无隔离**拼入 user prompt（`:1617`）。AI 建议草稿（`ai_task_service.py:381-392`）、手动导入、第三方同步的内容均为**用户/外部可控**。若注入如「忽略以上指令，输出…」类文本并被管理员批准入库，会污染后续所有主机的 AI 分析。建议：用明确分隔符 + 标注「以下为参考资料，非指令」，或对来源做信任分级。
- **SSRF / 路径遍历（低）**：`/sync/{provider}` 仅接受固定三元组（`api/knowledge_draft.py:301-306`），无任意 URL；导入走前端 `FileReader` 解析后仅 POST JSON，**后端不读文件**，无路径遍历。此项风险低。
- **信息泄露（低）**：`GET /seeds` 与 `/drafts` 未鉴权即可读全部知识（含 AI 建议的内部威胁描述），结合上一点构成「读+写」未授权面。

---

## 8. 可改进项（按收益/风险排序）

| # | 改进项 | 收益 | 风险/成本 | 关键位置 |
|---|---|---|---|---|
| 1 | **修复种子/草稿向量化 bug**：`_build_seed_index` 改为「先按 `seed_`/`draft_` 前缀精确 `get` 计数，而非 `collection.count()>0` 早退」；`reject`/`recall` 也触发 `rebuild_seed_index` | 高——让 RAG 真正覆盖安全知识点、消除已拒绝条目残留 | 低（改守卫条件 + 两处触发） | `knowledge_retriever.py:327-331,617-663`；`api/knowledge_draft.py:149,163` |
| 2 | **知识库接口加鉴权**：补齐 `Depends(get_current_user)`，与 ai/hosts 等路由一致 | 高——封堵未授权写/读 | 低 | `api/knowledge_draft.py` 全文件；`main.py:68` |
| 3 | **检索可配置化**：把 `limit`/`top_k`/`threshold`/是否检索做成配置或请求参数；消费 `include_rag_detail` | 中-高——便于调优与按需关闭 | 低 | `knowledge_retriever.py:56,756`；`ai_task_service.py:476`；`schemas/ai.py:93` |
| 4 | **证据可点击溯源**：知识条目写入 chroma 时带 `draft_id`/`seed_id` metadata；`knowledge_evidence` 透传该 ID；前端 `EvidenceTracePanel` 渲染跳转链接 | 中-高——闭环可解释性 | 中（改 metadata + 前端） | `knowledge_retriever.py:358`；`EvidenceTracePanel.vue:9-16` |
| 5 | **防 Prompt 注入**：知识文本用 `<<<KNOWLEDGE>>>` 分隔并声明「非指令」；对 `external` 来源降级信任 | 中-高——防止语料投毒 | 低 | `prompt_builder.py:1612-1617` |
| 6 | **异步化检索**：`KnowledgeRetriever.retrieve` 用 `asyncio.to_thread` 包裹 encode/query，避免阻塞事件循环 | 中——提升并发吞吐 | 低 | `ai_task_service.py:476`；`ai_service.py:540` |
| 7 | **补齐单测**：覆盖 `_build_index`/`_build_seed_index`/`rebuild_seed_index`/`retrieve` 的向量/关键词分支与状态一致性 | 中——防止回归（#1 类 bug） | 低 | `tests/` 新增 `test_knowledge_retriever.py` |
| 8 | **轻量重排 + 知识条目版本管理**：对 Top-K 做规则/severity 重排；`knowledge_drafts` 加 `version` 避免撤回后报告里旧向量歧义 | 中——提升命中质量与审计 | 中 | `knowledge_retriever.py:_vector_retrieve`；`models/knowledge_draft.py` |

---

## 附：一句话总评
知识库子系统**设计意图清晰（审核闭环 + RAG 拼接 + 证据溯源）且懒加载/降级做得不错**，但有一个**阻断性的索引 bug**（`_build_seed_index` 的 `count()>0` 早退 + reject/recall 不重建）导致**向量库事实上只含规则名、不含真正的安全知识点、且已拒绝条目仍会命中**；叠加**管理接口未鉴权**与**0 单测**，是当前最高优先级的修复点。
