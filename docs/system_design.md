# IOC 外联威胁情报增强（微步 Outbound Enrichment）— 架构设计 + 任务分解

> 作者：架构师 高见远（Gao）　|　面向：主理人 / 工程师　|　阶段：架构设计（SOP 架构阶段产出）
> 范围：既有 SOC 平台 IOC 模块的 **Outbound 增强**——把 `iocs` 表里的外联 IP/域名主动推送/查询到微步 ThreatBook，取回威胁评分/判定/标签/团伙，落独立表 + 展示 + **回灌规则引擎判黑** + **自动调度**。

---

## 一、实现方案 + 框架选型

### 1.1 核心难点
| 难点 | 应对 |
|------|------|
| 外联查询依赖第三方威胁情报平台 API，需统一抽象以便后续扩 provider | 基类 `BaseThreatIntelProvider` + `ThreatBookProvider` 实现；轻量扩展点（不建完整插件系统，但新增 provider = 加一段 JSON + 一个子类） |
| 回灌引擎不能破坏既有 list 命中语义与降级能力 | 仅在 `evaluate` 入口"额外"加载威胁等级字典；开关关闭时完全不加载、`_match_list` 不查，`_load_iocs_by_type` 原逻辑零改动 |
| 自动调度不能引入重依赖、需与既有 feed 同步一致 | 复刻 `ioc_feed_sync.py` 的 `--once`/`--loop` + `expand_env` 范式，不引 APScheduler |
| apikey 不落明文 | 一律 `$ENV_VAR` 引用，JSON 配置只存引用，运行期 `expand_env` 展开 |
| 配额/限流，避免烧外部 API 额度 | EnrichmentService 统一编排：单 provider 串行 + QPS 限流 + 当日配额计数 + 短期 TTL 去重 |

### 1.2 框架选型（**零新增重依赖**）
- **后端**：复用既有 **FastAPI + SQLite + httpx(0.27.0，已存在)**。
- **Provider 抽象**：基类 + 微步实现（文件内 `class`，非独立插件包）。
- **自动调度**：`--loop` 内置 `time.sleep` 轮询（与 `ioc_feed_sync` 完全一致），`--once` 配系统 cron 生产部署。
- **落库**：新增独立 `threat_intel` 表（保留历史，支持趋势对比）。
- **配置**：provider 连接信息 → JSON 文件（`threat_intel_providers.json`）；运行策略（开关/配额/调度） → 另一 JSON（`threat_intel_settings.json`）。两者均不落密钥明文。
- **前端**：复用既有 Vue3 + ElementPlus（`IocsView.vue` 改造 + 新增 `ThreatIntelConfigView.vue`），axios 封装 `request` 不动。

---

## 二、文件列表（相对仓库根）

### 新增
- `backend/app/models/threat_intel.py` — `ThreatIntel` / `ThreatIntelProviderConfig` / `EnrichSettings` 模型（静态方法 + JSON 读写）
- `backend/app/services/enrichment_service.py` — `BaseThreatIntelProvider` / `ThreatBookProvider` / `EnrichmentService`
- `backend/app/api/threat_intel.py` — provider / settings 配置端点（挂 `/api/threat-intel`）
- `backend/scripts/enrichment_scheduler.py` — 复刻 `--once`/`--loop` 的自动调度脚本
- `backend/scripts/threat_intel_providers.json` — 默认微步 provider 模板（api_key 用 `$ENV_VAR`）
- `backend/config/threat_intel_settings.json` — 默认运行策略（开关/配额/调度）
- `frontend/src/views/ThreatIntelConfigView.vue` — 威胁情报配置页（provider + 策略）
- `frontend/src/router/index.js`（改）— 新增配置页路由
- `backend/tests/test_enrichment_provider.py`、`test_enrichment_service.py`、`test_enrichment_api.py`、`test_rule_engine_feedback.py`、`test_enrichment_scheduler.py`

### 修改
- `backend/app/database.py` — `DDL_STATEMENTS` 增加 `threat_intel` 建表（含索引）
- `backend/app/config.py` — 新增 `ENABLE_THREAT_INTEL_ENRICHMENT`（默认 `True`）、`AUTO_ENRICHMENT`（默认 `False`）等常量兜底
- `backend/app/api/iocs.py` — 新增 IOC 作用域端点：`POST /iocs/{id}/enrich`、`POST /iocs/enrich/batch`、`GET /iocs/{id}/threat-intel`
- `backend/app/api/__init__.py` / `backend/app/main.py` — `include_router(threat_intel.router, prefix="/api/threat-intel")`
- `backend/app/schemas/analysis.py` — 新增 `ThreatIntelResponse` / `EnrichRequest` / `ProviderConfig` / `EnrichSettings` / `EnrichResult`
- `backend/app/rules/rule_engine.py` — 回灌改造（仅 `evaluate` 入口 + `_match_list`，见第六节）
- `frontend/src/api/iocs.js` — 新增 enrich 系列函数
- `frontend/src/views/IocsView.vue` — 威胁情报列/按钮/详情弹窗

> **端点归属约定**：IOC 作用域动作（`/iocs/{id}/enrich` 等）放在 `iocs.py`（与既有 ioc 管理同路由）；provider/settings 配置放在新 `threat_intel.py`（挂 `/api/threat-intel`）。这同时满足"改 iocs.py"与"新增 threat_intel.py"两份要求。

---

## 三、数据库设计（Mermaid 类图）

见 `docs/class-diagram.mermaid`。要点：

### 3.1 `threat_intel` 表（独立、保留历史）
| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增 |
| `ioc_id` | INTEGER | FK → `iocs.id`（一对多；删除 ioc 时其情报由业务层级联或保留审计，本期不强制 ON DELETE） |
| `ioc_type` | TEXT | 仅 `ip` / `domain`（本期） |
| `ioc_value` | TEXT | 查询值（原值，落库冗余便于直查） |
| `provider` | TEXT | 来源，如 `ThreatBook` |
| `risk_score` | INTEGER | 0–100 威胁评分 |
| `judgments` | TEXT(JSON list) | `["malicious"]` / `["suspicious"]` / `["clean"]` / `["unknown"]` |
| `tags` | TEXT(JSON list) | 标签 |
| `confidence` | INTEGER | 置信度 0–100 |
| `attck` | TEXT(JSON list) | ATT&CK 技战术 ID 列表 |
| `company` | TEXT | 微步团伙/归属公司 |
| `threat_level` | TEXT | **派生冗余列**：`high`/`medium`/`low`/`null`（由 judgments 映射，便于查询与回灌） |
| `queried_at` | TEXT | 查询时间（SQLite `datetime('now')`） |
| `raw_summary` | TEXT | provider 原始摘要 / 原始响应 JSON（留证） |
| `created_at` | TEXT | 落库时间 |

**索引**：`(ioc_id)`、`(ioc_value, provider)`、`(provider, queried_at)`。
**去重策略**：落库**不去重、保留全历史**（满足"后续趋势对比"）；仅调度/运行时用 TTL 去重避免重复打 API（见第八节）。

### 3.2 provider 配置：放 JSON（推荐）
**建议用 JSON 文件，而非建表**。理由：
1. 与既有 `ioc_feeds.json` 范式一致（同项目已验证），`api_key` 用 `$ENV_VAR` 引用不落明文；
2. provider 接入稀少、变动不频繁，建表 + CRUD 属过度工程；
3. 可手写编辑、可版本控制、与密钥分离；
4. 扩展新 provider = 加一段 JSON + 一个 `Provider` 子类，满足"留扩展点"且轻量。

### 3.3 运行策略（开关/配额/调度）：单独 JSON
`backend/config/threat_intel_settings.json` 由 `EnrichSettings` 读写，经 `GET/PUT /api/threat-intel/settings` 持久化；与 `providers.json` 分离（连接配置 vs 运行策略）。`app/config.py` 提供默认值作为兜底。

---

## 四、程序调用流程（时序图 Mermaid）

见 `docs/sequence-diagram.mermaid`，包含三条核心链路：
1. **手动单条 enrich**（前端 → `iocs.py` → `EnrichmentService` → `ThreatBookProvider` → 落 `threat_intel`）
2. **自动调度 enrich**（`enrichment_scheduler` → 扫描未查询 ioc → `EnrichmentService` → 落库）
3. **引擎回灌**（`evaluate` 入口加载 `threat_level_by_value` → `_match_list` 命中标记 → severity 升级）

---

## 五、接口契约（API + Service 边界，无代码）

### 5.1 IOC 作用域端点（`backend/app/api/iocs.py`）
- `POST /api/iocs/{id}/enrich`
  - 入参：路径 `id`；Body 可选 `{ "provider": "ThreatBook" }`（默认用 enabled 的首个支持该类型的 provider）
  - 出参：`{code:0, data: ThreatIntelResponse, message:"success"}`
  - 失败：`code:400` 类型非 ip/domain；`code:500` provider/网络错误；`code:429` 配额超限；`code:404` ioc 不存在
- `POST /api/iocs/enrich/batch`
  - Body：`{ "ids": [int,...] }` 或 `{ "filter": {"ioc_type":"ip","enabled":true} }`
  - 出参：`{code:0, data:{"total":N,"enriched":X,"skipped":Y,"failed":Z,"results":[...]}, message}`
- `GET /api/iocs/{id}/threat-intel`
  - 出参：`{code:0, data:[ThreatIntelResponse,...]（按 queried_at 倒序）, message}`

### 5.2 配置端点（`backend/app/api/threat_intel.py`，挂 `/api/threat-intel`）
- `GET /api/threat-intel/providers` → 列表（**不返回 api_key_ref 明文**，仅返回 `name/type/api_url/enabled/rate_limit_qps`）
- `POST /api/threat-intel/providers` → upsert by `name`（接受 `api_key_ref: "$ENV_VAR"`）
- `PUT /api/threat-intel/providers/{name}` → 更新单条
- `GET /api/threat-intel/settings` → `EnrichSettings`
- `PUT /api/threat-intel/settings` → 持久化到 `threat_intel_settings.json`

### 5.3 Service 边界（`EnrichmentService`）
- `enrich_ioc(ioc: dict) -> ThreatIntel`：选 provider → 短期 TTL 去重 → `provider.query()` → `ThreatIntel.create()` → 返回
- `enrich_batch(iocs: list[dict]) -> dict`：逐条 `enrich_ioc`，受 `daily_quota` 约束，单条失败不阻断整体（记 failed）
- `scan_pending_iocs() -> dict`：供 scheduler 调用；扫描 `enabled=1 & ioc_type∈{ip,domain}`，按 `(ioc_id,provider)` 看 `queried_at` 是否超出 `recheck_days` 决定重查，配额耗尽即停

### 5.4 Provider 契约
- `BaseThreatIntelProvider`（抽象）：`name`、`supported_types: set`、`query(ioc_type, ioc_value) -> NormalizedIntel`（网络/API 错误向上抛，**不落库**）、`normalize(raw) -> NormalizedIntel`
- `NormalizedIntel`：`{provider, ioc_type, ioc_value, risk_score, judgments, tags, confidence, attck, company, raw_summary}`
- `ThreatBookProvider`：用 `expand_env(api_key_ref)` + `httpx` 调微步（ip 信誉 / 域名情报），`normalize` 将 verdict 映射为 `judgments`（见第六节），解析 `tags/attck/company/risk_score/confidence`

### 5.5 Schema（追加到 `analysis.py`）
- `ThreatIntelResponse`：`id, ioc_id, ioc_type, ioc_value, provider, risk_score, judgments, tags, confidence, attck, company, threat_level, queried_at, raw_summary, created_at`
- `EnrichRequest`：`provider?: str`
- `EnrichBatchRequest`：`ids?: List[int]` / `filter?: dict`
- `ProviderConfig`：`name, type, api_key_ref, api_url, enabled, rate_limit_qps`
- `EnrichSettings`：`enable_enrichment: bool, auto_enrich: bool, daily_quota: int, recheck_days: int, scheduler_interval: int`
- `EnrichResult`：`total, enriched, skipped, failed, results`

---

## 六、回灌映射规则（引擎改造契约）

### 6.1 judgments → threat_level 映射
| judgments 含 | threat_level | 是否回灌 |
|------|------|------|
| `malicious` | `high` | ✅ 回灌（判黑/升级） |
| `suspicious` | `medium` | ✅ 回灌（标注） |
| `clean` | — | ❌ 不回灌 |
| `unknown` | — | ❌ 不回灌 |

### 6.2 开关与生效位置
- **总开关 `ENABLE_THREAT_INTEL_ENRICHMENT`（默认 `True`）**：在 `RuleEngine.evaluate` 入口判断。
  - `True`：加载 `threat_level_by_value = { value_lower: {"level": "high"|"medium", "provider": "..."} }`，仅取 **最新一条** per `(ioc_value, provider)` 且 judgments 含 `malicious`/`suspicious` 的记录（经 `ThreatIntel.get_latest_threat_level()`）。
  - `False`：**完全不加载** `threat_level_by_value`，`_match_list` 不查该字典，`_load_iocs_by_type` 原逻辑零改动，对既有 list 命中语义与降级能力零影响。

### 6.3 `rule_engine.py` 最小改造点（仅两处）
1. **`evaluate` 入口**（约 237 行后）：在注入 `iocs_by_type` 之后，按开关加载 `threat_level_by_value` 并写入 `global_context`；同时初始化 `global_context["_ti_hits"] = {}`。
2. **`_match_list`**（约 329–372 行）：维持原"合并 iocs_by_type + values 匹配"逻辑不变；**仅**在"命中"且 `value_lower ∈ global_context["threat_level_by_value"]` 时，向 `global_context["_ti_hits"][id(item)] = {"level":..., "provider":...}` 记录（不改变其 `return True/False` 语义）。
3. **`evaluate` 构造 match 结果处**（约 255–262 行）：`match_rule` 返回 `True` 后，查 `global_context["_ti_hits"].get(id(item))`：
   - `level == "high"`（malicious）：`severity = max(severity, "high")`，`reason += "【威胁情报平台判黑: provider=ThreatBook, judgment=malicious】"`
   - `level == "medium"`（suspicious）：`severity` 不变，`reason += "【威胁情报平台可疑: provider=ThreatBook, judgment=suspicious】"`
   - severity 比较按 `SEVERITY_ENUM = [critical, high, medium, low]` 取高。

> 回灌**仅作用于 list 类规则**（即 IOC 黑名单命中路径），regex/threshold/behavior/composite/exists 不引入威胁情报，保持范围清晰、改动面最小。

---

## 七、任务列表（有序、含依赖、按实现顺序）

> 按主理人要求拆成 **T1–T9**（未套用通用 5 任务上限，便于工程师直接批量实现）。
> 依赖图见第九节；推荐交付序见第十节。

### T1 — 数据层与模型层
- 目标：建 `threat_intel` 表 + 三个模型/配置读写 + 默认 JSON + config 兜底常量。
- 涉及文件：`backend/app/database.py`(改)、`backend/app/models/threat_intel.py`(新)、`backend/scripts/threat_intel_providers.json`(新)、`backend/config/threat_intel_settings.json`(新)、`backend/app/config.py`(改)
- 依赖：无
- 验收：
  1. `init_db()` 创建 `threat_intel` 表与三索引；
  2. `ThreatIntel.create/get_by_ioc/list_by_ioc/get_latest_threat_level` 工作；
  3. `ThreatIntelProviderConfig.load_all()` 能加载 JSON 且 `expand_env` 生效；
  4. `EnrichSettings.load/save` 可读写 `threat_intel_settings.json`；
  5. `config.ENABLE_THREAT_INTEL_ENRICHMENT` 默认 `True`、`AUTO_ENRICHMENT` 默认 `False`。

### T2 — Provider 抽象 + 微步实现
- 目标：定义 `BaseThreatIntelProvider` 契约与 `ThreatBookProvider`（httpx + expand_env + normalize 映射）。
- 涉及文件：`backend/app/services/enrichment_service.py`(新，仅 Provider 部分)、`backend/scripts/threat_intel_providers.json`(字段对齐)
- 依赖：T1
- 验收：
  1. `ThreatBookProvider.query("ip","1.2.3.4")` 返回 `NormalizedIntel`（mock httpx 验证）；
  2. `api_key_ref="$THREATBOOK_API_KEY"` 经 `expand_env` 展开；
  3. verdict→judgments 映射正确（malicious/suspicious/clean/unknown）；
  4. 网络/HTTP 错误向上抛异常、**不落库**。

### T3 — EnrichmentService 编排
- 目标：选 provider、短期 TTL 去重、当日配额、落库、扫描待查 ioc。
- 涉及文件：`backend/app/services/enrichment_service.py`(新增 `EnrichmentService` 类)、`backend/app/models/threat_intel.py`(必要时补查询方法)
- 依赖：T1、T2
- 验收：
  1. `enrich_ioc` 写 `threat_intel` 且同 `(ioc_value,provider,ioc_type)` 短期 TTL 内不重复打 API；
  2. `enrich_batch` 受 `daily_quota` 限制，单条失败计入 `failed` 不阻断；
  3. `scan_pending_iocs` 仅选出 `enabled=1 & type∈{ip,domain} & (无记录 或 queried_at 超 recheck_days)`；
  4. 单 provider 串行 + `rate_limit_qps` 限流。

### T4 — Schemas 扩展
- 目标：追加响应/请求模型。
- 涉及文件：`backend/app/schemas/analysis.py`(改)
- 依赖：T1
- 验收：`ThreatIntelResponse/EnrichRequest/EnrichBatchRequest/ProviderConfig/EnrichSettings/EnrichResult` 可正常序列化；`ioc_type` 校验仅 `ip/domain` 可被 enrich 接口接受（或可放宽由 service 校验）。

### T5 — API 端点 + 路由挂载（后端闭环）
- 目标：实现全部端点并注册路由，端到端手动 enrich 落库可用。
- 涉及文件：`backend/app/api/iocs.py`(改)、`backend/app/api/threat_intel.py`(新)、`backend/app/main.py`(改)、`backend/app/api/__init__.py`(若有注册表)
- 依赖：T3、T4
- 验收：
  1. `POST /iocs/{id}/enrich` 成功返回 `ThreatIntelResponse` 并落库；
  2. 非 `ip/domain` 返回 `code:400`；
  3. provider/settings 端点读写 JSON 正常，且 providers 列表**不泄露 api_key_ref**；
  4. 所有端点统一 `{code,data,message}`；鉴权沿用 `get_current_user`。

### T6 — 引擎回灌（rule_engine 改造）
- 目标：按第六节契约在 `evaluate`/`_match_list` 注入威胁等级并升级 severity。
- 涉及文件：`backend/app/rules/rule_engine.py`(改)
- 依赖：T1
- 验收：
  1. `ENABLE_THREAT_INTEL_ENRICHMENT=False` 时完全不加载、既有 list 命中零变化；
  2. malicious 命中 → severity 升 `high` 且 reason 含"判黑"；
  3. suspicious 命中 → reason 含"可疑"、severity 不变；
  4. 既有 `_load_iocs_by_type` 逻辑未被改动、降级路径不受影响。

### T7 — 自动调度脚本
- 目标：复刻 `--once`/`--loop` + `expand_env`，扫描未查询 ioc 自动 enrich，受开关/配额控制。
- 涉及文件：`backend/scripts/enrichment_scheduler.py`(新)
- 依赖：T3
- 验收：
  1. `--once` 单次扫全部待查 ioc；`--loop` 按 `scheduler_interval` 轮询，`Ctrl+C` 优雅退出；
  2. `AUTO_ENRICHMENT=False` 时直接退出/不动作；
  3. 单源/单条失败隔离不阻断；配额耗尽停止本轮；
  4. 复用 `init_db()` 与 `expand_env` 范式，独立 CLI 可运行。

### T8 — 前端集成
- 目标：`IocsView` 加威胁情报列/按钮/弹窗；`iocs.js` 加函数；新增配置页与路由。
- 涉及文件：`frontend/src/api/iocs.js`(改)、`frontend/src/views/IocsView.vue`(改)、`frontend/src/views/ThreatIntelConfigView.vue`(新)、`frontend/src/router/index.js`(改)
- 依赖：T4、T5
- 验收：
  1. 列表对 `ip/domain` 行显示"立即查询"/"查看情报"按钮（url/hash/cert 禁用并提示"仅支持 ip/domain"）；
  2. "查看情报"弹窗展示 `risk_score/judgments/tags/threat_level/company/attck/queried_at/raw_summary`；
  3. 支持多选批量 enrich；
  4. 配置页可编辑 provider（`api_key_ref` 输入框提示填 `$ENV_VAR`）+ 策略开关/配额，保存走对应端点。

### T9 — 测试
- 目标：覆盖 provider / service / API / 引擎回灌 / 调度。
- 涉及文件：`backend/tests/test_enrichment_provider.py`、`test_enrichment_service.py`、`test_enrichment_api.py`、`test_rule_engine_feedback.py`、`test_enrichment_scheduler.py`
- 依赖：T5、T6、T7、T8
- 验收：
  1. provider 单测 mock httpx，验证映射与异常；
  2. service 验证去重/TTL/配额/扫描逻辑；
  3. API 端点返回结构与错误码；
  4. `test_rule_engine_feedback` 验证 malicious 升级、suspicious 标注、开关关闭无影响；
  5. scheduler 验证扫描筛选与配额停止。

---

## 八、依赖包列表

**仅 `httpx==0.27.0`（已存在于 `backend/requirements.txt`），无新增第三方依赖。**
（微步/STIX 解析用内置 `json`/`re`；调度用内置 `time`/`argparse`；前端无新增库。）

---

## 九、共享知识（跨文件约定）

- **统一返回结构**：所有 API 返回 `{code, data, message}`；enrich 失败 `code≠0`（400 类型不支持 / 404 不存在 / 429 配额超限 / 500 provider 错误），**不影响既有 `iocs` 列表/管理逻辑**。
- **apikey 不落明文**：provider 配置一律 `api_key_ref: "$ENV_VAR"`，运行期 `expand_env` 展开；JSON/DB 均不存真实 key；配置列表接口不回传该字段。
- **去重键**：
  - 落库去重：**不去重**，保留 `threat_intel` 全历史（趋势对比）；
  - 调度去重：按 `(ioc_id, provider)` 看 `queried_at` 是否在 `recheck_days`（默认 30）内，在则跳过；
  - 运行时短期 TTL：同 `(ioc_value, provider, ioc_type)` 内存 TTL（默认 10min）避免重复打 API。
- **限流策略**：单 provider 单 key 串行（`rate_limit_qps` 默认 2，微步保守值），scheduler 与手动 API 调用走同一 `EnrichmentService`，共享配额计数（按自然日重置，默认 `daily_quota=1000`）。
- **查询类型限制**：enrich 仅 `ip`/`domain`；`url`/`hash`/`cert` 返回明确 `400` 错误（不静默跳过）。
- **时间格式**：`queried_at`/`created_at` 用 SQLite `datetime('now')`（与现有表一致，本地时间）。
- **threat_level 派生冗余列**：落库时由 `judgments` 映射写入，便于查询与回灌，避免回灌时重复计算。

---

## 十、待明确事项 + 默认假设

### 默认假设（用户未明确但合理，已落地于设计）
- **A1** `ENABLE_THREAT_INTEL_ENRICHMENT` 默认 `True`（回灌是本期核心诉求；无 provider key 时无数据自然不生效）。
- **A2** `AUTO_ENRICHMENT`（自动调度）默认 `False`（谨慎，避免未配置即烧外部 API 配额）。
- **A3** 默认参数：`daily_quota=1000`、`recheck_days=30`、`scheduler_interval=3600s`、`rate_limit_qps=2`。
- **A4** `threat_intel` 保留全历史，不去重覆盖。
- **A5** 微步 judgment 取响应中 verdict/status 字段映射为 `malicious/suspicious/clean/unknown`（具体 endpoint 与字段在 `ThreatBookProvider.normalize` 内实现）。
- **A6** 回灌仅作用于 list 类规则（IOC 黑名单命中路径）。
- **A7** 配额按"自然日"计数（当天 00:00 重置）。

### 需用户/主理人确认（待明确）
- **Q1（最关键）**：微步具体 API endpoint 与返回字段（ip 信誉、域名情报的 URL、verdict 字段名）。我已按归一 `NormalizedIntel` 给契约，具体解析交由 `ThreatBookProvider` 按微步文档落地——需 PM/用户提供接口文档或确认"工程师按微步开放 API 自行对接"。
- **Q2（最关键）**：自动调度默认推荐方式——生产用 `--once` + 系统 cron，还是必须用 `--loop` 内置轮询？我默认两者都实现、`--loop` 用于开发/演示、`--once`+cron 用于生产。
- **Q3**：回灌时对 `suspicious` 是否也升级 severity（我默认仅 `malicious` 升级、`suspicious` 仅标注 reason）。
- **Q4**：provider/settings 配置放 JSON（我推荐）而非 DB 表，是否违背既有"配置进 DB"偏好？
- **Q5**：配额计数口径（自然日 vs 滚动窗口）——默认自然日。

---

## 十一、附录：配置文件结构契约（接口契约，非代码）

### A.1 `backend/scripts/threat_intel_providers.json`（provider 连接配置，列表）
```json
[
  {
    "name": "ThreatBook",
    "type": "threatbook",
    "api_key_ref": "$THREATBOOK_API_KEY",
    "api_url": "https://api.threatbook.cn/v3",
    "enabled": true,
    "rate_limit_qps": 2,
    "supported_types": ["ip", "domain"]
  }
]
```
> 扩展新 provider = 追加一段 + 在 `enrichment_service.py` 注册一个 `BaseThreatIntelProvider` 子类；`api_key_ref` 一律 `$ENV_VAR`，`load_all()` 经 `expand_env` 展开。

### A.2 `backend/config/threat_intel_settings.json`（运行策略，单对象）
```json
{
  "enable_enrichment": true,
  "auto_enrich": false,
  "daily_quota": 1000,
  "recheck_days": 30,
  "scheduler_interval": 3600
}
```
> `enable_enrichment` 对应引擎回灌总开关（兜底于 `config.ENABLE_THREAT_INTEL_ENRICHMENT`）；`auto_enrich` 对应调度开关；其余为配额/调度参数。`EnrichSettings` 读写此文件，`PUT /api/threat-intel/settings` 持久化。

---

## 十二、最小可用交付序

**T1 → T2 → T3 → T4 → T5（后端闭环） → T6（引擎回灌） → T7（调度） → T8（前端） → T9（测试）**
