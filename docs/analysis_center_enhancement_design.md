# 分析中心增强方案设计（7 功能）

> 基于应急响应分析师工作流，对齐活林（Qi）评审后执行

---

## 功能一：进程树视图

### 目标
在事件详情面板中展示完整的进程调用链，替代当前仅显示单层父进程名。

### 现状
详情面板第 83-85 行：
```html
<div v-if="event.evidence?.parent_name">
  <span>父进程</span>
  <span>{{ event.evidence.parent_name }} (PPID: {{ event.evidence.ppid || '?' }})</span>
</div>
```
仅显示直系父进程，无调用链。

### 方案

#### 后端：新增 `GET /api/analysis/events/{id}/process-tree`

**职责**：以当前事件为叶子节点，向上回溯构建进程树，向下展开子进程。

**伪代码逻辑**：
```python
def get_process_tree(event_id, host_id, event_timestamp):
    # 1. 从 current event.evidence 获取 pid/ppid/process_name
    # 2. 向上回溯：SELECT * FROM security_events 
    #    WHERE host_id=? AND event_type='process_start'
    #    AND evidence->>'pid' = current_ppid
    #    最多回溯 10 层
    # 3. 向下展开：SELECT * FROM security_events
    #    WHERE host_id=? AND event_type='process_start'
    #    AND evidence->>'ppid' = current_pid
    #    最多展 5 层
    # 4. 时间窗口：事件时间前后 5 分钟
    # 5. 返回树形结构
```

**返回结构**：
```json
{
  "tree": [
    {"pid": 1116, "name": "explorer.exe", "ppid": 888, "cmdline": "C:\\Windows\\explorer.exe", "depth": 0},
    {"pid": 3296, "name": "cmd.exe", "ppid": 1116, "cmdline": "cmd.exe /c powershell ...", "depth": 1},
    {"pid": 4120, "name": "powershell.exe", "ppid": 3296, "cmdline": "powershell -EncodedCommand ...", "depth": 2},
    {"pid": 5200, "name": "malware.exe", "ppid": 4120, "cmdline": "C:\\Users\\Public\\malware.exe", "depth": 3}
  ],
  "current_event_pid": 5200,
  "total_depth": 4
}
```

#### 前端：EventDetailPanel.vue 新增区块

插入在"基本信息"区块之后、"命令执行"区块之前：

```html
<div class="detail-section" v-if="processTree?.length">
  <div class="section-title">进程树</div>
  <div class="proc-tree">
    <div v-for="(node, i) in processTree" :key="node.pid"
         class="pt-node" :class="{ 'pt-current': node.pid === currentPid }"
         :style="{ paddingLeft: (node.depth * 24 + 8) + 'px' }">
      <!-- 竖线+连接线（SVG） -->
      <svg v-if="i > 0" class="pt-line" width="24" height="32">
        <line x1="0" y1="0" x2="0" y2="16" stroke="#888" stroke-width="1.5" />
        <line x1="0" y1="16" x2="16" y2="16" stroke="#888" stroke-width="1.5" />
      </svg>
      <!-- 进程图标 -->
      <span class="pt-icon">⚙</span>
      <!-- 进程名 + PID -->
      <strong>{{ node.name }}</strong>
      <span class="pt-pid">({{ node.pid }})</span>
      <!-- 命令行缩略 -->
      <span class="pt-cmdline" :title="node.cmdline">{{ truncate(node.cmdline, 80) }}</span>
    </div>
  </div>
</div>
```

**状态管理**：在 analysis store 新增 `processTree`、`fetchProcessTree(eventId)`。
懒加载——用户展开详情面板时才调用。

### 工作量
- 后端：1 个新 API 文件或添加到 events.py，~80 行
- 前端：EventDetailPanel.vue 新区块 + store 方法，~60 行
- 合计：约 140 行

---

## 功能二：事件标记/收藏

### 目标
为分析师提供一个轻量的、纯前端的"标记待查"机制，不污染后端状态。

### 方案

#### 纯前端实现（零后端改动）

利用 `localStorage` 或 `sessionStorage`，以 `bookmarked_event_ids` 为 key 存储 Set。

**store 变更**（`stores/analysis.js`）：
```javascript
// 新增属性和方法
const bookmarkedIds = reactive(new Set(
  JSON.parse(localStorage.getItem('bm_events') || '[]')
))

function toggleBookmark(id) {
  if (bookmarkedIds.has(id)) bookmarkedIds.delete(id)
  else bookmarkedIds.add(id)
  localStorage.setItem('bm_events', JSON.stringify([...bookmarkedIds]))
}

function isBookmarked(id) { return bookmarkedIds.has(id) }
```

#### 表格变更（EventTable.vue）

复选框列左侧新增书签列：
```html
<el-table-column width="32">
  <template #default="{ row }">
    <span class="bm-icon" :class="{ 'bm-active': store.isBookmarked(row.id) }"
          @click.stop="store.toggleBookmark(row.id)">
      {{ store.isBookmarked(row.id) ? '⚑' : '⚐' }}
    </span>
  </template>
</el-table-column>
```

#### 筛选栏新增"只看标记"切换

在现有 viewFilter 标签组中加一个可选 tab：
```
[全部] [已匹配] [未匹配] [AI推荐] [📌 已标记]
```
点击后表格只显示 `bookmarkedIds` 中的事件。

### 工作量
- store 新增 ~15 行
- EventTable.vue 新增 ~15 行
- ViewFilter.vue 加 1 个 tab 项
- 零后端改动

---

## 功能三：网络连接图

### 目标
将事件中的 `network_connections` 数据可视化为 `来源→目的` 关系图，替代纯列表查看。

### 方案

#### 后端：新增 `GET /api/analysis/events/{id}/network-graph`

**逻辑**：
```python
def get_network_graph(event_id):
    # 取 event.evidence，解析 network_connections 列表
    # 每条连接格式：{local_port, remote_ip, remote_port, protocol}
    # 去重聚合：(remote_ip, remote_port) → count
    # 构建图数据
```

**返回结构**：
```json
{
  "nodes": [
    {"id": "local", "label": "本机", "type": "host", "ip": "10.0.0.5"},
    {"id": "1.2.3.4", "label": "1.2.3.4", "type": "remote", "port": 443},
    {"id": "10.0.0.1", "label": "10.0.0.1", "type": "remote", "port": 80}
  ],
  "edges": [
    {"source": "local", "target": "1.2.3.4", "protocol": "TCP", "port": 443, "count": 12},
    {"source": "local", "target": "10.0.0.1", "protocol": "TCP", "port": 80, "count": 3}
  ]
}
```

#### 前端：EventDetailPanel.vue 新增区块

利用纯 SVG 绘制简易关系图（不引入 D3，保持零额外依赖）：
- 左侧"本机"圆形节点
- 右侧远程 IP 矩形节点（按连接数排大小）
- 连线标注端口和协议
- 恶意 IP 用红色边框

简化方案（备选）：对远端连接多的场景，改用表格展示但每行加一个协议图标 + 端口标注，只对 ≤3 个远端 IP 的场景用 SVG 图。

**建议实现策略**：先推"轻量版"——表格 + 小标记，数据打通后若用户觉得不够直观再升级 SVG 图。

### 工作量
- 后端：~40 行
- 前端：~80 行（含 SVG 绘制逻辑）
- 合计：~120 行

---

## 功能四：同类事件首次/最近出现时间

### 目标
在详情面板显示该事件的"同类事件统计"，帮助分析师判断这是个孤立事件还是批量爆发。

### 方案

#### 后端：原有 `get_event` 接口扩展

在 `events.py:get_event()`（526行）的 SQL 中增加聚合子查询，或者新增一个轻量端点 `GET /api/analysis/events/{id}/frequency`。

**推荐**：在现有 `get_event` 的 `_row_to_dict` 中追加聚合数据，避免额外 API 调用。

**SQL**：
```sql
SELECT 
  COUNT(*) as total_count,
  MIN(se.timestamp) as first_seen,
  MAX(se.timestamp) as last_seen,
  COUNT(DISTINCT se.host_id) as affected_hosts
FROM security_events se
WHERE se.event_key = (SELECT event_key FROM security_events WHERE id = ?)
```

#### 前端：EventDetailPanel.vue 显示

在"基本信息"区块末尾加：
```html
<div class="detail-row" v-if="eventFrequency">
  <span class="detail-label">同类事件</span>
  <span class="detail-value">
    首次 {{ formatTime(eventFrequency.first_seen) }}
    · 最近 {{ formatTime(eventFrequency.last_seen) }}
    · 共 {{ eventFrequency.total_count }} 次
    · {{ eventFrequency.affected_hosts }} 台主机
  </span>
</div>
```

**视觉**：如果 `total_count > 50`，用红色文字警示"高频事件"。

### 工作量
- 后端：~20 行（SQL + 字段追加）
- 前端：~15 行
- 合计：~35 行

---

## 功能五：批量操作工具栏

### 目标
实现事件多选后的批量处理能力，覆盖批量转案、批量指派、批量导出、批量标记误报。

### 方案

#### 后端新增 API

**批量状态变更**：`POST /api/analysis/events/batch-status`
```json
{
  "ids": [1, 2, 3, ...],
  "status": "rejected",
  "comment": "误报 - 内网扫描器行为"
}
```

**批量指派**：`POST /api/analysis/events/batch-assign`
```json
{"ids": [1, 2, 3], "assignee": "zhangsan"}
```

**批量加入案件**：`POST /api/analysis/events/batch-link-case`
```json
{"ids": [1, 2, 3], "case_id": 8}
```

#### 前端：EventTable 上方批量操作栏

当 `selectedIds.length >= 2` 时浮出，固定在表格顶部：

```html
<div v-if="selectedIds.length >= 2" class="batch-bar">
  <span class="batch-count">已选 {{ selectedIds.length }} 条</span>
  <el-divider direction="vertical" />
  <el-button size="small" @click="onBatchReject">标记误报</el-button>
  <el-button size="small" @click="onBatchAssign">指派</el-button>
  <el-button size="small" @click="onBatchLinkCase">关联案件</el-button>
  <el-button size="small" @click="onBatchExport">导出</el-button>
  <el-button size="small" text @click="clearSelection">取消选择</el-button>
</div>
```

### 工作量
- 后端：3 个新端点，~90 行
- 前端：EventTable 新增 batch-bar 组件 + AnalysisCenterView handler，~80 行
- 合计：~170 行

---

## 功能六：自动 IOC 提取展示

### 目标
从 `security_events.evidence` JSON 中自动提取所有威胁指标（IP、域名、哈希、文件路径），作为独立结构化区块展示，方便分析师快速获取关键情报。

### 方案

#### 后端：新增 IOC 解析器服务

新建 `backend/app/services/ioc_extractor.py`：

```python
import re
from typing import Dict, List

def extract_iocs(evidence: dict) -> dict:
    """从 evidence 字典中统一提取所有 IOC."""
    iocs = {
        "ips": set(),
        "domains": set(),
        "md5": set(),
        "sha1": set(),
        "sha256": set(),
        "file_paths": set(),
    }
    # 遍历 evidence 所有值，递归字典/列表
    # 正则匹配 IPv4 / domain / hash ...
    _recurse_extract(evidence, iocs)
    return {k: list(v) for k, v in iocs.items()}
```

在 `get_event`（`events.py:526`）中调用该解析器，将结果追加到返回字段 `iocs`。

#### 前端：EventDetailPanel.vue 新区块

在"基本信息"之后、"进程树"之前：

```html
<div class="detail-section" v-if="eventIOCs?.ips?.length || eventIOCs?.sha256?.length">
  <div class="section-title">威胁指标 ({{ totalIocCount }})</div>
  <div class="ioc-group" v-if="eventIOCs.ips?.length">
    <span class="ioc-group-label">🌐 IP 地址</span>
    <span v-for="ip in eventIOCs.ips" class="ioc-chip ioc-ip"
          @click="copyIOC(ip)" :title="'复制: ' + ip">{{ ip }}</span>
  </div>
  <div class="ioc-group" v-if="eventIOCs.sha256?.length">
    <span class="ioc-group-label">📁 文件哈希</span>
    <span v-for="h in eventIOCs.sha256" class="ioc-chip ioc-hash"
          @click="copyIOC(h)" :title="'复制: ' + h">
      {{ h.substring(0,16) }}...
      <a @click.stop="openVT(h)" class="ioc-vt-link">VT</a>
    </span>
  </div>
  <!-- 域名 / MD5 等类推 -->
</div>
```

**IOC chip 样式**：圆角标签，不同颜色区分类型（蓝色=IP、红色=哈希、绿色=域名），hover 展开完整值，点击复制。

### 工作量
- 后端：新建 `ioc_extractor.py` ~80 行 + events.py 调用 ~5 行
- 前端：EventDetailPanel.vue 新区块 ~60 行 + 样式
- 合计：~145 行

---

## 功能七：一键上下文切换（同主机事件快速导航）

### 目标
在当前详情面板中支持"上一条/下一条"导航，以及"查看此主机全部事件"的快速跳转，消除分析师查看多条事件时的页面反复操作。

### 方案

#### 后端：无需新增 API

利用现有的 `list_events` 接口（`events.py:133`），传 `host_id=xxx` 即可获取同主机事件列表。

#### 前端：EventDetailPanel.vue 改造

**改造 1：主机名变为可点击链接**
```html
<span class="host-link" @click="onFilterByHost(event.host_id)">
  {{ event.hostname || ('#主机' + event.host_id) }}
</span>
```
`onFilterByHost()` 将表格筛选条件设为该 host_id，刷新表格内容，关闭当前详情。

**改造 2：添加上一条/下一条导航**
```html
<div class="detail-nav" v-if="siblingEvents.length">
  <button :disabled="!prevEvent" @click="navigateTo(prevEvent)">‹ 上一条</button>
  <span class="nav-pos">{{ currentPos + 1 }} / {{ siblingEvents.length }}</span>
  <button :disabled="!nextEvent" @click="navigateTo(nextEvent)">下一条 ›</button>
</div>
```

`siblingEvents` 来自 store 中当前表格的数据源——不需要额外请求，直接复用已经加载的 `store.items`。

**改造 3（可选）**：事件 ID 旁边的"查看详情"链接改为可点击事件 ID，跳转到独立详情页（利用已有路由 `/analysis-center/event/{id}`）。

### 工作量
- 后端：无改动
- 前端：EventDetailPanel.vue ~40 行
- 合计：~40 行

---

## 汇总

| # | 功能 | 后端行数 | 前端行数 | 总行数 | 优先级建议 |
|---|------|---------|---------|-------|-----------|
| 1 | 进程树 | 80 | 60 | 140 | P1 |
| 2 | 事件标记/收藏 | 0 | 30 | 30 | P0（零成本） |
| 3 | 网络连接图 | 40 | 80 | 120 | P2 |
| 4 | 同类事件统计 | 20 | 15 | 35 | P1 |
| 5 | 批量操作工具栏 | 90 | 80 | 170 | P1 |
| 6 | IOC 提取展示 | 85 | 60 | 145 | P0 |
| 7 | 上下文切换 | 0 | 40 | 40 | P0（零成本） |
| **合计** | | **315** | **365** | **680** | |

**实施建议**：按 P0 → P1 → P2 排期，P0 的 3 个功能（标记、IOC、上下文切换）互不依赖，可并行开发。P1 的 3 个功能（进程树、同类统计、批量操作）建议按依赖顺序做。P2 的网络连接图可最后做或视业务需要再决定。
