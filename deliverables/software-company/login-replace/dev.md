# 登录页替换 · 开发说明（dev.md）

> 工程师：寇豆码｜日期：2026-08-06
> 依据：`design.md`（设计方案，权威规格）+ `audit.md`（审计报告）+ `login_preview_emergency.html`（UI 事实来源）
> team-lead 已批准 3 个待确认项：**R7 方案 A（动拦截器 3 行）**、**username 默认置空**、**协议默认勾选 true**。

---

## 1. 文件清单

### 1.1 新建

| 文件 | 说明 |
|---|---|
| `frontend/src/components/login/BrandArt.vue` | 3D 云品牌 SVG 资产组件（纯展示） |
| `deliverables/software-company/login-replace/dev.md` | 本开发说明 |

### 1.2 修改

| 文件 | 说明 |
|---|---|
| `frontend/src/views/LoginView.vue` | 模板 + script + scoped 样式整体重写（T1/T2/T3） |
| `frontend/src/api/index.js` | R7 方案 A：401 分支增加登录 URL 特例（+3 行） |

### 1.3 未改动（红线确认）

`stores/auth.js`、`api/auth.js`、`router/index.js`、后端全部文件、`ir_token`/`ir_user` localStorage key、`data.token` 字段名、JSON 请求格式、跳转 `/`、路由守卫 —— **均未触碰**。

---

## 2. 实现说明

### 2.1 `frontend/src/components/login/BrandArt.vue`（新增，T1）

- **SVG 原样复制**：`<svg class="hero-art" viewBox="0 0 480 360">` 内容逐行取自 `login_preview_emergency.html` L258-373：
  - defs：`gBaseTop/gBaseRight/gBaseLeft/gCloud/gCloudDark/gChip/gGround` 渐变 + `fBlur` filter（id 全局唯一，登录页单处引用无冲突）；
  - 地面投影（ellipse）、哑光六边形基座（3 个 polygon）、3D 云（`gCloudDark` 底面 + `gCloud` 主体 + 高光 ellipse ×2）、六边形芯片 5 枚（`chip c1~c5`）、装饰光点 4 个（`spark s1~s4`）。
- **动画（scoped CSS，设计 §3.2 推荐方式）**：`.cloud` cloudBob 6s、`.chip` chipFloat 4.5s（c2 0.6s / c3 1.2s / c4 1.8s / c5 2.4s 延迟）、`.spark` sparkPulse 3s（s2 0.8s / s3 1.6s / s4 2.2s 延迟），与 preview L205-228 完全一致。
- **reduced-motion 降级**：`@media (prefers-reduced-motion: reduce) { .cloud, .chip, .spark { animation: none; } }`。
- `.hero-art { width:100%; height:auto; display:block; }`，实际尺寸由父级 `.brand-art`（LoginView）控制；Vue 作用域规则允许父组件 class 落到子组件根元素。

### 2.2 `frontend/src/views/LoginView.vue`（重写，T1+T2+T3）

**模板（设计 §2.2 骨架）**
- `.login-page`（根，min-height:100vh + 固定背景）→ `.login-main` → 左 `.login-brand`（`BrandArt` + `h1.brand-title`「应急平台 安全护航」（span + .gap 字距）+ `p.brand-sub` 4 短语）+ 右 `.login-panel` → `.login-card`（`card-head` logo+h2「应急运营门户」+ `card-sub` + `el-form` + `card-foot`）。
- **保留 el-form/el-form-item/el-input**：复用 Element Plus 校验机制；`hide-required-asterisk`（preview 无必填红星）。
- **移除**（新设计无）：旧版 `User`/`Lock` 前缀图标（删除 `@element-plus/icons-vue` import）、顶部横条、3 个装饰色块、左侧绿底品牌区、忘记密码/联系管理员链接、默认账号提示、底部合规徽标。

**script（设计 §4/§5 + R8）**
- `form = reactive({ username: '', password: '' })` —— **username 置空**（R8 决策，配合移除默认账号提示）。
- `agreed = ref(true)` —— **默认勾选**（与 preview `checked` 一致）。
- `rules`：username/password `required`（trigger `blur`），消息与旧版一致「请输入用户名/请输入密码」。
- `handleLogin()` 流程：
  1. `if (!agreed.value) { ElMessage.warning('请先阅读并同意用户协议和隐私政策声明'); return }` —— **防 Enter 绕过**（Enter 提交不经过按钮 disabled，必须函数内校验）；
  2. `formRef.value.validate(...)`；
  3. `loading.value = true`；
  4. `await authStore.login(form.username, form.password)`（复用 store 封装，链路不变）；
  5. `ElMessage.success('登录成功')` + `router.push('/')`（固定跳转）；
  6. `catch` 留空（错误由拦截器处理，R7 后登录失败为单条 detail toast）；
  7. `finally { loading.value = false }`。
- 两个输入框均绑 `@keyup.enter="handleLogin"`（比现状更完整）；el-form `@submit.prevent="handleLogin"` 保留。
- 按钮 `:disabled="!agreed"` `:loading="loading"`。

**scoped 样式（设计 §8）**
- `.login-page` 固定 `background: #f0f2f5`（**不用主题变量**，注释标注「登录页固定品牌色，不随主题切换」）。
- 卡片：白底、`border: 1px solid #e9ecef`、`border-radius: 16px`、阴影 `0 18px 50px rgba(17,24,39,.10), 0 2px 6px rgba(17,24,39,.04)`。
- 文字固定色（显式设置防暗色变量串扰）：`#111827`（品牌标题/卡片标题）、`#374151`（field-label）、`#6b7280`（brand-sub/协议文案）、`#9aa1ab`（card-foot）；`card-sub` 用 preview 原值 `#8a919c`。
- Element Plus 覆盖：
  - `.el-input__wrapper`：`height:46px; border-radius:10px; padding:0 14px; box-shadow:0 0 0 1px #d7dbe1 inset`；hover 边框 `#c3c9d2`；`:focus-within`/`.is-focus` 绿环 `0 0 0 1px #3fa84b inset, 0 0 0 3px rgba(63,168,75,.14) inset` + 背景 `#fcfefc`；placeholder `#a3aab4`。
  - `.login-submit.el-button`：全宽、`height:48px`、`border-radius:10px`、`letter-spacing:6px`、`text-indent:6px`、`font-weight:600`、`background-image:linear-gradient(180deg,#43b051,#37a048)`、`box-shadow:0 8px 18px rgba(63,168,75,.30)`；hover `linear-gradient(180deg,#3aa548,#2f8f3d)` + 阴影加深；active `translateY(1px)`；`:disabled`/`.is-disabled` `opacity:.55`（配合协议门槛）。
  - 协议 checkbox `accent-color: #3fa84b`。
- 响应式（§8.3）：1024px 单列（brand-art `min(340px,80%)`、卡片 max-width 420px）；560px 标题 26px 可换行、卡片 padding `32px 24px 26px`。

### 2.3 `frontend/src/api/index.js`（R7 方案 A，+3 行，已批准）

401 分支最前插入（在清 token 逻辑**之前**）：

```js
if (status === 401) {
  // 登录失败特例：展示后端 detail，登录页本就在 /login，无需踢回（R7）
  if (url === '/auth/login') {
    ElMessage.error(detail || '用户名或密码错误')
    return Promise.reject(error)
  }
  localStorage.removeItem('ir_token')
  ...
}
```

- 变量按实际命名：`status`（L49）、`url`（L50）、`detail`（L51）、`error`（L47）；登录 URL 为 `request.post('/auth/login')`（baseURL `/api`），故 `url === '/auth/login'` 成立。
- 效果：登录失败（401 `{detail:"用户名或密码错误"}`）→ 单条 toast「用户名或密码错误」，不弹「登录已过期」、不踢回（本就在 /login）。
- 隔离性：仅登录 URL 提前 return；**其他页面 401 行为完全不变**（清 token → 「登录已过期，请重新登录」→ push /login → reject）。

---

## 3. 自测结果

```bash
cd C:\Users\xyz\WorkBuddy\2026-07-06-17-00-58\frontend

npx vitest run
# Test Files  41 passed (41)
#      Tests  534 passed (534)
#   Duration  72.14s
# 重点：views-smoke.spec.js（8 tests）✓、router-reachability.spec.js（3 tests）✓ 全绿

npx vite build --outDir "$TMPDIR/ir_login_build_check"
# ✓ built in 25.25s（chunk >500kB 为既有优化警告，非错误；构建后已清理临时目录）
```

结论：**测试全量通过、生产构建成功**。

---

## 4. 与设计的偏差

| # | 项 | 设计 | 实现 | 说明 |
|---|---|---|---|---|
| 1 | `card-sub` 颜色 | §8.1 表格归纳「副文案/协议 #6b7280」 | `#8a919c` | 采用 preview L109 原值（UI 事实来源）；§8.1 的「副文案 #6b7280」对应 brand-sub（preview L73），「协议 #6b7280」对应 agree-text（preview L157），card-sub 在 preview 中本就是 `#8a919c` |
| 2 | 按钮 `:disabled` 时 hover 渐变 | 设计 §8.2 仅描述 `:disabled` 降透明度 | hover 选择器加 `:not(.is-disabled)` | 防止禁用态下悬停误触发 hover 渐变/阴影，属样式细节增强，视觉/行为与设计一致 |
| 3 | 无 | — | — | 其余实现与设计完全一致，无功能偏差 |

---

## 5. 交付物

- commit：见最终提交记录（`feat: replace login page with emergency-platform UI — BrandArt 3D cloud, agree gate, R7 401 detail toast`）
- 文件变动行数：见提交统计。
