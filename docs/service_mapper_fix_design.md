# 服务事件字段映射修复方案

> 日期: 2026-07-20 | 版本: v1.0

---

## 一、问题描述

分析中心筛选"服务操作"事件时，`evidence` 字段大量为 `null`：

```json
{
  "name": "MSSQLSERVER",
  "command": null,    ← agent 实际发的是 "path"
  "location": null,   ← agent 没有这个字段
  "type": null,       ← agent 实际发的是 "display_name"
  "user": null,
  "details": null     ← agent 实际发的是 "description"
}
```

**根因**：`PersistenceMapper` 的 evidence 字段名与 Agent 实际数据格式不匹配。

---

## 二、Agent 数据格式

### 新版 Agent（有 path 字段）

```json
{
  "name": "FakeUpdateSvc",
  "display_name": "Windows Update Helper Service",
  "path": "C:\\Windows\\Temp\\svch0st.exe",
  "start_type": "auto",
  "status": "running",
  "user": "LocalSystem",
  "description": "伪装更新"
}
```

### 旧版 Agent（无 path，用 account 代替 user）

```json
{
  "name": "AeLookupSvc",
  "display_name": "Application Experience",
  "status": "stopped",
  "start_type": "manual",
  "account": "localSystem"
}
```

---

## 三、字段映射方案

### 3.1 PersistenceMapper 映射表

| 新版 Agent 字段 | 旧版 Agent 字段 | Mapper 新字段 | 用途 |
|-----------------|----------------|--------------|------|
| `name` | `name` | `name` | 服务名 |
| `path` | 无 | `path` | 二进制路径（最关键） |
| `display_name` | `display_name` | `display_name` | 显示名 |
| `start_type` | `start_type` | `start_type` | 启动类型 |
| `status` | `status` | `status` | 运行状态 |
| `user` | `account` | `user` | 运行账户 |
| `description` | 无 | `description` | 描述 |

### 3.2 向后兼容

```python
"path": raw.get("path"),
"user": raw.get("user") or raw.get("account"),
# status/start_type/display_name 新旧版字段名一致
```

### 3.3 EventSummary 增强

`event_enrichment.py` 中 service_operation 摘要生成，从 `path` 提取可执行文件名：

```python
elif event_type == "service_operation":
    svc_name = _g("name", default="?")
    svc_path = _g("path", default="")
    if svc_path:
        # 从路径提取 exe 名
        import re
        m = re.search(r'([^\\\/]+\.exe)', svc_path, re.I)
        pname = m.group(1) if m else svc_path.split()[-1]
        summary = f"服务 {svc_name} ({pname})"
    else:
        summary = f"服务 {svc_name}"
    parts.append(summary)
```

---

## 四、影响范围

| 文件 | 改动 | 影响 |
|------|------|------|
| `event_normalizer.py` | PersistenceMapper.map() 字段映射 | ✅ 新导入事件 |
| `event_enrichment.py` | service_operation 摘要生成 | ✅ 前端显示 |
| `scripts/backfill_service_events.py` | 新建：回溯已有事件 | ✅ 历史数据 |

---

## 五、测试方案

### 单元测试

| 用例 | 输入 | 预期 |
|------|------|------|
| 新版 Agent 数据 | 7 字段完整 | evidence.path = "C:\\Windows\\Temp\\svch0st.exe" |
| 旧版 Agent 数据 | 5 字段（含 account） | evidence.user = "localSystem" |
| 空字段数据 | {name: "test"} | evidence.name = "test", 其余 None |
| 摘要生成-有 path | path="svchost.exe -k netsvcs" | 摘要含 "svchost.exe" |
| 摘要生成-无 path | name="TestSvc" | 摘要为 "服务 TestSvc" |

### 集成测试

| 场景 | 步骤 | 预期 |
|------|------|------|
| 导入服务数据 | 触发 import → 查 DB | service_operation 事件 evidence 含 path/user |
| API 查询 | GET /events → 查 summary 字段 | 摘要含 exe 名 |
| 前端展示 | 分析中心筛选"服务操作" | path 列有值 |

---

## 六、技术难点

1. **兼容旧版 Agent**：有的 agent 发 `account` 而非 `user`，需 `or` 兜底
2. **历史数据不回填**：已有 162 条 service_operation 事件 evidence 只有 name。需 backfill 脚本重读导入 JSON 再写入
3. **摘要计算是实时的**：`build_event_summary` 不会改数据库，只影响前端显示。对于历史事件，即使 evidence 没更新，摘要也能从已有数据（至少 name）展示

---

*方案设计完毕，进入开发阶段。*
