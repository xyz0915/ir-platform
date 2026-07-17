# IR（应急响应）平台 — 安全审计报告

> 审计范围：后端 FastAPI（`backend/app/`）+ 前端 Vue3（`frontend/src/`）
> 审计方式：静态代码审查（实际读取源码 + 模式定向搜索）。**仅审计，未做任何修改。**
> 审计人：software-qa-engineer（Edward）

---

## 一、总体安全评估

**整体风险等级：🔴 高（含 1 个 Critical、8 个 High）**

该平台当前处于"本地部署、开发默认值"状态，**生产环境直接运行会暴露严重风险**。最突出的问题是：
- 认证体系依赖**硬编码的 JWT 密钥**（且默认管理员口令硬编码），一旦部署即等于"无认证"；
- 存在**整模块未鉴权**的日志检索 API，结合过度宽松的 CORS，任何外部网页即可读取/写入全部敏感取证数据；
- 多处以用户输入**直接拼接进 SQL / Shell / HTML** 的写法，构成 SQL 注入、命令注入、存储型 XSS 三合一攻击面。

**最危险的 3 个漏洞（建议优先修复）：**
1. **[Critical] 日志检索 API 完全未鉴权**（`api/log_search.py`）——任何人无需 token 即可读取全部主机日志/原始 JSON（含 IP、用户名、文件路径），并通过 `/import` 注入任意数据。
2. **[High] 硬编码 JWT 密钥 + 默认管理员口令**（`config.py`）——可伪造任意身份（含 admin）Token，造成完全认证绕过与权限提升。
3. **[High] 存储型 XSS（v-html 渲染未净化的日志/报告内容）**（`LogResultList.vue`、`markdown.js`）——与 #1 的未鉴权 `/import` 链式组合后，攻击者**无需登录**即可向分析师浏览器注入恶意脚本，窃取 localStorage 中的 JWT。

---

## 二、发现清单（按风险等级排序，共 21 条）

### 🔴 CRITICAL

#### C1. 日志检索 API 完全缺失鉴权（未授权数据读取 + 数据注入）
- **位置**：`backend/app/api/log_search.py`（第 22 行 `from fastapi import ...` 甚至**未导入 `Depends`**；全部 9 个端点 第 45–269 行均无 `Depends(get_current_user)`）
- **攻击路径**：
  - `GET /api/log-search/search`、`/search/advanced`、`/search/raw`、`/imports`、`/imports/{id}`、`/trend`、`/export` 返回全部导入日志与 `raw_json`（含 `source_ip`、`user_name`、文件路径等敏感字段），**无需任何 token**；
  - `POST /api/log-search/import` 允许**未授权**提交任意 `raw_json` 到任意 `host_id`，可直接投毒取证库。
  - 配合下面的 CORS `*` 问题，可被任意外部网页跨域调用。
- **风险等级**：Critical（破坏访问控制 + 敏感数据泄露）
- **修复建议**：
  - 为每个端点加入 `current_user: dict = Depends(get_current_user)`；
  - 或在 `include_router` 时统一加 `dependencies=[Depends(get_current_user)]`；
  - `/import` 至少校验调用方为可信 Agent（共享密钥 / mTLS），而非开放 POST。
- **预期收益**：消除"无需登录即可读取/投毒全部取证数据"的攻击面；阻断与 XSS 的未授权链式利用。

---

### 🟠 HIGH

#### H1. SQL 注入 — `sort` 参数直接进入 ORDER BY
- **位置**：
  - 入口 `backend/app/api/logs.py:31`（`sort: str = Query("timestamp DESC")`）
  - 落点 `backend/app/models/normalized_log.py:138-140`（`sort_clause = sort or "timestamp DESC"`，随后 `f"... ORDER BY {sort_clause} LIMIT ? OFFSET ?"`）
- **攻击路径**：`/api/logs/search?sort=...` 的 `sort` 参数**无任何白名单校验**，被直接拼入 SQL。攻击者可构造 `sort=(SELECT password_hash FROM users)` 或 `sort=id;DROP TABLE normalized_logs;--` 实施布尔/报错/堆叠注入（SQLite 支持多条语句时危害更大）。
- **风险等级**：High
- **修复建议**：对 `sort` 字段与方向做白名单（如 `valid = {"timestamp","severity","host_id",...}` 且方向 ∈ `asc/desc`），不在白名单内则回退默认；或改用参数化列映射字典。
- **预期收益**：消除日志检索接口的 SQL 注入面。

#### H2. SQL 注入 — `field` 参数直接进入 WHERE 列名（pivot）
- **位置**：
  - 入口 `backend/app/api/logs.py:78`（`field: str = Query(...)`）
  - 落点 `backend/app/models/normalized_log.py:257`（`conditions = [f"{field}=?"]`）
- **攻击路径**：`/api/logs/pivot?field=...` 的 `field` 仅文档约定为 `source_ip|user_name|...`，**代码未做任何白名单校验**，直接拼为列名。攻击者可传 `field=1=1;DELETE FROM normalized_logs;--` 实施注入。
- **风险等级**：High
- **修复建议**：用硬编码字典映射 `{"source_ip": "source_ip", ...}`，对非法 `field` 直接 400 拒绝。
- **预期收益**：消除 pivot 接口的 SQL 注入面。

#### H3. 硬编码 JWT 密钥 → 可伪造任意身份 Token
- **位置**：`backend/app/config.py:37-40`
  ```python
  SECRET_KEY = os.environ.get("IR_SECRET_KEY",
      "ir-platform-secret-key-2025-please-change-in-production")
  ```
- **攻击路径**：若生产环境未设置 `IR_SECRET_KEY` 环境变量，服务端将使用上述固定字符串作为 HS256 签名密钥。攻击者知晓该默认值即可**本地签发任意 `user_id` / `role=admin` 的 JWT**，通过 `jwt.decode` 校验，实现完全认证绕过与权限提升。该密钥同时被用于 WebSocket 鉴权（`api/alerts.py:99`）。
- **风险等级**：High
- **修复建议**：
  - 启动时若未提供 `IR_SECRET_KEY` 则**拒绝启动**（或生成一次性随机密钥并持久化）；
  - 密钥长度 ≥ 32 字节随机值，仅存于环境变量/密钥管理；
  - 考虑迁移至非对称算法（RS256）并将公钥内置前端不可篡改。
- **预期收益**：根因性消除"伪造 Token / 越权"类全部衍生漏洞。

#### H4. 危险 CORS：`allow_origins=['*']` 与 `allow_credentials=True` 同时开启
- **位置**：`backend/app/config.py:49-55`（`CORS_ORIGINS` 含 `"*"`）、`backend/app/main.py:32-38`（`allow_credentials=True` + `allow_methods/headers=["*"]`）
- **攻击路径**：Starlette 的 `CORSMiddleware` 在 origins 含 `*` 时会**反射请求中的 `Origin`** 并放行凭据。任意恶意网站可在受害者已登录状态下，跨域调用本平台 API（含上面未鉴权的 `log_search` 与需凭据的接口），读取/写入数据。
- **风险等级**：High
- **修复建议**：生产环境**移除 `"*"`**，改为明确的前端域名白名单；`allow_credentials=True` 时绝不可与 `*` 同开；收紧 `allow_methods`/`allow_headers`。
- **预期收益**：阻断跨站凭据滥用，是 H1/H2/C1 等漏洞被远程利用的前提条件。

#### H5. 存储型 XSS — `v-html` 渲染未 HTML 转义的日志 JSON
- **位置**：`frontend/src/components/logs/LogResultList.vue:60`（`v-html="highlightIoc(item.raw_json)"`）、`highlightIoc` 函数 第 150–162 行
- **攻击路径**：`highlightIoc` 仅对 JSON 字符串做 IP 正则高亮，**其余字段（user_name、command_line、文件路径、描述等）原样写入 `innerHTML`**。由于 `raw_json` 来自主机日志（可被攻击者通过 H1 的未鉴权 `/import` 或失陷主机投毒），其中若含 `<img src=x onerror=alert(document.cookie)>` 等载荷，分析师查看日志时即触发 XSS。
- **风险等级**：High
- **修复建议**：先 `escapeHtml` 再插入高亮 `<span>`（参考同文件 `markdown.js` 的 `escapeHtml` 思路）；或改用 `{{ }}` 文本绑定 + 纯文本高亮。
- **预期收益**：消除日志查看场景的存储型 XSS，切断"未授权投毒 → 分析师浏览器被控 → JWT 被盗"链路。

#### H6. 存储型 XSS — `v-html` + 未净化的 Markdown 渲染报告内容
- **位置**：
  - `frontend/src/utils/markdown.js:81-96`（`renderMarkdown` 直接 `marked.parse(text)`，无 DOMPurify/sanitize）
  - 渲染点：`components/AiAnalysisDialog.vue:404/412/420/428`、`views/CaseDetailView.vue:247/252`、`components/ai/ReportVersionDiff.vue:71-121`
- **攻击路径**：`marked` 默认**不过滤原始 HTML**。AI 报告内容（`risk_assessment`/`threat_analysis`/`recommendations` 等）由安全事件推导而来，而事件源数据（IOC 值、日志字段、主机名、用户名）可被攻击者操纵。攻击者在可控字段中嵌入 `<script>`/`<img onerror>` 即被原样写入 `v-html` 执行。
- **风险等级**：High
- **修复建议**：在 `renderMarkdown` 输出前用 **DOMPurify** 净化（或 `marked` 配置 `sanitize`/自定义 renderer 转义 HTML 节点）；对 `renderPlainText` 同样转义。
- **预期收益**：消除报告/对比场景的存储型 XSS。

#### H7. SSRF — 攻击者可控的威胁情报 `base_url` 被服务端请求
- **位置**：
  - 落点 `backend/app/services/enrichment_service.py:300-311`（`url = f"{self.base_url}{endpoint}"`，且 `follow_redirects=True`）
  - 入口 `backend/app/api/threat_intel.py:44-104`（`create_provider`/`update_provider`/`delete_provider` 仅 `Depends(get_current_user)`，**无 admin 角色校验**，且 `base_url` 直接来自请求体）
- **攻击路径**：任意已登录用户（甚至非 admin）可注册一个 `base_url=http://169.254.169.254/`（云元数据）或 `http://127.0.0.1:6379/` 的 provider；后续系统外联查询会由**服务端**发起请求，读取内网/元数据，且 `follow_redirects=True` 可绕过部分重定向限制。
- **风险等级**：High
- **修复建议**：
  - 威胁情报 provider 管理加 **admin 角色校验**；
  - 对 `base_url` 做 SSRF 防护：解析后拒绝私有/环回/链路本地地址与非常规端口，禁用重定向到内网，使用独立出口网络。
- **预期收益**：消除服务端被用作内网探测/元数据窃取跳板的风险。

#### H8. OS 命令注入 — `create_subprocess_shell` 执行用户提供的命令
- **位置**：
  - `backend/app/services/dispatch_service.py:212`（`await asyncio.create_subprocess_shell(cmd, ...)`）
  - 弱校验 `:25-33` 关键字黑名单、`_reject_dangerous` `:285-291`（仅 `kw in low` 子串匹配）
  - 入口 `backend/app/api/ai.py:371-408`（`command_or_api=data.command_or_api` 来自请求体，端点仅 `Depends(get_current_user)`）
- **攻击路径**：`create_subprocess_shell` 经系统 shell 解释。黑名单只拦截少量子串（如 `rm -rf`、`kill `），**完全不拦截 shell 元字符** `; | & $() 反引号` 以及 `curl|sh`、`IEX(...)`、`net user` 等。任意已登录用户可提交 `powershell -Command "Get-Process & whoami"` 或更危险的链式命令，在服务端以进程权限执行。
- **风险等级**：High
- **修复建议**：
  - 改用 `create_subprocess_exec`（参数列表，无 shell 解释）；
  - 维护**只读采集器二进制白名单**（如 `osqueryi`、`powershell` + 固定脚本）；
  - 以严格正则校验 `target`/`action_type`，命令参数白名单化，而非黑名单。
- **预期收益**：消除"只读采集"被升级为任意命令执行的攻击面。

---

### 🟡 MEDIUM

#### M1. 硬编码默认管理员凭据
- **位置**：`backend/app/config.py:47-48`（`DEFAULT_ADMIN_USER="admin"`、`DEFAULT_ADMIN_PASSWORD="admin123"`）
- **风险**：若部署后未改密，攻击者用默认账号即可直接登录（与 H3 叠加更致命）。
- **修复建议**：首次启动强制改密；口令不写死，从环境变量注入；提供"是否存在默认口令"的健康检查告警。
- **预期收益**：消除默认口令登录风险。

#### M2. 硬编码 AI 加密（Fernet）密钥
- **位置**：`backend/app/config.py:58-61`（`AI_ENCRYPTION_KEY` 默认 `QSLeoOZ1...=`）
- **风险**：存储的第三方 AI API Key 用此密钥加密，默认值已知即可解密全部密钥。
- **修复建议**：同 H3，密钥仅来自环境变量/密钥管理，缺失则拒绝启动。
- **预期收益**：防止存储的 API Key 被离线解密。

#### M3. 威胁情报 provider 管理缺少 admin 角色校验（赋能 H7）
- **位置**：`backend/app/api/threat_intel.py:44-104`（create/update/delete 仅 `get_current_user`）
- **风险**：任意已登录用户可增删 provider，直接促成 SSRF（H7）。
- **修复建议**：所有写操作加 `if current_user.get("role")!="admin": raise 403`（参考 `api/users.py` 的做法）。
- **预期收益**：将 provider 配置收敛为管理员专属，封堵 SSRF 入口。

#### M4. 敏感字段在列表/详情接口未脱敏
- **位置**：`backend/app/services/data_masking.py` 仅被 `report_service.py:132` 与 `prompt_builder.py` 调用；而 `api/alerts.py`、`api/logs.py`、`api/events.py`、`api/log_search.py` 将原始 `source_ip`、`user_name`、文件路径等**完整返回**前端。
- **风险**：脱敏引擎已存在却未覆盖查询接口。结合 C1/H4，敏感取证数据以明文大范围暴露（即使对内部分析师也违反最小可见原则）。
- **修复建议**：在返回层对 `ip`/`user`/`path` 类字段按角色/场景脱敏（如非 admin 或导出场景）；或至少为导出/审计接口启用 `data_masking.apply`。
- **预期收益**：降低凭据/隐私数据横向泄露面。

#### M5. JWT `role` 缺省为 `admin`
- **位置**：`backend/app/services/auth_service.py:59`（`"role": user.get("role", "admin")`）、`backend/app/api/auth.py:47,62`
- **风险**：若某 Token/用户记录缺失 `role` 字段，将被当作 admin，构成权限提升边界条件。
- **修复建议**：缺省应为最小权限（如 `analyst`）或显式拒绝签发；签发前强制 `role` 存在且合法。
- **预期收益**：消除"缺字段即提权"的边界漏洞。

#### M6. 全局缺少速率限制（登录爆破 / SSE·AI 接口被刷）
- **位置**：后端未发现 `slowapi`/`RateLimit`/limiter（仅 `enrichment_service.py` 有内部 QPS 节流，无 API 层限流）。
- **风险**：登录接口可被暴力破解；`/ai/query-stream`（SSE）、`/ai/analyze` 等 AI 接口无频控，易被滥用导致资源耗尽/费用失控。
- **修复建议**：引入 `slowapi` 或网关层限流；对 `/auth/login` 加重试锁定与验证码；对 AI/SSE 按用户配额。
- **预期收益**：阻断爆破与资源滥用类拒绝服务。

#### M7. WebSocket `/ws/alerts` 鉴权薄弱
- **位置**：`backend/app/api/alerts.py:87-103`
- **风险**：仅用共享密钥 `jwt.decode(token)`，结合 H3 可被伪造；除 `user_id` 外无角色/授权校验，任何可构造 Token 者均可订阅告警流。
- **修复建议**：复用 `get_current_user` 的校验逻辑；校验 `exp` 与 `role`；必要时按案件/主机做订阅授权。
- **预期收益**：防止告警流被未授权订阅。

#### M8. 错误信息向客户端泄露内部细节
- **位置**：`backend/app/api/ai.py:367,408`（`detail=str(e)`）、`backend/app/api/import_data.py:39-42`、`backend/app/services/sync_service.py`（返回 `str(exc)`）
- **风险**：异常原文（含 SQL 片段、路径、内部模块名）直接回显给客户端，助长进一步攻击。
- **修复建议**：对外只返回通用错误码/提示，详细堆栈仅记日志（`logger.exception`）；对 `detail=str(e)` 做收敛。
- **预期收益**：减少信息泄露，增加攻击成本。

#### M9. JWT 存于 localStorage → 与 XSS 组合导致会话被盗
- **位置**：`frontend/src/stores/auth.js:6,15`、`frontend/src/api/index.js:12`（`localStorage.getItem('ir_token')`）
- **风险**：Token 存 localStorage，一旦触发 H5/H6 的 XSS，脚本即可读取并外传 Token，实现会话劫持。
- **修复建议**：改存 **HttpOnly + Secure + SameSite** Cookie；或前端内存态 + 短时效刷新 Token；务必配合 H5/H6 的 XSS 修复。
- **预期收益**：即使存在 XSS 也大幅降低 Token 被窃取的可能。

---

### 🟢 LOW

#### L1. 未鉴权的路由枚举端点
- **位置**：`backend/app/main.py:258-262`（`/api/routes-debug`，无 `Depends(get_current_user)`）
- **风险**：匿名列出全部路由，便于攻击者测绘攻击面（与 C1 叠加更易被利用）。
- **修复建议**：移除该诊断端点或加 admin 鉴权/仅调试环境启用。
- **预期收益**：减少攻击面暴露。

#### L2. 潜在不安全 SQL 拼接（当前不可利用）
- **位置**：`backend/app/api/ai_advanced.py:268`（`cond = f"WHERE status='{status}'"`）
- **说明**：`status` 由调用方按关键字匹配**限定为 `online`/`offline`**（见 `ai_advanced.py:182-185`），故当前不可利用；但仍属不安全写法，建议参数化。
- **修复建议**：改为 `conditions.append("status=?")` + 参数绑定。
- **预期收益**：消除未来重构引入注入的风险。

#### L3. 生产配置使用 `reload=True`
- **位置**：`backend/run.py:19`（`uvicorn.run(..., reload=True)`）
- **风险**：`reload` 为开发热重载模式，不适用于生产，且会额外监听/重启进程。
- **修复建议**：生产入口移除 `reload`；通过进程管理器（如 gunicorn/uvicorn workers）启动。
- **预期收益**：符合生产部署规范，降低意外行为。

---

## 三、值得肯定的安全实践（供参考）
- 绝大多数 SQL 使用参数化 `?` 占位，`WHERE` 条件由固定片段 + 参数拼接（如 `api/audit_logs.py`、`api/events.py`、`models/alert.py`），规避了常见注入。
- `api/events.py:159-165` 对 `sort_field`/`sort_order` 做了**白名单校验**，是正确的安全范式（建议推广到 H1 的 `sort`）。
- 用户管理接口（`api/users.py`）普遍做了 `role=='admin'` 校验，口令使用 bcrypt 哈希，无明文存储。
- `data_masking.py` 脱敏引擎实现完整，已在报告/提示词场景启用。
- 派发服务对危险命令有关键字黑名单与超时中断，初衷良好（但实现需按 H8 改为白名单 + `exec`）。

---

## 四、修复优先级建议
1. **立即（阻断远程利用）**：C1（log_search 鉴权）、H3（JWT 密钥）、H4（CORS）、M1/M2（默认口令/密钥）。
2. **高优（注入/XSS/SSRF）**：H1、H2、H5、H6、H7、H8 及配套 M3/M9。
3. **加固（纵深防御）**：M4–M8、L1–L3。
