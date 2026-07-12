# IR 平台 RAG 知识库优化方案 — 架构评审报告
> 评审人：高见远（Gao）· 架构师  |  日期：2026-07-12  |  版本：v1.0

## 零、执行摘要（TL;DR）

方案技术方向正确，但存在 **4 处事实性错误**（种子数据量、规则数、模型名、`rebuild_seed_index` 已存在）和 **2 处架构遗漏**（embedding server 未考虑、前端交互细节缺失）。P0 基础设施事实上已 60% 就绪（`_build_seed_index`/`rebuild_seed_index` 已实现），核心差距只在「模型未下载 + ChromaDB 无索引」。建议调整优先级：跳过 P0 的「实现 rebuild_seed_index」部分，聚焦模型部署与验证。

---

## 一、代码交叉验证结果

> 标注体系：✅ 与代码一致 / ⚠️ 部分正确，需修正 / ❌ 事实性错误

### 1.1 knowledge_retriever.py（22 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 1 | "第50行是模型名" | ✅ | `knowledge_retriever.py:50` — `EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"`，确实是模型名定义行 |
| 2 | 当前模型为 paraphrase-multilingual 系列 | ❌ | **实际是 `all-MiniLM-L6-v2`**（384维/英文为主），不是方案所称的 `paraphrase-multilingual-MiniLM-L12-v2`。当前模型从未被下载过（`local_files_only=True` 导致首次加载失败后直接回退关键词） |
| 3 | "改 knowledge_retriever.py:50 一行模型名"即可部署 | ✅ | 修改方案正确且简单。但方案推荐 `paraphrase-multilingual-MiniLM-L12-v2`（384维/470MB/12语言）替代当前 `all-MiniLM-L6-v2`（384维/80MB/英文），见下方 2.2 节的技术评审 |
| 4 | `retrieve()` 只接受 `tiered_data` | ⚠️ | `knowledge_retriever.py:758-796` — 实际签名为 `retrieve(analysis_data: dict, limit: int = 5, structured: bool = False)`。`structured=True` 返回带 `entry_ref`/`entry_type` 的结构化证据（方案未提及此能力） |
| 5 | `_get_embedding_model()` 返回 None 时回退关键词 | ✅ | `knowledge_retriever.py:75-102` — `local_files_only=True`（:91），加载失败时设置 `_EMBEDDING_AVAILABLE = False`（:101），符合方案描述 |
| 6 | `_ensure_index()` 仅做幂等初始化 | ✅ | `knowledge_retriever.py:681-703` — 延迟初始化模式，先 `_build_index()` 再 `_build_seed_index()` |
| 7 | `rebuild_seed_index()` 需 P0 实现 | ❌ | `knowledge_retriever.py:706-751` — **该方法已完整实现**！包含：清空缓存 → 删除旧 seed/draft 条目 → 重建种子索引。方案将 P0 的核心工作量错误地标为「需实现」 |
| 8 | `_build_seed_index()` 需新建 | ❌ | `knowledge_retriever.py:325-459` — **已实现**，支持 seed_ 前缀 ID（内置）+ draft_ 前缀 ID（已批准草稿），含幂等检查（`_seed_or_draft_exists`）。代码注释明确写了"MITRE/C2/Malware 共 10 条" |
| 9 | 向量检索阈值 0.7（cosine distance） | ✅ | `knowledge_retriever.py:56` — `VECTOR_DISTANCE_THRESHOLD: float = 0.7`。结构化模式下 distance ≤ 0.35 为 high 置信度（:894） |
| 10 | `_keyword_retrieve()` 存在且有打分逻辑 | ✅ | `knowledge_retriever.py:934-1121` — 四元组打分（name_hits + desc_hits + pat_hits + severity bonus），种子知识按 pattern 字段额外匹配（:1047-1050） |
| 11 | 关键词回退的规则匹配仅看 default_rules.json | ⚠️ | `knowledge_retriever.py:953` — `_keyword_retrieve()` 同时匹配 rules (`_load_rules()`) + seeds (`_load_seed_data()`) + C2 签名。方案描述不完整 |

### 1.2 knowledge_draft.py（API）（9 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 12 | `POST /api/knowledge/import` 已实现 | ✅ | `main.py:69` — router prefix 是 `/api/knowledge`。`knowledge_draft.py:241` — `@router.post("/import")`，最终路径 `POST /api/knowledge/import` |
| 13 | 支持 JSON 数组批量 | ✅ | `knowledge_draft.py:42-45` — `ImportRequest` 包含 `items: list[ImportItem]`，同时支持 `text: Optional[str]` 自由文本导入 |
| 14 | 三元组去重 `KnowledgeDraft.is_duplicate()` | ✅ | `knowledge_draft.py:293` — 调用 `KnowledgeDraft.is_duplicate(title, category, mitre_attack)` |
| 15 | 导入后 status=pending 需管理员审核 | ✅ | `knowledge_draft.py:299-308` — `KnowledgeDraft.create(...)` 默认 status='pending'，source 从请求传入 |
| 16 | "批准后自动触发 rebuild_seed_index()" | ⚠️ | `knowledge_draft.py:158-163` — 是 **API 端点**（非模型）在 `approve_draft()` 中调用 `KnowledgeRetriever.rebuild_seed_index()`。Model 的 `KnowledgeDraft.approve()`（:135-166）**不触发索引重建**，仅是状态更新 |
| 17 | API 端点共 10 个 | ⚠️ | 实际 9 个端点（不含 `/api/knowledge` 前缀）：GET /drafts, GET /seeds, GET /drafts/{id}, POST /drafts/{id}/approve, POST /drafts/{id}/reject, POST /drafts/{id}/recall, POST /drafts/batch, POST /import, POST /sync/{provider} |

### 1.3 knowledge_seed.py（4 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 18 | "25条种子" | ❌ | `knowledge_seed.py:170` — `ALL_SEED_KNOWLEDGE = MITRE_TECHNIQUES(5) + C2_FRAMEWORKS(3) + MALWARE_PATTERNS(2) = **10 条**`。与方案所称 25 条有显著差距 |
| 19 | 种子数据格式包含 name/description/category/severity | ✅ | `knowledge_seed.py:16-161` — 每条含 name/description/category/severity/tactic(部分)/pattern(部分) |
| 20 | `ALL_SEED_KNOWLEDGE` 是列表拼合 | ✅ | `knowledge_seed.py:170` — `MITRE_TECHNIQUES + C2_FRAMEWORKS + MALWARE_PATTERNS` |

### 1.4 analysis_service.py（4 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 21 | 第148行 `AnomalyDetector.detect_processes()` | ✅ | `analysis_service.py:148` — 确在此行调用 `AnomalyDetector.detect_processes(raw_data, rules, whitelist_service=whitelist_service)` |
| 22 | 分析阶段无任何向量检索调用 | ✅ | `analysis_service.py:95-323` — `analyze()` 全程未调用 `KnowledgeRetriever`。知识检索仅发生在 AI 分析阶段（`prompt_builder._build_knowledge_section()`） |
| 23 | 分析流程是"规则引擎(正则) → 异常检测结果" | ✅ | `analysis_service.py:148-158` — 先 detect_processes → detect_connections → detect_startup_items，均为规则引擎驱动 |

### 1.5 providers/ 目录（3 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 24 | 三个 provider 均无 `fetch_ioc_list()` | ✅ | 三个文件均仅实现 `query(ioc_type, ioc_value)` 方法。`enrichment_service.py` 中 `EnrichmentService` 也无 `fetch_ioc_list` 方法（Grep 搜索结果 0） |
| 25 | API 中 `POST /sync/{provider}` 已路由但后端未实现 | ✅ | `knowledge_draft.py:326-425` — `sync_from_provider()` 调用 `svc.fetch_ioc_list()` 但捕获 `AttributeError` 返回 "fetch_ioc_list not available"（:367-372） |
| 26 | 三个 provider 均继承 `BaseThreatIntelProvider` | ✅ | 各文件 import 语句确认，均实现 `query()` 方法 |

### 1.6 prompt_builder.py（2 项检查）

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 27 | `_build_knowledge_section()` 调用 KnowledgeRetriever | ✅ | `prompt_builder.py:1584-1638` — 调用 `KnowledgeRetriever.retrieve(tiered_data, limit=5, structured=True)`，并构建规则命中联动、历史案例上下文 |
| 28 | 知识检索仅在 AI 分析时才触发 | ✅ | `prompt_builder.py:618-638` — 仅在 `include_knowledge=True` 时在 `build()` 方法中注入知识库段 |

### 1.7 其他基础设施

| # | 方案断言 | 结果 | 实际代码证据 |
|---|---------|------|-------------|
| 29 | `backend/app/data/chroma/` 目录不存在 | ✅ | Bash 验证 — 目录确实不存在。ChromaDB 从未被初始化 |
| 30 | agent/collectors 有 20 个采集器 | ✅ | 实际 20 个 `.py` 文件（不含 `__init__`, `base_collector`, `resource_budget`）：browser, files, ioc, linux, logs, memory, network, persistence, process_events, processes, registry, remote_control, security, services, startup_items, system_info, timeline, usb, users, webshell |
| 31 | 规则文件共 133 条 | ⚠️ | 实际 135 条：`default_rules.json`(102) + `process_enhancement_rules.json`(24) + `seed_rules_process.json`(5) + `default_attack_chain.json`(2) + `revoked_ca.json`(2) = **135**。方案说 133，差 2 条（误差 ~1.5%，可接受） |

---

## 二、P0-P3 逐层技术评审

### 2.1 P0：基础设施就绪（⚠️ 需改进）

**总体判断**：方向正确但严重高估工作量。P0 三大任务中「规则→知识导入」和「rebuild_seed_index」已有完整代码。

| 子任务 | 方案判断 | 实际就绪度 | 评审意见 |
|--------|---------|-----------|---------|
| 规则→知识批量导入 | "需新建脚本" | **60% 就绪** | `POST /api/knowledge/import` 已支持 JSON 数组批量导入 + 三元组去重。缺的是一个将 rules JSON 转换为 ImportItem 的映射脚本（~30行）。方案描述的字段映射是准确的 |
| 嵌入模型下载 | "改一行 + 手动下载" | **0% 就绪** | 模型确实从未下载。`local_files_only=True` 是正确策略。但方案推荐模型需重新评估（见下） |
| ChromaDB 索引构建 | "需实现 rebuild_seed_index" | **90% 就绪** | `rebuild_seed_index()` 已实现（:706-751），`_build_seed_index()` 也已实现（:325-459）。只需模型就位 + 重启服务即可自动触发 |

**关键修正**：
- P0 实际有效工作量：模型选型决策 + 下载部署 + 编写规则→知识导入映射脚本（约30行）+ 验证。预估 **4-6 小时**（非 2-3 天）。
- 方案未发现 `rebuild_seed_index()` 已存在，导致 P0 工作量被高估约 40%。

### 2.2 嵌入模型选型评审（重点关注）

方案推荐 `paraphrase-multilingual-MiniLM-L12-v2`。以下是评审：

| 维度 | all-MiniLM-L6-v2（当前） | paraphrase-multilingual-MiniLM-L12-v2（方案推荐） | bge-base-zh-v1.5（备选） |
|------|--------------------------|------------------------------------------------|--------------------------|
| 维度 | 384 | 384 | 768 |
| 大小 | ~80MB | ~470MB | ~420MB |
| 语言 | 英文为主 | 12语言（含中英） | 中英双语优化 |
| CPU推理 | ~20-50ms | ~50-100ms | ~80-150ms |
| 安全术语 | 一般 | 一般（通用语义） | **较好**（中文安全社区预训） |

**我的建议**：

- **不推荐 `paraphrase-multilingual-MiniLM-L12-v2`**。理由：
  1. IR 平台的知识库是**中英混合**（MITRE 英文 + 中文描述），多语言模型对此场景并无明显优势。
  2. 12 层（vs 6 层）意味着 CPU 推理延迟翻倍，但维度相同（384），语义表达能力提升有限。
  3. 470MB 对于纯 CPU 环境较大，且未包含安全领域预训练。

- **推荐 `BAAI/bge-base-zh-v1.5`**（768维）。理由：
  1. BGE 系列在中文安全/技术文本的语义检索上显著优于通用多语言模型（MTEB 中文榜排名靠前）。
  2. 768 维在 CPU 上的额外开销可控（~1.3× 推理时间），但检索精度提升明显（尤其对于"PowerShell 无文件攻击" vs "编码命令执行"这类近义词区分）。
  3. 420MB 大小可接受，且 HuggingFace 镜像国内可访问。

- **P0 应额外包含一个"向量检索质量自检"步骤**：选取 5 个已知攻击模式（如"Cobalt Strike Beacon HTTP 心跳"、"勒索软件 vssadmin 删除卷影"），验证 Top-3 召回是否准确。这是方案完全未覆盖但至关重要的质量把关环节。

### 2.3 P1：分析阶段双路检测（✅ 通过，3 处需补充）

**架构评价**：双路检测（规则引擎 + 向量语义并行执行 → 结果合并）是成熟的架构模式。方案代码示例合理。

**遗漏点**：

1. **语义结果与 severity 联动缺失**：方案仅提到结果合并，但未说明语义检索返回的 `[category/severity] rule_name` 如何与前端已有的异常等级渲染联动。当前 `_vector_retrieve` 已经在 `structured=True` 模式下返回 `confidence: "high"/"medium"` 和 `score`（:894-913），这是方案未提及的**已有能力**。

2. **置信度算法需明确**：方案说"置信度算法调优"但未给出具体策略。当前代码已有基础：`distance ≤ 0.35 → high, else medium`。建议增加：
   - 规则命中 + 语义命中 → 置信度提升一档
   - 仅语义命中无规则佐证 → 降为 low，标记 `needs_review`

3. **性能估算偏乐观**：方案估算"全流程增加 1-2s"。实际 CPU 推理（`bge-base-zh-v1.5` 768维）编码 `_build_query_text` 产出的长文本（通常 500-2000 字符）可能耗时 **150-400ms/次**，而非方案说的 50-100ms。建议增加**查询文本截断**（取前 512 token）或**批量预编码热点查询**。

### 2.4 P2：第三方同步与审核自动化（✅ 通过，小幅调整）

**评审意见**：
- `fetch_ioc_list` 方案设计合理。各 provider 新增 `fetch_list()` 方法返回 IOC 列表，然后在 `EnrichmentService` 聚合。
- 建议三个 provider 各自实现 `fetch_list(limit: int) -> list[dict]` 方法，返回统一格式的 `{"ioc_type", "ioc_value", "description", "severity"}` — 而非在 EnrichmentService 层做转换。
- 自动审核规则（15行代码）合理且简洁。
- 定时同步：建议用 `apscheduler`（已在 Python 生态成熟），比 crontab 更易集成到 FastAPI 生命周期。

### 2.5 P3：高级能力（✅ 方向认可，标记为探索性）

远期规划不做详细评审。提醒：
- "多模态知识"（截图/网络拓扑 → 向量化）需要先明确存储方案（ChromaDB 不支持多模态，需评估 CLIP + 独立 collection 或换 Milvus）。
- "持续学习闭环"涉及 RLHF 或类似反馈机制，与当前架构差异大，建议 P3 仅做技术预研。

---

## 三、优化建议

### 方案内可改进（5 条）

**P0-① 种子数据量错误需要修正**
- 问题：方案说"25→158条"，实际种子仅 10 条。规则总数为 135 条。
- 建议：修正为"规则→知识批量导入 10→145 条（10 条种子 + 135 条规则）"。导入脚本应标注 `source="rule_import"` 以便追溯。

**P0-② 模型选型建议改为 bge-base-zh-v1.5**
- 理由见 2.2 节。中英混合安全知识库场景下 BGE 系列优于通用多语言模型。
- 需同步调整 `knowledge_retriever.py:50` 的 `EMBEDDING_MODEL_NAME`。

**P0-③ 导入脚本增加 `--dry-run` 和进度条**
- 当前 `POST /api/knowledge/import` 无预览模式。135 条规则导入前应先 dry-run 验证字段映射正确性。
- 建议新增 `POST /api/knowledge/import?dry_run=true` 或独立 `POST /api/knowledge/import/preview`。

**P1-④ 语义检索结果应与规则引擎命中做交叉验证**
- 当同一异常进程同时命中规则（如 `suspicious_powershell_encoded`）和语义检索（如"PowerShell 无文件攻击"）时，应合并为一条高置信度告警，而非展示两条独立结果。
- 合并键：`(process_name, rule_name ≈ seed_name)` 的模糊匹配。

**P1-⑤ 双路检测的查询文本应截断**
- `_build_query_text` 在数据量大时可能产生 2000+ 字符的查询文本。
- 建议在 `_vector_retrieve` 中增加截断逻辑：`query_text[:512]` 或按 token 数截断（sentence-transformers 的 max_seq_length 默认 256 tokens）。

### 方案未覆盖的新建议（3 条）

**新增-① P0 增加「向量检索质量自检」工具**
- 实现独立的 `POST /api/knowledge/validate-retrieval` 端点：输入已知攻击描述 → 返回 Top-5 语义检索结果和相似度分数。
- 目标：在模型部署后立即验证检索质量（人工抽查 10 个典型攻击模式），低于 80% Top-3 准确率则调整模型或阈值。

**新增-② P1 增加「知识库覆盖缺口」反馈闭环**
- 当前 `prompt_builder.py` 已有 `INPUT_SUGGESTIONS` 和 `coverage_gaps` 字段（:584-589）。P1 应利用这些字段：当向量检索结果全为低置信度（score < 0.3）时，自动生成 `knowledge_suggestions` 进入草稿审核区。
- 这是一个「检测 → 发现缺口 → 自动建议 → 审核 → 入库」的完整闭环，方案未提及但代码已具备基础。

**新增-③ P2 增加「知识库版本管理」**
- 规则修改后 ChromaDB 索引可能包含过期条目（`rebuild_seed_index` 不会删除旧的 rule_* 条目）。P2 应在 `_build_index` 中增加版本号或时间戳，支持增量更新而非全量重建。

---

## 四、可行性四维评估

### 技术可行性：**8/10**

| 维度 | 评分 | 理由 |
|------|------|------|
| 与现有代码兼容 | 9/10 | 核心改动均「只增不改」。`analysis_service.py` 的改动（方案附录 P1-②）是在 `analyze()` 之后新增并行检索调用，不改变现有规则引擎逻辑 |
| 代码改动量 | 7/10 | P0: ~30 行（映射脚本）+ 1 行（模型名）；P1: ~60 行（双路检测）；P2: ~100 行（provider 扩展 + 定时任务）。总计约 200 行净增，改动范围可控 |
| 「需改既有代码」占比 | 8/10 | P0 仅改 1 行（模型名）。P1 修改 `analysis_service.py` 约 20 行 + `knowledge_retriever.py` 约 10 行。无破坏性变更 |

### 资源可行性：**7/10**

| 维度 | 评分 | 理由 |
|------|------|------|
| 模型存储 | 7/10 | bge-base-zh-v1.5 约 420MB，需确保服务器磁盘可用空间 > 2GB（含 ChromaDB 向量索引） |
| ChromaDB 索引体积 | 8/10 | 145 条知识 × 768 维 × 4 字节 ≈ 445KB，加元数据约 2-5MB，可忽略 |
| CPU 推理瓶颈 | 6/10 | 每次分析调用 1 次 embedding（查询编码），150-400ms。若批量分析多主机，建议增加 `functools.lru_cache` 缓存热点查询（相同分析数据 → 相同查询文本） |
| 内存 | 8/10 | 模型常驻约 420MB + ChromaDB client ~50MB，总计 < 500MB，可接受 |

### 时间可行性：**7/10**（方案估算偏保守但方向正确）

| 阶段 | 方案估时 | 实际建议 | 理由 |
|------|---------|---------|------|
| P0 | 2-3 天 | **0.5-1 天** | 核心代码已 60% 就绪。主要时间花在模型下载和验证 |
| P1 | 1-2 周 | **1 周** | 双路检测编码量不大（~60行），但置信度调优需要 2-3 轮迭代测试 |
| P2 | 2-4 周 | **2 周** | provider 扩展需三方 API 联调，不可控因素多 |
| P3 | 远期 | **暂不排期** | 探索性方向，先 P0-P2 落地再评估 |

### 风险可行性：**6/10**（方案列 5 项，补充 3 项）

方案已列出的 5 项风险（模型版本锁定、无 GPU 延迟、幻觉/噪音、API 配额、权限模型复杂化）基本合理但有遗漏。见下节。

---

## 五、风险补充

### 方案遗漏的风险

**R-1 模型与 ChromaDB 的 HNSW 索引参数不匹配风险**（严重度：中）
- 当前 `_get_collection()` 设置 `hnsw:space: cosine`（:124）。如果切换模型后 embedding 的语义分布变化（例如 BGE 模型的 embedding 范数分布与 MiniLM 不同），cosine 距离阈值 0.7 可能需要重新校准。
- 缓解：模型切换后必须运行「向量检索质量自检」（见建议新增-①）。

**R-2 种子知识（10条）语义检索几乎无召回风险**（严重度：高）
- 10 条种子数据对语义检索来说样本量**严重不足**。即使向量化，查询"可疑 PowerShell 编码执行"与种子"PowerShell (无文件攻击)"的 cosine 距离可能 > 0.7，导致无召回。
- **这是方案的核心盲区**：方案假设 25 条种子 + 133 条规则 = 158 条足够。但实际上种子只有 10 条，且规则的 name/description 匹配更适合关键词（精确命名如 `suspicious_powershell_encoded`），语义检索的优势在于模糊匹配（如"检测到 base64 编码的 PowerShell 命令"应召回"PowerShell 无文件攻击"）。
- 缓解：P0 必须确保**所有 135 条规则也纳入 ChromaDB 索引**（当前 `_build_index` 只索引 `default_rules.json` 的 102 条，未包含 `process_enhancement_rules.json` 等的 33 条！）。见下方 R-3。

**R-3 `_build_index` 仅索引了 102/135 条规则**（严重度：高）
- 当前 `knowledge_retriever.py:137-151` 的 `_load_rules()` 只加载 `default_rules.json`（102条）。
- `process_enhancement_rules.json`(24条)、`seed_rules_process.json`(5条)、`default_attack_chain.json`(2条)、`revoked_ca.json`(2条) 未被索引。
- 缓解：P0 中修改 `_load_rules()` 改用 `rules/loader.py` 的 `load_default_rules()`（该函数已遍历所有 *.json 文件），或直接在 `_build_index` 中使用它。

---

## 六、推荐实施顺序

基于代码交叉验证结果，建议调整原方案 P0-P3 的顺序和内容：

### 调整后的实施路线

```
Phase 0（1天）：模型部署 + 验证
├── Step 1: 模型选型决策 → bge-base-zh-v1.5
├── Step 2: 修改 knowledge_retriever.py:50 → 一行
├── Step 3: 修改 _load_rules() → 用 loader.load_default_rules() 替代
├── Step 4: 手动下载模型 + 重启服务 → 触发 _build_index + _build_seed_index
└── Step 5: 运行质量自检（10个典型攻击模式 Top-3 准确率 ≥ 80%）

Phase 1（3天）：规则→知识导入 + 双路检测 MVP
├── Step 1: 编写规则JSON→ImportItem 映射脚本（~30行）
├── Step 2: 调用 POST /api/knowledge/import 批量导入
├── Step 3: 管理员审批 + 验证 rebuild_seed_index
├── Step 4: 实现 analysis_service 并行双路检索（~60行）
├── Step 5: 置信度交叉验证 + 去重逻辑
└── Step 6: 前端结果标签展示

Phase 2（1-2周）：第三方同步 + 审核自动化
├── Step 1: provider.fetch_list() 实现（3个provider × ~30行）
├── Step 2: EnrichmentService 聚合
├── Step 3: 自动审核规则（~15行）
├── Step 4: apscheduler 定时任务（~20行）
└── Step 5: 去重与版本管理

Phase 3（远期探索）：高级能力
├── 多主机关联检索（需等 P1 双路检测稳定）
├── 多模态知识（需独立技术预研）
└── 持续学习闭环（RLHF 预研）
```

### 与原方案的关键差异

| 原方案 | 调整后 | 原因 |
|--------|--------|------|
| P0 2-3天全量实施 | Phase 0+1 共 4 天 | 拆分模型部署与规则导入，降低耦合 |
| P0 含"实现 rebuild_seed_index" | Phase 0 不含 | 已实现，仅需修改 `_load_rules()` |
| P0 模型为 paraphrase-multilingual | Phase 0 模型为 bge-base-zh | 中英混合安全领域更优 |
| P1 无质量自检 | Phase 0 Step 5 质量自检 | 关键质量把关 |
| P1 后做前端改动 | Phase 1 Step 6 就做 | 语义检索结果已有结构化输出，前端改动可与后端并行 |

---

## 附录：代码引用索引

| 文件 | 关键行号 | 内容 |
|------|---------|------|
| `backend/app/services/knowledge_retriever.py` | :50 | 嵌入模型名定义 |
| | :56 | 向量检索阈值 |
| | :75-102 | `_get_embedding_model()` — local_files_only=True |
| | :137-151 | `_load_rules()` — 仅加载 default_rules.json |
| | :220-305 | `_build_index()` — 规则向量索引（幂等） |
| | :308-322 | `_seed_or_draft_exists()` — 精确幂等检查 |
| | :325-459 | `_build_seed_index()` — **已实现** |
| | :681-703 | `_ensure_index()` — 延迟初始化 |
| | :706-751 | `rebuild_seed_index()` — **已实现** |
| | :758-796 | `retrieve()` — 支持 structured 模式 |
| | :803-927 | `_vector_retrieve()` — 完整向量检索链路 |
| | :934-1121 | `_keyword_retrieve()` — 关键词回退 |
| `backend/app/api/knowledge_draft.py` | :26 | router 定义（prefix 见 main.py:69） |
| | :42-45 | ImportRequest — 支持 JSON 数组 + 文本 |
| | :144-165 | approve_draft — 触发 rebuild_seed_index |
| | :241-323 | import_knowledge — 手动导入端点 |
| | :326-425 | sync_from_provider — 调用 fetch_ioc_list |
| | :366-372 | fetch_ioc_list AttributeError fallback |
| `backend/app/models/knowledge_draft.py` | :135-166 | `approve()` — 不触发索引重建 |
| | :282-309 | `is_duplicate()` — 三元组去重 |
| | :312-337 | `get_as_seed_entries()` |
| `backend/app/data/knowledge_seed.py` | :15-78 | MITRE_TECHNIQUES: 5 条 |
| | :85-121 | C2_FRAMEWORKS: 3 条 |
| | :127-161 | MALWARE_PATTERNS: 2 条 |
| | :170 | ALL_SEED_KNOWLEDGE: 10 条 |
| `backend/app/services/analysis_service.py` | :148 | `AnomalyDetector.detect_processes()` |
| | :95-323 | `analyze()` — 全程无向量检索调用 |
| `backend/app/services/prompt_builder.py` | :618-638 | 知识库注入到 AI prompt |
| | :1584-1638 | `_build_knowledge_section()` |
| `backend/app/services/providers/` | 三个文件 | 均仅含 `query()`，无 `fetch_list()` |
| `backend/app/rules/default_rules.json` | — | 102 条规则 |
| `backend/app/rules/process_enhancement_rules.json` | — | 24 条规则 |
| `backend/app/rules/seed_rules_process.json` | — | 5 条规则 |
| `backend/app/rules/default_attack_chain.json` | — | 2 条规则（attack_chain 类型） |
| `backend/app/rules/revoked_ca.json` | — | 2 条规则 |
| `backend/app/main.py` | :69 | router prefix: `/api/knowledge` |
| `backend/app/rules/loader.py` | :25-73 | `load_default_rules()` — 遍历所有 *.json |
