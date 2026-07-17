<template>
  <div class="report-page">
    <!-- ===== 顶部导航栏 ===== -->
    <div class="page-head">
      <div class="page-head-left">
        <h2>报告输出</h2>
        <span class="page-sub">应急响应报告 · 取证简报 · 合规审计</span>
      </div>
      <div class="page-head-right">
        <el-button size="small" plain @click="loadReports">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <div class="rp-layout">
      <!-- ===== 左侧报告列表 ===== -->
      <div class="rp-sidebar">
        <!-- 头部 -->
        <div class="sb-head">
          <div class="sb-head-left">
            <el-icon :size="16"><Document /></el-icon>
            <span>报告列表</span>
            <el-tag size="small" type="info" round>{{ reports.length }}</el-tag>
          </div>
          <el-button type="primary" size="small" @click="showCreate = true">
            <el-icon :size="14"><Plus /></el-icon>
            新建
          </el-button>
        </div>

        <!-- 搜索 -->
        <div class="sb-search">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索报告标题..."
            size="small"
            clearable
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>

        <!-- 过滤 -->
        <div class="sb-filter">
          <el-radio-group v-model="filterStatus" size="small" @change="loadReports">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="draft">草稿</el-radio-button>
            <el-radio-button value="review">待审</el-radio-button>
            <el-radio-button value="published">已发</el-radio-button>
          </el-radio-group>
        </div>

        <!-- 列表（按主机分组） -->
        <div class="sb-list">
          <!-- 状态过滤后无数据 -->
          <div v-if="!filteredGroupedReports.length && reports.length" class="empty-state">
            <div class="empty-text">该状态下暂无报告</div>
          </div>
          <!-- 完全无报告 -->
          <div v-if="!reports.length" class="empty-state">
            <div class="empty-icon">
              <el-icon :size="32"><Document /></el-icon>
            </div>
            <div class="empty-text">暂无报告</div>
            <div class="empty-hint">选择或创建一份报告开始编辑</div>
            <el-button size="small" type="primary" @click="showCreate = true" style="margin-top: 14px;">
              <el-icon :size="13"><Plus /></el-icon>
              新建报告
            </el-button>
          </div>

          <el-collapse v-model="expandedGroups" v-if="filteredGroupedReports.length">
            <el-collapse-item
              v-for="group in filteredGroupedReports"
              :key="group.host_id"
              :name="String(group.host_id)"
            >
              <template #title>
                <div class="gh-header">
                  <span class="gh-icon">{{ group.host_id === 0 ? '综合' : '主机' }}</span>
                  <span class="gh-hostname">{{ group.hostname || '未命名主机' }}</span>
                  <span class="gh-ip" v-if="group.ip">({{ group.ip }})</span>
                  <el-tag size="small" type="info" round class="gh-count">{{ group.reports.length }}</el-tag>
                  <span class="gh-label" v-if="group.host_id === 0">案件综合</span>
                </div>
              </template>
              <div
                v-for="r in group.reports" :key="r.id"
                :class="['rp-item', { active: selectedId === r.id, hover: hoverId === r.id }]"
                @click="selectReport(r.id)"
                @mouseenter="hoverId = r.id"
                @mouseleave="hoverId = null"
              >
                <!-- 类型色标 -->
                <div class="rp-accent" :style="{ background: typeBorderColor(r.report_type) }"></div>
                <!-- 图标 -->
                <div class="rp-item-icon">{{ reportIcon(r.report_type) }}</div>
                <!-- 主体 -->
                <div class="rp-item-body">
                  <div class="rp-item-top">
                    <div class="rp-item-title" :title="r.title">{{ r.title }}</div>
                    <el-tag size="small" class="rp-aud-tag" round>{{ audienceLabel(r.audience) }}</el-tag>
                  </div>
                  <div class="rp-item-meta">
                    <!-- 状态流程指示 -->
                    <span class="rp-status-flow">
                      <span :class="['sf-dot', { done: r.status !== 'draft' }]"></span>
                      <span class="sf-line"></span>
                      <span :class="['sf-dot', { done: r.status === 'published' }, { current: r.status === 'review' }]"></span>
                      <span class="sf-line"></span>
                      <span :class="['sf-dot', { done: r.status === 'published' }, { current: r.status === 'published' }]"></span>
                    </span>
                    <span class="rp-item-status" :style="{ color: statusColor(r.status) }">
                      {{ statusLabel(r.status) }}
                    </span>
                    <span class="rp-item-date">{{ relativeTime(r.updated_at) }}</span>
                  </div>
                </div>
                <!-- 悬停删除 -->
                <el-button
                  v-if="hoverId === r.id"
                  size="small"
                  type="danger"
                  link
                  @click.stop="handleSidebarDelete(r.id)"
                  class="rp-del-btn"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>

      <!-- ===== 右侧编辑区 ===== -->
      <!-- 有报告选中 -->
      <div class="rp-main" v-if="detail">
        <!-- ── 工具栏卡片 ── -->
        <div class="card toolbar-card">
          <div class="toolbar-row">
            <div class="toolbar-title-row">
              <el-input
                v-model="edit.title"
                placeholder="输入报告标题..."
                size="large"
                class="title-input"
                :class="{ 'title-saved': !dirty && edit.title }"
                @input="markDirty"
              />
              <el-tooltip :content="dirty ? '有未保存的更改' : '已保存'" placement="bottom">
                <el-button
                  :type="dirty ? 'warning' : 'default'"
                  :icon="dirty ? Edit : Check"
                  size="small"
                  :disabled="!dirty"
                  @click="saveDraft"
                  circle
                />
              </el-tooltip>
            </div>
            <!-- 操作按钮组 -->
            <div class="toolbar-actions">
              <el-button size="small" @click="saveDraft" :disabled="!dirty">
                <el-icon :size="14"><Edit /></el-icon>
                保存
              </el-button>
              <el-button
                size="small"
                type="primary"
                :disabled="detail.status !== 'draft'"
                @click="submitReview"
                :loading="submitting"
              >
                <el-icon :size="14"><Upload /></el-icon>
                提交审核
              </el-button>
              <el-button
                size="small"
                :disabled="detail.status !== 'draft'"
                @click="showRegenerate = true"
              >
                <el-icon :size="14"><Refresh /></el-icon>
                重新生成草稿
              </el-button>
              <el-button
                size="small"
                type="success"
                :disabled="detail.status !== 'review'"
                @click="showPublish = true"
              >
                <el-icon :size="14"><Select /></el-icon>
                发布
              </el-button>
              <el-dropdown trigger="click" @command="handleExport">
                <el-button size="small">
                  <el-icon :size="14"><Download /></el-icon>
                  导出
                  <el-icon :size="12"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="pdf">导出 PDF（技术版）</el-dropdown-item>
                    <el-dropdown-item command="html">导出 PDF（管理版）</el-dropdown-item>
                    <el-dropdown-item command="docx" divided>导出 DOCX</el-dropdown-item>
                    <el-dropdown-item command="markdown">导出 Markdown</el-dropdown-item>
                    <el-dropdown-item command="json">导出 JSON</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-popconfirm
                title="确定删除此报告？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                @confirm="deleteReport"
              >
                <template #reference>
                  <el-button size="small" type="danger" plain>
                    <el-icon :size="14"><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
          <!-- 元信息栏 -->
          <div class="toolbar-meta">
            <div class="meta-left">
              <span class="meta-badge">
                状态：<el-tag size="small" :type="statusType(detail.status)" effect="dark">
                  {{ statusLabel(detail.status) }}
                </el-tag>
              </span>
              <span class="meta-badge">
                类型：<el-tag size="small">{{ typeLabel(detail.report_type) }}</el-tag>
              </span>
              <span class="meta-badge">
                读者：<el-tag size="small">{{ audienceLabel(detail.audience) }}</el-tag>
              </span>
            </div>
            <div class="meta-right">
              <span class="meta-time">创建：{{ detail.created_at?.slice(0, 16) }}</span>
              <span class="meta-time">更新：{{ detail.updated_at?.slice(0, 16) }}</span>
              <span v-if="savedAt" class="meta-time saved-indicator">
                <el-icon :size="12"><Check /></el-icon>
                {{ savedAt }}
              </span>
            </div>
          </div>
        </div>

        <!-- ── 7 段折叠式编辑器 ── -->
        <el-collapse v-model="activeSections" accordion class="editor-collapse">
          <!-- ① 概要 -->
          <el-collapse-item name="summary">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-summary" />
                <span class="section-name">概要</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('summary')) }" v-if="detail">{{ confidenceBar('summary') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.summary?.length">
                  {{ edit.summary.length }} 字
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <el-input
                v-model="edit.summary"
                type="textarea"
                :rows="6"
                placeholder="描述安全事件的核心概要信息，包括事件类型、发生时间、影响程度等关键要点..."
                @input="markDirty"
                maxlength="2000"
                show-word-limit
              />
            </div>
          </el-collapse-item>

          <!-- ② 影响范围 -->
          <el-collapse-item name="impact">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-impact" />
                <span class="section-name">影响范围</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('impact_scope')) }" v-if="detail">{{ confidenceBar('impact_scope') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.impactScope?.affected_systems?.length">
                  {{ edit.impactScope.affected_systems.length }} 个系统
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <div class="section-field">
                <label class="field-label">影响范围类型</label>
                <el-radio-group v-model="edit.impactScope.scope_type" @change="markDirty">
                  <el-radio value="internal">内部网络</el-radio>
                  <el-radio value="external">外部服务</el-radio>
                  <el-radio value="both">内部 + 外部</el-radio>
                </el-radio-group>
              </div>
              <div class="section-field">
                <label class="field-label">受影响系统</label>
                <el-select
                  v-model="edit.impactScope.affected_systems"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入系统名称后回车添加"
                  style="width: 100%"
                  @change="markDirty"
                >
                  <el-option
                    v-for="sys in commonSystems"
                    :key="sys"
                    :label="sys"
                    :value="sys"
                  />
                </el-select>
              </div>
              <div class="section-field">
                <label class="field-label">业务影响分析</label>
                <el-input
                  v-model="edit.impactScope.business_impact"
                  type="textarea"
                  :rows="3"
                  placeholder="描述对业务运营、数据机密性/完整性/可用性的影响..."
                  @input="markDirty"
                />
              </div>
              <div class="section-field">
                <label class="field-label">经济损失估算</label>
                <el-input
                  v-model="edit.impactScope.financial_estimate"
                  placeholder="如：¥50,000-¥100,000 或 待评估"
                  @input="markDirty"
                />
              </div>
            </div>
          </el-collapse-item>

          <!-- ③ 时间线 -->
          <el-collapse-item name="timeline">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-timeline" />
                <span class="section-name">时间线</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('timeline')) }" v-if="detail">{{ confidenceBar('timeline') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.timeline.length">
                  {{ edit.timeline.length }} 个事件
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <div
                v-for="(evt, idx) in edit.timeline"
                :key="evt._key"
                class="tl-event"
              >
                <div class="tl-event-bar">
                  <span class="tl-index">{{ idx + 1 }}</span>
                  <span class="tl-connector" />
                </div>
                <div class="tl-event-body">
                  <div class="tl-event-row">
                    <el-date-picker
                      v-model="evt.time"
                      type="datetime"
                      placeholder="事件时间"
                      size="small"
                      style="width: 180px"
                      value-format="YYYY-MM-DD HH:mm"
                      @change="markDirty"
                    />
                    <el-select
                      v-model="evt.severity"
                      size="small"
                      style="width: 100px"
                      placeholder="级别"
                      @change="markDirty"
                    >
                      <el-option label="严重" value="critical" />
                      <el-option label="高危" value="high" />
                      <el-option label="中危" value="medium" />
                      <el-option label="低危" value="low" />
                      <el-option label="信息" value="info" />
                    </el-select>
                    <el-button
                      size="small"
                      type="danger"
                      link
                      :icon="Delete"
                      @click="removeTimelineEvent(idx)"
                    />
                  </div>
                  <el-input
                    v-model="evt.event"
                    placeholder="事件名称"
                    size="small"
                    style="margin-top: 6px"
                    @input="markDirty"
                  />
                  <el-input
                    v-model="evt.description"
                    type="textarea"
                    :rows="2"
                    placeholder="事件描述"
                    style="margin-top: 6px"
                    @input="markDirty"
                  />
                </div>
              </div>
              <el-button
                size="small"
                class="tl-add-btn"
                @click="addTimelineEvent"
              >
                <el-icon :size="14"><Plus /></el-icon>
                添加事件
              </el-button>
            </div>
          </el-collapse-item>

          <!-- ④ MITRE 战术覆盖 -->
          <el-collapse-item name="mitre">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-mitre" />
                <span class="section-name">MITRE ATT&CK 战术覆盖</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('mitre')) }" v-if="detail">{{ confidenceBar('mitre') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.mitreTactics.length">
                  已选 {{ edit.mitreTactics.length }}
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <div class="mitre-grid">
                <label
                  v-for="t in MITRE_TACTICS"
                  :key="t.id"
                  :class="['mitre-item', { active: edit.mitreTactics.includes(t.id) }]"
                >
                  <el-checkbox
                    v-model="edit.mitreTactics"
                    :label="t.id"
                    :value="t.id"
                    @change="markDirty"
                  >
                    <span class="mitre-id">{{ t.id }}</span>
                    <span class="mitre-name">{{ t.name }}</span>
                  </el-checkbox>
                </label>
              </div>
            </div>
          </el-collapse-item>

          <!-- ⑤ 证据 -->
          <el-collapse-item name="evidence">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-evidence" />
                <span class="section-name">证据</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('evidence')) }" v-if="detail">{{ confidenceBar('evidence') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.evidence?.length">
                  {{ edit.evidence.length }} 字
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <el-input
                v-model="edit.evidence"
                type="textarea"
                :rows="8"
                placeholder="记录取证发现、日志片段、文件哈希、网络连接等关键证据..."
                @input="markDirty"
                maxlength="5000"
                show-word-limit
              />
              <div class="section-tip">
                <el-icon :size="14"><InfoFilled /></el-icon>
                提示：详细的取证数据可在主机分析的"证据" Tab 中查看，此处仅记录关键摘要
              </div>
            </div>
          </el-collapse-item>

          <!-- ⑥ 建议措施 -->
          <el-collapse-item name="recommendations">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-rec" />
                <span class="section-name">建议措施</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('recommendations')) }" v-if="detail">{{ confidenceBar('recommendations') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="edit.recommendations.length">
                  {{ doneCount }}/{{ edit.recommendations.length }}
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <div class="rec-list">
                <div
                  v-for="(item, idx) in edit.recommendations"
                  :key="item._key"
                  class="rec-item"
                >
                  <el-checkbox
                    v-model="item.checked"
                    @change="markDirty"
                    :class="{ 'rec-done': item.checked }"
                  />
                  <el-input
                    v-model="item.text"
                    placeholder="输入处置措施..."
                    :class="{ 'rec-text-done': item.checked }"
                    @input="markDirty"
                  />
                  <el-select
                    v-model="item.priority"
                    size="small"
                    style="width: 110px; flex-shrink: 0"
                    @change="markDirty"
                  >
                    <el-option label="紧急 / P0" value="high" />
                    <el-option label="短期 / P1" value="medium" />
                    <el-option label="长期 / P2" value="low" />
                  </el-select>
                  <span class="priority-badge" :class="item.priority">
                    {{ item.priority === 'high' ? 'P0' : item.priority === 'medium' ? 'P1' : 'P2' }}
                  </span>
                  <el-button
                    size="small"
                    type="danger"
                    link
                    :icon="Delete"
                    @click="removeRec(idx)"
                  />
                </div>
              </div>
              <el-button size="small" @click="addRec">
                <el-icon :size="14"><Plus /></el-icon>
                添加措施
              </el-button>
            </div>
          </el-collapse-item>

          <!-- ⑦ 协作评论 -->
          <el-collapse-item name="collaboration">
            <template #title>
              <div class="section-header">
                <span class="section-dot dot-collab" />
                <span class="section-name">协作评论</span>
                <span class="conf-bar" :style="{ color: confidenceColor(getConfidenceScore('collaboration')) }" v-if="detail">{{ confidenceBar('collaboration') }}</span>
                <el-tag size="small" type="info" effect="plain" v-if="comments.length">
                  {{ comments.length }}
                </el-tag>
                <span class="sec-arr">&#9654;</span>
              </div>
            </template>
            <div class="section-body">
              <div class="comment-list" v-if="comments.length">
                <div v-for="(c, idx) in comments" :key="idx" class="comment-item">
                  <div class="comment-avatar">{{ c.author?.charAt(0) || '?' }}</div>
                  <div class="comment-content">
                    <div class="comment-header">
                      <span class="comment-author">{{ c.author || '匿名' }}</span>
                      <span class="comment-time">{{ c.time }}</span>
                    </div>
                    <div class="comment-text">{{ c.text }}</div>
                  </div>
                </div>
              </div>
              <div v-else class="comment-empty">
                <div class="comment-empty">暂无评论</div>
              </div>
              <div class="comment-input-row">
                <el-input
                  v-model="newComment"
                  placeholder="输入评论内容..."
                  size="small"
                  @keyup.enter="addComment"
                />
                <el-button size="small" type="primary" @click="addComment" :disabled="!newComment.trim()">
                  发送
                </el-button>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- AI 分析质量信息卡片 -->
        <div class="card ai-quality-card" v-if="aiQualityStats">
          <div class="aiq-header">
            <el-icon :size="16"><InfoFilled /></el-icon>
            <span>AI 分析质量</span>
          </div>
          <div class="aiq-body">
            <div class="aiq-stat">
              <span class="aiq-label">平均置信度</span>
              <span class="aiq-value" :style="{ color: confidenceColor(Number(aiQualityStats.avg)) }">{{ aiQualityStats.avg }}</span>
            </div>
            <div class="aiq-stat">
              <span class="aiq-label">最高</span>
              <span class="aiq-value" :style="{ color: confidenceColor(aiQualityStats.max) }">{{ aiQualityStats.max }}</span>
            </div>
            <div class="aiq-stat">
              <span class="aiq-label">最低</span>
              <span class="aiq-value" :style="{ color: confidenceColor(aiQualityStats.min) }">{{ aiQualityStats.min }}</span>
            </div>
            <div class="aiq-stat">
              <span class="aiq-label">高质量 (≥90)</span>
              <span class="aiq-value" style="color: #67c23a">{{ aiQualityStats.high }}</span>
            </div>
            <div class="aiq-stat">
              <span class="aiq-label">中等 (70-89)</span>
              <span class="aiq-value" style="color: #409eff">{{ aiQualityStats.medium }}</span>
            </div>
            <div class="aiq-stat">
              <span class="aiq-label">待改进 (&lt;70)</span>
              <span class="aiq-value" style="color: #e6a23c">{{ aiQualityStats.low }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 未选报告空状态 -->
      <div class="rp-main rp-main-empty" v-else>
        <div class="empty-state">
          <div class="empty-icon">
            <el-icon :size="36"><Document /></el-icon>
          </div>
          <div class="empty-text">选择或创建一份报告开始编辑</div>
          <el-button size="small" type="primary" @click="showCreate = true" style="margin-top: 14px;">
            <el-icon :size="13"><Plus /></el-icon>
            新建报告
          </el-button>
        </div>
      </div>
    </div>

    <!-- ===== 新建报告对话框 ===== -->
    <el-dialog v-model="showCreate" title="新建报告" width="480px" destroy-on-close>
      <el-form label-position="top" size="small">
        <el-form-item label="报告标题">
          <el-input v-model="createForm.title" placeholder="输入报告标题" />
        </el-form-item>
        <el-form-item label="报告类型">
          <el-select v-model="createForm.report_type" style="width: 100%">
            <el-option label="应急响应报告" value="emergency" />
            <el-option label="取证分析简报" value="forensic" />
            <el-option label="合规审计报告" value="compliance" />
            <el-option label="安全态势报告" value="situation" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标读者">
          <el-select v-model="createForm.audience" style="width: 100%">
            <el-option label="管理层" value="leader" />
            <el-option label="技术人员" value="technical" />
            <el-option label="客户" value="client" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="showCreate = false">取消</el-button>
        <el-button size="small" type="primary" @click="createReport" :loading="creating">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== 发布对话框 ===== -->
    <el-dialog v-model="showPublish" title="发布确认" width="420px">
      <div class="publish-warn">
        <el-icon :size="20" color="#d97706"><WarningFilled /></el-icon>
        <span>发布后报告将进入"已发布"状态，内容锁定不可直接编辑。</span>
      </div>
      <el-form label-position="top" size="small" class="publish-form">
        <el-form-item label="报告级别">
          <el-radio-group v-model="publishLevel">
            <el-radio value="executive">管理层摘要</el-radio>
            <el-radio value="technical">技术详细报告</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button size="small" @click="showPublish = false">取消</el-button>
        <el-button size="small" type="success" @click="confirmPublish" :loading="publishing">
          确认发布
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== 增量更新对话框 ===== -->
    <el-dialog v-model="showRegenerate" title="重新生成草稿" width="500px" destroy-on-close>
      <div class="reg-hint">
        <el-icon :size="18" color="#409eff"><InfoFilled /></el-icon>
        <span>将使用最新的 AI 分析结果重新填充报告内容。</span>
      </div>
      <el-radio-group v-model="regenerateMode" style="margin-top: 12px; display: flex; flex-direction: column; gap: 8px;">
        <el-radio value="all">全部段落（完整替换）</el-radio>
        <el-radio value="partial">仅更新所选段落</el-radio>
      </el-radio-group>

      <div class="reg-sections" v-if="regenerateMode === 'partial'">
        <div class="reg-section-title">选择要更新的段落：</div>
        <el-checkbox-group v-model="regenerateSections">
          <div
            v-for="sec in REGENERATE_SECTIONS"
            :key="sec.key"
            class="reg-section-item"
          >
            <el-checkbox :label="sec.key" :value="sec.key">
              <span class="reg-sec-name">{{ sec.label }}</span>
              <span
                class="reg-sec-score"
                :style="{ color: confidenceColor(getConfidenceScore(sec.confKey)) }"
              >
                {{ getConfidenceScore(sec.confKey) !== null ? getConfidenceScore(sec.confKey) + ' 分' : '—' }}
              </span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
      </div>

      <template #footer>
        <el-button size="small" @click="showRegenerate = false">取消</el-button>
        <el-button size="small" type="primary" @click="confirmRegenerate" :loading="regenerating">
          确认生成
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== 版本差异对比面板 ===== -->
    <el-dialog v-model="showDiff" title="版本差异对比" width="680px" top="5vh" destroy-on-close>
      <div class="diff-summary" v-if="diffData">
        <span class="diff-stat diff-changed">变更 {{ diffData.changed?.length || 0 }}</span>
        <span class="diff-stat diff-added">新增 {{ diffData.added?.length || 0 }}</span>
        <span class="diff-stat diff-removed">移除 {{ diffData.removed?.length || 0 }}</span>
      </div>

      <div class="diff-list" v-if="diffData">
        <!-- 变更 -->
        <div v-if="diffData.changed?.length" class="diff-group">
          <div class="diff-group-title">变更的段落</div>
          <div v-for="item in diffData.changed" :key="item.section" class="diff-item diff-item-changed">
            <div class="diff-section-label">{{ sectionLabel(item.section) }}</div>
            <div class="diff-compare">
              <div class="diff-side diff-old">
                <div class="diff-side-title">旧版本</div>
                <div class="diff-side-content">{{ item.old }}</div>
              </div>
              <div class="diff-vs">
                <el-icon :size="20" color="#409eff"><Refresh /></el-icon>
              </div>
              <div class="diff-side diff-new">
                <div class="diff-side-title">新版本</div>
                <div class="diff-side-content">{{ item.new }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 新增 -->
        <div v-if="diffData.added?.length" class="diff-group">
          <div class="diff-group-title">新增的段落</div>
          <div v-for="item in diffData.added" :key="item.section" class="diff-item diff-item-added">
            <div class="diff-section-label">{{ sectionLabel(item.section) }}</div>
            <div class="diff-side-content">{{ item.content }}</div>
          </div>
        </div>

        <!-- 移除 -->
        <div v-if="diffData.removed?.length" class="diff-group">
          <div class="diff-group-title">移除的段落</div>
          <div v-for="item in diffData.removed" :key="item.section" class="diff-item diff-item-removed">
            <div class="diff-section-label">{{ sectionLabel(item.section) }}</div>
            <div class="diff-side-content">{{ item.content }}</div>
          </div>
        </div>
      </div>

      <div v-else class="diff-empty">
        <div class="diff-empty">暂无差异数据</div>
      </div>

      <template #footer>
        <el-button size="small" @click="showDiff = false">关闭</el-button>
        <el-button size="small" type="primary" @click="acceptNewVersion">采纳新版本</el-button>
        <el-button size="small" type="success" @click="editAndSave">手动编辑后保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, Document, Plus, Search, Edit, Check,
  Upload, Select, Download, ArrowDown, Delete,
  InfoFilled, WarningFilled
} from '@element-plus/icons-vue'
import incidentReportApi from '@/api/incidentReport'

// ── MITRE ATT&CK 战术列表 ──
const MITRE_TACTICS = [
  { id: 'TA0001', name: '初始访问' },
  { id: 'TA0002', name: '执行' },
  { id: 'TA0003', name: '持久化' },
  { id: 'TA0004', name: '权限提升' },
  { id: 'TA0005', name: '防御规避' },
  { id: 'TA0006', name: '凭据访问' },
  { id: 'TA0007', name: '发现' },
  { id: 'TA0008', name: '横向移动' },
  { id: 'TA0009', name: '收集' },
  { id: 'TA0010', name: '命令与控制' },
  { id: 'TA0011', name: '数据渗出' },
  { id: 'TA0040', name: '影响' },
]

const commonSystems = [
  '域控服务器', '邮件服务器', '文件服务器', 'Web 服务器',
  '数据库服务器', 'ERP 系统', 'OA 系统', '堡垒机',
  '终端用户设备', '网络设备', '安全设备',
]

// ── 响应式状态 ──
const reports = ref([])
const groupedReports = ref([])
const expandedGroups = ref([])
const selectedId = ref(null)
const detail = ref(null)
const searchKeyword = ref('')
const filterStatus = ref('all')
const dirty = ref(false)
const loading = ref(false)
const submitting = ref(false)
const publishing = ref(false)
const creating = ref(false)
const savedAt = ref('')

// 新建对话框
const showCreate = ref(false)
const createForm = reactive({
  title: '',
  report_type: 'emergency',
  audience: 'leader',
})

// 发布对话框
const showPublish = ref(false)
const publishLevel = ref('technical')

// 增量更新对话框
const showRegenerate = ref(false)
const regenerateMode = ref('all')
const regenerateSections = ref([])
const regenerating = ref(false)

const REGENERATE_SECTIONS = [
  { key: 'summary', confKey: 'summary', label: '概要' },
  { key: 'impact_scope', confKey: 'impact_scope', label: '影响范围' },
  { key: 'timeline', confKey: 'timeline', label: '时间线' },
  { key: 'mitre', confKey: 'mitre', label: 'MITRE 战术覆盖' },
  { key: 'evidence', confKey: 'evidence', label: '证据' },
  { key: 'recommendations', confKey: 'recommendations', label: '建议措施' },
]

// 版本差异对比
const showDiff = ref(false)
const diffData = ref(null)

// 编辑态（展开的 section）
const activeSections = ref('summary')

// 编辑数据模型
const edit = reactive({
  title: '',
  summary: '',
  impactScope: { scope_type: 'internal', affected_systems: [], business_impact: '', financial_estimate: '' },
  timeline: [],
  mitreTactics: [],
  evidence: '',
  recommendations: [],
})

// 协作评论
const comments = ref([])
const newComment = ref('')

// ── 计算属性 ──
const filteredReports = computed(() => {
  let list = reports.value
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    list = list.filter(r => r.title?.toLowerCase().includes(kw))
  }
  return list
})

// 按主机分组且支持搜索过滤（用于左侧树形展示）
const filteredGroupedReports = computed(() => {
  if (!searchKeyword.value) return groupedReports.value
  const kw = searchKeyword.value.toLowerCase()
  return groupedReports.value.map(group => {
    const filtered = group.reports.filter(r => r.title?.toLowerCase().includes(kw))
    return { ...group, reports: filtered }
  }).filter(g => g.reports.length > 0)
})

const doneCount = computed(() => edit.recommendations.filter(i => i.checked).length)

// 悬停状态
const hoverId = ref(null)

// ── 工具函数 ──
let _keyCounter = 0
function uid() { return `_k${++_keyCounter}` }

function reportIcon(type) {
  const icons = { emergency: '应', forensic: '证', compliance: '审', situation: '势' }
  return icons[type] || '报'
}

function statusType(status) {
  const map = { draft: 'info', review: 'warning', published: 'success' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { draft: '草稿', review: '待审核', published: '已发布' }
  return map[status] || status
}

function relativeTime(dateStr) {
  if (!dateStr) return ''
  const now = Date.now()
  const d = new Date(dateStr).getTime()
  const diff = now - d
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return mins + '分钟前'
  const hours = Math.floor(mins / 60)
  if (hours < 24) return hours + '小时前'
  const days = Math.floor(hours / 24)
  if (days < 30) return days + '天前'
  return dateStr.slice(0, 10)
}

function typeBorderColor(type) {
  const map = { emergency: '#f56c6c', forensic: '#e6a23c', compliance: '#409eff', situation: '#67c23a' }
  return map[type] || '#909399'
}

function typeBgColor(type) {
  const map = { emergency: '#fef0f0', forensic: '#fdf6ec', compliance: '#ecf5ff', situation: '#f0f9eb' }
  return map[type] || '#f4f4f5'
}

function statusColor(status) {
  const map = { draft: '#909399', review: '#e6a23c', published: '#67c23a' }
  return map[status] || '#909399'
}

function typeLabel(type) {
  const map = { emergency: '应急响应', forensic: '取证分析', compliance: '合规审计', situation: '安全态势' }
  return map[type] || type
}

function audienceLabel(aud) {
  const map = { leader: '管理层', technical: '技术人员', client: '客户' }
  return map[aud] || aud
}

function sectionLabel(key) {
  const map = {
    summary: '概要',
    impact_scope: '影响范围',
    timeline: '时间线',
    mitre: 'MITRE 战术覆盖',
    evidence: '证据',
    recommendations: '建议措施',
    collaboration: '协作评论'
  }
  return map[key] || key
}

// ── AI 置信度辅助 ──
function getConfidenceScore(sectionKey) {
  const raw = detail.value?.confidence_metadata || detail.value?.ai_confidence
  if (!raw) return null
  const conf = typeof raw === 'string'
    ? parseJsonField(raw, {})
    : raw
  return conf[sectionKey] ?? null
}

function confidenceColor(score) {
  if (score === null || score === undefined) return '#d1d5db'
  if (score >= 90) return '#67c23a'
  if (score >= 70) return '#409eff'
  if (score >= 40) return '#e6a23c'
  return '#f56c6c'
}

function confidenceBar(sectionKey) {
  const score = getConfidenceScore(sectionKey)
  if (score === null) return ''
  const filled = score >= 90 ? 7 : score >= 70 ? 6 : score >= 40 ? 4 : 2
  const empty = 7 - filled
  return '█'.repeat(filled) + '░'.repeat(empty)
}

const SECTION_KEYS = {
  summary: 'summary',
  impact: 'impact_scope',
  timeline: 'timeline',
  mitre: 'mitre',
  evidence: 'evidence',
  recommendations: 'recommendations',
  collaboration: 'collaboration'
}

// AI 分析质量统计数据
const aiQualityStats = computed(() => {
  const raw = detail.value?.confidence_metadata || detail.value?.ai_confidence
  if (!raw) return null
  const conf = typeof raw === 'string'
    ? parseJsonField(raw, {})
    : raw
  const scores = Object.values(conf).filter(v => typeof v === 'number')
  if (!scores.length) return null
  const avg = (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1)
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const high = scores.filter(s => s >= 90).length
  const medium = scores.filter(s => s >= 70 && s < 90).length
  const low = scores.filter(s => s < 70).length
  return { avg, min, max, high, medium, low, total: scores.length }
})

// ── 数据序列化 / 反序列化 ──
function parseJsonField(val, fallback) {
  if (!val) return fallback
  try { return JSON.parse(val) } catch { return fallback }
}

function loadDetailIntoEdit(d) {
  edit.title = d.title || ''
  edit.summary = d.summary || ''
  edit.impactScope = parseJsonField(d.impact_scope, { scope_type: 'internal', affected_systems: [], business_impact: '', financial_estimate: '' })
  edit.timeline = (parseJsonField(d.timeline_json, [])).map(e => ({ ...e, _key: uid() }))
  edit.mitreTactics = parseJsonField(d.mitre_cover, [])
  edit.evidence = d.evidence || ''
  edit.recommendations = (parseJsonField(d.recommendations, { items: [] }).items || []).map(r => ({ ...r, _key: uid() }))
  dirty.value = false
}

function buildUpdatePayload() {
  const payload = { title: edit.title }
  if (edit.summary !== (detail.value?.summary || '')) payload.summary = edit.summary
  if (edit.evidence !== (detail.value?.evidence || '')) payload.evidence = edit.evidence

  const newImpact = JSON.stringify(edit.impactScope)
  if (newImpact !== (detail.value?.impact_scope || '{}')) payload.impact_scope = newImpact

  const newTimeline = JSON.stringify(edit.timeline.map(({ _key, ...rest }) => rest))
  if (newTimeline !== (detail.value?.timeline_json || '[]')) payload.timeline_json = newTimeline

  const newMitre = JSON.stringify(edit.mitreTactics)
  if (newMitre !== (detail.value?.mitre_cover || '[]')) payload.mitre_cover = newMitre

  const newRecs = JSON.stringify({ items: edit.recommendations.map(({ _key, ...rest }) => rest) })
  const oldRecs = detail.value?.recommendations || '{}'
  if (newRecs !== oldRecs) payload.recommendations = newRecs

  return payload
}

// ── CRUD 操作 ──
async function loadReports() {
  loading.value = true
  try {
    const res = await incidentReportApi.list(filterStatus.value)
    console.log('[loadReports] res =', res)
    if (res?.success) {
      reports.value = res.data?.items || []
      console.log('[loadReports] set', reports.value.length, 'items')
    } else {
      console.warn('[loadReports] res?.success is falsy', res)
    }
    // 同时加载分组数据
    await fetchGroupedReports()
  } catch (e) {
    console.error('[loadReports] error', e)
    if (!reports.value.length) {
      ElMessage.error('加载报告列表失败')
    }
  } finally {
    loading.value = false
  }
}

async function fetchGroupedReports() {
  try {
    const res = await incidentReportApi.listGroupedByHost(filterStatus.value)
    if (res?.success) {
      const groups = res.data?.groups || []
      groupedReports.value = groups

      // 自动展开：最新草稿所在分组，以及 host_id=0 的案件综合分组
      const toExpand = new Set()
      // 找到最新草稿所在 host_id
      let latestDraftHostId = null
      let latestTime = ''
      for (const g of groups) {
        for (const r of g.reports) {
          if (r.status === 'draft' && (!latestTime || r.updated_at > latestTime)) {
            latestTime = r.updated_at
            latestDraftHostId = g.host_id
          }
        }
      }
      if (latestDraftHostId !== null) toExpand.add(String(latestDraftHostId))
      // host_id=0 的案件综合分组始终可见
      const caseGroup = groups.find(g => g.host_id === 0)
      if (caseGroup) toExpand.add('0')

      expandedGroups.value = Array.from(toExpand)
    }
  } catch (e) {
    console.error('[fetchGroupedReports] error', e)
  }
}

async function selectReport(id) {
  if (dirty.value) {
    try { await saveDraft() } catch { /* ignore */ }
  }
  selectedId.value = id
  try {
    const res = await incidentReportApi.get(id)
    if (res?.success) {
      detail.value = res.data
      comments.value = []
      loadDetailIntoEdit(detail.value)
      activeSections.value = 'summary'
    }
  } catch (e) {
    ElMessage.error('加载报告详情失败')
    detail.value = null
  }
}

async function saveDraft() {
  if (!selectedId.value || !dirty.value) return
  try {
    const payload = buildUpdatePayload()
    const res = await incidentReportApi.update(selectedId.value, payload)
    if (res?.success) {
      dirty.value = false
      savedAt.value = new Date().toLocaleTimeString()
      // 刷新详情
      const detailRes = await incidentReportApi.get(selectedId.value)
      if (detailRes?.success) {
        detail.value = detailRes.data
        loadDetailIntoEdit(detail.value)
      }
      // 刷新列表
      await loadReports()
      ElMessage.success('保存成功')
    }
  } catch (e) {
    ElMessage.error('保存失败')
    throw e
  }
}

async function submitReview() {
  if (!selectedId.value) return
  submitting.value = true
  try {
    const res = await incidentReportApi.submit(selectedId.value)
    if (res?.success) {
      ElMessage.success('已提交审核')
      await selectReport(selectedId.value)
      await loadReports()
    }
  } catch (e) {
    ElMessage.error('提交审核失败')
  } finally {
    submitting.value = false
  }
}

async function confirmPublish() {
  if (!selectedId.value) return
  publishing.value = true
  try {
    const res = await incidentReportApi.publish(selectedId.value)
    if (res?.success) {
      showPublish.value = false
      ElMessage.success('报告已发布')
      await selectReport(selectedId.value)
      await loadReports()
    }
  } catch (e) {
    ElMessage.error('发布失败')
  } finally {
    publishing.value = false
  }
}

async function confirmRegenerate() {
  if (!selectedId.value) return
  regenerating.value = true
  try {
    const sections = regenerateMode.value === 'all' ? null : regenerateSections.value
    const res = await incidentReportApi.regenerateFromAi(selectedId.value, sections)
    if (res?.success) {
      showRegenerate.value = false
      ElMessage.success('草稿已重新生成')
      await selectReport(selectedId.value)
      await loadReports()
      // 生成成功后自动弹出差异对比面板
      await fetchDiff()
    }
  } catch (e) {
    ElMessage.error('重新生成失败')
  } finally {
    regenerating.value = false
  }
}

async function fetchDiff() {
  if (!selectedId.value) return
  try {
    const res = await incidentReportApi.diffReport(selectedId.value)
    if (res?.success) {
      diffData.value = res.data
      showDiff.value = true
    }
  } catch (e) {
    console.error('[fetchDiff] error', e)
  }
}

async function acceptNewVersion() {
  // 采纳新版本：重新加载详情即可
  showDiff.value = false
  ElMessage.success('已采纳新版本')
  await selectReport(selectedId.value)
}

async function editAndSave() {
  // 关闭对比面板，让用户手动编辑后保存
  showDiff.value = false
  ElMessage.info('请检查并编辑内容后手动保存')
}

async function deleteReport() {
  if (!selectedId.value) return
  try {
    const res = await incidentReportApi.remove(selectedId.value)
    if (res?.success) {
      ElMessage.success('报告已删除')
      detail.value = null
      selectedId.value = null
      Object.assign(edit, { title: '', summary: '', evidence: '' })
      await loadReports()
    }
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

async function handleSidebarDelete(id) {
  try {
    const res = await incidentReportApi.remove(id)
    if (res?.success) {
      if (selectedId.value === id) {
        detail.value = null
        selectedId.value = null
        Object.assign(edit, { title: '', summary: '', evidence: '' })
      }
      await loadReports()
      ElMessage.success('报告已删除')
    }
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

async function createReport() {
  if (!createForm.title.trim()) {
    ElMessage.warning('请输入报告标题')
    return
  }
  creating.value = true
  try {
    const res = await incidentReportApi.create({
      title: createForm.title,
      report_type: createForm.report_type,
      audience: createForm.audience,
      created_by: '当前用户',
    })
    if (res?.success) {
      showCreate.value = false
      ElMessage.success('报告创建成功')
      createForm.title = ''
      await loadReports()
      await nextTick()
      await selectReport(res.data.id)
    }
  } catch (e) {
    ElMessage.error('创建失败')
  } finally {
    creating.value = false
  }
}

// ── 编辑操作 ──
function markDirty() {
  dirty.value = true
}

// 时间线
function addTimelineEvent() {
  edit.timeline.push({
    _key: uid(),
    time: '',
    event: '',
    description: '',
    severity: 'medium',
  })
  markDirty()
}

function removeTimelineEvent(idx) {
  edit.timeline.splice(idx, 1)
  markDirty()
}

// 建议措施
function addRec() {
  edit.recommendations.push({ _key: uid(), text: '', checked: false, priority: 'medium' })
  markDirty()
}

function removeRec(idx) {
  edit.recommendations.splice(idx, 1)
  markDirty()
}

// 协作评论
function addComment() {
  const text = newComment.value.trim()
  if (!text) return
  comments.value.push({
    author: '当前用户',
    text,
    time: new Date().toLocaleString(),
  })
  newComment.value = ''
}

// 导出
function downloadExport(url, filename) {
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
}

function handleExport(format) {
  if (!selectedId.value) {
    ElMessage.warning('请先选择报告')
    return
  }

  // 服务器端导出（DOCX / Markdown / JSON）
  if (format === 'docx') {
    const url = incidentReportApi.getDocxExportUrl(selectedId.value)
    downloadExport(url, `${edit.title || '报告'}.docx`)
    ElMessage.success('正在下载 DOCX 文件')
    return
  }
  if (format === 'json') {
    const url = incidentReportApi.getJsonExportUrl(selectedId.value)
    downloadExport(url, `${edit.title || '报告'}.json`)
    ElMessage.success('正在下载 JSON 文件')
    return
  }
  if (format === 'markdown') {
    const url = incidentReportApi.getMarkdownExportUrl(selectedId.value)
    downloadExport(url, `${edit.title || '报告'}.md`)
    ElMessage.success('正在下载 Markdown 文件')
    return
  }

  // 本地客户端导出（PDF / HTML — 原有的 Markdown 导出逻辑保留）
  const title = edit.title || '未命名报告'
  let content = `# ${title}\n\n`
  content += `## 概要\n${edit.summary || '(空)'}\n\n`
  content += `## 影响范围\n${JSON.stringify(edit.impactScope, null, 2)}\n\n`
  content += `## 时间线\n`
  edit.timeline.forEach(e => {
    content += `- [${e.time}] ${e.event}: ${e.description}\n`
  })
  content += `\n## MITRE 战术\n${edit.mitreTactics.join(', ') || '(空)'}\n\n`
  content += `## 证据\n${edit.evidence || '(空)'}\n\n`
  content += `## 建议措施\n`
  edit.recommendations.forEach(r => {
    content += `- [${r.checked ? 'x' : ' '}] [${r.priority}] ${r.text}\n`
  })

  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${title}.md`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`报告已导出为 ${format.toUpperCase()}`)
}

// ── 初始化 ──
onMounted(() => {
  loadReports()
})
</script>

<style scoped>
/* ===== 页面布局 ===== */
.report-page { height: 100%; display: flex; flex-direction: column; }
.page-head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 16px; flex-shrink: 0; }
.page-head-left h2 { margin: 0; font-size: 16px; font-weight: 500; line-height: 1.3; }
.page-sub { display: block; font-size: 12px; color: var(--color-text-secondary, #555); margin-top: 2px; }

/* ===== 左右布局 ===== */
.rp-layout { flex: 1; display: flex; gap: 12px; overflow: hidden; }

/* ===== 左侧边栏 ===== */
.rp-sidebar {
  width: 260px; flex-shrink: 0; display: flex; flex-direction: column;
  background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  overflow: hidden; position: relative;
}
.sb-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px 8px; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  flex-shrink: 0;
}
.sb-head-left { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; }
.sb-search { padding: 8px 14px; flex-shrink: 0; }
.sb-filter { padding: 0 14px 8px; flex-shrink: 0; }
.sb-list { flex: 1; overflow-y: auto; padding: 4px 6px; }

/* ── 报告条目卡片 ── */
.rp-item {
  display: flex; align-items: flex-start; gap: 8px; padding: 10px 8px 10px 0;
  border-radius: 6px; cursor: pointer; margin-bottom: 3px;
  position: relative; transition: all .15s;
  border: 0.5px solid transparent;
}
.rp-item:hover {
  background: var(--color-canvas-subtle, #fafafa);
  border-color: var(--color-border-tertiary, #e5e5e5);
}
.rp-item.active {
  background: var(--color-accent-subtle, #eff6ff);
  border-color: var(--color-accent-fg, #2563eb);
}

/* 类型色标 */
.rp-accent { width: 3px; height: 100%; min-height: 42px; border-radius: 0 2px 2px 0; flex-shrink: 0; margin-right: 2px; }

.rp-item-icon {
  font-size: 11px; line-height: 1.5; flex-shrink: 0;
  width: 24px; height: 24px; border-radius: 4px;
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-text-secondary, #555);
  display: flex; align-items: center; justify-content: center;
  font-weight: 500;
}
.rp-item-body { flex: 1; min-width: 0; }

/* 标题行 */
.rp-item-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.rp-item-title {
  font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; flex: 1; color: var(--color-text-primary, #111); line-height: 1.4;
}
.rp-item.active .rp-item-title {
  color: var(--color-accent-fg, #2563eb);
  font-weight: 500;
}
.rp-aud-tag {
  flex-shrink: 0; font-size: 10px !important; height: 18px !important;
  line-height: 18px !important; padding: 0 6px !important;
  border: none !important;
  background: var(--color-canvas-inset, #f5f5f5) !important;
  color: var(--color-text-secondary, #555) !important;
}

/* 元信息行 */
.rp-item-meta { display: flex; align-items: center; gap: 6px; }

/* 状态流程指示器 */
.rp-status-flow { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.sf-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-border-default, #e5e5e5); transition: all .2s; }
.sf-dot.done { background: var(--color-text-success, #16a34a); }
.sf-dot.current { background: var(--color-text-success, #16a34a); }
.sf-line { width: 8px; height: 2px; background: var(--color-border-default, #e5e5e5); border-radius: 1px; }

/* 状态文字 */
.rp-item-status { font-size: 11px; font-weight: 500; flex-shrink: 0; }
.rp-item-date { font-size: 11px; color: var(--color-text-tertiary, #888); flex-shrink: 0; }

/* 悬停删除按钮 */
.rp-del-btn { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); flex-shrink: 0; padding: 4px !important; }
.rp-del-btn :deep(.el-icon) { font-size: 14px; }

/* ===== 右侧 ===== */
.rp-main { flex: 1; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; min-height: 0; }
.rp-main-empty { display: flex; align-items: center; justify-content: center; }

/* ===== 工具栏 ===== */
.toolbar-card {
  background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 14px 16px; flex-shrink: 0;
}
.toolbar-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.toolbar-title-row { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 200px; }
.toolbar-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

/* 标题输入框 — 下划线风格 */
.title-input :deep(.el-input__wrapper) { background: transparent; box-shadow: none !important; border-bottom: 0.5px solid transparent; border-radius: 0; transition: border-color .2s; }
.title-input :deep(.el-input__wrapper:hover) { border-bottom-color: var(--color-border-tertiary, #e5e5e5); }
.title-input :deep(.el-input__wrapper.is-focus) { border-bottom-color: var(--color-accent-fg, #2563eb); }
.title-input.title-saved :deep(.el-input__wrapper) { border-bottom-color: var(--color-text-success, #16a34a); }
.title-input :deep(.el-input__inner) { font-size: 16px; font-weight: 500; height: 40px; }

/* 按钮紧凑覆盖 */
.toolbar-actions :deep(.el-button), .toolbar-title-row :deep(.el-button) { height: 28px; padding: 0 12px; font-size: 12px; }
.toolbar-actions :deep(.el-button--small) { height: 28px; padding: 0 12px; font-size: 12px; }
.toolbar-actions :deep(.el-button--small.is-circle) { height: 28px; width: 28px; padding: 0; }
.toolbar-actions :deep(.el-button .el-icon), .toolbar-title-row :deep(.el-button .el-icon) { font-size: 13px; margin-right: 3px; }
.toolbar-actions :deep(.el-button--small.is-circle .el-icon) { margin-right: 0; }
.toolbar-actions :deep(.el-dropdown .el-button) { height: 28px; padding: 0 12px; font-size: 12px; }

/* ── 元信息栏 ── */
.toolbar-meta {
  display: flex; align-items: center; justify-content: space-between;
  margin-top: 10px; padding-top: 10px; border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  flex-wrap: wrap; gap: 6px;
}
.meta-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.meta-badge { font-size: 12px; color: var(--color-text-secondary, #555); display: flex; align-items: center; gap: 4px; }
.meta-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.meta-time { font-size: 11px; color: var(--color-text-tertiary, #888); }
.saved-indicator { color: var(--color-text-success, #16a34a); display: flex; align-items: center; gap: 3px; }

/* el-tag 覆盖 */
.toolbar-meta :deep(.el-tag) { border-radius: 4px; font-size: 11px; padding: 0 8px; height: 20px; line-height: 20px; border-width: 0.5px; }
.toolbar-meta :deep(.el-tag--dark) { border: none; }

/* ===== 折叠编辑器 ===== */
.editor-collapse { border: none; background: transparent; }

/* ── 折叠头 ── */
.editor-collapse :deep(.el-collapse-item__header) {
  height: auto; padding: 10px 12px;
  background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px); margin-bottom: 4px;
  transition: border-color .2s;
}
.editor-collapse :deep(.el-collapse-item__header:hover) { border-color: var(--color-border-secondary, #d0d0d0); }
.editor-collapse :deep(.el-collapse-item__wrap) { border: none; background: transparent; }
.editor-collapse :deep(.el-collapse-item__content) { padding: 0; }
.editor-collapse :deep(.el-collapse-item.is-active .el-collapse-item__header) {
  border-radius: 10px 10px 0 0; border-bottom: none;
}

/* ── 折叠箭头（▶ 旋转动画） ── */
.sec-arr { margin-left: auto; font-size: 12px; color: var(--color-text-tertiary, #888); transition: transform .2s; flex-shrink: 0; }
.editor-collapse :deep(.el-collapse-item.is-active) .sec-arr { transform: rotate(90deg); }

/* ── Section 标题 ── */
.section-header { display: flex; align-items: center; gap: 8px; flex: 1; }
.section-dot { width: 4px; height: 20px; border-radius: 2px; flex-shrink: 0; }
.dot-summary { background: var(--color-accent-fg, #2563eb); }
.dot-impact { background: var(--color-text-warning, #d97706); }
.dot-timeline { background: var(--color-text-success, #16a34a); }
.dot-mitre { background: #7F77DD; }
.dot-evidence { background: var(--color-text-danger, #dc2626); }
.dot-rec { background: #185FA5; }
.dot-collab { background: #1D9E75; }
.section-name { font-size: 13px; font-weight: 500; }

/* ── Section 内容体 ── */
.section-body {
  padding: 16px; background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-top: none; border-radius: 0 0 10px 10px; margin-bottom: 4px;
}
.section-field { margin-bottom: 14px; }
.field-label { display: block; font-size: 12px; font-weight: 500; color: var(--color-text-secondary, #555); margin-bottom: 6px; }
.section-tip { display: flex; align-items: center; gap: 6px; margin-top: 10px; font-size: 12px; color: var(--color-text-tertiary, #888); }

/* ── 时间线 ── */
.tl-event { display: flex; gap: 12px; margin-bottom: 14px; padding-left: 4px; }
.tl-event-bar { display: flex; flex-direction: column; align-items: center; width: 20px; flex-shrink: 0; }
.tl-index {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
  font-size: 11px; font-weight: 500;
  display: flex; align-items: center; justify-content: center;
}
.tl-connector { width: 2px; flex: 1; background: var(--color-border-default, #e5e5e5); min-height: 20px; margin: 4px 0; }
.tl-event-body { flex: 1; min-width: 0; }
.tl-event-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }

/* ── MITRE 网格 ── */
.mitre-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px,1fr)); gap: 8px; }
.mitre-item {
  padding: 8px 10px; border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px; cursor: pointer; transition: all .15s;
  background: var(--color-canvas-subtle, #fafafa);
}
.mitre-item:hover { border-color: var(--color-accent-fg, #2563eb); background: var(--color-accent-subtle, #eff6ff); }
.mitre-item.active { border-color: var(--color-accent-fg, #2563eb); background: var(--color-accent-subtle, #eff6ff); }
.mitre-item :deep(.el-checkbox__label) { display: flex !important; flex-direction: column; gap: 2px; }
.mitre-id { font-size: 10px; color: var(--color-text-tertiary, #888); font-family: monospace; }
.mitre-name { font-size: 13px; font-weight: 500; }

/* ── 建议措施 ── */
.rec-list { margin-bottom: 10px; }
.rec-item {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
  padding: 6px 8px; border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
}
.rec-item:hover { background: var(--color-canvas-subtle, #fafafa); }
.rec-done :deep(.el-checkbox__label) { text-decoration: line-through; color: var(--color-text-tertiary, #888); }
.rec-text-done { text-decoration: line-through; color: var(--color-text-tertiary, #888); }
.priority-badge { font-size: 11px; padding: 0 6px; border-radius: 4px; font-weight: 500; white-space: nowrap; flex-shrink: 0; height: 20px; line-height: 18px; }
.priority-badge.high { background: var(--color-background-danger, #fef2f2); color: var(--color-text-danger, #dc2626); border: 0.5px solid var(--color-border-default, #e5e5e5); }
.priority-badge.medium { background: var(--color-background-warning, #fffbeb); color: var(--color-text-warning, #d97706); border: 0.5px solid var(--color-border-default, #e5e5e5); }
.priority-badge.low { background: var(--color-background-success, #f0fdf4); color: var(--color-text-success, #16a34a); border: 0.5px solid var(--color-border-default, #e5e5e5); }

/* ── 协作评论 ── */
.comment-list { margin-bottom: 12px; }
.comment-item { display: flex; gap: 10px; margin-bottom: 12px; }
.comment-avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: var(--color-accent-subtle, #eff6ff);
  color: var(--color-accent-fg, #2563eb);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 500; flex-shrink: 0;
}
.comment-content { flex: 1; min-width: 0; }
.comment-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.comment-author { font-size: 13px; font-weight: 500; }
.comment-time { font-size: 11px; color: var(--color-text-tertiary, #888); }
.comment-text { font-size: 13px; line-height: 1.5; color: var(--color-text-primary, #111); white-space: pre-wrap; }
.comment-empty { padding: 10px 0; font-size: 12px; color: var(--color-text-tertiary, #888); text-align: center; }
.comment-input-row { display: flex; gap: 8px; }

/* ── 发布确认 ── */
.publish-warn {
  display: flex; align-items: flex-start; gap: 8px; padding: 12px 14px;
  background: var(--color-background-warning, #fffbeb);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px; font-size: 13px;
  color: var(--color-text-warning, #d97706);
  margin-bottom: 16px;
}

/* ── 增量更新对话框 ── */
.reg-hint {
  display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px;
  background: var(--color-accent-subtle, #eff6ff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px; font-size: 13px; color: var(--color-text-primary, #111);
}
.reg-sections {
  margin-top: 12px; padding: 12px;
  background: var(--color-canvas-subtle, #fafafa);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
}
.reg-section-title { font-size: 13px; font-weight: 500; color: var(--color-text-secondary, #555); margin-bottom: 8px; }
.reg-section-item { padding: 6px 8px; border-radius: 4px; transition: background .15s; }
.reg-section-item:hover { background: var(--color-accent-subtle, #eff6ff); }
.reg-section-item :deep(.el-checkbox__label) { display: flex !important; align-items: center; gap: 8px; }
.reg-sec-name { font-size: 13px; }
.reg-sec-score { font-size: 11px; font-weight: 500; font-family: 'Courier New', monospace; }

/* ── 版本差异对比 ── */
.diff-summary { display: flex; gap: 12px; margin-bottom: 16px; }
.diff-stat { font-size: 13px; font-weight: 500; padding: 4px 12px; border-radius: 4px; }
.diff-changed { background: var(--color-accent-subtle, #eff6ff); color: var(--color-accent-fg, #2563eb); }
.diff-added { background: var(--color-background-success, #f0fdf4); color: var(--color-text-success, #16a34a); }
.diff-removed { background: var(--color-background-danger, #fef2f2); color: var(--color-text-danger, #dc2626); }
.diff-list { max-height: 450px; overflow-y: auto; }
.diff-group { margin-bottom: 16px; }
.diff-group-title {
  font-size: 13px; font-weight: 500; color: var(--color-text-primary, #111);
  margin-bottom: 8px; padding-bottom: 6px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
}
.diff-item {
  padding: 10px 12px;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px; margin-bottom: 8px;
}
.diff-item-changed { background: var(--color-accent-subtle, #eff6ff); }
.diff-item-added { background: var(--color-background-success, #f0fdf4); }
.diff-item-removed { background: var(--color-background-danger, #fef2f2); }
.diff-section-label { font-size: 12px; font-weight: 500; color: var(--color-text-secondary, #555); margin-bottom: 6px; }
.diff-compare { display: flex; gap: 8px; align-items: flex-start; }
.diff-side { flex: 1; min-width: 0; }
.diff-side-title { font-size: 11px; color: var(--color-text-tertiary, #888); margin-bottom: 4px; font-weight: 500; }
.diff-side-content {
  font-size: 12px; line-height: 1.5; color: var(--color-text-primary, #111);
  white-space: pre-wrap; word-break: break-word; max-height: 120px; overflow-y: auto;
  padding: 6px 8px;
  background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 4px;
}
.diff-vs { display: flex; align-items: center; padding-top: 24px; flex-shrink: 0; }
.diff-empty { padding: 20px 0; font-size: 12px; color: var(--color-text-tertiary, #888); text-align: center; }

/* ── 通用克制空状态（去 el-empty 撕纸动画） ── */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 48px 16px; text-align: center;
}
.empty-icon {
  display: flex; align-items: center; justify-content: center;
  width: 56px; height: 56px; border-radius: 50%;
  background: var(--color-canvas-subtle, #fafafa);
  color: var(--color-text-tertiary, #888);
  margin-bottom: 12px;
}
.empty-text {
  font-size: 13px; font-weight: 500;
  color: var(--color-text-primary, #111);
  margin-bottom: 4px;
}
.empty-hint {
  font-size: 12px; color: var(--color-text-tertiary, #888);
}

/* ── 滚动条 ── */
.sb-list::-webkit-scrollbar, .rp-main::-webkit-scrollbar { width: 5px; }
.sb-list::-webkit-scrollbar-thumb, .rp-main::-webkit-scrollbar-thumb { background: var(--color-text-tertiary, #888); border-radius: 4px; }
.sb-list::-webkit-scrollbar-track, .rp-main::-webkit-scrollbar-track { background: transparent; }

/* ── 主机分组头部 ── */
.gh-header { display: flex; align-items: center; gap: 6px; flex: 1; }
.gh-icon {
  font-size: 10px; line-height: 1;
  padding: 1px 5px; border-radius: 3px;
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-text-secondary, #555);
  font-weight: 500;
}
.gh-hostname { font-size: 13px; font-weight: 500; color: var(--color-text-primary, #111); }
.gh-ip { font-size: 11px; color: var(--color-text-tertiary, #888); }
.gh-count { flex-shrink: 0; font-size: 10px !important; height: 18px !important; }
.gh-label {
  font-size: 10px; color: var(--color-accent-fg, #2563eb);
  background: var(--color-accent-subtle, #eff6ff);
  padding: 1px 6px; border-radius: 3px;
}

/* 分组 collapse 覆盖 */
.sb-list :deep(.el-collapse) { border: none; }
.sb-list :deep(.el-collapse-item__header) {
  height: auto; padding: 8px 4px; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  background: transparent;
}
.sb-list :deep(.el-collapse-item__wrap) { border: none; }
.sb-list :deep(.el-collapse-item__content) { padding: 0 0 4px 4px; }
.sb-list :deep(.el-collapse-item__arrow) { margin-right: 4px; }
.sb-list :deep(.el-collapse-item.is-active .el-collapse-item__header) { border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); }

/* 分组内的报告条目间距微调 */
.sb-list .rp-item { margin-bottom: 2px; padding: 8px 8px 8px 4px; }

/* ── 置信度条 ── */
.conf-bar { font-size: 11px; font-family: 'Courier New', monospace; letter-spacing: 1px; margin-right: 4px; }

/* ── AI 分析质量卡片 ── */
.ai-quality-card {
  background: var(--color-canvas-subtle, #fafafa);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-card, 10px);
  padding: 12px 16px;
}
.aiq-header { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 500; color: var(--color-text-primary, #111); margin-bottom: 10px; }
.aiq-body { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.aiq-stat { display: flex; align-items: center; gap: 6px; min-width: 120px; }
.aiq-label { font-size: 12px; color: var(--color-text-secondary, #555); }
.aiq-value { font-size: 13px; font-weight: 500; font-family: 'Courier New', monospace; }
</style>
