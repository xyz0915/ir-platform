# 规则管理页（/rules）应急专家视角分析与增强方案

## 一、截图信息确认

截图页面为 **规则管理（`/rules`）**，非策略配置（`/policies`）。当前状态：

- 规则总数 26，已启用 19，中高危规则 26，用户规则 0，规则引擎 176，行为引擎 4
- 当前分类筛选为「持久化」
- 列表中可见 `adv_schtasks_persistence`、`adv_suspicious_service_create`、`pki_*_exists` 等 P3 新增规则

## 二、规则详情能不能点开？

**可以点开**，但体验不佳。

- 列表每行操作列有「眼睛」和「编辑」图标，点击都会打开「规则详情」弹窗（`showDetail`）
- 弹窗内容仅包括：名称、中文名、类别、规则类型、严重度、来源、描述、**原始 JSON 条件**
- 对一线应急人员不友好：看到 `{"field":"command_line","pattern":"..."}` 需要自行脑补规则在检测什么

## 三、从应急专家角度看的 6 个关键缺陷

| 缺陷 | 应急场景影响 | 风险等级 |
|---|---|---|
| 1. 无严重度筛选 | 上线前无法快速核查「还有哪些高危规则未启用」 | 高 |
| 2. 无规则类型筛选 | 无法单独查看攻击链、复合规则、存在性检测等类型，难以评估覆盖完整性 | 高 |
| 3. 无启用状态筛选 | 不能一键只看「未启用规则」，漏配检测难发现 | 高 |
| 4. 无来源/生命周期筛选 | 无法区分内置/用户/AI/导入规则，也无法发现待审批或已废弃规则 | 中 |
| 5. 分类下拉硬编码 | 新增 category（如 P3 的 `impact`、`exfiltration`、`webshell`）不会自动出现 | 中 |
| 6. 详情弹窗可读性差 | 条件 JSON 不直观，HITL/死规则/待接采集器等信息未显性标注 | 中 |

## 四、已落地的增强（本次已实现）

### 4.1 后端：`backend/app/models/rule.py` + `backend/app/api/rules.py`

`/api/rules` 主列表接口新增查询参数：

- `severity`：严重度过滤
- `rule_type`：规则类型过滤
- `source`：来源过滤（default/user/ai/import）
- `status`：生命周期过滤（active/pending_approval/deprecated）

### 4.2 前端：`frontend/src/views/RulesView.vue`

#### A. 顶部应急运营 Chips
- 已启用 / 未启用 数量
- 严重 / 高危 数量
- 需审批（HITL）数量
- 待激活死规则数量

点击 Chip 即可快速切换对应筛选。

#### B. 筛选面板扩展
- 分类：改为**动态从实际规则推导**，新增 category 自动出现
- 引擎类型、严重度、规则类型、启用状态、来源、生命周期状态

#### C. 详情弹窗增强
- 新增「条件（可读化）」表格：按 `regex`/`list`/`threshold`/`behavior`/`composite`/`exists`/`attack_chain`/`event_log_summary` 分别展示关键字段
- 新增运营标记：死规则（待采集器）、需人工审批
- 保留「原始条件 JSON」供高级用户核对

## 五、验证结果

- `vite build` 通过，无语法错误
- 后端 API 登录后测试：
  - `GET /api/rules?severity=high&rule_type=regex&source=default` 返回正确
  - `GET /api/rules?rule_type=exists&enabled=0` 返回 6 条存在性兜底规则（含 `pending_collector`）

## 六、后续建议

如需进一步提升应急响应效率，可继续补充：

1. **规则命中统计**：在列表/详情展示近 7 天命中次数、最近命中时间
2. **MITRE 覆盖矩阵**：按 Tactics 维度展示已启用规则覆盖情况
3. **一键高危全启**：类似策略页的「补全高危未选」能力
4. **死规则治理入口**：对 `pending_collector` 规则提供「已接入采集器后批量启用」工作流
