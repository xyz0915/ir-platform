<template>
  <div class="event-detail-panel">
    <!-- 决策条（§10.3） -->
    <div class="decision-bar">
      <div class="db-left">
        <span class="severity-badge" :class="'badge-' + (event.severity || 'info')">{{ event.severity }}</span>
        <span class="db-risk" :style="{ color: riskScoreColor(riskScore) }">{{ riskScore }}</span>
        <span v-if="categoryLabel" class="db-category" :class="'cat-' + (event.category || 'unknown')">{{ categoryLabel }}</span>
        <span v-if="event.attack_stage" class="db-stage">{{ stageLabel(event.attack_stage) }}</span>
        <span class="db-status" :class="'stat-' + (event.status || 'pending')">{{ statusLabel(event.status) }}</span>
      </div>
      <button class="close-btn-fixed" @click="$emit('close')" title="关闭">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M1 1L13 13M13 1L1 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </button>
    </div>

    <!-- 操作行（按钮组） -->
    <div class="action-row">
      <button v-if="event.status === 'pending'" class="btn btn-primary btn-xs" @click="onStatusChange('triaging')">分诊</button>
      <button v-if="event.status === 'triaging'" class="btn btn-warning btn-xs" @click="onStatusChange('investigating')">调查</button>
      <button v-if="event.status === 'investigating'" class="btn btn-success btn-xs" @click="onStatusChange('resolved')">解决</button>
      <button v-if="event.status === 'resolved'" class="btn btn-warning btn-xs" @click="onStatusChange('investigating')">重开</button>
      <button v-if="event.status !== 'rejected' && event.status !== 'resolved'" class="btn btn-danger btn-xs" @click="onStatusChange('rejected')">误报</button>
      <button class="btn btn-primary btn-xs" @click="onDeepInvestigation">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="margin-right:3px">
          <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.3"/>
          <path d="M8 5V11M5 8H11" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
        </svg>
        深度调查
      </button>
    </div>

    <!-- 上一条/下一条导航 -->
    <div class="detail-nav" v-if="siblingEvents.length > 1">
      <button class="nav-btn" :disabled="currentIdx <= 0" @click="navigateSibling(-1)">‹ 上一条</button>
      <span class="nav-pos">{{ currentIdx + 1 }} / {{ siblingEvents.length }}</span>
      <button class="nav-btn" :disabled="currentIdx >= siblingEvents.length - 1" @click="navigateSibling(1)">下一条 ›</button>
    </div>

    <!-- 查看详情入口 -->
    <div class="detail-section edv-entry">
      <router-link :to="'/analysis-center/event/' + event.id" class="edv-entry-btn">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 4L8 7L2 10V4Z" fill="currentColor"/><rect x="8" y="3" width="4" height="8" rx="1" fill="currentColor" opacity="0.6"/></svg>
        查看完整详情
      </router-link>
    </div>

    <!-- v2 AI 研判区块（AI 推荐事件） -->
    <div class="detail-section ai-verdict-section" v-if="event.event_type === 'ai_recommended'">
      <div class="ai-v-header">🤖 AI 优先推荐</div>
      <div class="ai-v-body">
        <div class="ai-v-row"><span class="ai-v-label">置信度</span><span class="ai-v-val">{{ aiConfidence }}</span></div>
        <div class="ai-v-row" v-if="aiAnalysis"><span class="ai-v-label">研判结果</span><span class="ai-v-val ai-summary-text">{{ aiAnalysis }}</span></div>
        <div class="ai-v-row" v-if="aiAttackType"><span class="ai-v-label">攻击类型</span><span class="ai-v-val">{{ aiAttackType }}</span></div>
        <div class="ai-v-row" v-if="aiAction"><span class="ai-v-label">建议动作</span><span class="ai-v-val ai-action-tag">{{ aiAction }}</span></div>
        <div class="ai-v-row" v-if="aiOriginalId">
          <span class="ai-v-label">原始事件</span>
          <span class="ai-v-val">
            <router-link :to="'/analysis-center/event/' + event.id" class="ai-orig-link">查看 →</router-link>
          </span>
        </div>
      </div>
    </div>

    <!-- v2 AI 研判区块（已标记原事件） -->
    <div class="detail-section ai-verdict-section" :class="'vl-' + (verdictLabel || 'unknown')" v-else-if="event.ai_verdict">
      <div class="ai-v-header">
        <span class="verdict-badge" :class="'vlabel-' + (verdictLabel || 'unknown')">{{ verdictLabelText }}</span>
      </div>
      <div class="ai-v-body">
        <div class="ai-v-row"><span class="ai-v-label">置信度</span><span class="ai-v-val">{{ aiConfidence }}</span></div>
        <div class="ai-v-row" v-if="aiAttackType"><span class="ai-v-label">攻击类型</span><span class="ai-v-val">{{ aiAttackType }}</span></div>
        <div class="ai-v-row" v-if="aiReason"><span class="ai-v-label">理由</span><span class="ai-v-val">{{ aiReason }}</span></div>
      </div>
    </div>

    <!-- 基本信息 -->
    <div class="detail-section">
      <div class="section-title">基本信息</div>
      <div class="detail-row">
        <span class="detail-label">时间</span>
        <span class="detail-value">{{ formatTime(event.timestamp) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">类型</span>
        <span class="detail-value">{{ eventTypeLabel(event.event_type) }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">主机</span>
        <span class="detail-value">
          <span class="host-link" @click="onFilterByHost(event.host_id)">
            {{ event.hostname || ('#主机' + event.host_id) }}
          </span>
        </span>
      </div>
      <div class="detail-row">
        <span class="detail-label">采集器</span>
        <span class="detail-value">{{ event.source_collector || '—' }}</span>
      </div>
      <!-- 父进程 -->
      <div class="detail-row" v-if="event.evidence?.parent_name">
        <span class="detail-label">父进程</span>
        <span class="detail-value">{{ event.evidence.parent_name }} (PPID: {{ event.evidence.ppid || '?' }})</span>
      </div>
      <!-- 文件哈希 -->
      <div class="detail-row" v-if="event.evidence?.sha256">
        <span class="detail-label">文件哈希</span>
        <span class="detail-value">
          <div class="hash-with-actions">
            <span class="hash-val">{{ event.evidence.sha256.substring(0, 16) }}...</span>
            <button class="hash-act-btn" @click.stop="copyHash(event.evidence.sha256)">复制</button>
            <button class="hash-act-btn" @click.stop="openVT(event.evidence.sha256)">VT</button>
          </div>
        </span>
      </div>
      <!-- 签名状态 -->
      <div class="detail-row" v-if="event.evidence?.is_signed !== undefined">
        <span class="detail-label">签名状态</span>
        <span class="detail-value">
          <span v-if="event.evidence.is_signed" style="background:var(--color-success-subtle);padding:0 6px;border-radius:3px;color:var(--color-success-fg)">已签名</span>
          <span v-else style="background:var(--color-danger-subtle);padding:0 6px;border-radius:3px;color:var(--color-danger-fg)">未签名</span>
        </span>
      </div>
      <div class="detail-row" v-if="event.case_id">
        <span class="detail-label">案件</span>
        <span class="detail-value">{{ event.case_name || ('案件#' + event.case_id) }}</span>
      </div>
      <div class="detail-row" v-if="event.import_id">
        <span class="detail-label">日志 ID</span>
        <span class="detail-value">{{ event.import_id }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">攻击链</span>
        <span class="detail-value">{{ event.attack_chain_id || '—' }}</span>
      </div>
      <div class="detail-row">
        <span class="detail-label">ATT&CK</span>
        <span class="detail-value">
          {{ event.attack_stage ? stageLabel(event.attack_stage) : '—' }}
        </span>
      </div>
      <div class="detail-row">
        <span class="detail-label">负责人</span>
        <span class="detail-value">{{ event.assignee || '未指派' }}</span>
      </div>
      <div class="detail-row" v-if="eventFrequency">
        <span class="detail-label">同类事件</span>
        <span class="detail-value" :class="{ 'freq-high': eventFrequency.total > 50 }">
          首次 {{ formatTime(eventFrequency.first_seen) }}
          · 最近 {{ formatTime(eventFrequency.last_seen) }}
          · 共 {{ eventFrequency.total }} 次
          · {{ eventFrequency.affected_hosts }} 台主机
        </span>
      </div>
    </div>

    <!-- 威胁指标 -->
    <div class="detail-section" v-if="iocTotalCount > 0">
      <div class="section-title">威胁指标 ({{ iocTotalCount }})</div>
      <div class="ioc-group" v-if="eventIOCs.ips?.length">
        <span class="ioc-group-label">🌐 IP 地址 ({{ eventIOCs.ips.length }})</span>
        <span v-for="ip in eventIOCs.ips" :key="ip" class="ioc-chip ioc-ip"
              :title="ip" @click="copyText(ip)">{{ ip }}</span>
      </div>
      <div class="ioc-group" v-if="eventIOCs.sha256?.length">
        <span class="ioc-group-label">🔑 SHA256 ({{ eventIOCs.sha256.length }})</span>
        <span v-for="h in eventIOCs.sha256" :key="h" class="ioc-chip ioc-hash"
              :title="h" @click="copyText(h)">
          {{ h.substring(0, 16) }}...
          <a class="ioc-vt-link" @click.stop="openVT(h)">VT</a>
        </span>
      </div>
      <div class="ioc-group" v-if="eventIOCs.domains?.length">
        <span class="ioc-group-label">🌐 域名 ({{ eventIOCs.domains.length }})</span>
        <span v-for="d in eventIOCs.domains" :key="d" class="ioc-chip ioc-domain"
              :title="d" @click="copyText(d)">{{ d }}</span>
      </div>
      <div class="ioc-group" v-if="eventIOCs.md5?.length">
        <span class="ioc-group-label">🔏 MD5 ({{ eventIOCs.md5.length }})</span>
        <span v-for="m in eventIOCs.md5" :key="m" class="ioc-chip ioc-hash"
              :title="m" @click="copyText(m)">{{ m.substring(0, 16) }}...</span>
      </div>
      <div class="ioc-group" v-if="eventIOCs.file_paths?.length">
        <span class="ioc-group-label">📁 文件路径 ({{ eventIOCs.file_paths.length }})</span>
        <div v-for="fp in eventIOCs.file_paths.slice(0, 5)" :key="fp" class="ioc-fp">{{ fp }}</div>
        <span v-if="eventIOCs.file_paths.length > 5" class="ioc-more">+{{ eventIOCs.file_paths.length - 5 }} 更多</span>
      </div>
    </div>

    <!-- 网络连接图 -->
    <div class="detail-section" v-if="netGraph?.nodes?.length > 1">
      <div class="section-title">网络连接</div>
      <div class="net-graph">
        <svg :width="netGraphWidth" height="120" class="net-svg">
          <!-- 连接线 -->
          <line v-for="(e, i) in netGraph.edges" :key="'e'+i"
                :x1="40" :y1="60" :x2="netGraphWidth - 60" :y2="20 + i * 30"
                stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4 2"/>
          <line v-for="(e, i) in netGraph.edges" :key="'e2'+i"
                :x1="40" :y1="60" :x2="netGraphWidth - 60" :y2="20 + i * 30"
                stroke="#3b82f6" stroke-width="0.5"/>
          <!-- 本机节点 -->
          <circle cx="40" cy="60" r="16" fill="#dbeafe" stroke="#3b82f6" stroke-width="2"/>
          <text x="40" y="64" text-anchor="middle" font-size="9" fill="#1e40af">本机</text>
          <!-- 远端节点 -->
          <g v-for="(n, i) in remoteNodes" :key="n.id">
            <rect :x="netGraphWidth - 80" :y="10 + i * 30" width="60" height="22" rx="4"
                  :fill="n.ip.startsWith('10.') || n.ip.startsWith('192.') ? '#f0fdf4' : '#fef2f2'"
                  :stroke="n.ip.startsWith('10.') || n.ip.startsWith('192.') ? '#22c55e' : '#ef4444'"
                  stroke-width="1.5"/>
            <text :x="netGraphWidth - 50" :y="25 + i * 30" text-anchor="middle"
                  font-size="9" fill="#333">{{ n.label }}</text>
            <text v-if="n.port" :x="netGraphWidth - 50" :y="45 + i * 30"
                  text-anchor="middle" font-size="8" fill="#888">:{{ n.port }}</text>
          </g>
        </svg>
      </div>
    </div>

    <!-- 进程树 -->
    <div class="detail-section" v-if="procTree?.length">
      <div class="section-title">进程树</div>
      <div class="proc-tree">
        <div v-for="(node, i) in procTree" :key="node.pid"
             class="pt-node" :class="{ current: node.pid === currentProcPid }"
             :style="{ paddingLeft: (node.depth * 20 + 8) + 'px' }">
          <svg v-if="i > 0" class="pt-line" width="20" height="28">
            <line x1="0" y1="0" x2="0" y2="14" stroke="#aaa" stroke-width="1.5"/>
            <line x1="0" y1="14" x2="14" y2="14" stroke="#aaa" stroke-width="1.5"/>
          </svg>
          <span class="pt-icon">⚙</span>
          <strong>{{ node.name }}</strong>
          <span class="pt-pid">({{ node.pid }})</span>
          <span class="pt-cmdline" :title="node.cmdline">{{ node.cmdline ? node.cmdline.substring(0, 60) : '' }}</span>
        </div>
      </div>
    </div>

    <el-collapse v-model="activeCollapse" class="detail-collapse">
      <el-collapse-item title="更多详情" name="more">
        <!-- 风险评分 -->
        <div class="detail-section" v-if="riskScore > 0">
          <div class="section-title">风险评分</div>
      <div class="risk-score-wrap">
        <div class="rs-big" :style="{ color: riskScoreColor(riskScore) }">{{ riskScore }}</div>
        <div class="rs-breakdown">
          <div class="rs-item"><span>严重度</span><span>+{{ severityWeight }}</span></div>
          <div class="rs-item"><span>命中规则 ({{ matchedRuleCount }})</span><span>+{{ ruleScore }}</span></div>
          <div class="rs-item"><span>IOC 命中</span><span>+{{ iocScore }}</span></div>
        </div>
      </div>
    </div>

    <!-- 匹配规则 -->
    <div class="detail-section" v-if="event.rule_name || event.matched_rules">
      <div class="section-title">匹配规则</div>
      <div v-if="event.rule_name" class="rule-item">
        <span class="detail-value">{{ event.rule_name }}</span>
      </div>
      <div v-if="event.matched_rules && event.matched_rules.length > 0">
        <div v-for="(rule, i) in event.matched_rules" :key="i" class="rule-item">
          <span class="detail-value">{{ rule.name || rule.rule_id || ('规则 #' + (i + 1)) }}</span>
          <span v-if="rule.description" class="rule-desc">{{ rule.description }}</span>
        </div>
      </div>
      <div v-else class="rule-none">无匹配规则（基于模型推断）</div>
    </div>

    <!-- 原始命令 -->
    <div class="detail-section" v-if="event.evidence?.command_line || event.evidence?.process_cmdline">
      <div class="section-title">原始命令</div>
      <div class="cmd-block">
        <code class="cmd-code">{{ event.evidence.command_line || event.evidence.process_cmdline }}</code>
      </div>
    </div>

    <!-- 处置操作 -->
    <div class="detail-section">
      <div class="action-buttons">
        <button
          v-if="event.status === 'pending'"
          class="btn btn-primary"
          @click="onStatusChange('triaging')"
        >
          开始分诊
        </button>
        <button
          v-if="event.status === 'triaging'"
          class="btn btn-warning"
          @click="onStatusChange('investigating')"
        >
          进入调查
        </button>
        <button
          v-if="event.status === 'investigating'"
          class="btn btn-success"
          @click="onStatusChange('resolved')"
        >
          标记解决
        </button>
        <button
          v-if="event.status !== 'rejected' && event.status !== 'resolved'"
          class="btn btn-danger"
          @click="onStatusChange('rejected')"
        >
          标记误报
        </button>
        <button
          v-if="event.status === 'resolved'"
          class="btn btn-warning"
          @click="onStatusChange('investigating')"
        >
          重新开案
        </button>
      </div>
    </div>

    <!-- 主机概览 -->
    <div class="detail-section" v-if="store.hostStats">
      <div class="section-title">主机概览 — {{ event.hostname }}</div>
      <div class="host-stat-grid">
        <div class="host-stat"><div class="host-stat-val">{{ store.hostStats.total_24h }}</div><div class="host-stat-lbl">24h 事件</div></div>
        <div class="host-stat"><div class="host-stat-val" style="color:var(--color-risk-high)">{{ store.hostStats.matched_24h }}</div><div class="host-stat-lbl">规则命中</div></div>
        <div class="host-stat"><div class="host-stat-val" style="color:var(--color-risk-critical)">{{ store.hostStats.active_alerts }}</div><div class="host-stat-lbl">活跃告警</div></div>
      </div>
      <div v-if="store.hostStats.last_disposition" style="margin-top:8px;font-size:11px;color:var(--color-fg-subtle)">
        上次处置: {{ store.hostStats.last_disposition.at }} · {{ store.hostStats.last_disposition.operator }} — "{{ store.hostStats.last_disposition.comment }}"
      </div>
    </div>

    <!-- 时间线上下文 -->
    <div class="detail-section" v-if="store.eventContext.length">
      <div class="section-title">时间线上下文 · 前后 5 分钟</div>
      <div v-for="evt in store.eventContext" :key="evt.id" class="tl-item" :class="{ 'tl-current': evt.id === event.id }">
        <div class="tl-time">{{ formatTime(evt.timestamp) }}</div>
        <div class="tl-line">
          <div class="tl-dot" :class="dotColorClass(evt.severity)"></div>
          <div class="tl-line-conn"></div>
        </div>
        <div class="tl-body">
          <strong :style="{ color: sevTextColor(evt.severity) }">{{ eventTypeLabel(evt.event_type) }}</strong>
          <span class="tl-summary">{{ evt.summary || '' }}</span>
        </div>
      </div>
    </div>

    <!-- 影响范围 -->
    <div class="detail-section" v-if="store.impactScope">
      <div class="section-title">影响范围</div>
      <div class="impact-grid">
        <div class="impact-item" v-for="(val, key) in store.impactScope" :key="key">
          <div class="impact-icon">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.3"/>
              <path d="M8 4V9M8 11V12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>
          </div>
          <div><div class="impact-num">{{ val }}</div><div class="impact-lbl">{{ impactLabel(key) }}</div></div>
        </div>
      </div>
    </div>

    <!-- 处置记录 -->
    <div class="detail-section">
      <div class="section-title">处置记录</div>
      <div v-if="store.dispositions.length" class="disp-list">
        <div v-for="d in store.dispositions" :key="d.id" class="disp-item">
          <span class="disp-time">{{ d.created_at }}</span>
          <div>
            <span class="disp-actor">{{ d.operator }}</span>
            <span class="disp-action">{{ actionLabel(d.action) }}</span>
            <div v-if="d.comment" class="disp-comment">"{{ d.comment }}"</div>
          </div>
        </div>
      </div>
      <div v-else style="font-size:12px;color:var(--color-fg-light);padding:4px 0">暂无处置记录</div>
      <div class="disp-input-wrap">
        <input v-model="dispComment" class="disp-input" placeholder="添加处置备注...">
        <button class="btn btn-sm btn-primary" @click="onAddDisposition">发送</button>
      </div>
    </div>

    <!-- v2.1 必填字段展示 -->
    <div class="detail-section" v-if="requiredFields.length">
      <div class="section-title">必填字段 ({{ requiredFields.length }})</div>
      <div v-for="f in requiredFields" :key="f.key" class="detail-row">
        <span class="detail-label">{{ f.label }}</span>
        <span class="detail-value">{{ fieldValue(f) }}</span>
      </div>
    </div>

    <!-- v2.1 证据双视图 -->
    <div class="detail-section" v-if="evidenceViews">
      <div class="section-title">
        证据详情
        <span class="view-toggle" @click="toggleEvidenceView">
          {{ evidenceViewMode === 'normalized' ? '📋 范式化视图' : '📄 完整原始数据' }}
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="margin-left:4px"><path d="M4 2L8 6L4 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </span>
      </div>
      <div v-if="evidenceViewMode === 'normalized'" class="ev-json">
        <pre class="json-content">{{ formatJson(evidenceViews.normalized) }}</pre>
      </div>
      <div v-else class="ev-json">
        <div class="raw-source-label">来源: {{ evidenceViews.raw_source }}</div>
        <pre class="json-content">{{ formatJson(evidenceViews.raw) }}</pre>
      </div>
    </div>

    <!-- v2.1 自适应主体（按事件类型展开） -->
    <div class="detail-section" v-if="processSubject" key="process-subject">
      <div class="section-title">进程主体</div>
      <div class="subject-grid">
        <div v-for="(val, key) in processSubject" :key="key" class="sg-row" v-if="val && val !== '—'">
          <span class="sg-key">{{ key }}</span>
          <span class="sg-val">{{ val }}</span>
        </div>
      </div>
    </div>

    <div class="detail-section" v-if="networkSubject" key="network-subject">
      <div class="section-title">网络主体</div>
      <div class="subject-grid">
        <div v-for="(val, key) in networkSubject" :key="key" class="sg-row" v-if="val && val !== '—'">
          <span class="sg-key">{{ key }}</span>
          <span class="sg-val">{{ val }}</span>
        </div>
      </div>
    </div>

    <div class="detail-section" v-if="persistenceTarget" key="persistence-subject">
      <div class="section-title">持久化落点</div>
      <div class="detail-value">{{ persistenceTarget }}</div>
    </div>

    <!-- IOC 匹配 -->
    <div class="detail-section" v-if="event.ioc_matches && event.ioc_matches.length > 0">
      <div class="section-title">IOC 匹配 ({{ event.ioc_matches.length }})</div>
      <div class="ioc-list">
        <span
          v-for="ioc in event.ioc_matches"
          :key="ioc"
          class="ioc-tag"
        >
          {{ ioc }}
        </span>
      </div>
    </div>

    <!-- 处置建议 -->
    <div class="detail-section">
      <div class="section-title">处置建议</div>
      <div class="suggestion-text">
        <template v-if="event.severity === 'critical' || event.severity === 'high'">
          建议立即隔离受感染主机，终止可疑进程，并收集完整的取证数据。
        </template>
        <template v-else-if="event.severity === 'medium'">
          建议确认进程/网络行为是否为正常业务操作，可查询历史基线。
        </template>
        <template v-else>
          信息性事件，可归档记录，无需立即处置。
        </template>
      </div>
    </div>

    <!-- 关联事件 -->
    <div class="detail-section" v-if="event.related_events && event.related_events.length > 0">
      <div class="section-title">关联事件 ({{ event.related_events.length }})</div>
      <div class="related-list">
        <button
          v-for="rid in event.related_events"
          :key="rid"
          class="btn btn-link"
          @click="onViewRelated(rid)"
        >
          {{ rid.substring(0, 12) + '...' }}
        </button>
      </div>
    </div>

    <!-- 关联数据 -->
    <div class="detail-section" v-if="event.host_id">
      <div class="section-title">关联数据</div>
      <div class="action-buttons">
        <button class="btn btn-primary" @click="viewLog">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="margin-right: 4px;">
            <circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.3"/>
            <path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
          </svg>
          查看原始日志
        </button>
      </div>
    </div>
    </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '@/stores/analysis'

const props = defineProps({
  event: { type: Object, default: () => ({}) },
  display: { type: Object, default: null },  // v2.1 展示投影数据
})

const emit = defineEmits(['close', 'update-status', 'assign', 'view-related'])

const store = useAnalysisStore()
const router = useRouter()
const dispComment = ref('')
const activeCollapse = ref(['more'])

const SEV_COLORS = {
  critical: '#dc2626', high: '#dc2626', medium: '#d97706',
  low: '#2563eb', info: '#a3a3a3',
}
const STAGE_LABELS = {
  initial_access: '初始访问', execution: '执行', persistence: '持久化',
  privilege_escalation: '提权', defense_evasion: '防御规避',
  credential_access: '凭据访问', discovery: '发现',
  lateral_movement: '横向移动', collection: '收集',
  command_and_control: 'C2', exfiltration: '外泄',
  impact: '影响', unknown: '未知',
}
const EVENT_TYPE_LABELS = {
  process_start: '进程启动', process_terminate: '进程退出',
  network_outbound: '出站连接', network_listen: '端口监听',
  registry_modify: '注册表写入', registry_delete: '注册表删除',
  file_create: '文件创建', file_modify: '文件修改',
  persistence_register: '持久化注册', wmi_subscribe: 'WMI订阅',
  behavior_alert: '行为告警', ioc_match: 'IOC命中',
  user_login: '用户登录', user_logout: '用户登出',
  dns_query: 'DNS查询', module_load: '模块加载',
  scheduled_task: '计划任务', service_operation: '服务操作',
  pipe_connect: '管道连接', driver_load: '驱动加载',
}
const ACTION_LABELS = {
  isolate: '隔离主机', kill_process: '结束进程', block_ip: '封锁IP',
  add_rule: '添加规则', escalate: '上报', ignore: '忽略',
  review: '复核',
}

// ── 风险评分 computed ──
function calcRiskScore(ev) {
  if (!ev) return 0
  let s = { critical: 80, high: 60, medium: 40, low: 20, info: 5 }[ev.severity] || 5
  if (ev.matched_rules?.length) s += Math.min(ev.matched_rules.length * 5, 25)
  if (ev.ioc_matches?.length) s += Math.min(ev.ioc_matches.length * 15, 30)
  return Math.max(0, Math.min(100, s))
}

const riskScore = computed(() => calcRiskScore(props.event))
const severityWeight = computed(() => {
  return { critical: 80, high: 60, medium: 40, low: 20, info: 5 }[props.event?.severity] || 5
})
const matchedRuleCount = computed(() => props.event?.matched_rules?.length || 0)
const ruleScore = computed(() => Math.min((props.event?.matched_rules?.length || 0) * 5, 25))
const iocScore = computed(() => Math.min((props.event?.ioc_matches?.length || 0) * 15, 30))

function riskScoreColor(score) {
  if (score >= 70) return 'var(--color-risk-critical)'
  if (score >= 50) return 'var(--color-risk-medium)'
  if (score >= 30) return 'var(--color-risk-low)'
  return 'var(--color-fg-subtle)'
}

// ── 结构化证据 ──
const structuredEvidence = computed(() => {
  const ev = props.event?.evidence || {}
  const keys = Object.keys(ev).slice(0, 8)
  const result = {}
  keys.forEach(k => {
    const val = ev[k]
    result[k] = typeof val === 'object' ? JSON.stringify(val) : String(val)
  })
  return result
})

function sevColor(s) { return SEV_COLORS[s] || '#a3a3a3' }
function stageLabel(s) { return STAGE_LABELS[s] || s }
function eventTypeLabel(t) { return EVENT_TYPE_LABELS[t] || t }
function statusLabel(s) {
  const labels = { pending: '待处理', triaging: '分诊中', investigating: '调查中', resolved: '已解决', rejected: '已误报' }
  return labels[s] || s
}

const categoryLabel = computed(() => {
  const labels = { process: '进程', network: '网络', persistence: '持久化', startup: '启动项', behavior: '行为', ioc: '情报', credential: '凭据', discovery: '发现', execution: '执行', lateral: '横向', c2: 'C2', impact: '影响', defense_evasion: '防御规避', privilege_escalation: '提权', exfiltration: '数据外泄', webshell: 'WebShell', memory_shell: '内存马', attack_chain: '攻击链' }
  return labels[props.event?.category] || props.event?.category || ''
})

// AI 研判（v2）
const aiVerdict = computed(() => {
  const raw = props.event?.ai_verdict
  if (!raw) return null
  try { return typeof raw === 'string' ? JSON.parse(raw) : raw }
  catch { return null }
})
const verdictLabel = computed(() => aiVerdict.value?.label || '')
const verdictLabelText = computed(() => {
  const labels = {
    suspicious: '🟡 可疑·待复核',
    false_positive: '⚪ 误报',
    benign: '🟢 良性',
    unknown: '⚫ 未知/降级',
  }
  return labels[verdictLabel.value] || '🤖 AI 研判'
})
const aiConfidence = computed(() => (aiVerdict.value?.confidence ?? '') + '%')
const aiReason = computed(() => aiVerdict.value?.reason || '')
const aiAnalysis = computed(() => props.event?.ai_analysis || '')
const aiAttackType = computed(() => aiVerdict.value?.attack_type || '')
const aiAction = computed(() => {
  const labels = { isolate: '隔离主机', kill_process: '结束进程', block_ip: '封锁IP', review: '人工复核' }
  return labels[aiVerdict.value?.action] || aiVerdict.value?.action || ''
})
const aiOriginalId = computed(() => {
  const id = props.event?.id || ''
  return id.startsWith('ai:') ? id.substring(3) : null
})
function actionLabel(a) { return ACTION_LABELS[a] || a }

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatJson(obj) {
  if (!obj) return '{}'
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

function dotColorClass(severity) {
  return 'sev-' + (severity || 'info')
}

function sevTextColor(severity) {
  return SEV_COLORS[severity] || '#a3a3a3'
}

function impactLabel(key) {
  const labels = {
    hosts: '受影响主机', processes: '受影响进程', users: '受影响用户',
    ips: '关联IP', files: '关联文件',
  }
  return labels[key] || key
}

// ── v2.1 展示投影 ──
const projection = computed(() => props.display?.projection || props.display || {})
const requiredFields = computed(() => projection.value.required || [])
const auxiliaryFields = computed(() => projection.value.auxiliary || [])
const evidenceViews = computed(() => projection.value.evidence_views || null)
const evidenceViewMode = ref('normalized')

// 自适应主体：按事件类型展开进程/网络/持久化
const processSubject = computed(() => {
  const et = (props.event?.event_type || '')
  if (!et.startsWith('process') && et !== 'ioc_match') return null
  const aux = auxiliaryFields.value.find(f => f.key === 'process_subject')
  return aux?.value || null
})
const networkSubject = computed(() => {
  const et = (props.event?.event_type || '')
  if (!et.startsWith('network') && et !== 'dns_query') return null
  const aux = auxiliaryFields.value.find(f => f.key === 'network_subject')
  return aux?.value || null
})
const persistenceTarget = computed(() => {
  const et = (props.event?.event_type || '')
  if (!['persistence_register','registry_modify','registry_delete','scheduled_task','service_operation','wmi_subscribe']
      .includes(et)) return null
  const aux = auxiliaryFields.value.find(f => f.key === 'persistence_target')
  return aux?.value || null
})

function toggleEvidenceView() {
  evidenceViewMode.value = evidenceViewMode.value === 'normalized' ? 'raw' : 'normalized'
}

function fieldValue(f) {
  if (!f) return '—'
  const v = f.value
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'object') return formatJson(v)
  return String(v)
}

function copyHash(hash) {
  navigator.clipboard?.writeText(hash).then(() => {
    // 复制成功
  }).catch(() => {
    // fallback
  })
}

function openVT(hash) {
  window.open(`https://www.virustotal.com/gui/file/${hash}`, '_blank')
}

function onStatusChange(status) {
  emit('update-status', { id: props.event.id, status })
}

function onViewRelated(relatedId) {
  emit('view-related', [relatedId])
}

function viewLog() {
  const caseId = props.event.case_id || ''
  const hostId = props.event.host_id || ''
  const query = props.event.hostname || `host_id:${hostId}`
  window.open(`/log-search?case_id=${caseId}&host_id=${hostId}&keyword=${encodeURIComponent(query)}`, '_blank')
}

async function onAddDisposition() {
  if (!dispComment.value.trim()) return
  await store.addDispositionForEvent(props.event.id, {
    action: 'review',
    operator: '',
    comment: dispComment.value,
  })
  dispComment.value = ''
}

// ── IOC 提取展示 ──
const eventIOCs = computed(() => props.event?.iocs || null)
const iocTotalCount = computed(() => {
  const i = eventIOCs.value
  if (!i) return 0
  return (i.ips?.length || 0) + (i.domains?.length || 0) + (i.md5?.length || 0)
       + (i.sha1?.length || 0) + (i.sha256?.length || 0) + (i.file_paths?.length || 0)
})
function copyText(text) {
  navigator.clipboard.writeText(text).then(() => {
    // 成功
  }).catch(() => {})
}

// ── 同类事件统计 ──
const eventFrequency = computed(() => props.event?.frequency || null)

// ── 进程树 ──

const procTree = ref([])
const currentProcPid = ref(null)
const procLoading = ref(false)
const netGraph = ref(null)
const netGraphWidth = ref(380)

watch(() => props.event?.id, async (newId) => {
  if (!newId) return
  procLoading.value = true
  // 进程树
  try {
    const res = await fetch(`/api/analysis/events/${newId}/process-tree`, {
      headers: { 'Authorization': 'Bearer ' + (window.__token || '') }
    })
    const data = await res.json()
    if (data.code === 0) {
      procTree.value = data.data.tree || []
      currentProcPid.value = data.data.current_pid
    }
  } catch (e) {
    procTree.value = []
  } finally {
    procLoading.value = false
  }
  // 网络连接图
  try {
    const res2 = await fetch(`/api/analysis/events/${newId}/network-graph`, {
      headers: { 'Authorization': 'Bearer ' + (window.__token || '') }
    })
    const data2 = await res2.json()
    netGraph.value = data2.code === 0 ? data2.data : null
  } catch (e) {
    netGraph.value = null
  }
}, { immediate: false })

const remoteNodes = computed(() => (netGraph.value?.nodes || []).filter(n => n.type === 'remote'))

// ── 上下文切换 ──
const siblingEvents = computed(() => store.items || [])
const currentIdx = computed(() => siblingEvents.value.findIndex(e => e.id === props.event?.id))
function navigateSibling(delta) {
  const target = siblingEvents.value[currentIdx.value + delta]
  if (target) store.fetchEventDetail(target.id)
}
function onFilterByHost(hostId) {
  store.ruleFilters.hostId = hostId
  store.ruleFilters.page = 1
  store.fetchRuleEvents()
  emit('close')
}

// ── 深度调查 ──
function onDeepInvestigation() {
  const query = { eventId: props.event.id }
  if (props.event.case_id) query.caseId = props.event.case_id
  router.push({ path: '/agent-orchestration', query })
}
</script>

<style scoped>
.event-detail-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 13px;
  font-weight: 400;
}

/* 决策条（§10.3） */
.decision-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px 6px 12px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  flex-shrink: 0;
  gap: 6px;
  min-height: 36px;
}
.db-left, .db-right {
  display: flex;
  align-items: center;
  gap: 5px;
}
.db-left { flex: 1; min-width: 0; overflow-x: auto; overflow-y: hidden; }
.db-left::-webkit-scrollbar { height: 3px; }
.db-left::-webkit-scrollbar-thumb { background: var(--color-border-default); border-radius: 2px; }
.db-risk {
  font-size: 13px;
  font-weight: 600;
  min-width: 22px;
}
.db-category {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
  white-space: nowrap;
}
.db-category.cat-behavior {
  background: rgba(220,38,38,0.1);
  color: var(--color-danger-fg);
}
.db-stage {
  font-size: 10.5px;
  color: var(--color-fg-subtle);
  white-space: nowrap;
}
.db-status {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--color-canvas-inset);
  white-space: nowrap;
}
.db-status.stat-pending { background: var(--color-accent-subtle); color: var(--color-accent-fg); }
.db-status.stat-triaging { background: var(--color-warning-subtle, #fef3c7); color: #d97706; }
.db-status.stat-investigating { background: var(--color-warning-subtle, #fef3c7); color: #d97706; }
.db-status.stat-resolved { background: var(--color-success-subtle, #dcfce7); color: #16a34a; }
.db-status.stat-rejected { background: var(--color-danger-subtle, #fef2f2); color: #dc2626; }

/* 关闭按钮 - 固定右上角 */
.close-btn-fixed {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle, #888888);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
}
.close-btn-fixed:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-danger-fg, #dc2626);
}

/* 操作行（处置按钮） */
.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 12px;
  background: var(--color-canvas-subtle, #fafafa);
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  flex-shrink: 0;
}
.btn-xs { padding: 2px 8px; font-size: 10px; line-height: 1.5; }

/* 自适应主体网格 */
.subject-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.sg-row {
  display: contents;
}
.sg-key {
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  font-size: 11px;
  white-space: nowrap;
}
.sg-val {
  color: var(--color-fg-default);
  word-break: break-all;
}

/* AI 研判区块（v2 方案） */
.ai-verdict-section {
  background: var(--color-canvas-subtle, #fafafa);
  border-left: 3px solid #16a34a;
}
/* 按 label 上色的左边框（可靠的类选择器，替代脆弱的 :has(:contains)） */
.ai-verdict-section.vl-suspicious { border-left-color: #d97706; }
.ai-verdict-section.vl-false_positive { border-left-color: #a3a3a3; }
.ai-verdict-section.vl-benign { border-left-color: #16a34a; }
.ai-verdict-section.vl-unknown { border-left-color: #64748b; }
/* 兼容旧式 :has 写法（部分浏览器） */
.ai-verdict-section:has(.ai-v-header:contains('🟡')) {
  border-left-color: #d97706;
}
.ai-verdict-section:has(.ai-v-header:contains('⚪')) {
  border-left-color: #a3a3a3;
}
.ai-v-header {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
}
/* 按 label 上色的徽章 */
.verdict-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 4px;
  line-height: 1.4;
}
.verdict-badge.vlabel-suspicious { background: rgba(217,119,6,0.15); color: #d97706; border: 0.5px solid rgba(217,119,6,0.3); }
.verdict-badge.vlabel-false_positive { background: rgba(163,163,163,0.15); color: #6b7280; border: 0.5px solid rgba(163,163,163,0.3); }
.verdict-badge.vlabel-benign { background: rgba(22,163,74,0.15); color: #16a34a; border: 0.5px solid rgba(22,163,74,0.3); }
.verdict-badge.vlabel-unknown { background: rgba(100,116,139,0.15); color: #64748b; border: 0.5px solid rgba(100,116,139,0.3); }
.ai-v-body {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.ai-v-row { display: contents; }
.ai-v-label {
  color: var(--color-fg-subtle);
  font-size: 11px;
  white-space: nowrap;
}
.ai-v-val { color: var(--color-fg-default); word-break: break-all; }
.ai-summary-text { font-family: 'Courier New', monospace; font-size: 11px; }
.ai-action-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  background: #dcfce7;
  color: #16a34a;
  font-size: 11px;
}
.ai-orig-link { font-size: 11px; color: var(--color-accent-fg); text-decoration: none; }
.edv-entry { padding: 8px 16px; }
.edv-entry-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-accent-fg);
  background: var(--color-accent-subtle);
  border: 0.5px solid var(--color-accent-fg);
  border-radius: 6px;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.15s;
}
.edv-entry-btn:hover { opacity: 0.85; }

.severity-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
  font-size: 11px;
  font-weight: 500;
}

.severity-badge.badge-critical,
.severity-badge.badge-high {
  background: var(--color-danger-fg, #dc2626);
}

.severity-badge.badge-medium {
  background: var(--color-warning-fg, #d97706);
}

.severity-badge.badge-low {
  background: var(--color-accent-fg, #2563eb);
}

.severity-badge.badge-info {
  background: var(--color-fg-subtle, #888888);
}

.event-id {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  font-family: 'Courier New', monospace;
}

.close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  color: var(--color-fg-subtle, #888888);
  cursor: pointer;
  border-radius: var(--r-btn, 6px);
  transition: all 0.15s;
}

.close-btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
  color: var(--color-fg-default, #111111);
}

/* ===== Section ===== */
.detail-section {
  padding: 12px 16px;
  border-bottom: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
}

.section-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-fg-subtle, #888888);
  margin-bottom: 12px;
}

/* ===== Detail Row ===== */
.detail-row {
  display: flex;
  margin-bottom: 8px;
  align-items: flex-start;
}

.detail-row:last-child {
  margin-bottom: 0;
}

.detail-label {
  width: 64px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  line-height: 1.5;
}

.detail-value {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111111);
  flex: 1;
  word-break: break-all;
  line-height: 1.5;
}

/* ===== Hash Actions ===== */
.hash-with-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.hash-val {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.hash-act-btn {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
  border-radius: 3px;
  border: 0.5px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
  color: var(--color-accent-fg);
  cursor: pointer;
  line-height: 1.4;
  transition: all 0.15s;
}
.hash-act-btn:hover {
  background: var(--color-accent-subtle);
}

/* ===== Risk Score ===== */
.risk-score-wrap {
  display: flex;
  align-items: center;
  gap: 16px;
}
.rs-big {
  font-size: 32px;
  font-weight: 600;
  line-height: 1;
  min-width: 48px;
}
.rs-breakdown {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.rs-item {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  font-size: 11px;
  color: var(--color-fg-subtle);
}
.rs-item span:last-child {
  font-weight: 500;
  color: var(--color-fg-default);
}

/* ===== Action Buttons ===== */
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* ===== Buttons ===== */
.btn {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 400;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #ffffff);
  color: var(--color-fg-default, #111111);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.4;
}

.btn:hover {
  background: var(--color-canvas-inset, #f5f5f5);
}

.btn-primary {
  background: var(--color-accent-fg, #2563eb);
  color: #ffffff;
  border-color: var(--color-accent-fg, #2563eb);
}

.btn-primary:hover {
  opacity: 0.9;
  background: var(--color-accent-fg, #2563eb);
}

.btn-success {
  background: var(--color-success-fg, #16a34a);
  color: #ffffff;
  border-color: var(--color-success-fg, #16a34a);
}

.btn-success:hover {
  opacity: 0.9;
  background: var(--color-success-fg, #16a34a);
}

.btn-warning {
  background: var(--color-warning-fg, #d97706);
  color: #ffffff;
  border-color: var(--color-warning-fg, #d97706);
}

.btn-warning:hover {
  opacity: 0.9;
  background: var(--color-warning-fg, #d97706);
}

.btn-danger {
  background: transparent;
  color: var(--color-danger-fg, #dc2626);
  border-color: var(--color-danger-fg, #dc2626);
}

.btn-danger:hover {
  background: var(--color-danger-subtle, #fef2f2);
}

.btn-link {
  border: none;
  background: transparent;
  color: var(--color-accent-fg, #2563eb);
  padding: 4px 0;
  font-size: 12px;
  cursor: pointer;
  display: block;
  text-align: left;
}

.btn-link:hover {
  text-decoration: underline;
}

.btn-sm {
  padding: 4px 10px;
  font-size: 11px;
}

/* ===== Host Stats ===== */
.host-stat-grid {
  display: flex;
  gap: 12px;
}
.host-stat {
  flex: 1;
  text-align: center;
  padding: 8px;
  background: var(--color-canvas-inset);
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
}
.host-stat-val {
  font-size: 22px;
  font-weight: 600;
  line-height: 1.2;
}
.host-stat-lbl {
  font-size: 10px;
  color: var(--color-fg-subtle);
  margin-top: 2px;
}

/* ===== Timeline ===== */
.tl-item {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
  padding: 4px 0;
}
.tl-current {
  background: var(--color-accent-subtle);
  border-radius: 4px;
  padding: 4px 4px;
  margin-left: -4px;
}
.tl-time {
  width: 56px;
  flex-shrink: 0;
  font-size: 10px;
  font-family: 'Courier New', monospace;
  color: var(--color-fg-subtle);
  padding-top: 2px;
}
.tl-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 10px;
  flex-shrink: 0;
}
.tl-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tl-dot.sev-critical,
.tl-dot.sev-high {
  background: var(--color-risk-critical);
}
.tl-dot.sev-medium {
  background: var(--color-risk-medium);
}
.tl-dot.sev-low {
  background: var(--color-risk-low);
}
.tl-dot.sev-info {
  background: var(--color-fg-light);
}
.tl-line-conn {
  width: 1px;
  flex: 1;
  background: var(--color-border-default);
  min-height: 12px;
}
.tl-body {
  flex: 1;
  font-size: 11px;
  line-height: 1.5;
}
.tl-summary {
  margin-left: 4px;
  color: var(--color-fg-subtle);
}

/* ===== Impact ===== */
.impact-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.impact-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--color-canvas-inset);
  padding: 8px 12px;
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default);
}
.impact-icon {
  color: var(--color-fg-subtle);
  display: flex;
  align-items: center;
}
.impact-num {
  font-size: 18px;
  font-weight: 600;
  line-height: 1.2;
}
.impact-lbl {
  font-size: 10px;
  color: var(--color-fg-subtle);
}

/* ===== Disposition ===== */
.disp-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.disp-item {
  display: flex;
  gap: 8px;
  font-size: 12px;
}
.disp-time {
  font-size: 10px;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  white-space: nowrap;
  padding-top: 1px;
}
.disp-actor {
  font-weight: 500;
  margin-right: 8px;
}
.disp-action {
  color: var(--color-fg-subtle);
}
.disp-comment {
  font-size: 11px;
  color: var(--color-fg-light);
  margin-top: 2px;
  font-style: italic;
}
.disp-input-wrap {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}
.disp-input {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: var(--r-btn, 6px);
  background: var(--color-canvas-inset);
  color: var(--color-fg-default);
  outline: none;
}
.disp-input:focus {
  border-color: var(--color-accent-fg);
}

/* ===== Structured Evidence ===== */
.ev-row {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  font-size: 11px;
  line-height: 1.6;
}
.ev-key {
  width: 80px;
  flex-shrink: 0;
  color: var(--color-fg-subtle);
  font-family: 'Courier New', monospace;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ev-val {
  flex: 1;
  color: var(--color-fg-default);
  word-break: break-all;
}

/* ===== JSON Viewer ===== */
.json-viewer {
  background: var(--color-canvas-inset, #f5f5f5);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  max-height: 200px;
  overflow: auto;
}

.json-content {
  margin: 0;
  padding: 8px 12px;
  font-size: 11px;
  font-weight: 400;
  font-family: 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-fg-default, #111111);
}

/* ===== IOC Tags ===== */
.ioc-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.ioc-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  font-size: 11px;
  font-weight: 400;
  border-radius: 4px;
  background: var(--color-danger-subtle, #fef2f2);
  color: var(--color-danger-fg, #dc2626);
  border: 0.5px solid rgba(220, 38, 38, 0.2);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggestion-text {
  color: var(--color-fg-muted, #555555);
  line-height: 1.6;
  font-size: 13px;
  font-weight: 400;
}

.related-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rule-item {
  padding: 8px 12px;
  background: var(--color-canvas-inset, #f5f5f5);
  border-radius: var(--r-btn, 6px);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  margin-bottom: 4px;
}

.rule-desc {
  display: block;
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-subtle, #888888);
  margin-top: 4px;
}

.rule-none {
  font-size: 11px;
  font-weight: 400;
  color: var(--color-fg-light, #a3a3a3);
}

/* ===== Command Code Block ===== */
.cmd-block {
  background: #1e1e1e;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: var(--r-btn, 6px);
  padding: 12px;
  overflow-x: auto;
}

.cmd-code {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  font-weight: 400;
  color: #e5e5e5;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}

/* 导航 */
.detail-nav { display: flex; align-items: center; gap: 8px; padding: 6px 12px; background: var(--color-canvas-subtle); border-radius: 6px; margin: 0 12px 8px; font-size: 12px; }
.nav-btn { padding: 2px 10px; border: 0.5px solid var(--color-border-default); border-radius: 4px; background: var(--color-canvas-default); cursor: pointer; font-size: 12px; color: var(--color-fg-default); }
.nav-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.nav-pos { color: var(--color-fg-subtle); font-size: 11px; }
.host-link { cursor: pointer; color: var(--color-accent-fg, #2563eb); text-decoration: underline; }
.host-link:hover { opacity: 0.8; }
.ioc-group { margin: 8px 0; }
.ioc-group-label { display: block; font-size: 11px; color: var(--color-fg-subtle); margin-bottom: 4px; }
.ioc-chip { display: inline-block; padding: 2px 8px; margin: 2px 4px 2px 0; border-radius: 4px; font-size: 11px; cursor: pointer; font-family: monospace; transition: all 0.1s; }
.ioc-chip:hover { transform: scale(1.05); }
.ioc-ip { background: #dbeafe; color: #1e40af; }
.ioc-hash { background: #fce7f3; color: #9d174d; }
.ioc-domain { background: #d1fae5; color: #065f46; }
.ioc-fp { font-size: 11px; font-family: monospace; padding: 2px 4px; color: var(--color-fg-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px; }
.ioc-vt-link { margin-left: 4px; color: #2563eb; text-decoration: underline; cursor: pointer; }
.ioc-more { font-size: 11px; color: var(--color-fg-light); }

/* collapse 面板 */
.detail-collapse { border: none; margin: 0 12px; }
.detail-collapse :deep(.el-collapse-item__header) { font-size: 12px; font-weight: 500; padding-left: 0; color: var(--color-accent-fg, #2563eb); border: none; }
.detail-collapse :deep(.el-collapse-item__wrap) { border: none; }
.detail-collapse :deep(.el-collapse-item__content) { padding: 4px 0; }

/* 进程树 */
.proc-tree { font-size: 12px; }
.pt-node { display: flex; align-items: center; gap: 4px; padding: 3px 0; white-space: nowrap; overflow: hidden; }
.pt-node.current { background: var(--color-accent-subtle, #eff6ff); border-radius: 4px; }
.pt-line { flex-shrink: 0; }
.pt-icon { font-size: 13px; }
.pt-pid { color: var(--color-fg-subtle); font-size: 11px; }
.pt-cmdline { color: var(--color-fg-light); font-size: 11px; margin-left: 4px; overflow: hidden; text-overflow: ellipsis; max-width: 240px; }

/* 同类事件统计 */
.freq-high { color: #dc2626; font-weight: 600; }

/* 网络连接图 */
.net-graph { overflow-x: auto; padding: 4px 0; }
.net-svg { display: block; min-width: 360px; }
</style>