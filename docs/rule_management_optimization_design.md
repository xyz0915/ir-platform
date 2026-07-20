# 规则管理模块优化设计方案

> 日期: 2026-07-20 | 版本: v1.0 | 状态: 设计中

---

## 一、优化总览

| 优先级 | 编号 | 模块 | 类型 | 预估工时 |
|--------|------|------|------|---------|
| 🔴 P0 | #1 | RulesStore + 组件拆分 | 架构重构 | 4h |
| 🔴 P0 | #2 | 后端统计接口 `/api/rules/stats` | 新接口 | 1h |
| 🟡 P1 | #3 | 规则测试沙盒 `/api/rules/test` | 新功能 | 3h |
| 🟡 P1 | #4 | 规则卡片视图 RuleCard.vue | 新 UI 组件 | 4h |
| 🟡 P1 | #5 | 导入自动触发匹配 | 功能增强 | 1h |
| 🟢 P2 | #6 | 统一数据库 Migration | 重构 | 1h |
| 🟢 P2 | #7 | 规则导入写入审计日志 | 功能补全 | 0.5h |
| 🟢 P2 | #8 | 规则条件编辑器组件 | UI 优化 | 3h |

---

## 二、各模块详细方案

---

### #1 RulesStore + 组件拆分

#### 现状问题
- `RulesView.vue` 1685 行，含概览/表格/CRUD/导入导出/覆盖率
- 规则数据存在组件 `ref([])`，每次进入页面全量请求
- RulesView 和 RuleDraftView 数据不互通

#### 方案
**文件结构**：
```
frontend/src/
├── stores/rulesStore.js         ← 新建！Pinia Store
├── views/RulesView.vue          ← 精简为主框架 + 子组件拼装
├── components/rules/
│   ├── RuleMetrics.vue          ← 概览指标卡片（从 RulesView 抽出）
│   ├── RuleCoverageCard.vue     ← ATT&CK 覆盖率卡片（从 RulesView 抽出）
│   ├── RuleTable.vue            ← 规则表格 + 批量操作（从 RulesView 抽出）
│   ├── RuleDetailDialog.vue     ← 规则编辑弹窗（从 RulesView 抽出）
│   ├── RuleCard.vue             ← 新建！规则详情滑出面板
│   └── RuleConditionEditor.vue  ← 新建！规则条件可视化编辑
```

**Store 设计**：
```js
// stores/rulesStore.js
export const useRulesStore = defineStore('rules', () => {
  const rules = ref([])
  const loading = ref(false)
  const stats = ref(null)        // 后端 /api/rules/stats 返回
  const categories = ref([])
  const coverage = ref(null)
  
  async function fetchRules(params)    // GET /api/rules
  async function fetchStats()          // GET /api/rules/stats ← #2
  async function fetchCoverage()       // GET /api/rules/coverage
  async function createRule(data)      // POST /api/rules
  async function updateRule(id, data)  // PUT /api/rules/{id}
  async function deleteRule(id)        // DELETE /api/rules/{id}
  async function bulkEnable(ids, en)   // PUT /api/rules/bulk-enable
  
  return { rules, loading, stats, categories, coverage,
           fetchRules, fetchStats, fetchCoverage, ... }
})
```

**组件树**：
```
RulesView.vue
├── RuleMetrics.vue         ← props: stats
├── RuleCoverageCard.vue    ← props: coverage
├── 搜索工具栏
├── RuleTable.vue           ← props: rules, loading
│   └── 行点击 → RuleCard.vue (右侧滑出)
├── RuleDetailDialog.vue    ← 新增/编辑
│   └── RuleConditionEditor.vue
└── 导入导出按钮
```

---

### #2 后端统计接口 `/api/rules/stats`

#### 接口定义
```python
GET /api/rules/stats
Response:
{
  "code": 0,
  "data": {
    "total": 120,              # 规则总数
    "enabled": 89,             # 已启用
    "high_risk": 42,           # critical+high
    "medium_risk": 28,         # medium
    "user_rules": 5,           # source != 'default'
    "coverage_pct": 68.5,      # ATT&CK 覆盖率
    "hit_top_10": [...],       # 命中 TOP 10 规则名
    "false_positive_rate": 3.2 # 误报率
  }
}
```

#### 实现逻辑
- 单条 SQL 完成所有计数（避免多次查询）
- 复用 `Rule.list()` 的多租户过滤

---

### #3 规则测试沙盒 `/api/rules/test`

#### 接口定义
```python
POST /api/rules/test
Body: {
  "rule": { ... },          # 完整 rule 对象（含 condition）
  "sample": { ... }         # 单条事件证据样本
}
Response: {
  "matched": true/false,
  "matched_fields": ["field1", "field2"],
  "confidence": 0.85,
  "reasons": ["理由1", "理由2"]
}
```

#### 实现逻辑
- 将 rule 临时注册到 RuleEngine 但不持久化
- 用 CanonicalAdapter 将 sample 转为引擎格式
- 调用 `RuleEngine.evaluate(item, rule)` 返回匹配结果
- 前端弹窗展示匹配详情

---

### #4 规则卡片视图 RuleCard.vue

#### UI 设计
右侧滑出面板（类似事件详情面板），内容：
```
┌─── RuleCard ──────────────────────┐
│  [关闭 ×]                         │
│                                   │
│  🔴 high  可疑进程启动    v2      │
│  ───────────────────────────────  │
│  基本信息                          │
│  类别: process                     │
│  类型: regex                       │
│  来源: default                     │
│  ATT&CK: T1055.001                │
│  创建: 2026-01-15                  │
│  ───────────────────────────────  │
│  条件原文                          │
│  ┌────────────────────────────┐   │
│  │ {"field": "process_name",  │   │
│  │  "pattern": ".*malware.*" }│   │
│  └────────────────────────────┘   │
│  ───────────────────────────────  │
│  📊 命中统计                      │
│  今日命中: 12  总命中: 342       │
│  误报率: 2.1%                     │
│  ───────────────────────────────  │
│  版本历史                          │
│  v2 2026-03-10 admin "调整阈值"   │
│  v1 2026-01-15 system "初始版本"  │
│  ───────────────────────────────  │
│  [编辑] [禁用] [删除] [回滚]     │
└────────────────────────────────────┘
```

---

### #5 导入自动触发匹配

#### 改动位置
`backend/app/services/import_service.py`

在 `import_json()` 末尾，`bulk_insert` 成功后自动调用：
```python
from app.api.events import batch_match_rules  
# 或直接调用 RuleEngine.evaluate 对新事件做匹配
```

#### 实现逻辑
```python
if raw_events and events:
    # 新事件已写入 → 触发规则匹配
    try:
        from app.rules.rule_engine import RuleEngine
        for event in events:
            matched = RuleEngine.evaluate(event)
            if matched:
                save_matched_rules(event.id, matched)
    except Exception as exc:
        logger.warning("Auto-match failed: %s", exc)
```

---

### #6 统一数据库 Migration

#### 改动
将 `database.py` 中 4 个散落的规则 migration 函数合并为：
```python
def _migrate_rules_schema():
    """规则模块统一 Migration（按版本号顺序执行）."""
    migrations = [
        ("v1", "创建 rules 表"),
        ("v2", "添加 label/source/mitre_attack 列"),
        ("v3", "规则治理：owner/status/approved_by + rule_history"),
        ("v4", "规则草稿表"),
        ("v5", "影子模式列 is_shadow/shadow_hit_count"),
    ]
    # 在 rules_migration_version 表中记录已执行版本
    # 按顺序执行未迁移的版本
```

---

### #7 规则导入写入审计日志

#### 改动位置
`backend/app/api/rules.py` → `import_rules` 函数

```python
# 在导入循环中为每条规则写入审计
from app.models.rule import _write_audit
for rule_data in rules:
    # ... 已有 upsert 逻辑 ...
    _write_audit(
        conn=conn,
        rule_id=rule_id,
        action="import",
        operator=current_user.get("username", "system"),
        changes=f"Imported from JSON: {rule_data.get('name')}",
    )
```

---

### #8 规则条件编辑器组件

#### 方案
`RuleConditionEditor.vue` 按 `rule_type` 渲染专用表单：

| rule_type | UI 控件 | 示例 |
|-----------|---------|------|
| regex | 字段选择 + 正则输入 | `process_name` = `.*malware.*` |
| list | 字段选择 + 值多选 | `severity` in `[critical,high]` |
| threshold | 字段选择 + 数字 + 比较符 | `count` >= `5` |
| behavior | 行为类型 + 时间窗口 | `process_create` + `60s` 内 |
| composite | 子条件列表（AND/OR） | (`A` AND `B`) OR `C` |
| exists | 字段存在性 | `evidence.sha256` exists |
| attack_chain | 链式条件 | 阶段 A → B → C |

---

## 三、实施顺序

```
Phase 1 ─ P0 基础优化
  Day 1:  #2 后端 stats 接口（1h）→ #7 导入审计（0.5h）
  Day 2:  #1 RulesStore + 组件拆分（4h）

Phase 2 ─ P1 功能增强
  Day 3:  #3 规则测试沙盒（3h）
  Day 4:  #4 规则卡片视图（4h）
  Day 5:  #5 导入自动匹配（1h）

Phase 3 ─ P2 体验优化
  Day 6:  #6 统一 Migration（1h）
  Day 7:  #8 规则条件编辑器（3h）
```

---

## 四、依赖关系图

```mermaid
graph TD
    #2 --> #1    <!-- stats 接口是 Store 的数据来源 -->
    #1 --> #4    <!-- Store 提供 RuleCard 所需数据 -->
    #3 --> #8    <!-- 条件编辑器是测试沙盒的输入组件 -->
    #7 --> #6    <!-- 审计日志依赖统一 Migration -->
```

---

*设计方案完毕，进入开发阶段后每个模块输出独立开发报告。*
