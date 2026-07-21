# Agent 时间戳采集改进 — Phase 2 设计方案

## 一、问题全貌

当前 Agent 采集的数据中，**大多数事件没有真实发生时间**，fallback 到了采集时间（`collected_at`）或批次时间（`_fallback_ts`）。

---

## 二、各采集器修复方案

### 2.1 processes — 进程创建时间 ✅ 基本可用，仅需补 `collected_at`

**当前状态**：主路径（`psutil.process_iter()`，`processes.py:71-77`）已经正确读取了进程创建时间：

```python
create_time = info.get("create_time")
if create_time:
    start_time = datetime.fromtimestamp(create_time).isoformat()
```

`psutil.create_time` 来自 Windows `NtQuerySystemInformation` 内核调用，**就是进程真正启动的时刻**。这条链路没毛病。

**问题 1**：**回退路径**（wmic/tasklist）不采集 `start_time`，3 种路径互斥：
- psutil 路径 ✅ 有创建时间（70% 场景）
- wmic 路径 ❌ 无创建时间（20% 场景）
- tasklist 路径 ❌ 无创建时间（10% 场景）

**问题 2**：**进程条目没有 `collected_at`**，导致 `collected_at` 无法作为 Mapper 的 timestamp 回退项。

**修复**：

```python
# processes.py, 在 _build_processes() 每个进程条目的末尾
{
    # ... 已有字段 ...
    "start_time": start_time,          # 已有（psutil 路径有值）
    "collected_at": get_timestamp(),   # ← 新增
}
```

在回退路径中也补上 `start_time` 的值：

```python
# wmic 路径：用 wmic 输出的 creationdate 字段
# tasklist 路径：无法获取，留空（collected_at 兜底）
```

---

### 2.2 network_connections — 连接建立时间

**当前状况**：连接创建时间有 3 条采集路径：

| 路径 | 是否支持创建时间 | 文件行号 |
|------|----------------|---------|
| **PowerShell `Get-NetTCPConnection`** | ✅ **支持！`CreationTime` 属性** | `network.py:67-118` |
| **psutil `net_connections()`** | ❌ Windows API `GetExtendedTcpTable` 不暴露 | `network.py:193-218` |
| **`netstat -ano`** | ❌ 不显示建立时间 | `network.py:227-264` |

PowerShell 路径已经存在，但 `Select-Object` 中没有选 `CreationTime`。修复：加一个字段。

**修复**：

```python
# network.py:79-86, PowerShell TCP 连接解析
conn = {
    "local_addr": parts.local_address,
    "local_port": parts.local_port,
    "remote_addr": parts.remote_address,
    "remote_port": parts.remote_port,
    "state": parts.state,
    "pid": parts.owning_process,
    "creation_time": str(getattr(parts, "CreationTime", "")),  # ← 新增
    "collected_at": get_timestamp(),                            # ← 新增
}
```

psutil 和 netstat 路径没有创建时间，但有 `collected_at`。

---

### 2.3 registry_keys — 注册表最后写入时间

**当前状况**：`last_write_time` 硬编码为空字符串（`registry.py:75`）。Windows `winreg.QueryInfoKey()` 可以返回 `last_write_time`，但从未被调用。

```python
# 当前（registry.py:123-133）
with winreg.OpenKey(hive, key_path) as key:
    i = 0
    while True:
        name, value, type_ = winreg.EnumValue(key, i)
        entries.append({
            "key": full_key,
            "name": name,
            "value": value,
            ...
            "last_write_time": "",  # ← 硬编码空
        })
        i += 1
```

**修复**：

```python
# registry.py:123, OpenKey 之后立即调用 QueryInfoKey
with winreg.OpenKey(hive, key_path) as key:
    try:
        info = winreg.QueryInfoKey(key)  # 返回 (sub_keys, values, last_write_time)
        last_write_dt = info[2]
        last_write_str = last_write_dt.isoformat() if last_write_dt else ""
    except Exception:
        last_write_str = ""
    
    i = 0
    while True:
        name, value, type_ = winreg.EnumValue(key, i)
        entries.append({
            ...
            "last_write_time": last_write_str,  # ← 真实的最后写入时间
            "collected_at": get_timestamp(),     # ← 已有
        })
        i += 1
```

**影响**：510 条注册表事件将获得真实的 `last_write_time`，精确到秒——这是注册表键值被攻击写入的真实时间。

---

### 2.4 services — 服务创建时间

**当前状况**：`sc query` + `sc qc` 输出不包含服务创建时间。

Windows SCM（Service Control Manager）在底层存储服务创建时间（`SERVICE_CONFIG_CREATED_INFO`），但：
- `sc qc` 命令行不暴露
- 需要通过 Windows API `QueryServiceConfig2` 以 `SERVICE_CONFIG_CREATED_INFO` 标志调用

**修复方案**：当前仅 `collected_at` 可用。建议**暂不修复**，等待 Agent 加入 Win32 API 调用能力后再补。

---

### 2.5 startup_items — 启动项时间

**启动项来自注册表**（Run keys、Startup 文件夹），可以复用 `registry.py` 的 `QueryInfoKey` 修复。

**修复**：在 `startup_items.py` 中 `OpenKey` 对应的 Run key hive 后调用 `QueryInfoKey`。

---

## 三、汇总对比

| 采集器 | 当前可用的最佳时间 | Phase 2 后将获得 | API 来源 |
|--------|------------------|----------------|---------|
| **processes** | `start_time`（仅 psutil 路径有值） | ✅ 回退路径也补 `start_time` + 全量 `collected_at` | `psutil.create_time()` / wmic |
| **network_connections** | `collected_at`（全有） | ✅ 新增 `creation_time`（PowerShell 路径） | `Get-NetTCPConnection.CreationTime` |
| **registry_keys** | `collected_at`（全有） | ✅ **新增真实的 `last_write_time`** | `winreg.QueryInfoKey()` |
| **services** | 无 | `collected_at`（新增） | 仅采集时间 |
| **startup_items** | 无 | ✅ `last_write_time`（来自注册表） | `winreg.QueryInfoKey()` |
| **files** | `modified`（已有） | `collected_at`（补齐缺失的项） | `os.stat().st_mtime` |

### 改进后 Mapper 端 timestamp 回退链

```
前提：Phase 1 已经改了后端 Mapper 回退链为 or 链
```

以 registry_keys 为例：

```
改前:  timestamp = _fallback_ts (2026-07-11 批次时间)
改后:  timestamp = last_write_time ?? collected_at ?? _fallback_ts
                    ↓                  ↓
              真正的注册表写入时间    采集时刻（最后的兜底）
              （攻击发生时间）         （精度从"天"降到"秒"）
```

---

## 四、涉及的文件及改动量

| 文件 | 改动内容 | 行数估计 |
|------|---------|---------|
| `agent/collectors/processes.py` | 进程条目加 `collected_at`；回退路径补 `start_time` | ~5 行 |
| `agent/collectors/network.py` | PowerShell 路径加 `CreationTime`；所有连接加 `collected_at` | ~8 行 |
| `agent/collectors/registry.py` | `OpenKey` 后调 `QueryInfoKey` 取 `last_write_time` | ~8 行 |
| `agent/collectors/startup_items.py` | 注册表路径调用 `QueryInfoKey` 取 | ~5 行 |
| `agent/collectors/services.py` | 加 `collected_at` | ~2 行 |
| **后端 Mapper（Phase 1）** | 改 11 个 Mapper 的 timestamp 兜底链为 `or` 链 | 11 行 |

---

## 五、风险与注意事项

1. **`QueryInfoKey` 性能**：每次 `OpenKey` 后调用一次，不会显著影响性能。注册表枚举已经是 O(n) 的逐项遍历，加一次 `QueryInfoKey` 是 O(1)。

2. **PowerShell `CreationTime`**：`Get-NetTCPConnection` 仅在 Windows 8/2012 以上可用。低版本 Windows 会回退到 psutil/netstat 路径，没有创建时间。

3. **psutil 路径进程创建时间**：这已经是正确的——`psutil.create_time` 来自内核。你的事件时间线里那些 `process_start` 事件的 `timestamp` 是导入时间而不是 `start_time`，是 **后端 Mapper 的空字符串问题**（Phase 1 修复），不是 Agent 的问题。

4. **向后兼容**：新 Agent 输出的 JSON 和旧 Agent 输出的 JSON 格式兼容——字段不存在时后端 Mapper 会 fallback。不需要同时升级所有端点。
