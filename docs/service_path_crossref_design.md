# 服务路径交叉补全方案

> 日期: 2026-07-20 | 版本: v1.0 | 状态: 设计中

---

## 一、问题

`data["services"]`（162 条）生成 `service_operation` 事件时 evidence.path 为 null，
因为该数据源不包含路径。而 `data["persistence"]["services"]`（419 条）有 `command`
字段（即二进制路径），但未被事件生成流程使用。

## 二、方案

**不改变事件来源**，在事件生成时按 name 交叉匹配 `persistence.services` 补全 path。

## 三、数据流

```
导入 JSON
  │
  ├─ services[162] → 产生 162 条 service_operation 事件
  │                   每个 raw item 注入 _persistence_map
  │
  └─ persistence.services[419] → 构建 name→command 索引
      传给 import_service.py，附加到每个 raw item
       
import_service.py 中：
  # 构建 persistence 服务名→command 映射
  persist_map = {s["name"]: s.get("command") for s in persistence_services}
  for item in services:
      item["_persistence_map"] = persist_map

PersistenceMapper.map() 中：
  path = raw.get("path") or raw.get("binary_path") 
         or raw.get("_persistence_map", {}).get(raw.get("name"))
```

## 四、改动范围

| 文件 | 改动 | 风险 |
|------|------|------|
| `import_service.py` | 收集 persistence.services 传入 raw item | 低 |
| `event_normalizer.py` | PersistenceMapper 读取 `_persistence_map` | 低 |
| `backfill_service_events.py` | 同上逻辑补历史事件 | 低 |
| `tests/test_service_mapper.py` | 新增交叉补全测试用例 | — |

## 五、测试用例

1. service.item 的 name 能在 persistence 中找到 → path = command
2. service.item 的 name 在 persistence 中找不到 → path 保持 None
3. persistence 中没有 services → 兜底走旧逻辑
4. 非 service_operation 事件不受影响

---

*方案设计完毕。*
