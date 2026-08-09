<template>
  <div class="page-container">
    <!-- Header -->
    <div class="page-header">
      <div class="page-header-left">
        <h2 class="page-title">
          <span>规则管理</span>
          <span class="title-badge">检测引擎</span>
        </h2>
        <div class="page-sub">检测规则引擎 — 定义安全事件匹配与告警策略</div>
      </div>
      <div class="page-actions">
        <button v-if="isAdmin" class="btn btn-warning btn-sm" @click="handleReset">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/></svg>
          重置为默认
        </button>
        <button class="btn btn-primary" @click="showCreateDialog">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新增规则
        </button>
      </div>
    </div>

    <!-- Metrics -->
    <div class="metrics">
      <div class="metric">
        <div class="metric-top"><div class="metric-dot blue"></div><div class="metric-label">规则总数</div></div>
        <div class="metric-value">{{ rules.length }}</div>
        <div class="metric-sub">检测类别覆盖</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot green"></div><div class="metric-label">已启用</div></div>
        <div class="metric-value">{{ rules.filter(r => r.enabled).length }}</div>
        <div class="metric-sub up">{{ rules.length ? Math.round(rules.filter(r => r.enabled).length / rules.length * 100) : 0 }}% 激活率</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot amber"></div><div class="metric-label">中高危规则</div></div>
        <div class="metric-value">{{ rules.filter(r => r.severity === 'critical' || r.severity === 'high' || r.severity === 'medium').length }}</div>
        <div class="metric-sub">需关注</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot red"></div><div class="metric-label">用户规则</div></div>
        <div class="metric-value">{{ rules.filter(r => r.source !== 'default').length }}</div>
        <div class="metric-sub up">自定义</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot blue"></div><div class="metric-label">规则引擎</div></div>
        <div class="metric-value">{{ statsData?.rule_engine_count || 0 }}</div>
        <div class="metric-sub">引擎规则</div>
      </div>
      <div class="metric">
        <div class="metric-top"><div class="metric-dot purple"></div><div class="metric-label">行为引擎</div></div>
        <div class="metric-value">{{ statsData?.behavior_engine_count || 0 }}</div>
        <div class="metric-sub">检测规则</div>
      </div>
    </div>

    <!-- Main Card -->
    <div class="card">
      <!-- Quick Stats Chips -->
      <div class="quick-stats">
        <div class="qs-chip" :class="{ active: filterEnabled === '1' }" @click="setEnabledFilter(true)">
          <span class="qs-dot green"></span>
          <span>已启用 {{ enabledStats.enabled }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterEnabled === '0' }" @click="setEnabledFilter(false)">
          <span class="qs-dot gray"></span>
          <span>未启用 {{ enabledStats.disabled }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterSeverity === 'critical' }" @click="setSeverityFilter('critical')">
          <span class="qs-dot critical"></span>
          <span>严重 {{ severityStats.critical }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterSeverity === 'high' }" @click="setSeverityFilter('high')">
          <span class="qs-dot high"></span>
          <span>高危 {{ severityStats.high }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterHitl }" @click="setHitlFilter">
          <span class="qs-dot purple"></span>
          <span>需审批 {{ hitlRuleCount }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterDead }" @click="setDeadFilter">
          <span class="qs-dot dead"></span>
          <span>待激活死规则 {{ deadRuleCount }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterEffective === '1' }" @click="setEffectiveFilter(true)">
          <span class="qs-dot green"></span>
          <span>真实生效中 {{ effectiveStats.active }}</span>
        </div>
        <div class="qs-chip" :class="{ active: filterEffective === '0' }" @click="setEffectiveFilter(false)">
          <span class="qs-dot red"></span>
          <span>未生效 {{ effectiveStats.inactive }}</span>
        </div>
      </div>

      <!-- Toolbar -->
      <div class="toolbar">
        <div class="search-bar">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="searchKeyword" placeholder="搜索规则名称 / 中文名 / 描述" @keyup.enter="loadRules" />
        </div>
        <select v-model="filterCategory" class="select" style="width:130px;" @change="loadRules">
          <option value="">全部类别</option>
          <option v-for="c in dynamicCategories" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="filterEngineType" class="select" style="width:110px;" @change="loadRules">
          <option value="">全部引擎</option>
          <option value="rule_engine">规则引擎</option>
          <option value="behavior_engine">行为引擎</option>
        </select>
        <select v-model="filterSeverity" class="select" style="width:100px;" @change="loadRules">
          <option value="">全部严重度</option>
          <option value="critical">严重</option>
          <option value="high">高危</option>
          <option value="medium">中危</option>
          <option value="low">低危</option>
        </select>
        <select v-model="filterRuleType" class="select" style="width:120px;" @change="loadRules">
          <option value="">全部类型</option>
          <option value="regex">正则匹配</option>
          <option value="list">列表匹配</option>
          <option value="threshold">阈值检测</option>
          <option value="behavior">行为分析</option>
          <option value="composite">复合规则</option>
          <option value="exists">存在性检测</option>
          <option value="attack_chain">攻击链</option>
          <option value="event_log_summary">事件日志聚合</option>
        </select>
        <select v-model="filterEnabled" class="select" style="width:100px;" @change="loadRules">
          <option value="">全部状态</option>
          <option value="1">已启用</option>
          <option value="0">未启用</option>
        </select>
        <select v-model="filterEffective" class="select" style="width:120px;" @change="loadRules">
          <option value="">全部生效态</option>
          <option value="1">真实生效中</option>
          <option value="0">未生效</option>
        </select>
        <select v-model="filterSource" class="select" style="width:100px;" @change="loadRules">
          <option value="">全部来源</option>
          <option value="default">内置</option>
          <option value="user">用户</option>
          <option value="ai">AI生成</option>
          <option value="import">导入</option>
        </select>
        <select v-model="filterStatus" class="select" style="width:110px;" @change="loadRules">
          <option value="">全部生命周期</option>
          <option value="active">生效中</option>
          <option value="pending_approval">待审批</option>
          <option value="deprecated">已废弃</option>
        </select>
        <div class="toolbar-spacer"></div>
        <button class="btn btn-default btn-sm" @click="resetFilters">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          重置
        </button>
        <button class="btn btn-primary btn-sm" @click="loadRules">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          搜索
        </button>
      </div>

      <!-- Loading overlay -->
      <div v-if="loading" class="loading-overlay">
        <div class="loading-spinner"></div>
      </div>

      <!-- Bulk Bar -->
      <div v-if="selectedRows.length" class="bulk-bar">
        <span>已选 {{ selectedRows.length }} 条</span>
        <button class="btn btn-sm btn-default" @click="handleBulkEnable(true)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          批量启用
        </button>
        <button class="btn btn-sm btn-default" @click="handleBulkEnable(false)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="1" y1="4" x2="23" y2="4"/><path d="M4 4v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4"/></svg>
          批量禁用
        </button>
        <button class="btn btn-sm btn-ghost" style="color:var(--color-accent-fg);" @click="clearSelection">取消选择</button>
      </div>

      <!-- Table -->
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width:28px;"><input type="checkbox" class="cbx" :checked="rules.length && selectedRows.length === rules.length" @change="(e) => { if(e.target.checked) { selectedRows = [...rules]; handleSelectionChange(selectedRows); } else { selectedRows = []; handleSelectionChange(selectedRows); } }" /></th>
              <th>规则名称</th>
              <th style="width:84px;">类别</th>
              <th style="width:90px;">引擎类型</th>
              <th style="width:72px;">类型</th>
              <th style="width:80px;">严重度</th>
              <th style="width:100px;">ATT&amp;CK</th>
              <th>描述</th>
              <th style="width:60px;">来源</th>
              <th style="width:50px;">启用</th>
              <th style="width:86px;">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in rules" :key="row.id || idx">
              <td><input type="checkbox" class="cbx" :checked="selectedRows.includes(row)" @change="(e) => { if(e.target.checked) selectedRows.push(row); else selectedRows = selectedRows.filter(r => r !== row); handleSelectionChange(selectedRows); }" /></td>
              <td>
                <div class="rule-cell">
                  <div class="rule-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                  </div>
                  <div class="rule-text">
                    <div class="rule-en">{{ row.label || row.name }}</div>
                    <div v-if="row.label && row.label !== row.name" class="rule-cn">{{ row.name }}</div>
                    <div v-if="getMitreAttack(row)" class="rule-tags">
                      <span class="rule-tag">{{ getMitreAttack(row) }}</span>
                    </div>
                  </div>
                </div>
              </td>
              <td><span class="badge badge-info">{{ row.category }}</span></td>
              <td>
                <span v-if="row.engine_type === 'behavior_engine'" class="badge badge-behavior">行为引擎</span>
                <span v-else class="badge badge-rule">规则引擎</span>
              </td>
              <td><span class="td-mono">{{ row.rule_type }}</span></td>
              <td>
                <div class="sev">
                  <div :class="['sev-dot', row.severity]"></div>
                  <span :class="['sev-text', 'sev-' + row.severity]">{{ severityLabel(row.severity) }}</span>
                </div>
              </td>
              <td>
                <span v-if="getMitreAttack(row)" class="td-mono">{{ getMitreAttack(row) }}</span>
                <span v-else class="td-muted">—</span>
              </td>
              <td><div class="desc-cell" :title="row.description">{{ row.description }}</div></td>
              <td>
                <span :class="['badge', row.source === 'default' ? 'badge-builtin' : 'badge-user']">{{ row.source === 'default' ? '内置' : '用户' }}</span>
              </td>
              <td>
                <label class="toggle">
                  <input type="checkbox" :checked="row.enabled" @change="(val) => handleToggle(row, $event.target.checked)" />
                  <div class="toggle-slider"></div>
                </label>
                <span :class="['badge', row.effective_active ? 'badge-success' : 'badge-low']" :title="row.effective_reason" style="margin-top:4px;display:inline-block;">{{ row.effective_active ? '生效中' : (row.effective_reason || '未生效') }}</span>
              </td>
              <td>
                <div class="row-actions">
                  <button class="icon-btn" title="查看" @click="showDetail(row)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                  </button>
                  <button class="icon-btn" title="编辑" @click="showDetail(row)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                  </button>
                  <button class="icon-btn danger" title="删除" :disabled="row.source === 'default'" @click="handleDelete(row)">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="!rules.length && !loading">
              <td colspan="11">
                <div class="empty-state">没有匹配的规则</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination placeholder -->
      <div class="pagination">
        <div class="pg-info">共 {{ rules.length }} 条规则</div>
      </div>
    </div>

    <!-- Rule Detail Modal -->
    <div v-if="detailDialogVisible" class="modal-overlay" @click.self="detailDialogVisible = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">规则详情</div>
          <button class="modal-close" @click="detailDialogVisible = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="detail-grid" v-if="currentRule">
            <div class="detail-item">
              <div class="detail-item-label">名称（英文键）</div>
              <div class="detail-item-value" style="font-weight:500;">{{ currentRule.name }}</div>
            </div>
            <div class="detail-item" v-if="currentRule.label">
              <div class="detail-item-label">中文名称</div>
              <div class="detail-item-value">{{ currentRule.label }}</div>
            </div>
            <div class="detail-item">
              <div class="detail-item-label">类别 / 类型</div>
              <div class="detail-item-value">
                <span class="badge badge-info" style="margin-right:6px;">{{ currentRule.category }}</span>
                <span class="badge badge-rule">{{ ruleTypeLabel(currentRule.rule_type) }}</span>
              </div>
            </div>
            <div class="detail-item">
              <div class="detail-item-label">引擎 / 来源</div>
              <div class="detail-item-value">
                <span :class="['badge', currentRule.engine_type === 'behavior_engine' ? 'badge-behavior' : 'badge-rule']" style="margin-right:6px;">
                  {{ currentRule.engine_type === 'behavior_engine' ? '行为引擎' : '规则引擎' }}
                </span>
                <span :class="['badge', currentRule.source === 'default' ? 'badge-builtin' : 'badge-user']">{{ sourceLabel(currentRule.source) }}</span>
              </div>
            </div>
            <div class="detail-item">
              <div class="detail-item-label">严重程度</div>
              <div class="detail-item-value">
                <div class="sev">
                  <div :class="['sev-dot', currentRule.severity]"></div>
                  <span :class="['sev-text', 'sev-' + currentRule.severity]">{{ severityLabel(currentRule.severity) }}</span>
                </div>
              </div>
            </div>
            <div class="detail-item" v-if="getMitreAttack(currentRule)">
              <div class="detail-item-label">ATT&amp;CK</div>
              <div class="detail-item-value td-mono">{{ getMitreAttack(currentRule) }}</div>
            </div>
            <div class="detail-item">
              <div class="detail-item-label">启用 / 生命周期</div>
              <div class="detail-item-value">
                <span :class="['badge', currentRule.enabled ? 'badge-success' : 'badge-low']" style="margin-right:6px;">{{ currentRule.enabled ? '已启用' : '未启用' }}</span>
                <span :class="['badge', currentRule.effective_active ? 'badge-success' : 'badge-low']" style="margin-right:6px;">{{ currentRule.effective_active ? '真实生效' : ('未生效·' + (currentRule.effective_reason || '')) }}</span>
                <span class="badge badge-info">{{ statusLabel(currentRule.status) }}</span>
              </div>
            </div>
            <div class="detail-item" v-if="isDeadRule(currentRule) || isHitlRule(currentRule)">
              <div class="detail-item-label">运营标记</div>
              <div class="detail-item-value">
                <span v-if="isDeadRule(currentRule)" class="badge badge-low" style="margin-right:6px;">死规则（待采集器）</span>
                <span v-if="isHitlRule(currentRule)" class="badge badge-warning">需人工审批</span>
              </div>
            </div>
            <div class="detail-item full">
              <div class="detail-item-label">描述</div>
              <div class="detail-item-value" style="color:var(--color-fg-subtle);line-height:1.6;">{{ currentRule.description || '—' }}</div>
            </div>
            <div class="detail-item full">
              <div class="detail-item-label">条件（可读化）</div>
              <div class="cond-readable" v-html="renderCondition(currentRule)"></div>
            </div>
            <div class="detail-item full">
              <div class="detail-item-label">原始条件 JSON</div>
              <div class="cond-block">{{ JSON.stringify(currentRule.condition, null, 2) }}</div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="detailDialogVisible = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Create Rule Modal -->
    <div v-if="createDialogVisible" class="modal-overlay" @click.self="createDialogVisible = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">新增规则</div>
          <button class="modal-close" @click="createDialogVisible = false">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="fg">
              <label class="fl">规则名称 <span class="required">*</span></label>
              <input class="fi" v-model="createForm.name" placeholder="英文技术键，唯一（如 suspicious_powershell）" />
            </div>
            <div class="fg">
              <label class="fl">中文名称</label>
              <input class="fi" v-model="createForm.label" placeholder="中文展示名（可选）" />
            </div>
            <div class="fg">
              <label class="fl">类别 <span class="required">*</span></label>
              <select class="fs" v-model="createForm.category">
                <option value="process">进程</option>
                <option value="execution">执行</option>
                <option value="network">网络</option>
                <option value="startup">启动项</option>
                <option value="persistence">持久化</option>
                <option value="ioc">IOC</option>
                <option value="behavior">行为</option>
                <option value="credential">凭据</option>
                <option value="lateral">横向移动</option>
                <option value="exfiltration">数据窃取</option>
                <option value="discovery">发现</option>
                <option value="defense_evasion">防御规避</option>
                <option value="privilege_escalation">权限提升</option>
                <option value="impact">影响</option>
              </select>
            </div>
            <div class="fg">
              <label class="fl">规则类型 <span class="required">*</span></label>
              <select class="fs" v-model="createForm.rule_type">
                <option value="regex">正则匹配</option>
                <option value="list">列表匹配</option>
                <option value="threshold">阈值检测</option>
                <option value="behavior">行为检测</option>
                <option value="composite">组合条件</option>
                <option value="exists">存在性检查</option>
              </select>
            </div>
            <div class="fg" v-if="!editingRuleId">
              <label class="fl">引擎类型</label>
              <div style="display:flex;gap:16px;margin-top:4px;">
                <label style="display:flex;align-items:center;gap:4px;cursor:pointer;">
                  <input type="radio" v-model="createForm.engine_type" value="rule_engine" />
                  <span>规则引擎</span>
                </label>
                <label style="display:flex;align-items:center;gap:4px;cursor:pointer;">
                  <input type="radio" v-model="createForm.engine_type" value="behavior_engine" />
                  <span>行为引擎</span>
                </label>
              </div>
              <div class="fg-hint" v-if="createForm.engine_type === 'behavior_engine'">行为引擎规则适用于系统服务风险检测场景</div>
            </div>
            <div class="fg">
              <label class="fl">严重程度</label>
              <select class="fs" v-model="createForm.severity">
                <option value="critical">严重</option>
                <option value="high">高危</option>
                <option value="medium">中危</option>
                <option value="low">低危</option>
              </select>
            </div>
            <div class="fg">
              <label class="fl">描述</label>
              <input class="fi" v-model="createForm.description" placeholder="规则用途描述" />
            </div>
          </div>
          <div class="fg" style="margin-top:4px;">
            <label class="fl">条件 JSON</label>
            <textarea class="fta" v-model="createForm.conditionStr" rows="6" :placeholder="conditionPlaceholder"></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-ghost" @click="createDialogVisible = false">取消</button>
          <button class="btn btn-primary" :disabled="creating" @click="handleCreate">
            <svg v-if="creating" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v2M12 16v2M6 12H4M20 12h-2"/></svg>
            {{ creating ? '创建中...' : '创建规则' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Search, RefreshLeft } from '@element-plus/icons-vue'
import request from '@/api/index'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const rules = ref([])
const loading = ref(false)
const statsData = ref(null)
async function loadStats() {
  try { const r = await request.get('/rules/stats'); statsData.value = r.data } catch (e) {}
}
const filterCategory = ref('')
const filterEngineType = ref('')
const filterSeverity = ref('')
const filterRuleType = ref('')
const filterEnabled = ref('')
const filterSource = ref('')
const filterStatus = ref('')
const filterEffective = ref('')
const filterDead = ref(false)
const filterHitl = ref(false)
const searchKeyword = ref('')
const selectedRows = ref([])
const tableRef = ref(null)

const detailDialogVisible = ref(false)
const currentRule = ref(null)

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  label: '',
  category: 'process',
  rule_type: 'regex',
  engine_type: 'rule_engine',
  severity: 'medium',
  description: '',
  conditionStr: '{}'
})

/** 根据选中的 rule_type 动态切换 placeholder */
const conditionPlaceholder = computed(() => {
  const placeholders = {
    regex: '{"field": "command_line", "pattern": "powershell.*-enc", "flags": "ignorecase"}',
    list: '{"field": "remote_port", "values": [4444, 1337], "match_mode": "exact"}',
    threshold: '{"field": "connection_count", "operator": ">", "value": 50}',
    behavior: '{"pattern": "orphan_process", "description": "孤立进程检测"}',
    composite: '{"logic": "AND", "sub_rules": [{"type": "regex", "field": "command_line", "pattern": "mimikatz"}, {"type": "exists", "field": "remote_address"}]}',
    exists: '{"field": "remote_address"}'
  }
  return placeholders[createForm.rule_type] || '{}'
})

onMounted(() => {
  loadRules()
  loadStats()
})

async function loadRules() {
  loading.value = true
  try {
    const params = {}
    if (filterCategory.value) params.category = filterCategory.value
    if (filterEngineType.value) params.engine_type = filterEngineType.value
    if (filterSeverity.value) params.severity = filterSeverity.value
    if (filterRuleType.value) params.rule_type = filterRuleType.value
    if (filterEnabled.value) params.enabled = filterEnabled.value === '1'
    if (filterSource.value) params.source = filterSource.value
    if (filterStatus.value) params.status = filterStatus.value
    if (searchKeyword.value.trim()) params.q = searchKeyword.value.trim()
    const res = await request.get('/rules', { params })
    let list = res.data || []
    // HITL / 死规则 为客户端语义筛选（condition._meta 不落在 DB 列）
    if (filterHitl.value) list = list.filter(isHitlRule)
    if (filterDead.value) list = list.filter(isDeadRule)
    // 生效态（effective_active）客户端筛选：单一真值展示
    if (filterEffective.value) {
      const want = filterEffective.value === '1'
      list = list.filter(r => Boolean(r.effective_active) === want)
    }
    rules.value = list
  } catch (error) {
    // handled by interceptor
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

async function handleBulkEnable(enabled) {
  const ids = selectedRows.value.map((r) => r.id)
  if (!ids.length) return
  try {
    await request.put('/rules/bulk-enable', { ids, enabled })
    ElMessage.success(`已${enabled ? '启用' : '禁用'} ${ids.length} 条规则`)
    loadRules()
  } catch (error) {
    // handled by interceptor
  }
}

async function handleReset() {
  try {
    await request.post('/rules/reset')
    ElMessage.success('已重置为默认规则（用户规则保留）')
    loadRules()
  } catch (error) {
    // handled by interceptor (403 非管理员等)
  }
}

function showDetail(rule) {
  currentRule.value = rule
  detailDialogVisible.value = true
}

function showCreateDialog() {
  createForm.name = ''
  createForm.label = ''
  createForm.category = 'process'
  createForm.rule_type = 'regex'
  createForm.engine_type = 'rule_engine'
  createForm.severity = 'medium'
  createForm.description = ''
  createForm.conditionStr = '{}'
  createDialogVisible.value = true
}

/**
 * 从规则中提取 MITRE ATT&CK 编号（T-P2-3 顶层字段优先，兼容 condition 内嵌）.
 * 读取优先级：顶层 mitre_attack → condition._meta.mitre_attack → condition.mitre_attack
 */
function getMitreAttack(rule) {
  if (!rule) return null
  if (rule.mitre_attack) return rule.mitre_attack
  if (!rule.condition) return null
  const cond = typeof rule.condition === 'string'
    ? (() => { try { return JSON.parse(rule.condition) } catch { return {} } })()
    : rule.condition
  if (cond._meta && cond._meta.mitre_attack) {
    return cond._meta.mitre_attack
  }
  if (cond.mitre_attack) {
    return cond.mitre_attack
  }
  return null
}

async function handleCreate() {
  if (!createForm.name) {
    ElMessage.warning('请输入规则名称')
    return
  }
  let condition
  try {
    condition = JSON.parse(createForm.conditionStr)
  } catch (error) {
    ElMessage.error('条件 JSON 格式错误')
    return
  }
  creating.value = true
  try {
    await request.post('/rules', {
      name: createForm.name,
      label: createForm.label || undefined,
      category: createForm.category,
      rule_type: createForm.rule_type,
      engine_type: createForm.engine_type,
      condition,
      severity: createForm.severity,
      description: createForm.description
    })
    ElMessage.success('规则创建成功')
    createDialogVisible.value = false
    loadRules()
  } catch (error) {
    // handled by interceptor
  } finally {
    creating.value = false
  }
}

async function handleToggle(rule, enabled) {
  try {
    await request.put(`/rules/${rule.id}`, { enabled })
    ElMessage.success(`规则已${enabled ? '启用' : '禁用'}`)
  } catch (error) {
    rule.enabled = !enabled
  }
}

async function handleDelete(rule) {
  if (rule.source === 'default') {
    ElMessage.warning('默认规则不可删除，请使用「重置为默认」')
    return
  }
  try {
    await request.delete(`/rules/${rule.id}`)
    ElMessage.success('规则已删除')
    loadRules()
  } catch (error) {
    // handled by interceptor
  }
}

function severityType(severity) {
  const map = {
    critical: 'danger',
    high: 'danger',
    medium: 'warning',
    low: 'primary'
  }
  return map[severity] || 'info'
}

function severityLabel(severity) {
  const map = {
    critical: '严重',
    high: '高危',
    medium: '中危',
    low: '低危'
  }
  return map[severity] || severity
}

// ── 应急运营筛选辅助 ──
const RULE_TYPE_LABELS = {
  regex: '正则匹配',
  list: '列表匹配',
  threshold: '阈值检测',
  behavior: '行为分析',
  composite: '复合规则',
  exists: '存在性检测',
  attack_chain: '攻击链',
  event_log_summary: '事件日志聚合'
}
const SOURCE_LABELS = { default: '内置', user: '用户', ai: 'AI生成', import: '导入' }
const STATUS_LABELS = { active: '生效中', pending_approval: '待审批', deprecated: '已废弃' }
function ruleTypeLabel(t) { return RULE_TYPE_LABELS[t] || t || '-' }
function sourceLabel(s) { return SOURCE_LABELS[s] || s || '-' }
function statusLabel(s) { return STATUS_LABELS[s] || s || '-' }

function isDeadRule(rule) {
  // 后端暂无对应采集器产出的 exists 规则（P3-2 兜底策略）
  if (rule.rule_type !== 'exists') return false
  const meta = rule.condition?._meta || {}
  return rule.enabled === false && !!meta.pending_collector
}
function isHitlRule(rule) {
  return rule.condition?._meta?.requires_hitl === true || rule.status === 'pending_approval'
}

const dynamicCategories = computed(() => {
  const set = new Set(rules.value.map(r => r.category).filter(Boolean))
  return Array.from(set).sort()
})

const severityStats = computed(() => {
  const stats = { critical: 0, high: 0, medium: 0, low: 0 }
  rules.value.forEach(r => { if (stats[r.severity] !== undefined) stats[r.severity]++ })
  return stats
})
const enabledStats = computed(() => ({
  enabled: rules.value.filter(r => r.enabled).length,
  disabled: rules.value.filter(r => !r.enabled).length
}))
const deadRuleCount = computed(() => rules.value.filter(isDeadRule).length)
const hitlRuleCount = computed(() => rules.value.filter(isHitlRule).length)
const effectiveStats = computed(() => {
  const active = rules.value.filter(r => r.effective_active).length
  return { active, inactive: rules.value.length - active }
})

function setSeverityFilter(sev) {
  filterSeverity.value = filterSeverity.value === sev ? '' : sev
  loadRules()
}
function setEnabledFilter(enabled) {
  const val = enabled ? '1' : '0'
  filterEnabled.value = filterEnabled.value === val ? '' : val
  loadRules()
}
function setEffectiveFilter(active) {
  const val = active ? '1' : '0'
  filterEffective.value = filterEffective.value === val ? '' : val
  loadRules()
}
function setDeadFilter() {
  filterDead.value = !filterDead.value
  if (filterDead.value) {
    filterRuleType.value = 'exists'
    filterEnabled.value = '0'
  } else {
    filterRuleType.value = ''
    filterEnabled.value = ''
  }
  loadRules()
}
function setHitlFilter() {
  filterHitl.value = !filterHitl.value
  loadRules()
}
function resetFilters() {
  filterCategory.value = ''
  filterEngineType.value = ''
  filterSeverity.value = ''
  filterRuleType.value = ''
  filterEnabled.value = ''
  filterSource.value = ''
  filterStatus.value = ''
  filterEffective.value = ''
  filterDead.value = false
  filterHitl.value = false
  searchKeyword.value = ''
  loadRules()
}

function renderCondition(rule) {
  const cond = rule?.condition || {}
  const type = rule?.rule_type
  const rows = []
  const meta = cond._meta || {}

  // 通用元信息
  if (meta.mitre_attack) rows.push(['MITRE ATT&CK', meta.mitre_attack])
  if (meta.requires_hitl) rows.push(['人审标记', '是（高危/默认规则变更需审批）'])
  if (meta.pending_collector) rows.push(['待接采集器', meta.pending_collector])
  if (meta.severity_note) rows.push(['严重度说明', meta.severity_note])

  // 按规则类型渲染
  if (type === 'regex') {
    rows.push(['匹配字段', cond.field])
    rows.push(['正则模式', cond.pattern])
    if (cond.flags) rows.push(['模式标志', cond.flags])
  } else if (type === 'list') {
    rows.push(['匹配字段', cond.field])
    rows.push(['匹配方式', cond.match_mode])
    rows.push(['候选值', Array.isArray(cond.values) ? cond.values.join('、') : cond.values])
  } else if (type === 'threshold') {
    rows.push(['检测字段', cond.field])
    rows.push(['阈值条件', `${cond.operator || ''} ${cond.value !== undefined ? cond.value : ''}`])
    if (cond.window) rows.push(['时间窗口', cond.window])
  } else if (type === 'behavior') {
    rows.push(['行为模式', cond.pattern])
    if (cond.baseline) rows.push(['基线', JSON.stringify(cond.baseline)])
  } else if (type === 'composite') {
    rows.push(['逻辑组合', cond.logic])
    rows.push(['子规则数', cond.sub_rules?.length || 0])
  } else if (type === 'exists') {
    rows.push(['存在性字段', cond.field])
  } else if (type === 'attack_chain') {
    rows.push(['链阶段数', cond.chain?.length || 0])
    rows.push(['窗口', cond.window || '—'])
  } else if (type === 'event_log_summary') {
    rows.push(['事件 ID', cond.event_ids?.join('、') || cond.event_id])
    rows.push(['操作符', cond.operator])
    rows.push(['阈值', cond.count])
    if (cond.window) rows.push(['时间窗口', cond.window])
  }

  let html = '<table class="cond-table">'
  rows.forEach(([k, v]) => {
    html += `<tr><td class="cond-k">${k}</td><td class="cond-v">${escapeHtml(String(v ?? '—'))}</td></tr>`
  })
  html += '</table>'
  return html
}

function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
</script>

<style scoped>
/* ── Page Layout ── */
.page-container {
  max-width: 1340px;
  margin: 0 auto;
  padding: 28px 24px;
}

/* ── Header ── */
.page-header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  margin-bottom: 24px;
}
.page-header-left {
  flex: 1;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 20px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.title-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
  font-weight: 500;
}
.page-sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-subtle);
  margin-top: 3px;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ── Metrics ── */
.metrics {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.metric {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-card, 10px);
  padding: 14px 18px;
}
.metric-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.metric-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.metric-dot.blue { background: var(--color-accent-fg); }
.metric-dot.green { background: var(--color-success-fg); }
.metric-dot.amber { background: var(--color-warning-fg); }
.metric-dot.red { background: var(--color-danger-fg); }
.metric-dot.purple { background: #7c3aed; }
.metric-label {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle);
}
.metric-value {
  font-size: 20px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--color-fg-default);
}
.metric-sub {
  font-size: 11px;
  color: var(--color-fg-subtle);
  margin-top: 4px;
}
.metric-sub.up {
  color: var(--color-success-fg);
}

/* ── Card ── */
.card {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-card, 10px);
  overflow: hidden;
}

/* ── Toolbar ── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 14px 20px;
  border-bottom: 0.5px solid var(--color-border-default);
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 12px;
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  width: 260px;
  transition: border-color 0.12s;
}
.search-bar:focus-within {
  border-color: var(--color-accent-fg);
}
.search-bar svg {
  width: 14px;
  height: 14px;
  color: var(--color-fg-light);
  flex-shrink: 0;
}
.search-bar input {
  border: none;
  outline: none;
  flex: 1;
  font-size: 13px;
  background: transparent;
  color: var(--color-fg-default);
}
.search-bar input::placeholder {
  color: var(--color-fg-light);
}
.toolbar-spacer {
  flex: 1;
}

/* ── Select ── */
.select {
  height: 30px;
  padding: 0 30px 0 10px;
  font-size: 12px;
  color: var(--color-fg-default);
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  outline: none;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
}

/* ── Buttons ── */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: var(--r-btn, 6px);
  cursor: pointer;
  transition: all 0.12s;
  white-space: nowrap;
  border: 0.5px solid transparent;
  font-family: inherit;
}
.btn:disabled {
  opacity: 0.4;
  pointer-events: none;
}
.btn-default {
  background: var(--color-canvas-default);
  color: var(--color-fg-default);
  border-color: var(--color-border-default);
}
.btn-default:hover {
  background: var(--color-canvas-subtle);
  border-color: var(--color-fg-light);
}
.btn-primary {
  background: var(--color-accent-fg);
  color: white;
  border-color: var(--color-accent-fg);
}
.btn-primary:hover {
  background: #1d4ed8;
}
.btn-ghost {
  background: transparent;
  color: var(--color-fg-muted);
  border-color: transparent;
}
.btn-ghost:hover {
  background: var(--color-canvas-inset);
}
.btn-danger {
  background: var(--color-canvas-default);
  color: var(--color-danger-fg);
  border-color: var(--color-border-default);
}
.btn-danger:hover {
  background: var(--color-danger-subtle);
  border-color: var(--color-danger-fg);
}
.btn-warning {
  background: var(--color-canvas-default);
  color: var(--color-warning-fg);
  border-color: var(--color-border-default);
}
.btn-warning:hover {
  background: var(--color-warning-subtle);
  border-color: var(--color-warning-fg);
}
.btn-sm {
  height: 26px;
  padding: 0 8px;
  font-size: 11px;
}
.btn svg {
  width: 13px;
  height: 13px;
}

/* ── Badge ── */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 18px;
  padding: 0 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 3px;
  white-space: nowrap;
}
.badge-critical {
  background: var(--color-danger-subtle);
  color: var(--color-danger-fg);
}
.badge-high {
  background: #fef2f2;
  color: #ef4444;
}
.badge-medium {
  background: var(--color-warning-subtle);
  color: var(--color-warning-fg);
}
.badge-low {
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
}
.badge-info {
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
}
.badge-success {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}
.badge-builtin {
  background: #f0f0f0;
  color: #888;
}
.badge-user {
  background: #e0f2fe;
  color: #0369a1;
}
.badge-rule {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  background: #e0f2fe;
  color: #0369a1;
}
.badge-behavior {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  background: #f3e8ff;
  color: #7c3aed;
}

/* ── Severity ── */
.sev {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.sev-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.sev-dot.critical { background: #dc2626; }
.sev-dot.high { background: #ef4444; }
.sev-dot.medium { background: var(--color-warning-fg); }
.sev-dot.low { background: var(--color-accent-fg); }
.sev-text {
  font-size: 12px;
  font-weight: 400;
}
.sev-text.sev-critical { color: #dc2626; font-weight: 500; }
.sev-text.sev-high { color: #ef4444; }
.sev-text.sev-medium { color: var(--color-warning-fg); }
.sev-text.sev-low { color: var(--color-accent-fg); }

/* ── Toggle ── */
.toggle {
  position: relative;
  display: inline-block;
  width: 28px;
  height: 16px;
  cursor: pointer;
}
.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}
.toggle-slider {
  position: absolute;
  inset: 0;
  background: var(--color-border-default);
  border-radius: 999px;
  transition: 0.15s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 2px;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  transition: 0.15s;
}
.toggle input:checked + .toggle-slider {
  background: var(--color-success-fg);
}
.toggle input:checked + .toggle-slider::before {
  transform: translateX(12px);
}

/* ── Bulk Bar ── */
.bulk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: var(--color-accent-subtle);
  border-bottom: 0.5px solid var(--color-border-default);
  font-size: 12px;
  color: var(--color-accent-fg);
}
.bulk-bar span {
  font-weight: 500;
  margin-right: 4px;
}

/* ── Table ── */
.table-wrap {
  overflow: hidden;
}
table {
  width: 100%;
  border-collapse: collapse;
}
thead {
  background: var(--color-canvas-subtle);
}
th {
  padding: 9px 14px;
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  text-align: left;
  white-space: nowrap;
  border-bottom: 0.5px solid var(--color-border-default);
}
td {
  padding: 11px 14px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-default);
  border-bottom: 0.5px solid var(--color-canvas-inset);
  vertical-align: middle;
}
tr:last-child td {
  border-bottom: none;
}
tr:hover td {
  background: var(--color-canvas-subtle);
}
.td-mono {
  font-family: var(--font-mono, 'SF Mono', 'Fira Code', 'Consolas', monospace);
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.td-muted {
  color: var(--color-fg-subtle);
  font-size: 11px;
}

/* ── Rule Name Cell ── */
.rule-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.rule-icon {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: var(--color-canvas-inset);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--color-fg-muted);
}
.rule-icon svg {
  width: 13px;
  height: 13px;
}
.rule-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.rule-en {
  font-size: 12px;
  font-weight: 500;
}
.rule-cn {
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.rule-tags {
  display: flex;
  gap: 3px;
  margin-top: 2px;
  flex-wrap: wrap;
}
.rule-tag {
  font-size: 9px;
  padding: 0 5px;
  height: 15px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
  font-weight: 500;
}

/* ── Description ── */
.desc-cell {
  font-size: 11px;
  color: var(--color-fg-subtle);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Actions ── */
.row-actions {
  display: flex;
  gap: 2px;
}
.icon-btn {
  width: 26px;
  height: 26px;
  border-radius: var(--r-btn, 6px);
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-fg-muted);
  font-family: inherit;
}
.icon-btn:hover {
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
}
.icon-btn.danger:hover {
  color: var(--color-danger-fg);
  background: var(--color-danger-subtle);
}
.icon-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.icon-btn svg {
  width: 13px;
  height: 13px;
}

/* ── Checkbox ── */
.cbx {
  width: 14px;
  height: 14px;
  accent-color: var(--color-accent-fg);
  cursor: pointer;
}

/* ── Pagination ── */
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
}
.pg-info {
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.pg-btns {
  display: flex;
  gap: 3px;
}
.pg-btn {
  min-width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  font-size: 11px;
  color: var(--color-fg-muted);
  cursor: pointer;
  background: var(--color-canvas-default);
  font-family: inherit;
}
.pg-btn:hover {
  border-color: var(--color-fg-light);
}
.pg-btn.active {
  border-color: var(--color-accent-fg);
  color: var(--color-accent-fg);
  font-weight: 500;
  background: var(--color-accent-subtle);
}
.pg-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

/* ── Loading ── */
.loading-overlay {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}
.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--color-border-default);
  border-top-color: var(--color-accent-fg);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ── Empty State ── */
.empty-state {
  text-align: center;
  padding: 32px 0;
  font-size: 13px;
  color: var(--color-fg-light);
}

/* ── Modal ── */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0,0,0,0.18);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}
.modal {
  background: var(--color-canvas-default);
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-container, 12px);
  max-width: 600px;
  width: 100%;
}
.modal-header {
  padding: 18px 22px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-fg-default);
}
.modal-close {
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  color: var(--color-fg-light);
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal-close:hover {
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
}
.modal-body {
  padding: 14px 22px 18px;
}
.modal-footer {
  padding: 10px 22px;
  border-top: 0.5px solid var(--color-border-default);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

/* ── Detail Grid ── */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.detail-item.full {
  grid-column: 1 / -1;
}
.detail-item-label {
  font-size: 10px;
  font-weight: 500;
  color: var(--color-fg-subtle);
  margin-bottom: 3px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.detail-item-value {
  font-size: 12px;
  font-weight: 400;
  color: var(--color-fg-default);
}
.cond-block {
  background: var(--color-canvas-inset);
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  padding: 10px 12px;
  font-family: var(--font-mono, 'SF Mono', 'Fira Code', 'Consolas', monospace);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-x: auto;
  max-height: 240px;
  overflow-y: auto;
}

/* ── Form ── */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.fg {
  margin-bottom: 0;
}
.fl {
  display: block;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-default);
  margin-bottom: 5px;
}
.required {
  color: var(--color-danger-fg);
}
.fi {
  width: 100%;
  height: 30px;
  padding: 0 10px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  font-size: 12px;
  outline: none;
  color: var(--color-fg-default);
  background: var(--color-canvas-default);
}
.fi:focus {
  border-color: var(--color-accent-fg);
}
.fi::placeholder {
  color: var(--color-fg-light);
}
.fs {
  width: 100%;
  height: 30px;
  padding: 0 28px 0 10px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  font-size: 12px;
  color: var(--color-fg-default);
  outline: none;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg width='10' height='6' viewBox='0 0 10 6' fill='none' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M1 1L5 5L9 1' stroke='%23888' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  background-color: var(--color-canvas-default);
  cursor: pointer;
}
.fs:focus {
  border-color: var(--color-accent-fg);
}
.fta {
  width: 100%;
  padding: 8px 10px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  font-size: 11px;
  outline: none;
  resize: vertical;
  font-family: var(--font-mono, 'SF Mono', 'Fira Code', 'Consolas', monospace);
  line-height: 1.5;
  color: var(--color-fg-default);
  background: var(--color-canvas-default);
}
.fta:focus {
  border-color: var(--color-accent-fg);
}
.fta::placeholder {
  color: var(--color-fg-light);
}

/* ── Spinner ── */
.spin {
  animation: spin 0.6s linear infinite;
}

/* ── Quick Stats Chips ── */
.quick-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 20px 0;
  border-bottom: 0.5px solid var(--color-border-default);
}
.qs-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--color-canvas-subtle);
  border: 0.5px solid var(--color-border-default);
  font-size: 11px;
  color: var(--color-fg-default);
  cursor: pointer;
  user-select: none;
  transition: all 0.12s;
}
.qs-chip:hover {
  border-color: var(--color-fg-light);
  background: var(--color-canvas-inset);
}
.qs-chip.active {
  border-color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
  color: var(--color-accent-fg);
}
.qs-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.qs-dot.green { background: var(--color-success-fg); }
.qs-dot.gray { background: var(--color-fg-light); }
.qs-dot.critical { background: #dc2626; }
.qs-dot.high { background: #ef4444; }
.qs-dot.purple { background: #7c3aed; }
.qs-dot.dead { background: var(--color-fg-muted); }

/* ── Condition Readable Table ── */
.cond-readable {
  background: var(--color-canvas-inset);
  border: 0.5px solid var(--color-border-default);
  border-radius: 4px;
  padding: 0;
  overflow: hidden;
}
.cond-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.cond-table td {
  padding: 8px 12px;
  border-bottom: 0.5px solid var(--color-border-default);
  vertical-align: top;
}
.cond-table tr:last-child td {
  border-bottom: none;
}
.cond-k {
  width: 120px;
  color: var(--color-fg-subtle);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.cond-v {
  color: var(--color-fg-default);
  font-family: var(--font-mono, 'SF Mono', 'Fira Code', 'Consolas', monospace);
  word-break: break-all;
}

/* ── Badges extras ── */
.badge-success {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}
.badge-low {
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
}
.badge-warning {
  background: var(--color-warning-subtle);
  color: var(--color-warning-fg);
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
