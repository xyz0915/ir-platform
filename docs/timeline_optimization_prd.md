# 攻击链时间线优化 PRD — 阶段 1

> **版本**: v1.0  
> **作者**: 许清楚（Xu），产品经理  
> **日期**: 2026-07-24  
> **状态**: 草稿  

---

## 1. 项目信息

| 字段 | 值 |
|------|-----|
| 语言 | 中文 |
| 编程语言 | Vite + Vue 3 + MUI + Tailwind CSS |
| 项目名称 | timeline_optimization |
| 组件 | AttackChainTimeline.vue |
| 原始需求 | 攻击链时间线组件仅显示事件数量和事件类型名称，缺乏进程名、文件路径、IP 等关键上下文，分析师无法据此做出决策。需要将时间线从"数字堆叠"改造为"攻击故事"。 |

---

## 2. 产品目标

1. **从"数字"到"故事"**：每个攻击阶段不再只显示事件数量，而要展示具体发生了什么——哪个进程启动了、哪个文件被创建了、哪个 IP 被访问了。分析师扫一眼就能理解攻击路径。
2. **提供决策依据**：时间线本身就能支撑分析师的判断决策——看到"LsaIso.exe 启动"+"ToDesk.exe 启动"+"出站连接 1.2.3.4:443"就知道这是可疑行为链路，无需跳转到详情页。
3. **大数量下保持可用**：单阶段可能承载数百甚至上千条事件（1729 条总量），必须通过可折叠、虚拟滚动或分页截断等机制保证渲染性能和交互流畅度。
4. **一致的信息优先级**：每条事件展示的信息量应在"足够决策"和"保持简洁"之间平衡，事件类型决定展示哪些字段（进程事件展示进程名+PID，网络事件展示 IP+端口）。

---

## 3. 用户故事

| ID | 用户故事 |
|----|----------|
| US-01 | 作为安全分析师，我想在时间线中直接看到每个事件的进程名和 PID，以便快速判断哪些进程是可疑的，无需逐条点开详情。 |
| US-02 | 作为安全分析师，我想在时间线中看到事件的精确时间（HH:MM:SS）和严重度标签，以便按时间脉络还原攻击时序。 |
| US-03 | 作为安全分析师，当我在事件列表中选中某条事件时，我希望时间线自动滚动并高亮对应事件，以便建立"列表←→时间线"的上下文关联。 |
| US-04 | 作为安全分析师，我希望每个阶段的事件列表默认折叠，只在点击后才展开，以便在事件量大的情况下仍能快速浏览各阶段概览。 |
| US-05 | 作为安全分析师，我想看到阶段之间的箭头连接，以便直观理解攻击链的阶段流转顺序。 |

---

## 4. 需求池

### P0 — 必须有（本轮必须交付）

| ID | 需求 | 验收标准 |
|----|------|----------|
| R-01 | 每阶段下展示真实事件条目（非事件类型名称） | 展开后每条事件显示：时间戳 HH:MM:SS、事件类型图标+标签、进程名+PID（如有）、严重度标签 |
| R-02 | 事件条目展示关键上下文信息 | 根据 event_type 动态展示：process_start → 进程名 (PID)、network_outbound → 远程 IP:端口、file_create → 文件路径、registry_modify → 注册表路径 |
| R-03 | 当前事件高亮 + 自动滚动 | 当 currentEventId 变化时，对应事件条目高亮（背景色区分）并自动滚动到可视区域 |
| R-04 | 阶段折叠/展开 | 每个阶段可点击展开/收起事件列表，默认收起（仅当前阶段默认展开） |
| R-05 | 事件严重度标签 | 每条事件显示 severity 标签（HIGH/medium/low/info），使用对应颜色区分 |
| R-06 | 时间戳 HH:MM:SS 显示 | 每条事件前显示格式化的时间戳，精确到秒 |

### P1 — 应该有（本轮应交付）

| ID | 需求 | 验收标准 |
|----|------|----------|
| R-07 | 阶段间箭头连接 | 相邻阶段之间显示 "→" 箭头指示流转方向 |
| R-08 | 阶段头部信息增强 | 阶段头部除数量和圆点颜色外，显示该阶段内最高严重度标记 |
| R-09 | 加载态 | 数据加载中时显示骨架屏或加载指示器 |
| R-10 | 空阶段占位 | 无事件的阶段在时间线中不显示，避免空白浪费空间 |
| R-11 | 错误态/重试 | 数据加载失败时显示错误提示 + 重试按钮 |
| R-12 | 事件数量过多时的截断 | 阶段内事件 > 50 条时，展开后默认只显示前 50 条 + "显示全部 N 条"按钮 |

### P2 — 可以有（后续版本）

| ID | 需求 | 验收标准 |
|----|------|----------|
| R-13 | 虚拟滚动（大量事件优化） | 单阶段事件 > 200 条时启用虚拟滚动，DOM 节点数不超过 50 |
| R-14 | 事件搜索/过滤 | 在时间线头部提供关键词搜索框，可过滤所有阶段中的事件 |
| R-15 | 复制事件信息 | 每条事件提供复制按钮，可快速复制事件摘要到剪贴板 |
| R-16 | 事件标签/标记 | 分析师可在时间线中为事件添加临时标记（书签） |

---

## 5. UI 布局说明

### 5.1 总体布局（改造后）

```
┌─────────────────────────────────────────┐
│ 攻击链 #chain-001  [执行中]              │
├─────────────────────────────────────────┤
│                                         │
│  ● ① 执行 (386 事件)  [2 HIGH]          │  ← 阶段头部（默认折叠）
│     ↓                                   │  ← 阶段间箭头（P1）
│  ● ② 持久化 (405 事件)  [5 HIGH]        │  ← 默认展开（当前阶段）
│  ├─ 14:32:15  🚀 process_start          │
│  │  LsaIso.exe (PID 1088)         [HIGH] │  ← 当前事件高亮
│  ├─ 14:32:18  🚀 process_start          │
│  │  ToDesk.exe (PID 8528)         [HIGH] │
│  ├─ 14:33:02  📝 persistence_register    │
│  │  SecurityHealth                [HIGH] │
│  ├─ ... 显示前 50 条                     │
│  │  [显示全部 405 条]                    │  ← 截断扩展
│     ↓                                   │
│  ● ③ 防御规避 (238 事件)  [1 HIGH]      │  ← 默认折叠
│     ↓                                   │
│  ● ④ C2 (15 事件)  [0 HIGH]            │
│  ├─ 14:35:44  🌐 network_outbound        │
│  │  1.2.3.4:443  ← ToDesk.exe    [MEDIUM]│  ← 网络事件展示 IP+端口
│                                         │
├─────────────────────────────────────────┤
│ 时间跨度统计：06-24 14:32 - 06-25 03:12  │
│ 涉及阶段：5/13 · 事件总量：1729          │
└─────────────────────────────────────────┘
```

### 5.2 各状态说明

#### 状态 A：有数据（正常态）
- 阶段按 MITRE ATT&CK 顺序排列
- 仅有关联事件的阶段显示（无事件阶段不渲染）
- 当前阶段（selectedEvent.attack_stage）默认展开，其余折叠
- 当前事件（currentEventId）高亮并自动滚动到可视区域
- 阶段头部：圆点 + 阶段序号 + 阶段名 + 事件数 + 最高严重度标记
- 事件条目：时间戳 + 事件类型图标 + 动态关键字段 + 严重度标签
- 事件条目点击 → emit('select-event', eventId) 与主事件列表联动

#### 状态 B：空数据
- 显示空状态插画 + 文案 "暂无时间线数据"
- 可补充提示："请确认案件关联的事件是否存在"
- 保留时间跨度统计区块（显示 0/0）

#### 状态 C：加载中（P1 需求）
- 显示骨架屏：3-4 个灰色阶段块占位，每个块包含 2-3 条灰色矩形条
- 骨架屏应模拟最终布局的形状（阶段头部 + 事件条目），让用户感知页面结构正在加载

#### 状态 D：加载失败（P1 需求）
- 显示错误提示："时间线数据加载失败"
- 提供"重试"按钮，点击重新调用 fetchTimeline()
- 可附加错误详情（如网络超时等）

### 5.3 事件条目动态展示规则

每种 event_type 展示不同的关键字段，保持信息密度适中：

| 事件类型 | 展示字段 | 示例 |
|----------|----------|------|
| process_start | 进程名 (PID) | LsaIso.exe (PID 1088) |
| process_terminate | 进程名 (PID) | explorer.exe (PID 2816) |
| network_outbound | 远程IP:端口 ← 进程名 | 1.2.3.4:443 ← ToDesk.exe |
| network_listen | 本地IP:端口 (进程名) | 0.0.0.0:445 (svchost.exe) |
| registry_modify | 注册表路径 | HKLM\...\SecurityHealth |
| registry_delete | 注册表路径 | HKLM\...\Run\Malware |
| file_create | 文件路径 | C:\Users\...\evil.exe |
| file_modify | 文件路径 | C:\Windows\system32\hosts |
| persistence_register | 服务名 | SecurityHealth |
| dns_query | 域名 ← 进程名 | evil.com ← powershell.exe |
| behavior_alert | 行为描述 | 进程注入检测 |
| ioc_match | 匹配规则名 + IOC 值 | Rule: cobaltstrike_beacon |
| user_login | 用户名 + 登录类型 | admin (远程登录) |
| module_load | 模块名 (进程名) | ntdll.dll (svchost.exe) |
| scheduled_task | 任务名 | UpdateTask |
| driver_load | 驱动名 | EasyAntiCheat.sys |

---

## 6. 数据需求

### 6.1 当前可用字段（从现有 API 和 EventTable 提取）

```
event.id          — 事件唯一标识
event.event_type  — 事件类型（process_start, network_outbound 等）
event.attack_stage — MITRE 攻击阶段
event.severity    — 严重度（critical/high/medium/low/info）
event.timestamp   — 时间戳（ISO 8601）
event.process_name — 进程名
event.pid         — 进程 PID
event.ppid        — 父进程 PID
event.hostname    — 主机名
event.host_id     — 主机 ID
event.remote_address — 远程 IP（网络事件）
event.remote_port — 远程端口（网络事件）
event.local_address  — 本地 IP（网络事件）
event.local_port  — 本地端口（网络事件）
event.file_name   — 文件名
event.file_path   — 文件路径
event.evidence    — 证据对象（含 parent_name, command_line 等）
event.summary     — 文本摘要（现有）
event.case_id     — 关联案件 ID
```

### 6.2 新增/确认字段需求

以下字段建议后端在 `/analysis/events/timeline` 接口中**确保返回**（部分可能已有但需要确认数据结构）：

| 字段 | 类型 | 说明 | 必要性 |
|------|------|------|--------|
| `event_type` | string | 事件类型标识 | P0（已有） |
| `timestamp` | string | ISO 8601 时间戳 | P0（已有） |
| `process_name` | string | 进程名称 | P0（已有，需确认在 timeline 接口中返回） |
| `pid` | number | 进程 ID | P0（已有，需确认） |
| `remote_address` | string | 远程 IP 地址 | P0 |
| `remote_port` | number | 远程端口 | P0 |
| `local_address` | string | 本地 IP 地址 | P0 |
| `local_port` | number | 本地端口 | P0 |
| `file_path` | string | 文件完整路径 | P0 |
| `registry_key` | string | 注册表路径 | P0 |
| `hostname` | string | 主机名 | P1 |
| `severity` | string | 严重度等级 | P0（已有） |
| `attack_chain_id` | string | 所属攻击链 ID | P1（用于多链场景） |

### 6.3 API 响应格式建议

保持现有 `/api/analysis/events/timeline` 接口不变，确保 `events` 数组中的每个事件对象包含上述 P0 字段。

```
GET /api/analysis/events/timeline?case_id=xxx

Response:
{
  "code": 0,
  "data": {
    "chains": [
      { "id": "chain-001", "status": "in_progress", ... }
    ],
    "events": [
      {
        "id": "evt-001",
        "event_type": "process_start",
        "attack_stage": "execution",
        "severity": "high",
        "timestamp": "2026-06-24T14:32:15Z",
        "process_name": "LsaIso.exe",
        "pid": 1088,
        "hostname": "WIN-B3K4M9",
        "summary": "LsaIso.exe 进程启动 (PID 1088)"
      },
      ...
    ]
  }
}
```

---

## 7. 组件 Props 调整

当前 `AttackChainTimeline.vue` 的 props 设计合理，调整如下：

| Prop | 类型 | 说明 | 变更 |
|------|------|------|------|
| `timelineEvents` | Array | 时间线事件列表 | 不变，内容需丰富 |
| `currentEventId` | String | 当前选中事件 ID | 不变 |
| `currentStage` | String | 当前选中阶段 | 不变 |
| `loading` | Boolean | 加载状态（新增） | P1 新增 |
| `error` | String | 错误信息（新增） | P1 新增 |

Emit 保持不变：
- `select-event` — 选中事件时触发
- `toggle-stage` — 展开/折叠阶段时触发

---

## 8. 组件内部状态

| 状态 | 类型 | 说明 |
|------|------|------|
| `expandedStages` | Ref<Object> | 各阶段展开状态 { stageKey: boolean } |
| `maxVisibleEvents` | number | 每阶段默认显示事件数上限（50） |
| `showAllStages` | Ref<Object> | 每阶段是否显示全部事件 { stageKey: boolean } |

---

## 9. 待确认问题

| ID | 问题 | 建议 |
|----|------|------|
| Q-01 | timeline 接口返回的 events 数组中，是否已包含 `process_name`、`pid`、`remote_address` 等字段？还是需要单独从 `evidence` 对象中提取？ | 建议后端统一在 events 顶层返回关键字段，前端优先使用顶层字段，降级到 `evidence` 对象 |
| Q-02 | 多条攻击链（多 chain）时，时间线如何展示？是切换 tab 还是合并展示？ | 阶段1先按单链处理，后续阶段再讨论多链方案 |
| Q-03 | 事件类型图标使用 emoji 还是 SVG 图标？ | 建议使用轻量 emoji（🚀📝🌐🔧📁），不增加图标库依赖；后续可替换为 SVG |
| Q-04 | "显示全部 N 条" 是一次性加载全部还是分页加载？ | 阶段1采用一次性展开（前端已有全量数据），后续阶段需要时分页加载 |
| Q-05 | 时间线中的事件与事件列表（EventTable）中的事件是否为同一个数据源？选中联动时是否需要避免重复请求？ | 建议使用同一数据源，选中事件时由父组件同步更新 currentEventId，避免重复请求 |

---

## 10. 实施边界

### 阶段 1（本轮）范围
- AttackChainTimeline.vue 改造：事件条目展示 + 动态字段 + 高亮/滚动 + 折叠
- Props 接口微调（扩展数据结构但不破坏兼容）
- 样式更新：事件条目布局、颜色标签、箭头连接

### 不在本轮范围
- 后端接口改造（假设现有接口已含所需字段，仅前端渲染改造）
- 虚拟滚动（P2）
- 多攻击链切换（P2）
- 事件搜索/过滤（P2）

---

## 11. 性能考虑

| 场景 | 措施 |
|------|------|
| 阶段内 > 50 条事件 | 默认只渲染前 50 条，其余通过"显示全部"按钮展开 |
| 阶段内 > 200 条事件 | P2 引入虚拟滚动 |
| 自动滚动 | 使用 scrollIntoView({ block: 'nearest' }) 避免不必要的页面跳动 |
| 展开/折叠切换 | 仅切换 CSS display，不销毁/重建 DOM（v-show 而非 v-if） |
