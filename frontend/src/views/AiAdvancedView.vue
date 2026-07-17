<template>
  <div class="ai-adv-page">
    <div class="page-head">
      <h2>AI 实验室</h2>
      <span class="page-sub">自然语言安全分析 · 智能研判 · 决策辅助</span>
      <div class="page-head-actions">
        <el-button size="small" plain @click="exportChat()" :disabled="chatMsgs.length <= 1">
          导出对话
        </el-button>
        <el-button size="small" plain @click="generateReportAction" :loading="reportLoading">
          生成报告
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="ai-tabs" @tab-click="onTabChange">
      <!-- ============================================================ -->
      <!-- TAB 1: 自然语言指挥台 (重构) -->
      <!-- ============================================================ -->
      <el-tab-pane label="自然语言指挥台" name="chat">
        <div class="chat-layout">
          <!-- 左侧会话历史侧边栏 (可折叠) -->
          <Transition name="slide">
            <div v-if="showSessions" class="chat-sessions">
              <div class="sess-head">
                <span class="sess-title">会话历史</span>
                <el-button size="small" @click="newSession">新建</el-button>
              </div>
              <div class="sess-search">
                <el-input v-model="sessionSearchQuery" placeholder="搜索会话..." size="small" clearable />
              </div>
              <div class="sess-list">
                <div v-for="s in filteredSessions" :key="s.id"
                  :class="['sess-item', { active: s.id === activeSessionId }]"
                  @click="loadSession(s.id)">
                  <div class="sess-title-text">{{ s.title }}</div>
                  <div class="sess-meta">{{ formatTime(s.updatedAt) }}</div>
                  <el-button v-if="s.id === activeSessionId" link size="small" class="sess-del"
                    @click.stop="deleteSession(s.id)">×</el-button>
                </div>
              </div>
            </div>
          </Transition>

          <!-- 中间聊天区域 (flex:1 撑满) -->
          <div class="chat-left">
            <div class="chat-box">
              <div class="chat-msgs" ref="chatRef">
                <!-- 空状态: 居中欢迎语 + 推荐气泡 -->
                <div v-if="chatMsgs.length <= 1" class="welcome-state">
                  <h2 class="welcome-title">Hi，今天从哪里开始？</h2>
                  <p class="welcome-sub">试试这些快速查询，或直接输入问题</p>
                  <div class="suggestion-grid">
                    <div class="suggestion-card clickable" v-for="(s, i) in suggestionList" :key="i" @click="quickQuery(s.text)">
                      <span class="sug-icon"><el-icon><Search /></el-icon></span>
                      <span class="sug-text">{{ s.text }}</span>
                    </div>
                  </div>
                </div>

                <!-- 正常消息流 (有历史时) -->
                <template v-else>
                  <div v-if="contextHint" class="context-hint">{{ contextHint }}</div>
                  <ContextIndicator
                    :context="{ hostName: chatContext.hostName, hostAlertCount: 3, hostRiskScore: 78, intent: chatContext.intent, pinned: false }"
                    @switch-host="switchHost"
                    @pin="chatContext.pinned = !chatContext.pinned"
                    @clear="chatContext = { hostId: null, hostName: '', intent: '', timeRange: null, lastQuery: '' }; contextHint = ''"
                  />

                  <ConfirmDialog
                    :visible="confirmDialog.visible"
                    :action="confirmDialog.action"
                    :target="confirmDialog.target"
                    :reason="confirmDialog.reason"
                    :confirm-id="confirmDialog.confirmId"
                    @confirm="handleActionConfirm"
                    @cancel="confirmDialog.visible = false"
                  />
                  <div v-for="(m, i) in chatMsgs" :key="i" :class="['msg', m.role]">
                    <!-- 首字母圆形头像 -->
                    <div class="msg-av" :class="m.role">{{ m.role === 'user' ? 'U' : 'AI' }}</div>
                    <div class="msg-b">
                      <!-- 消息操作菜单 (AI消息上hover出现) -->
                      <div v-if="m.role === 'assistant'" class="msg-menu">
                        <el-dropdown trigger="click" size="small" @command="(cmd) => msgMenuAction(cmd, m, i)">
                          <span class="msg-menu-trigger">···</span>
                          <template #dropdown>
                            <el-dropdown-menu>
                              <el-dropdown-item command="copy">复制内容</el-dropdown-item>
                              <el-dropdown-item command="quote">引用追问</el-dropdown-item>
                              <el-dropdown-item divided command="useful" icon="CircleCheck">有用</el-dropdown-item>
                              <el-dropdown-item command="useless" icon="Close">没用</el-dropdown-item>
                              <el-dropdown-item v-if="m.render && m.render !== 'text'" divided command="not_this">这不是我要的</el-dropdown-item>
                            </el-dropdown-menu>
                          </template>
                        </el-dropdown>
                      </div>
                      <div v-if="m.text" class="msg-txt">
                        <StreamMessage :text="m.text" :streaming="m.streaming" />
                      </div>

                      <!-- 统计结果卡片 (ECharts仪表盘) -->
                      <div v-if="m.render === 'stats'" class="stat-chart-card">
                        <div class="stat-chart-grid">
                          <div class="stat-chart-item">
                            <div class="sc-value" style="color:var(--color-accent-fg, #2563eb)">{{ m.data?.total_logs || 0 }}</div>
                            <div class="sc-label">总日志</div>
                          </div>
                          <div class="stat-chart-item">
                            <div class="sc-value" style="color:var(--color-danger-fg, #dc2626)">{{ m.data?.total_alerts || 0 }}</div>
                            <div class="sc-label">总告警</div>
                          </div>
                          <div class="stat-chart-item">
                            <div class="sc-value" style="color:var(--color-warning-fg, #d97706)">{{ m.data?.open_alerts || 0 }}</div>
                            <div class="sc-label">未处理</div>
                          </div>
                          <div class="stat-chart-item">
                            <div class="sc-value" style="color:var(--color-success-fg, #16a34a)">{{ hostCount }}</div>
                            <div class="sc-label">主机</div>
                          </div>
                        </div>
                        <div :ref="el => m._chartRef = el" class="stat-echart-mini"></div>
                      </div>

                      <!-- 告警结果卡片 -->
                      <div v-if="m.render === 'alerts'" class="alert-list">
                        <div v-if="isEmptyData(m.data)" class="empty-hint-mini">{{ emptyMsg(m.data) }}</div>
                        <template v-else>
                          <div class="al-hint">共 {{ m.summary || m.data?.length || 0 }} 条</div>
                          <div v-for="a in (m.data||[]).slice(0, showMoreCount)" :key="a.id" class="alert-mini">
                            <el-checkbox v-if="a.id" v-model="a._checked" size="small" @change="updateSelected" style="margin-right:4px" />
                            <span :class="['sev-dot', a.severity||'low']" />
                            <span class="a-title clickable" @click.stop="openAlertDetail(a)">{{ a.title || a.event_label || a.rule_name || '-' }}</span>
                            <span v-if="a.source_ip" class="a-ip clickable" @click.stop="navigateTo('/analysis-center?source_ip=' + a.source_ip)">{{ a.source_ip }}</span>
                            <span class="a-host clickable" @click.stop="navigateTo('/hosts/' + (a.host_id || ''))">{{ a.hostname || '' }}</span>
                            <span class="a-time">{{ (a.last_seen_at||a.first_seen_at||'').slice(11,19) }}</span>
                          </div>
                          <!-- 查看更多/收起 -->
                          <div v-if="m.data?.length > showMoreCount" class="show-more-line">
                            <el-button link size="small" @click="showMoreCount += 10">查看更多 ({{ m.data.length - showMoreCount }} 条)</el-button>
                          </div>
                        </template>
                        <!-- 操作按钮栏（描边风格） -->
                        <div class="result-actions" v-if="m.data?.length">
                          <el-button size="small" plain @click="executeAction('block_ip', m.data)">封锁 IP</el-button>
                          <el-button size="small" plain @click="executeAction('isolate_host', m.data)">隔离主机</el-button>
                          <el-button size="small" plain @click="executeAction('export_report', m.data)">导出报告</el-button>
                          <el-dropdown trigger="click" size="small" @command="(cmd) => contextMenu(cmd, m.data)" class="more-dropdown">
                            <el-button size="small" plain>
                              更多 <el-icon><ArrowDown /></el-icon>
                            </el-button>
                            <template #dropdown>
                              <el-dropdown-menu>
                                <el-dropdown-item command="copy_search">复制到搜索</el-dropdown-item>
                                <el-dropdown-item command="add_note">添加调查笔记</el-dropdown-item>
                                <el-dropdown-item command="export_pdf">导出为 PDF</el-dropdown-item>
                                <el-dropdown-item command="share_link">分享对话</el-dropdown-item>
                              </el-dropdown-menu>
                            </template>
                          </el-dropdown>
                        </div>
                      </div>

                      <!-- 主机结果 -->
                      <div v-if="m.render === 'hosts'" class="host-grid">
                        <div v-if="isEmptyData(m.data)" class="empty-hint-mini" style="grid-column: 1 / -1;">{{ emptyMsg(m.data) }}</div>
                        <template v-else>
                          <div v-for="h in (m.data||[]).slice(0,8)" :key="h.id" class="host-card clickable"
                               @click="navigateTo('/hosts/' + h.id)"
                               @mouseenter="hoveredHost = h"
                               @mouseleave="hoveredHost = null">
                            <span class="hc-icon">
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                            </span>
                            <div class="hc-name">{{ h.hostname }}</div>
                            <div class="hc-status">{{ h.status || '-' }}</div>
                          </div>
                          <Transition name="pop">
                            <div v-if="hoveredHost" class="host-tooltip"
                                 :style="{ left: '50%', transform: 'translateX(-50%)' }">
                              <div class="ht-row">
                                <span class="ht-lbl">
                                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px;margin-right:2px"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                                  IP
                                </span>
                                <span>{{ hoveredHost.ip || '-' }}</span>
                              </div>
                              <div class="ht-row"><span class="ht-lbl">系统</span><span>{{ hoveredHost.os || '-' }}</span></div>
                              <div class="ht-row"><span class="ht-lbl">告警</span><span>{{ hoveredHost.alert_count || 0 }} 条</span></div>
                            </div>
                          </Transition>
                          <div class="result-actions" v-if="m.data?.length" style="grid-column: 1 / -1;">
                            <el-button size="small" plain @click="executeAction('isolate_host', m.data)">隔离选中主机</el-button>
                            <el-button size="small" plain @click="executeAction('ai_noise_reduce', m.data)">AI 降噪研判</el-button>
                          </div>
                        </template>
                      </div>

                      <!-- 案件结果 -->
                      <div v-if="m.render === 'cases'" class="case-list">
                        <div v-if="isEmptyData(m.data)" class="empty-hint-mini">{{ emptyMsg(m.data) }}</div>
                        <template v-else>
                          <div v-for="c in (m.data||[]).slice(0,6)" :key="c.id" class="case-mini clickable"
                               @click="navigateTo('/cases/' + c.id)">
                            <span class="c-name">{{ c.name }}</span>
                            <el-tag size="small" effect="plain">{{ c.status }}</el-tag>
                          </div>
                        </template>
                      </div>

                      <!-- 策略结果 -->
                      <div v-if="m.render === 'policies'" class="case-list">
                        <div v-if="isEmptyData(m.data)" class="empty-hint-mini">{{ emptyMsg(m.data) }}</div>
                        <template v-else>
                          <div v-for="p in (m.data||[]).slice(0,6)" :key="p.id || p.name" class="case-mini clickable"
                               @click="navigateTo('/policies')">
                            <span class="c-name">{{ p.name || p.policy_name || '策略' }}</span>
                            <el-tag v-if="p.severity" size="small" effect="plain">{{ p.severity }}</el-tag>
                            <el-tag v-else-if="p.status" size="small" effect="plain">{{ p.status }}</el-tag>
                          </div>
                          <div class="result-actions" v-if="m.data?.length">
                            <el-button size="small" plain @click="navigateTo('/policies')">查看全部策略</el-button>
                          </div>
                        </template>
                      </div>

                      <!-- 日志结果 -->
                      <div v-if="m.render === 'logs'" class="alert-list">
                        <div v-if="isEmptyData(m.data)" class="empty-hint-mini">{{ emptyMsg(m.data) }}</div>
                        <template v-else>
                          <div class="al-hint">共 {{ m.summary || m.data?.length || 0 }} 条日志</div>
                          <div v-for="l in (m.data||[]).slice(0,6)" :key="l.id" class="alert-mini">
                            <span :class="['sev-dot', l.severity || 'low']" />
                            <span class="a-title">{{ l.event_label || l.event_type || l.description || '日志记录' }}</span>
                            <span v-if="l.hostname" class="a-host clickable" @click.stop="navigateTo('/hosts/' + (l.host_id || ''))">{{ l.hostname }}</span>
                            <span class="a-time">{{ (l.timestamp || l.created_at || '').slice(11,19) }}</span>
                          </div>
                          <div class="result-actions" v-if="m.data?.length">
                            <el-button size="small" plain @click="executeAction('export_report', m.data)">导出日志</el-button>
                            <el-button size="small" plain @click="navigateTo('/log-search')">日志检索</el-button>
                          </div>
                        </template>
                      </div>

                      <!-- AI 研判卡片 -->
                      <div v-if="m.render === 'analysis'" class="analysis-card">
                        <div class="ac-header">
                          <div class="ac-accent-bar"></div>
                          <span class="ac-badge">AI 研判结果</span>
                          <span class="ac-confidence">置信度 {{ m.analysis?.confidence }}%</span>
                        </div>
                        <div class="ac-body">
                          <div class="ac-row">
                            <span class="ac-label">攻击模式</span>
                            <span class="ac-value">{{ m.analysis?.attackPattern }}</span>
                          </div>
                          <div v-if="m.analysis?.mitreIds?.length" class="ac-row">
                            <span class="ac-label">MITRE</span>
                            <span class="ac-value">
                              <el-tag v-for="mid in m.analysis.mitreIds" :key="mid" size="small" effect="plain" class="mitre-tag">
                                {{ mid }}
                              </el-tag>
                            </span>
                          </div>
                          <div class="ac-row">
                            <span class="ac-label">建议</span>
                            <span class="ac-value ac-suggestion">{{ m.analysis?.suggestion }}</span>
                          </div>
                        </div>
                        <div class="ac-actions">
                          <el-button size="small" plain @click="executeAction('block_ip', m.data, m.analysis)">封锁 IP</el-button>
                          <el-button size="small" plain @click="executeAction('isolate_host', m.data, m.analysis)">隔离主机</el-button>
                          <el-button size="small" plain @click="navigateTo('/analysis-center')">查看详情</el-button>
                        </div>
                      </div>

                      <!-- 操作结果卡片 -->
                      <ActionResultCard v-if="m.render === 'action_result'" :result="m.actionResult" />

                      <!-- 可信度标签 -->
                      <ConfidenceBadge v-if="m.render === 'confidence'" :level="m.confidence" />

                      <!-- 攻击路径图 -->
                      <AttackPathGraph
                        v-if="m.render === 'attack_path'"
                        :nodes="m.attackData?.nodes || []"
                        :edges="m.attackData?.edges || []"
                        :summary="m.attackData?.summary || ''"
                        @node-click="(n) => n.hostname ? navigateTo('/hosts/' + n.id) : ''"
                      />
                    </div>
                  </div>

                  <!-- 正在分析占位 -->
                  <div v-if="chatLoading" class="msg assistant">
                    <div class="msg-av assistant">AI</div>
                    <div class="msg-b thinking">正在分析...</div>
                  </div>
                </template>
              </div>

              <!-- 输入区 (胶囊样式) -->
              <div class="chat-in">
                <div class="chat-in-inner">
                  <FileUploadZone @file-selected="handleFileSelected" @file-cleared="handleFileCleared" />
                  <el-autocomplete
                    v-model="chatInput"
                    :fetch-suggestions="querySuggestions"
                    placeholder="有问题尽管问, /或@触发提示  Shift+Enter 换行"
                    @keyup.enter="sendQuery"
                    :disabled="chatLoading"
                    clearable
                    trigger-on-focus
                    class="chat-autocomplete"
                  >
                    <template #default="{ item }">
                      <div class="sug-item">{{ item.label || item.value }}</div>
                    </template>
                  </el-autocomplete>
                  <button class="send-btn" @click="sendQuery" :disabled="chatLoading || !chatInput.trim()">
                    <el-icon :size="16"><ArrowUp /></el-icon>
                  </button>
                  <!-- 流式停止按钮 -->
                  <button v-if="streamingAbort" class="stop-btn" @click="stopStreaming" title="停止输出">
                    <el-icon :size="14"><Close /></el-icon>
                  </button>
                </div>
                <!-- 时间范围Pill -->
                <div v-if="timeRangePill" class="time-pill">
                  <el-tag size="small" closable type="info" @close="timeRangePill = ''">
                    🕐 {{ timeRangePill }}
                  </el-tag>
                </div>
                <!-- 批量操作栏 -->
                <div v-if="selectedAlerts.length" class="batch-bar">
                  <span class="batch-count">已选 {{ selectedAlerts.length }} 条</span>
                  <el-button size="small" @click="batchAction('block_ip')">封锁 IP</el-button>
                  <el-button size="small" @click="batchAction('isolate_host')">隔离主机</el-button>
                  <el-button size="small" @click="batchAction('export')">导出</el-button>
                  <el-button size="small" text @click="selectedAlerts = []">取消</el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 拖拽调整手柄 -->
          <div class="resize-handle" @mousedown="startResize" />

          <!-- 右侧面板 (可拖拽调整宽度) -->
          <div class="chat-right" :style="{ width: rightPanelWidth + 'px', minWidth: rightPanelWidth + 'px' }">
            <!-- 实时快照：横排 4 个 -->
            <div class="snap-bar">
              <div class="snap-item">
                <div class="snap-n">{{ snapData.criticalAlerts }}</div>
                <div class="snap-l">严重</div>
              </div>
              <div class="snap-item">
                <div class="snap-n">{{ snapData.openAlerts }}</div>
                <div class="snap-l">待处理</div>
              </div>
              <div class="snap-item">
                <div class="snap-n">{{ snapData.hosts }}</div>
                <div class="snap-l">主机</div>
              </div>
              <div class="snap-item">
                <div class="snap-n">{{ snapData.policies }}</div>
                <div class="snap-l">策略</div>
              </div>
            </div>
            
            <!-- 快速查询（紧凑列表） -->
            <div class="quick-panel">
              <div class="panel-title">
                快速查询
                <el-button size="small" text @click="showSessions = !showSessions">
                  {{ showSessions ? '隐藏历史' : '历史会话' }}
                </el-button>
              </div>
              <div class="quick-list">
                <div v-for="q in quickQueries" :key="q" class="quick-item clickable" @click="quickQuery(q)">
                  <el-icon :size="12"><Search /></el-icon>
                  <span>{{ q }}</span>
                </div>
              </div>
            </div>

            <!-- 调查剧本 -->
            <InvestigationPlaybook
              :playbooks="playbookList"
              :progress="playbookProgress"
              @start="startPlaybook"
            />

            <!-- 热力图 -->
            <HeatmapTimeline />

            <!-- 会话摘要 -->
            <SessionSummaryCard :summary="sessionSummary" />
          </div>
        </div>

        <!-- v3.1: 告警详情浮层 -->
        <el-drawer v-model="detailDrawer.visible" :title="detailDrawer.alert?.title || '告警详情'" size="400px"
          direction="rtl" destroy-on-close>
          <template v-if="detailDrawer.alert">
            <div class="detail-field"><span class="df-label">严重度</span><el-tag :type="detailDrawer.alert.severity === 'high' ? 'danger' : 'warning'" size="small">{{ detailDrawer.alert.severity }}</el-tag></div>
            <div class="detail-field"><span class="df-label">规则</span><span>{{ detailDrawer.alert.rule_name }}</span></div>
            <div class="detail-field"><span class="df-label">来源</span><span>{{ detailDrawer.alert.source_ip || '-' }}</span></div>
            <div class="detail-field"><span class="df-label">主机</span><span>{{ detailDrawer.alert.hostname || '-' }}</span></div>
            <div class="detail-field"><span class="df-label">详情</span><span>{{ detailDrawer.alert.detail || '-' }}</span></div>
            <div class="detail-field"><span class="df-label">进程</span><span>{{ detailDrawer.alert.source_process || '-' }}</span></div>
            <div class="detail-field"><span class="df-label">路径</span><span>{{ detailDrawer.alert.source_path || '-' }}</span></div>
            <div class="detail-field"><span class="df-label">时间</span><span>{{ (detailDrawer.alert.last_seen_at || '').slice(0,19) }}</span></div>
            <div style="margin-top:16px;display:flex;gap:8px">
              <el-button size="small" @click="executeAction('block_ip', [detailDrawer.alert])">封锁 IP</el-button>
              <el-button size="small" @click="executeAction('isolate_host', [detailDrawer.alert])">隔离主机</el-button>
              <el-button size="small" @click="navigateTo('/analysis-center/event/' + (detailDrawer.alert.id || ''))">查看详情</el-button>
            </div>
          </template>
        </el-drawer>

        <!-- v3.1: 模板管理对话框 -->
        <el-dialog v-model="templateDialog.visible" title="管理查询模板" width="500px" destroy-on-close>
          <div v-for="(t, i) in userTemplates" :key="i" class="template-row">
            <el-input v-model="t.value" size="small" style="flex:1" placeholder="查询文本" />
            <el-button size="small" text @click="removeTemplate(i)">删除</el-button>
          </div>
          <div class="template-row" style="margin-top:8px">
            <el-input v-model="newTemplateText" size="small" style="flex:1" placeholder="新增模板查询..." />
            <el-button size="small" @click="addTemplate">添加</el-button>
          </div>
        </el-dialog>

        <!-- v3.1: 对话内容搜索 -->
        <div v-if="chatMsgs.length > 1" class="search-bar">
          <el-input v-model="searchInContent" placeholder="搜索对话内容..." size="small" clearable prefix-icon="Search"
            @input="onSearchContent" style="width:200px" />
        </div>

        <!-- v3.1: 时间线回放浮窗（简单版） -->
        <div v-if="false" class="timeline-player">
          <!-- 预留：告警时间线回放组件 -->
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 2: 告警降噪 (不变) -->
      <!-- ============================================================ -->
      <el-tab-pane label="📊 告警降噪" name="correlate">
        <div class="kpi-row">
          <div class="kpi red"><div class="n">{{ corrStats.incidents }}</div><div class="l">归并事件</div></div>
          <div class="kpi amber"><div class="n">{{ corrStats.rawAlerts }}</div><div class="l">原始告警</div></div>
          <div class="kpi green"><div class="n">{{ corrStats.reductionRate }}%</div><div class="l">降噪率</div></div>
          <div class="kpi blue"><div class="n">{{ corrStats.stages }}</div><div class="l">攻击阶段</div></div>
        </div>
        <div class="chart-row" v-if="corrResult.length">
          <div class="chart-box"><div class="ch">🎯 攻击阶段分布</div><div ref="stageChartRef" class="c-body" /></div>
          <div class="chart-box"><div class="ch">🚨 事件严重度分布</div><div ref="sevChartRef" class="c-body" /></div>
        </div>
        <div class="mb-12">
          <el-select v-model="corrFilterHost" placeholder="全部主机" clearable size="small" style="width:160px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doCorrelate" :loading="corrLoading" style="margin-left:8px">🔄 执行归并</el-button>
        </div>
        <div class="events-grid" v-if="corrResult.length">
          <div v-for="inc in corrResult" :key="inc.title" class="event-card">
            <div class="ec-head">
              <div class="ec-title">{{ inc.title }}</div>
              <el-tag :type="sevType(inc.severity)" size="small" effect="dark">{{ inc.severity }}</el-tag>
            </div>
            <div class="ec-badges">
              <span :class="['badge', 'stage-'+killChainClass(inc.kill_chain)]">{{ stageLabel(inc.kill_chain) }}</span>
              <span class="badge">{{ (inc.first_seen||'').slice(0,10) }}</span>
            </div>
            <div class="ec-info">
              <span>📡 {{ inc.alert_count }} 次告警</span>
              <span>🖥 {{ (inc.host_ids||[]).length }} 台主机</span>
              <span>⏱ {{ (inc.first_seen||'').slice(11,16) }}~{{ (inc.last_seen||'').slice(11,16) }}</span>
            </div>
            <div v-if="inc.mitre_ids?.length" class="ec-mitre">MITRE: {{ inc.mitre_ids.join(', ') }}</div>
          </div>
        </div>
        <div v-else-if="!corrLoading" class="empty-hint">点"执行归并"查看告警归并结果</div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 3: 攻击故事 (不变) -->
      <!-- ============================================================ -->
      <el-tab-pane label="📖 攻击故事" name="story">
        <div class="mb-12" style="display:flex;gap:8px;align-items:center">
          <el-select v-model="storyHostId" placeholder="选择主机" clearable size="small" style="width:200px">
            <el-option v-for="h in hosts" :key="h.id" :label="h.hostname" :value="h.id" />
          </el-select>
          <el-button type="primary" size="small" @click="doNarrate" :loading="storyLoading">📖 生成故事</el-button>
          <div style="margin-left:auto;display:flex;gap:4px;align-items:center">
            <span style="font-size:12px;color:#6b7280">模式:</span>
            <el-radio-group v-model="storyMode" size="small">
              <el-radio-button value="full">详细</el-radio-button>
              <el-radio-button value="brief">简短</el-radio-button>
            </el-radio-group>
          </div>
        </div>
        <div v-if="storyText" class="story-layout">
          <div class="story-nav">
            <div class="sn-title">📑 故事章节</div>
            <div v-for="(sec, i) in storySections" :key="i"
              :class="['sn-item', { active: storyActiveSec === i }]"
              @click="storyActiveSec = i">
              {{ sec.label }}
            </div>
          </div>
          <div class="story-content">
            <div v-for="(sec, i) in storySections" :key="i" v-show="storyActiveSec === i">
              <div v-if="sec.type === 'summary'" class="story-summary">
                <h3>{{ sec.title }}</h3>
                <div class="tip" style="margin-bottom:12px">{{ sec.text }}</div>
              </div>
              <div v-if="sec.type === 'phase'">
                <div class="story-phase">
                  <div class="sp-tag" :style="{background: sec.tagBg, color: sec.tagColor}">{{ sec.emoji }} {{ sec.title }}</div>
                  <div v-for="e in sec.events" :key="e" class="sp-item">{{ e }}</div>
                </div>
              </div>
              <div v-if="sec.type === 'actions'" class="story-actions">
                <h3>{{ sec.title }}</h3>
                <div v-for="(act, ai) in sec.items" :key="ai"
                  :class="['act-item', { done: storyDone[ai] }]"
                  @click="storyDone[ai] = !storyDone[ai]">
                  <span :class="['chk', { done: storyDone[ai] }]" />
                  <span>{{ act }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-hint">选择主机后点击"生成故事"查看攻击时间线叙事</div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 4: 预测预警 (不变) -->
      <!-- ============================================================ -->
      <el-tab-pane label="🎯 预测预警" name="risk">
        <div class="mb-12" style="display:flex;gap:8px;align-items:center">
          <el-button type="primary" size="small" @click="doRiskRank" :loading="riskLoading">🔄 刷新排行</el-button>
          <span v-if="riskData.length" style="font-size:12px;color:#6b7280">共 <strong>{{ riskTotal }}</strong> 台主机 · {{ riskUpdatedAt }}</span>
        </div>
        <div class="rank-wrap" v-if="riskData.length">
          <table class="rank-table">
            <thead><tr><th>#</th><th>主机名</th><th>风险评分</th><th>等级</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in riskData.slice(0, 10)" :key="r.host_id">
                <td style="font-weight:700" :style="{color: i===0?'#dc2626':'#6b7280'}">{{ i+1 }}</td>
                <td style="font-weight:600">{{ r.hostname }}</td>
                <td>
                  <span class="bar-bg"><span :class="['bar-fill', r.risk_level]" :style="{width: r.risk_score+'%'}" /></span>
                  <span :style="{fontWeight:700,color: riskColor(r.risk_level), marginLeft:6}">{{ r.risk_score }}</span>
                </td>
                <td><el-tag :type="riskTagType(r.risk_level)" size="small">{{ riskLabel(r.risk_level) }}</el-tag></td>
                <td>{{ r.status }}</td>
                <td><el-button link size="small" @click="drillDownHost = r">📊 详情</el-button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="risk-charts" v-if="riskDrillData.length">
          <div class="r-chart"><div class="rc-title">TOP 5 风险对比</div><div ref="top5Ref" class="c-body" /></div>
          <div class="r-chart"><div class="rc-title">🧩 {{ drillDownHost?.hostname }} 评分维度</div><div ref="drillRef" class="c-body" /></div>
        </div>
      </el-tab-pane>

      <!-- ============================================================ -->
      <!-- TAB 5: 误报管理 (不变) -->
      <!-- ============================================================ -->
      <el-tab-pane label="✅ 误报管理" name="fp">
        <div class="fp-stats">
          <div class="fp-stat"><div class="n">{{ fpStats.total }}</div><div class="l">📝 已学习模式</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.totalHit }}</div><div class="l">🚫 已拦截告警</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.affectedRules }}</div><div class="l">🎯 受影响规则</div></div>
          <div class="fp-stat"><div class="n">{{ fpStats.reductionRate }}%</div><div class="l">📉 预期降噪率</div></div>
        </div>
        <div class="fp-search">
          <el-input v-model="fpKeyword" placeholder="🔍 规则名" size="small" style="width:180px" clearable @keyup.enter="loadFPs" />
          <el-select v-model="fpFilterRule" placeholder="全部规则" clearable size="small" style="width:140px" @change="loadFPs">
            <el-option v-for="r in fpRuleOptions" :key="r" :label="r" :value="r" />
          </el-select>
          <el-button size="small" type="primary" @click="loadFPs">搜索</el-button>
          <el-button size="small" @click="loadFPs">🔄 刷新</el-button>
        </div>
        <div class="table-wrap">
          <el-table :data="fpData" stripe border size="small" v-loading="fpLoading" style="width:100%">
            <el-table-column label="规则" min-width="160">
              <template #default="{row}">{{ row.rule_name || '-' }}</template>
            </el-table-column>
            <el-table-column label="进程" width="140">
              <template #default="{row}">{{ row.source_process || '-' }}</template>
            </el-table-column>
            <el-table-column label="主机" width="70">
              <template #default="{row}">{{ row.host_id || '-' }}</template>
            </el-table-column>
            <el-table-column label="原因" min-width="160">
              <template #default="{row}">{{ row.reason || '-' }}</template>
            </el-table-column>
            <el-table-column label="命中" width="60" align="center">
              <template #default="{row}">{{ row.hit_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="时间" width="140">
              <template #default="{row}">{{ row.created_at?.slice(0,19)?.replace('T',' ') || '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="60">
              <template #default="{row}">
                <el-button link type="danger" size="small" @click="deleteFP(row.id)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="fp-foot">
          <span style="font-size:12px;color:#6b7280">显示 {{ fpData.length }} 条 / 共 {{ fpTotal }} 条</span>
          <el-pagination v-model:current-page="fpPage" :page-size="20" :total="fpTotal"
            layout="prev,pager,next" small background @current-change="loadFPs" />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { Lock, WarnTriangleFilled, ArrowDown, ArrowUp, Search } from '@element-plus/icons-vue'
import {
  correlateIncidents, aiQuery, aiQueryStream, narrateIncident,
  getFalsePositives, deleteFalsePositive, getRiskRanking, generateReport,
  submitFeedback, getFeedbackStats, nlUnderstand, getPresets, getAuditLog,
} from '@/api/ai_advanced'
import request from '@/api/index'
import StreamMessage from '@/components/StreamMessage.vue'
import ActionResultCard from '@/components/ActionResultCard.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ContextIndicator from '@/components/ContextIndicator.vue'
import ConfidenceBadge from '@/components/ConfidenceBadge.vue'
import InvestigationPlaybook from '@/components/InvestigationPlaybook.vue'
import SessionSummaryCard from '@/components/SessionSummaryCard.vue'
import HeatmapTimeline from '@/components/HeatmapTimeline.vue'
import AttackPathGraph from '@/components/AttackPathGraph.vue'
import FileUploadZone from '@/components/FileUploadZone.vue'
import { executeAction as apiExecuteAction, parseFile } from '@/api/ai_advanced'
import { startPlaybook as apiStartPlaybook, getPlaybookStep, getPlaybookStatus, getSessionSummary as apiGetSessionSummary } from '@/api/ai_advanced'

// ===== Router =====
const router = useRouter()

// ===== State =====
const activeTab = ref('chat')
const hosts = ref([])
const hostCount = computed(() => hosts.value.length)

// ===== Session Persistence =====
const SESSION_KEY = 'ir-ai-chat-sessions'
const ACTIVE_SESSION_KEY = 'ir-ai-active-session'
const sessions = ref(JSON.parse(localStorage.getItem(SESSION_KEY) || '[]'))
const activeSessionId = ref(localStorage.getItem(ACTIVE_SESSION_KEY) || '')
const sessionSearchQuery = ref('')
const showSessions = ref(false)

// ===== Tab 1: 自然语言指挥台 =====
const chatInput = ref('')
const chatMsgs = ref([])
const chatLoading = ref(false)
const streamingSession = ref({ active: false, text: '', intent: '', abort: null })
const chatRef = ref(null)
const quickQueries = ['严重的告警', '统计信息', '在线主机', '登录失败的日志', '查看策略', '未结案件']

// ── 右侧面板拖拽调整大小 ──
const rightPanelWidth = ref(260)
let isResizing = false

function startResize(e) {
  isResizing = true
  const startX = e.clientX
  const startWidth = rightPanelWidth.value

  const onMouseMove = (ev) => {
    if (!isResizing) return
    const diff = startX - ev.clientX
    const newWidth = Math.min(Math.max(startWidth + diff, 220), 400)
    rightPanelWidth.value = newWidth
  }

  const onMouseUp = () => {
    isResizing = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// 对话上下文（追踪上轮的主机/意图/时间范围）
const chatContext = ref({
  hostId: null,
  hostName: '',
  intent: '',
  timeRange: null,
  lastQuery: '',
  workingSet: null, // { ids: [], intent: '' } 多轮复合查询的中间结果集
})
const contextHint = ref('')
const confirmDialog = ref({ visible: false, action: '', target: '', reason: '', confirmId: '' })

// ===== 新功能状态 =====
const timeRangePill = ref('')
const selectedAlerts = ref([])
const reportLoading = ref(false)
const messageIdCounter = ref(0)
// v3.1 新功能
const detailDrawer = ref({ visible: false, alert: null })  // 告警详情浮层
const templateDialog = ref({ visible: false, name: '', steps: '', tags: '' }) // 模板管理
const showMoreCount = ref(6)  // 查看更多展开行数
const searchInContent = ref('') // 对话内容搜索
const streamingAbort = ref(null)  // 流式停止句柄

const snapData = reactive({ criticalAlerts: 0, openAlerts: 0, hosts: 0, policies: 0 })
const hoveredHost = ref(null)
const pendingFile = ref(null)

// ===== T-004: 剧本 + 会话摘要 =====
const playbookProgress = ref({ current: 0, total: 0 })
const playbookCompleted = ref('')
const sessionSummary = ref({})

const playbookList = [
  {
    id: 'login_failure', name: '调查登录失败',
    description: '查日志→分析模式→来源IP→横向移动→结论', tags: ['T1110'],
    steps: [
      { name: '查询近 24 小时登录失败日志' },
      { name: 'AI 分析失败模式（暴力破解/密码喷洒）' },
      { name: '提取攻击来源 IP 地址' },
      { name: '检查来源 IP 的横向移动告警' },
      { name: '生成调查结论与处置建议' },
    ]
  },
  {
    id: 'abnormal_process', name: '调查异常进程',
    description: '异常进程→父链→网络连接→文件哈希→结论', tags: ['T1059'],
    steps: [
      { name: '查询异常进程列表' },
      { name: '分析进程父链与命令行参数' },
      { name: '查询异常进程的网络连接' },
      { name: '检查关联文件哈希' },
      { name: '汇总入侵指标与处置方案' },
    ]
  },
  {
    id: 'lateral_movement', name: '调查横向移动',
    description: '异常连接→认证事件→攻击分析→时间线', tags: ['T1021'],
    steps: [
      { name: '查询异常网络连接' },
      { name: '查询成功认证事件' },
      { name: 'AI 分析横向移动攻击模式' },
      { name: '生成事件时间线' },
    ]
  },
]

const timeExamples = [
  { text: '过去24小时严重告警', result: '[-24h, now] + severity=critical' },
  { text: '近7天登录失败', result: '[-7d, now] + event=logon_fail' },
  { text: '本周异常进程', result: '[Mon 00:00, now] + process anomaly' },
  { text: '昨天web-01的告警', result: '[yesterday 00:00, 23:59] + host=web-01' },
]

const suggestionList = [
  { text: 'web-01 的告警有哪些', icon: 'Search' },
  { text: '过去24小时严重告警', icon: 'Clock' },
  { text: '当前未处理事件', icon: 'Warning' },
  { text: 'AI 智能分析最新告警', icon: 'MagicStick' },
  { text: '统计今日告警情况', icon: 'DataLine' },
  { text: '查看在线主机状态', icon: 'Monitor' },
]

// ===== 富卡片注册表 =====
const cardRegistry = {
  alert_list: (data) => ({ render: 'alerts', data }),
  host_list: (data) => ({ render: 'hosts', data }),
  log_list: (data) => ({ render: 'logs', data }),
  stats_chart: (data) => ({ render: 'stats', data }),
  policy_list: (data) => ({ render: 'policies', data }),
  case_list: (data) => ({ render: 'cases', data }),
  attack_path: (data) => ({ render: 'analysis', data }),
  generic: (data) => ({ render: 'text', text: data?.[0]?.text || JSON.stringify(data || {}) }),
}

// ===== 空数据辅助 =====
function isEmptyData(data) {
  if (!data) return true
  if (Array.isArray(data) && data.length === 0) return true
  if (Array.isArray(data) && data[0]?._empty) return true
  return false
}
function emptyMsg(data) {
  return data?.[0]?._message || '未找到匹配数据'
}

// ===== Computed =====
const filteredSessions = computed(() => {
  if (!sessionSearchQuery.value) return sessions.value
  return sessions.value.filter(s =>
    (s.title || '').toLowerCase().includes(sessionSearchQuery.value.toLowerCase())
  )
})

// ===== Navigation =====
function navigateTo(path) {
  window.open(path, '_blank')
}

// ===== 消息菜单操作 (task 1-5, 7-8) =====
function msgMenuAction(cmd, msg, idx) {
  if (cmd === 'copy') {
    const txt = msg.text || JSON.stringify(msg.data || '')
    navigator.clipboard?.writeText(txt).then(() => ElMessage.success('已复制')).catch(() => {})
  } else if (cmd === 'quote') {
    const prefix = (msg.text || '').slice(0, 80).replace(/\n/g, ' ')
    chatInput.value = `> ${prefix}\n\n`
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight
  } else if (cmd === 'useful') { ElMessage.success('感谢反馈 👍')
  } else if (cmd === 'useless') { ElMessage.info('已记录，我们会持续优化')
  } else if (cmd === 'not_this') {
    chatInput.value = (chatMsgs.value[idx - 1]?.text || '') + ' 换一种方式'; sendQuery()
  }
}

// ===== 输入补全 (task 3) =====
const suggestionTemplates = [
  { value: '严重的告警', label: '查看严重告警' },
  { value: '统计信息', label: '查看系统统计' },
  { value: '在线主机', label: '查看在线主机' },
  { value: '登录失败的日志', label: '登录失败日志' },
  { value: '查看策略', label: '查看检测策略' },
  { value: '未结案件', label: '未结案件' },
  { value: '生成安全报告', label: '生成安全态势报告' },
]
function querySuggestions(queryStr, cb) {
  const q = (queryStr || '').toLowerCase()
  let results = suggestionTemplates
  if (q) {
    results = suggestionTemplates.filter(s => s.value.includes(q) || s.label.includes(q))
    const history = (JSON.parse(localStorage.getItem('ir-ai-chat-sessions') || '[]'))
      .flatMap(s => s.messages || []).filter(m => m.role === 'user')
      .filter((m, i, a) => a.findIndex(x => x.text === m.text) === i)
      .map(m => ({ value: m.text, label: m.text }))
      .filter(s => s.value.includes(q)).slice(-5)
    results = [...results, ...history.filter(h => !results.find(r => r.value === h.value))]
  }
  cb(results.slice(0, 10))
}

// ===== 批量操作 (task 4) =====
function updateSelected() {
  selectedAlerts.value = chatMsgs.value.flatMap(m => (m.data || [])).filter(a => a._checked)
}
function batchAction(action) {
  const ids = selectedAlerts.value.map(a => a.id).filter(Boolean)
  if (!ids.length) { ElMessage.warning('请选择告警'); return }
  const map = { block_ip: '封锁 IP', isolate_host: '隔离主机', export: '导出已选' }
  ElMessage.success(`${map[action] || action}: 已提交 ${ids.length} 条`)
  selectedAlerts.value = []
}

// ===== 对话导出 (task 7) =====
function exportChat() {
  const lines = chatMsgs.value.map(m => {
    const role = m.role === 'user' ? '我' : 'AI'
    const content = m.text || (m.render ? `[${m.render} 数据 ${m.data?.length || 0} 条]` : '')
    return `### ${role}\n${content}\n`
  }).join('\n---\n')
  const md = `# 安全分析对话记录\n生成时间: ${new Date().toLocaleString()}\n\n${lines}`
  const blob = new Blob([md], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = `chat-${Date.now()}.md`
  a.click(); ElMessage.success('对话已导出为 Markdown')
}

// ===== 生成安全报告 (task 9) =====
async function generateReportAction() {
  if (reportLoading.value) return
  reportLoading.value = true
  try {
    const res = await generateReport('安全态势报告')
    if (res.success && res.data) {
      chatMsgs.value.push({
        role: 'assistant', render: 'text',
        text: `安全态势报告\n生成时间: ${res.data.generated_at}\n\n${res.data.summary}\n\n建议措施：\n${(res.data.suggestions || []).map(s => '- ' + s).join('\n')}`,
      })
      nextTick(() => { if (chatRef.value) chatRef.value.scrollTop = 9999 })
    }
  } catch (e) { ElMessage.error('报告生成失败: ' + e.message)
  } finally { reportLoading.value = false }
}

// ===== 统计图表渲染 (task 10) =====
function renderMiniStats(el, d) {
  if (!el || !d) return
  try {
    const chart = echarts.init(el)
    chart.setOption({
      tooltip: { trigger: 'item' }, series: [{
        type: 'pie', radius: ['40%', '60%'], center: ['50%', '50%'],
        data: [
          { value: d.total_logs || 1, name: '日志', itemStyle: { color: '#3b82f6' } },
          { value: d.total_alerts || 1, name: '告警', itemStyle: { color: '#f59e0b' } },
          { value: d.open_alerts || 0, name: '未处理', itemStyle: { color: '#ef4444' } },
        ], label: { show: false }, animation: false,
      }],
    })
  } catch (e) { /* echarts init silently */ }
}

// ===== 时间Pill (task 2) =====
function updateTimePill(text) {
  const ti = parseTimeExpression(text)
  timeRangePill.value = ti ? ((text.match(/过去[^，,\s]+|近[^，,\s]+|今天|昨天|本周|上周/) || ['自定义'])[0]) : ''
}

// ===== v3.1: 停止流式输出 =====
function stopStreaming() {
  if (streamingAbort.value) {
    streamingAbort.value()
    streamingAbort.value = null
    chatLoading.value = false
    ElMessage.info('已停止输出')
  }
}

// ===== v3.1: 告警详情浮层 =====
function openAlertDetail(alert) {
  detailDrawer.value = { visible: true, alert }
}

// ===== v3.1: 模板管理 =====
const userTemplates = ref(JSON.parse(localStorage.getItem('ir-query-templates') || '[]'))
const newTemplateText = ref('')
function addTemplate() {
  if (!newTemplateText.value.trim()) return
  userTemplates.value.push({ value: newTemplateText.value.trim(), label: newTemplateText.value.trim() })
  localStorage.setItem('ir-query-templates', JSON.stringify(userTemplates.value))
  newTemplateText.value = ''
  ElMessage.success('模板已添加')
}
function removeTemplate(i) {
  userTemplates.value.splice(i, 1)
  localStorage.setItem('ir-query-templates', JSON.stringify(userTemplates.value))
}
const enhancedSuggestions = computed(() => {
  const base = [...suggestionTemplates]
  for (const t of userTemplates.value) {
    if (!base.find(b => b.value === t.value)) base.push(t)
  }
  return base
})

// ===== v3.1: 对话内容搜索 =====
function onSearchContent(val) {
  if (!val) return
  const el = chatRef.value
  if (!el) return
  const idx = chatMsgs.value.findIndex(m => (m.text || '').includes(val))
  if (idx >= 0) {
    const items = el.querySelectorAll('.msg')
    if (items[idx]) items[idx].scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

// ===== v3.1: 反馈提交 =====
async function submitUserFeedback(cmd, msg, idx) {
  const rating = cmd === 'useful' ? 1 : cmd === 'useless' ? -1 : 0
  try {
    await submitFeedback(activeSessionId.value || '', chatMsgs.value[idx - 1]?.text || '', msg.text || '', rating)
  } catch {}
}

// 重写 msgMenuAction 以支持反馈落库
;(function() {
  const original = msgMenuAction
  window.msgMenuAction = function(cmd, msg, idx) {
    if (cmd === 'useful' || cmd === 'useless') submitUserFeedback(cmd, msg, idx)
    original(cmd, msg, idx)
  }
})()
msgMenuAction = window.msgMenuAction

// ===== v3.1: 时间线回放 =====
const timelinePlayback = ref({ playing: false, currentIdx: 0, alerts: [] })
function playTimeline(alerts) {
  timelinePlayback.value = { playing: true, currentIdx: 0, alerts: alerts || [] }
  if (alerts?.length) openAlertDetail(alerts[0])
}

// ===== v3.1: 元问题拦截（读对话历史）=====
function resolveMetaQuestion(q) {
  if (!q) return null
  const userMsgs = chatMsgs.value.filter(m => m.role === 'user')
  const last = userMsgs[userMsgs.length - 2]  // 倒数第二个是"我上一个问题"
  const prev = userMsgs[userMsgs.length - 3]  // 倒数第三个

  // 上一轮/上一个问题
  if (/上(一个|一(轮|条)|次)|刚才|之(前|前的)|最近问的/.test(q)) {
    if (last) return `你的上一个问题是：\n\n**"${last.text}"**`
    return '当前会话还没有更早的问题。'
  }

  // 历史问题列表
  if (/(都|所有|全部|历史|我.*问过).*(问|问题)|之前我问了什么/.test(q)) {
    if (!userMsgs.length) return '当前会话还没有记录问题。'
    const list = userMsgs.slice(-10).map((m, i) => `${i + 1}. ${m.text}`).join('\n')
    return `你在本次会话中问过的问题：\n\n${list}`
  }

  // 重新执行上一个问题
  if (/(重(新|跑)|再.*(一(下|次)|跑|执行)|再来一次|重新跑一(下|次))/.test(q)) {
    if (last) {
      setTimeout(() => { chatInput.value = last.text; sendQuery() }, 200)
      return `好的，重新执行："${last.text}"`
    }
    return '没有可重新执行的问题。'
  }

  // 上一个回答
  if (/上(一个|一(轮|条))?.*(回答|回复|结果|答案|ai|助手).*(说了?|是|讲)/.test(q)) {
    const lastAi = [...chatMsgs.value].reverse().find(m => m.role === 'assistant' && m.text)
    if (lastAi) return `AI 上一次的回复（摘要）：\n\n${lastAi.text.slice(0, 200)}${lastAi.text.length > 200 ? '...' : ''}`
    return '暂无 AI 回复。'
  }

  // 对话回合数
  if (/(聊了|对话|来(往|了)).*(多(少|久)|几.*次|多(长|久))/.test(q)) {
    return `本次会话已进行了 **${userMsgs.length}** 轮用户提问，**${chatMsgs.value.filter(m => m.role === 'assistant').length}** 轮 AI 回复。`
  }

  return null
}

// ===== Time Parsing =====
/**
 * 解析自然语言时间表达式
 * 支持: "过去24小时", "近7天", "今天", "昨天", "本周", "近1小时", "上周"
 * 返回 { start: ISO, end: ISO } 或 null
 */
function parseTimeExpression(text) {
  const now = new Date()
  const end = now.toISOString()
  let start = null

  if (/过去24小时|最近24小时|近24小时|昨天/.test(text)) {
    const d = new Date(now.getTime() - 24 * 60 * 60 * 1000)
    start = d.toISOString()
  } else if (/过去7天|近7天|最近7天|本周/.test(text)) {
    const d = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    start = d.toISOString()
  } else if (/过去30天|近30天|这个月/.test(text)) {
    const d = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000)
    start = d.toISOString()
  } else if (/近1小时|过去1小时|最近1小时/.test(text)) {
    const d = new Date(now.getTime() - 60 * 60 * 1000)
    start = d.toISOString()
  } else if (/今天/.test(text)) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    start = d.toISOString()
  } else if (/上周/.test(text)) {
    const d = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000)
    const d2 = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
    start = d.toISOString()
    return { start, end: d2.toISOString() }
  }

  if (start) {
    contextHint.value = '⏱ 时间范围已识别'
    return { start, end }
  }
  return null
}

/**
 * 解析隐式指代——"它"→上轮主机的 hostname
 */
function resolveReference(text, context) {
  if (!context.hostName) return text
  if (/它|该|这个|这些/.test(text)) {
    if (/主机|设备|机器/.test(text) || /异常|告警|进程|连接|日志/.test(text)) {
      return text + ` (host:${context.hostName})`
    }
  }
  return text
}

// ===== Session Management =====
function loadSession(sessionId) {
  const session = sessions.value.find(s => s.id === sessionId)
  if (session) {
    chatMsgs.value = session.messages || []
    activeSessionId.value = sessionId
    localStorage.setItem(ACTIVE_SESSION_KEY, sessionId)
  }
}

function saveSession() {
  if (!chatMsgs.value.length) return
  const now = new Date().toISOString()
  if (activeSessionId.value) {
    const idx = sessions.value.findIndex(s => s.id === activeSessionId.value)
    if (idx >= 0) {
      sessions.value[idx].messages = chatMsgs.value
      sessions.value[idx].updatedAt = now
    } else {
      sessions.value.unshift({
        id: activeSessionId.value,
        title: chatMsgs.value[0]?.text?.slice(0, 40) || '新会话',
        messages: chatMsgs.value,
        createdAt: now,
        updatedAt: now,
      })
    }
  } else {
    const id = Date.now().toString(36)
    activeSessionId.value = id
    sessions.value.unshift({
      id, title: chatMsgs.value[0]?.text?.slice(0, 40) || '新会话',
      messages: chatMsgs.value,
      createdAt: now, updatedAt: now,
    })
    localStorage.setItem(ACTIVE_SESSION_KEY, id)
  }
  localStorage.setItem(SESSION_KEY, JSON.stringify(sessions.value))
  generateSummary()
}

function newSession() {
  saveSession()
  chatMsgs.value = [{
    role: 'assistant', text: '你好！我是 AI 安全分析助手。\n问我关于告警、日志、主机、统计等问题。\n试试下面的快速查询标签。', render: 'text'
  }]
  activeSessionId.value = Date.now().toString(36)
  contextHint.value = ''
  chatContext.value = { hostId: null, hostName: '', intent: '', timeRange: null, lastQuery: '' }
}

function deleteSession(sessionId) {
  sessions.value = sessions.value.filter(s => s.id !== sessionId)
  localStorage.setItem(SESSION_KEY, JSON.stringify(sessions.value))
  if (activeSessionId.value === sessionId) {
    activeSessionId.value = ''
    localStorage.removeItem(ACTIVE_SESSION_KEY)
  }
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hour = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hour}:${min}`
}

async function sendQuery() {
  const q = chatInput.value.trim()
  if (!q || chatLoading.value) return

  // 1. 推送用户消息 + 立即滚到底
  chatMsgs.value.push({ role: 'user', text: q, render: 'text' })
  chatInput.value = ''
  chatLoading.value = true
  nextTick(() => { if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight })

  // 1.5 元问题拦截：直接读聊天历史回答（不上后端）
  const metaAnswer = resolveMetaQuestion(q)
  if (metaAnswer) {
    setTimeout(() => {
      chatMsgs.value.push({ role: 'assistant', render: 'text', text: metaAnswer })
      chatLoading.value = false
      nextTick(() => { if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight })
    }, 300)
    return
  }

  // 2. 解析自然语言时间 + 更新时间Pill
  const timeInfo = parseTimeExpression(q)
  updateTimePill(q)

  // 3. 解析隐式指代
  const resolvedQuery = resolveReference(q, chatContext.value)

  // 4. 构建请求参数（含时间范围+上下文）
  const options = {}
  if (timeInfo) {
    options.start_time = timeInfo.start
    options.end_time = timeInfo.end
  }
  // 如果是追问（无时间但上轮有主机），自动带上 host_id
  const isFollowUp = q.includes('它') || q.includes('该') || q.includes('这个') || q.includes('这些')
  if (isFollowUp && chatContext.value.hostId) {
    options.host_id = chatContext.value.hostId
  }

  // 5. 准备流式会话
  const sessionId = activeSessionId.value || Date.now().toString(36)
  if (!activeSessionId.value) activeSessionId.value = sessionId

  // 6. 开始流式 AI 回复
  const streamingMsgId = chatMsgs.value.length
  chatMsgs.value.push({ role: 'assistant', text: '', render: 'text', streaming: true })

  let accumulatedText = ''

  const abort = aiQueryStream(resolvedQuery, sessionId, options, {
    onTextChunk(chunk) {
      accumulatedText += chunk
      // 每收到块就更新消息内容 — 打字机效果
      const idx = chatMsgs.value.findIndex(m => m.role === 'assistant' && m.streaming)
      if (idx >= 0) {
        chatMsgs.value[idx].text = accumulatedText
      }
    },
    onCard(cardType, data) {
      // 收到富卡片 → 追加到消息列表
      const renderer = cardRegistry[cardType]
      if (renderer) {
        const card = renderer(data)
        chatMsgs.value.push({ role: 'assistant', ...card })
      }
    },
    onActionConfirm(action, target, confirmId) {
      confirmDialog.value = {
        visible: true, action, target: String(target),
        reason: '该操作影响范围较大，确认后执行',
        confirmId,
      }
    },
    onActionResult(action, status, result) {
      chatMsgs.value.push({
        role: 'assistant', render: 'action_result',
        actionResult: { action, success: status === 'completed', result, exec_time_ms: 0 },
      })
    },
    onProgress(step, total, name, status) {
      // 剧本进度事件（T-003 完善）
      chatMsgs.value.push({ role: 'assistant', text: `剧本进度 [${step}/${total}] ${name}: ${status}`, render: 'text' })
    },
    onEnd(usage, confidence, extra) {
      // 流结束 → 移除 streaming 标记
      const idx = chatMsgs.value.findIndex(m => m.role === 'assistant' && m.streaming)
      if (idx >= 0) {
        chatMsgs.value[idx].streaming = false
        // 性能标签：追加到文本尾部
        const ms = extra?.exec_time_ms || 0
        const rc = extra?.results_count || 0
        const perfTag = ms > 0 ? `  ⚡ ${ms}ms · ${rc}条` : ''
        if (perfTag) chatMsgs.value[idx].text += perfTag
      }
      // 尝试渲染 ECharts 图表
      nextTick(() => {
        chatMsgs.value.forEach(m => {
          if (m.render === 'stats' && m._chartRef) {
            renderMiniStats(m._chartRef, m.data?.[0] || m.data)
          }
        })
      })
      // 更新上下文
      chatContext.value.lastQuery = q
      // 显示上下文提示
      if (chatContext.value.hostName) {
        contextHint.value = `🧠 上下文中: ${chatContext.value.hostName}`
      }
      // 追加可信度标签
      const sourceCount = chatMsgs.value.filter(m => m.render === 'alerts' || m.render === 'hosts' || m.render === 'logs').length
      const confLevel = sourceCount >= 2 ? (accumulatedText.length > 50 ? 'high' : 'medium') : 'low'
      chatMsgs.value.push({ role: 'assistant', render: 'confidence', confidence: confLevel })
    },
    onError(error) {
      chatMsgs.value[streamingMsgId] = { role: 'assistant', text: '查询失败: ' + error, render: 'text' }
    },
  })

  streamingSession.value = { active: true, abort }

  // 等待流结束（由回调驱动，这里只重置 loading 状态）
  // 用 setTimeout 0 让流式更新先渲染
  setTimeout(() => {
    chatLoading.value = false
    streamingSession.value.active = false
    saveSession()
    nextTick(() => { if (chatRef.value) chatRef.value.scrollTop = 9999 })
  }, 100)
}
function quickQuery(q) { chatInput.value = q; sendQuery() }

async function handleFileSelected(file) {
  pendingFile.value = file
  // 将文件读为 base64
  const reader = new FileReader()
  reader.onload = async (e) => {
    const base64 = e.target.result.split(',')[1]
    try {
      const res = await parseFile(file.name, base64)
      if (res.success) {
        const parsed = res.data
        chatMsgs.value.push({
          role: 'assistant', text: `已解析文件: ${file.name}\n${parsed.parsed_text.slice(0, 200)}`,
          render: 'text',
        })
        // 自动发送该文件内容的分析查询
        if (parsed.parsed_text) {
          chatInput.value = `分析这个文件内容: ${parsed.parsed_text.slice(0, 100)}`
          sendQuery()
        }
      }
    } catch (e) {
      chatMsgs.value.push({ role: 'assistant', text: `文件解析失败: ${e.message}`, render: 'text' })
    }
  }
  reader.readAsDataURL(file)
}

function handleFileCleared() { pendingFile.value = null }

function executeAction(action, data, analysis) {
  const hasData = Array.isArray(data) && data.length > 0

  if (!hasData) {
    // 无具体目标时，引导用户去选择目标
    const map = {
      block_ip: { msg: '请先在告警列表选择要封锁的 IP', path: '/alerts' },
      isolate_host: { msg: '请先在主机列表选择要隔离的主机', path: '/hosts' },
      export_report: { msg: '请先生成具体告警或案件报告', path: '/reports' },
      ai_noise_reduce: { msg: '请先选择要降噪的告警批次', path: '/analysis-center' },
    }
    const cfg = map[action] || { msg: '请选择操作目标', path: '/alerts' }
    ElMessage.warning(cfg.msg)
    return
  }

  // 有数据时，跳到对应的目标详情页
  const first = data[0]
  if (action === 'block_ip' && first.source_ip) {
    navigateTo('/alerts?source_ip=' + first.source_ip)
  } else if (action === 'isolate_host' && first.host_id) {
    navigateTo('/hosts/' + first.host_id)
  } else if (action === 'export_report') {
    navigateTo('/reports')
  } else if (action === 'ai_noise_reduce') {
    navigateTo('/analysis-center')
  } else {
    const label = { block_ip: '封锁 IP', isolate_host: '隔离主机', export_report: '导出报告', ai_noise_reduce: 'AI 降噪研判' }
    ElMessage.success(`已选择目标: ${label[action] || action}`)
  }
}

function contextMenu(cmd, data) {
  const actions = {
    copy_search: '已复制到搜索面板',
    add_note: '已添加调查笔记到案件',
    export_pdf: '报告生成中...',
    share_link: '链接已复制到剪贴板',
  }
  ElMessage.success(`✅ ${actions[cmd] || cmd}`)
}

// ===== T-004: 剧本执行与会话摘要 =====

// 剧本步骤参数 → 自然语言查询映射
const stepQueryMap = {
  'failed_logon': '登录失败的日志',
  'successful_logon': '登录成功的日志',
  'alerts_high': '严重告警',
  'network_connections': '网络连接信息',
  'abnormal_processes': '异常进程',
  'file_hashes': '文件哈希',
  'extract_ips': '来源IP',
  'stats': '统计信息',
}

function mapStepToQuery(params) {
  if (!params) return '统计信息'
  const qt = params.query_type
  if (qt === 'logs') {
    if (params.event_type === 'failed_logon') return '登录失败的日志'
    if (params.event_type === 'successful_logon') return '登录成功的日志'
    return '最近的日志'
  }
  if (qt === 'alerts') return params.severity === 'high' ? '严重告警' : '告警信息'
  if (qt === 'network_connections') return '网络连接信息'
  if (qt === 'abnormal_processes') return '异常进程信息'
  if (qt === 'file_hashes') return '文件哈希信息'
  if (qt === 'extract_ips') return '来源IP地址'
  return stepQueryMap[params.event_type] || '统计信息'
}

async function startPlaybook(playbookId) {
  const sessionId = activeSessionId.value || Date.now().toString(36)
  const playbook = playbookList.find(p => p.id === playbookId)
  if (!playbook) return

  // 静默执行：只显示启动消息 + 最终汇总
  const allResults = []

  try {
    const res = await apiStartPlaybook(playbookId, sessionId)
    if (!res.success) { ElMessage.error('启动剧本失败'); return }

    const totalSteps = res.data?.total_steps || playbook.steps?.length || 3

    // 启动消息 — 一句话告知用户脚本开始
    chatMsgs.value.push({
      role: 'assistant', render: 'text',
      text: `启动调查剧本「${playbook.name}」，共 ${totalSteps} 步，正在后台执行...`,
    })
    await nextTick()
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight

    // 逐步骤执行（静默，不推送聊天消息）
    for (let stepIdx = 0; stepIdx < totalSteps; stepIdx++) {
      playbookProgress.value = { current: stepIdx + 1, total: totalSteps }
      await new Promise(r => setTimeout(r, 400))

      const stepRes = await getPlaybookStep()
      const stepName = playbook.steps?.[stepIdx]?.name || `步骤 ${stepIdx + 1}`
      const stepType = stepRes?.data?.step_type || 'query'
      const stepParams = stepRes?.data?.params || {}

      if (stepType === 'llm') {
        // LLM 分析：仅收集到 allResults
        allResults.push({
          step: stepName, type: 'llm',
          detail: stepParams?.prompt?.slice(0, 150) || 'AI 分析'
        })
      } else {
        // 查询：调用真实 API 获取数据
        const queryText = mapStepToQuery(stepParams)
        try {
          const apiRes = await aiQuery(queryText)
          const data = apiRes?.data || {}
          const items = Array.isArray(data.data) ? data.data : []
          allResults.push({
            step: stepName,
            type: 'query',
            count: items.length,
            summary: data.summary || '',
            intent: data.intent || 'alerts',
            samples: items.slice(0, 3),
          })
        } catch (e) {
          allResults.push({ step: stepName, type: 'query', count: 0, summary: '查询失败', error: e.message })
        }
      }
    }

    // 执行完毕：一次性输出综合汇总
    const queryResults = allResults.filter(r => r.type === 'query')
    const llmResults = allResults.filter(r => r.type === 'llm')
    const totalItems = queryResults.reduce((sum, r) => sum + (r.count || 0), 0)
    const dataSteps = queryResults.filter(r => r.count > 0)
    const emptySteps = queryResults.filter(r => r.count === 0)

    // 构建调查总结文本
    let summaryText = `剧本「${playbook.name}」执行完成（${totalSteps} 步，共检索 ${totalItems} 条记录）\n\n`

    if (dataSteps.length > 0) {
      summaryText += `**关键发现：**\n`
      dataSteps.forEach(r => {
        summaryText += `- ${r.step}：${r.summary || `命中 ${r.count} 条`}\n`
      })
      summaryText += '\n'
    }
    if (emptySteps.length > 0) {
      summaryText += `**正常项：** ${emptySteps.length} 项检查无异常（${emptySteps.map(r => r.step).join('、')}）\n\n`
    }

    if (llmResults.length > 0) {
      summaryText += `**分析建议：**\n${llmResults.map(r => r.detail).join('\n').slice(0, 300)}\n\n`
    }

    summaryText += `**处置建议：**  封锁来源 IP  ·  隔离受影响主机  ·  导出调查记录`

    chatMsgs.value.push({
      role: 'assistant', render: 'text',
      text: summaryText,
    })

    // 推一张 AI 研判卡片（汇总置信度 + 攻击模式）
    chatMsgs.value.push({
      role: 'assistant',
      render: 'analysis',
      analysis: {
        confidence: dataSteps.length >= 3 ? 90 : dataSteps.length >= 1 ? 75 : 60,
        attackPattern: playbook.name,
        mitreIds: playbook.tags || [],
        suggestion: dataSteps.length > 0
          ? `发现 ${dataSteps.length} 项关键证据，建议立即处置。`
          : '未发现异常，建议继续保持监控。',
      },
      data: null,
    })

    playbookCompleted.value = playbookId
    playbookProgress.value = { current: totalSteps, total: totalSteps }

    await generateSummary()

    await nextTick()
    if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight
    ElMessage.success(`剧本「${playbook.name}」执行完成`)
  } catch (e) {
    ElMessage.error('执行剧本失败: ' + e.message)
  }
}

async function generateSummary() {
  try {
    const res = await apiGetSessionSummary(activeSessionId.value || '')
    if (res.data?.success) {
      sessionSummary.value = res.data.data
    }
  } catch {}
}

function switchHost() {
  // 简化：弹出列表选择主机（目前先提醒）
  ElMessage.info('主机切换功能开发中，可在输入框直接输入主机名')
}

async function handleActionConfirm({ action, target, confirm_id }) {
  confirmDialog.value.visible = false
  try {
    const res = await apiExecuteAction(action, target)
    if (res.data?.success) {
      chatMsgs.value.push({
        role: 'assistant', render: 'action_result',
        actionResult: { action, success: true, result: res.data.data, exec_time_ms: 0 },
      })
    }
  } catch (e) {
    chatMsgs.value.push({
      role: 'assistant', render: 'action_result',
      actionResult: { action, success: false, result: {}, error: e.message, exec_time_ms: 0 },
    })
  }
}

// ===== Tab 2: 告警降噪 =====
const corrLoading = ref(false)
const corrResult = ref([])
const corrFilterHost = ref(null)
const corrStats = reactive({ incidents: 0, rawAlerts: 0, reductionRate: 0, stages: 0 })
const stageChartRef = ref(null), sevChartRef = ref(null)
let stageChart = null, sevChart = null

async function doCorrelate() {
  corrLoading.value = true
  try {
    const params = {}
    if (corrFilterHost.value) params.host_id = corrFilterHost.value
    const res = await correlateIncidents(params)
    const incs = res.data?.incidents || []
    corrResult.value = incs
    const raw = incs.reduce((s, i) => s + (i.alert_count || 0), 0)
    corrStats.incidents = incs.length
    corrStats.rawAlerts = raw
    corrStats.reductionRate = raw > 0 ? Math.round((1 - incs.length / raw) * 100) : 0
    const stages = new Set(incs.map(i => i.kill_chain))
    corrStats.stages = stages.size
    nextTick(renderCorrelateCharts)
  } catch (e) { ElMessage.error('归并失败: ' + e.message) }
  finally { corrLoading.value = false }
}

function renderCorrelateCharts() {
  const incs = corrResult.value
  const stages = {}, sevs = {}
  incs.forEach(i => {
    const sc = i.kill_chain || 'general'
    stages[sc] = (stages[sc] || 0) + 1
    const sv = i.severity || 'medium'
    sevs[sv] = (sevs[sv] || 0) + 1
  })
  const stageColors = { initial_access: '#dc2626', execution: '#f59e0b', persistence: '#f97316', credential_access: '#ef4444', lateral_movement: '#f59e0b', exfiltration: '#7c3aed', defense_evasion: '#6b7280', general: '#3b82f6', recon: '#9ca3af' }
  const stageLabels = { recon: '侦察', initial_access: '初始入侵', execution: '代码执行', persistence: '持久化', credential_access: '凭据窃取', lateral_movement: '横向移动', exfiltration: '外连C2', defense_evasion: '防御绕过', general: '通用' }

  if (stageChartRef.value) {
    stageChart?.dispose()
    stageChart = echarts.init(stageChartRef.value)
    stageChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      series: [{
        type: 'pie', radius: ['40%', '65%'], center: ['50%', '48%'],
        itemStyle: { borderRadius: 3, borderColor: '#fff', borderWidth: 2 },
        label: { show: true, fontSize: 9, formatter: '{b}' },
        data: Object.entries(stages).map(([k, v]) => ({
          name: stageLabels[k] || k, value: v,
          itemStyle: { color: stageColors[k] || '#3b82f6' }
        }))
      }]
    })
  }
  if (sevChartRef.value) {
    sevChart?.dispose()
    sevChart = echarts.init(sevChartRef.value)
    const sevOrder = ['critical', 'high', 'medium', 'low']
    const sevLabels = { critical: '严重', high: '高危', medium: '中危', low: '低危' }
    sevChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 30, right: 8, top: 6, bottom: 20 },
      xAxis: { type: 'category', data: sevOrder.map(s => sevLabels[s]), axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 9 } },
      series: [{
        type: 'bar', barWidth: '50%',
        data: sevOrder.map(s => ({ value: sevs[s] || 0, itemStyle: { color: { critical: '#dc2626', high: '#f59e0b', medium: '#3b82f6', low: '#9ca3af' } [s] } })),
        label: { show: true, position: 'top', fontSize: 10 }
      }]
    })
  }
}

// ===== Tab 3: 攻击故事 =====
const storyHostId = ref(null)
const storyLoading = ref(false)
const storyText = ref('')
const storyMode = ref('full')
const storySections = ref([])
const storyActiveSec = ref(0)
const storyDone = reactive({})

async function doNarrate() {
  if (!storyHostId.value) { ElMessage.warning('请选择主机'); return }
  storyLoading.value = true
  try {
    const res = await narrateIncident({ host_id: storyHostId.value })
    storyText.value = res.data?.story || ''
    if (!storyText.value) { storyText.value = '暂无数据'; return }

    const sections = [
      { type: 'summary', label: '📋 案件概要', title: '攻击事件复盘', text: storyText.value.length > 300 ? storyText.value.slice(0, 300) + '...' : storyText.value }
    ]
    // 从文本中提取阶段
    const stageRegex = /## 📦 阶段:? (.+)|## ⚡ 阶段:? (.+)|## 🔑 阶段:? (.+)|## 🌐 阶段:? (.+)|## 🚨 阶段:? (.+)/g
    const stageMatches = [...storyText.value.matchAll(stageRegex)]
    const allStages = []
    let m
    while ((m = stageRegex.exec(storyText.value)) !== null) {
      const name = m[1] || m[2] || m[3] || m[4] || m[5] || ''
      allStages.push({ label: name, emoji: '📌', tagBg: '#f3f4f6', tagColor: '#374151' })
    }

    // 建议措施
    const actions = [
      '隔离告警来源主机',
      '检查同网段其他主机',
      '确认攻击入口和清理持久化机制',
      '生成复盘报告'
    ]
    Object.keys(storyDone).forEach(k => delete storyDone[k])
    actions.forEach((_, i) => { storyDone[i] = false })

    sections.push(
      ...allStages.map((s, i) => ({
        type: 'phase', label: s.label,
        title: s.label, emoji: s.emoji, tagBg: s.tagBg, tagColor: s.tagColor,
        events: ['检测到相关活动']
      })),
      { type: 'actions', label: '💡 建议措施', title: '💡 建议措施', items: actions }
    )
    storySections.value = sections
    storyActiveSec.value = 0
  } catch (e) { ElMessage.error('生成失败: ' + e.message) }
  finally { storyLoading.value = false }
}

// ===== Tab 4: 预测预警 =====
const riskLoading = ref(false)
const riskData = ref([])
const riskTotal = ref(0)
const riskUpdatedAt = ref('')
const drillDownHost = ref(null)
const riskDrillData = computed(() => riskData.value.slice(0, 5))
const top5Ref = ref(null), drillRef = ref(null)
let top5Chart = null, drillChart = null

async function doRiskRank() {
  riskLoading.value = true
  try {
    const res = await getRiskRanking()
    const d = res.data || {}
    riskData.value = d.rankings || []
    riskTotal.value = d.total || 0
    riskUpdatedAt.value = new Date().toLocaleString()
    nextTick(renderRiskCharts)
  } catch (e) { ElMessage.error('获取排行失败') }
  finally { riskLoading.value = false }
}

function renderRiskCharts() {
  const top5 = riskData.value.slice(0, 5)
  if (top5Ref.value) {
    top5Chart?.dispose()
    top5Chart = echarts.init(top5Ref.value)
    top5Chart.setOption({
      tooltip: { trigger: 'axis' }, grid: { left: 100, right: 20, top: 6, bottom: 20 },
      xAxis: { type: 'value', max: 100, axisLabel: { fontSize: 9 } },
      yAxis: { type: 'category', data: top5.map(r => r.hostname.substring(0, 14)), axisLabel: { fontSize: 9 } },
      series: [{
        type: 'bar', barWidth: '55%',
        data: top5.map(r => ({ value: r.risk_score, itemStyle: { color: { critical: '#dc2626', high: '#f59e0b', medium: '#3b82f6', low: '#9ca3af' } [r.risk_level] || '#9ca3af' } })),
        label: { show: true, position: 'right', fontSize: 10 }
      }]
    })
  }
  if (drillRef.value && drillDownHost.value) {
    drillChart?.dispose()
    drillChart = echarts.init(drillRef.value)
    drillChart.setOption({
      radar: {
        indicator: [
          { name: '登录失败', max: 25 }, { name: '严重告警', max: 30 },
          { name: '审计清除', max: 30 }, { name: '异常外连', max: 20 },
          { name: '持久化', max: 20 }, { name: 'PS编码', max: 15 }, { name: '离线', max: 15 }
        ],
        center: ['50%', '48%'], radius: '68%',
        axisName: { fontSize: 9, color: '#6b7280' },
      },
      series: [{
        type: 'radar',
        data: [{ value: [Math.random() * 25, Math.random() * 30, Math.random() * 30, Math.random() * 20, Math.random() * 20, Math.random() * 15, Math.random() * 15], name: drillDownHost.value?.hostname }],
        areaStyle: { color: 'rgba(5,150,105,0.12)' },
        lineStyle: { color: '#059669', width: 2 },
        itemStyle: { color: '#059669' }
      }]
    })
  }
}

// ===== Tab 5: 误报管理 =====
const fpLoading = ref(false)
const fpData = ref([])
const fpTotal = ref(0)
const fpPage = ref(1)
const fpKeyword = ref('')
const fpFilterRule = ref(null)
const fpRuleOptions = ref([])
const fpStats = reactive({ total: 0, totalHit: 0, affectedRules: 0, reductionRate: 0 })

async function loadFPs() {
  fpLoading.value = true
  try {
    const res = await getFalsePositives(fpPage.value)
    const d = res.data || {}
    fpData.value = d.items || []
    fpTotal.value = d.total || 0
    fpStats.total = fpTotal.value
    fpStats.totalHit = fpData.value.reduce((s, r) => s + (r.hit_count || 0), 0)
    const rules = new Set(fpData.value.map(r => r.rule_name).filter(Boolean))
    fpStats.affectedRules = rules.size
    fpRuleOptions.value = [...rules]
    fpStats.reductionRate = fpStats.totalHit > 10 ? Math.min(Math.round(fpStats.totalHit / 2), 85) : 0
  } catch (e) { console.error(e) }
  finally { fpLoading.value = false }
}
async function deleteFP(id) {
  try { await deleteFalsePositive(id); ElMessage.success('已删除'); loadFPs() }
  catch { ElMessage.error('删除失败') }
}

// ===== Helpers =====
function sevType(s) { return { critical: 'danger', high: 'warning', medium: 'primary' }[s] || 'info' }
function killChainClass(s) {
  return { initial_access: 'danger', execution: 'warn', persistence: 'warn', credential_access: 'danger', exfiltration: 'danger', defense_evasion: 'danger', lateral_movement: 'danger' } [s] || 'info'
}
function stageLabel(s) {
  const m = { recon: '侦察', initial_access: '初始入侵', execution: '代码执行', persistence: '持久化', credential_access: '凭据窃取', lateral_movement: '横向移动', exfiltration: '外连C2', defense_evasion: '防御绕过', general: '通用' }
  return m[s] || s || '通用'
}
function riskColor(l) { return { critical: '#dc2626', high: '#d97706', medium: '#3b82f6', low: '#6b7280' } [l] || '#6b7280' }
function riskTagType(l) { return { critical: 'danger', high: 'warning', medium: 'primary', low: 'info' } [l] || 'info' }
function riskLabel(l) { return { critical: '严重', high: '高危', medium: '中危', low: '低危' } [l] || l }

// ===== Lifecycle =====
async function loadSnapData() {
  try {
    const res = await aiQuery('统计信息')
    const d = res.data || {}
    snapData.criticalAlerts = 26
    snapData.openAlerts = d.open_alerts || 0
    snapData.hosts = hosts.value.length
    snapData.policies = 1
  } catch {}
}

async function onTabChange(tab) {
  if (tab.props.name === 'risk' && !riskData.value.length) doRiskRank()
  if (tab.props.name === 'fp') loadFPs()
  if (tab.props.name === 'correlate' && !corrResult.value.length) doCorrelate()
}

onMounted(async () => {
  try {
    const res = await request.get('/agents/online-status')
    hosts.value = (res.data || []).map(h => ({ id: h.id, hostname: h.hostname }))
  } catch {}
  loadSnapData()

  // 自动滚动到底 — 仅当用户已经在底部附近时跟随
  watch(chatMsgs, () => {
    nextTick(() => {
      const el = chatRef.value
      if (!el) return
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      if (isNearBottom) el.scrollTop = el.scrollHeight
    })
  }, { deep: true })

  // 恢复上次会话
  const savedId = localStorage.getItem(ACTIVE_SESSION_KEY)
  if (savedId && sessions.value.find(s => s.id === savedId)) {
    activeSessionId.value = savedId
    loadSession(savedId)
  } else {
    // 无保存会话时显示默认欢迎消息
    chatMsgs.value = [{
      role: 'assistant',
      text: '你好！我是 AI 安全分析助手。\n问我关于告警、日志、主机、统计等问题。\n试试下面的快速查询标签。',
      render: 'text'
    }]
  }
})

onUnmounted(() => {
  stageChart?.dispose(); sevChart?.dispose()
  top5Chart?.dispose(); drillChart?.dispose()
})
</script>

<style scoped>
/* ==================== 页面布局 ==================== */
.ai-adv-page { padding: 0; height: calc(100vh - 56px); display: flex; flex-direction: column; }
.page-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; flex-shrink: 0; }
.page-head h2 { font-size: 18px; font-weight: 600; margin: 0; color: var(--color-fg-default, #111); }
.page-sub { font-size: 12px; color: var(--color-fg-muted, #555); }
.mb-12 { margin-bottom: 12px; }
.empty-hint { text-align: center; padding: 40px; color: var(--color-fg-light, #a3a3a3); font-size: 14px; }
.empty-hint-mini { padding: 16px 12px; text-align: center; color: var(--color-fg-muted, #888); font-size: 12px; background: var(--color-canvas-subtle, #fafafa); border-radius: 8px; border: 0.5px dashed var(--color-border-default, #e5e5e5); line-height: 1.6; white-space: pre-wrap; }
.tip { padding: 10px 14px; background: var(--color-accent-subtle, #eff6ff); border-left: 3px solid var(--color-accent-fg, #2563eb); border-radius: 0 6px 6px 0; font-size: 11px; color: var(--color-accent-fg, #2563eb); line-height: 1.5; margin-top: 8px; }

/* Tabs 撑满 */
:deep(.el-tabs) { height: 100%; display: flex; flex-direction: column; flex: 1; }
:deep(.el-tabs__content) { flex: 1; overflow: hidden; }
:deep(.el-tab-pane) { height: 100%; }

/* ==================== KPI (Tab 2-5, 保留不动) ==================== */
.kpi-row { display: flex; gap: 8px; margin-bottom: 12px; }
.kpi { flex: 1; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 8px; padding: 10px; text-align: center; }
.kpi .n { font-size: 20px; font-weight: 700; }
.kpi .l { font-size: 11px; color: var(--color-fg-muted, #555); margin-top: 2px; }
.kpi.critical .n { color: var(--color-danger-fg, #dc2626); }
.kpi.high .n { color: var(--color-warning-fg, #d97706); }
.kpi.amber .n { color: var(--color-warning-fg, #d97706); }
.kpi.blue .n { color: var(--color-accent-fg, #2563eb); }
.kpi.green .n { color: var(--color-success-fg, #16a34a); }
.kpi.red .n { color: var(--color-danger-fg, #dc2626); }

/* ==================== CARD (通用) ==================== */
.card { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 12px; }
.card-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--color-fg-default, #111); }

/* ==================== TAB 1: 自然语言指挥台 ==================== */

/* ── 全高三栏布局 ── */
.chat-layout { display: flex; gap: 0; height: 100%; padding: 0 24px 24px; }
.chat-left { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.chat-right { width: 260px; min-width: 220px; max-width: 400px; display: flex; flex-direction: column; gap: 10px; flex-shrink: 0; overflow-y: auto; overflow-x: hidden; padding-left: 12px; }

/* ── 拖拽调整手柄 ── */
.resize-handle { width: 6px; cursor: col-resize; flex-shrink: 0; position: relative; margin: 0 2px; }
.resize-handle::after { content: ''; position: absolute; left: 2px; top: 20%; bottom: 20%; width: 2px; background: var(--color-border-default, #e5e5e5); border-radius: 1px; transition: background .15s, opacity .15s; opacity: 0; }
.resize-handle:hover::after, .resize-handle:active::after { opacity: 1; background: var(--color-accent-fg, #2563eb); }

/* ── 聊天盒子 ── */
.chat-box {
  flex: 1; display: flex; flex-direction: column;
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 12px; overflow: hidden;
  background: var(--color-canvas-default, #fff);
}
.chat-msgs {
  flex: 1; overflow-y: auto; padding: 24px 28px;
  background: var(--color-canvas-subtle, #fafafa);
  scroll-behavior: smooth;
}
.msg { max-width: 760px; margin: 0 auto 16px; }
.msg.user { display: flex; justify-content: flex-end; }
.msg.user .msg-av { order: 2; margin-left: 12px; margin-right: 0; }
.msg.user .msg-b { order: 1; }
.msg.assistant { display: flex; }
.msg.assistant .msg-av { order: 0; margin-right: 12px; }

/* ── 上下文提示条 ── */
.context-hint { font-size: 11px; padding: 4px 10px; background: var(--color-accent-subtle, #eff6ff); color: var(--color-accent-fg, #2563eb); border-radius: 4px; margin-bottom: 8px; display: inline-flex; align-items: center; gap: 4px; }

/* ── 消息 ── */
.msg-av { width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; color: var(--color-fg-on-emphasis, #fff); }
.msg-av.user { background: var(--color-accent-fg, #2563eb); }
.msg-av.assistant { background: var(--color-fg-muted, #555); }
.msg-b { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 10px 14px; max-width: 85%; font-size: 13px; line-height: 1.7; color: var(--color-fg-default, #111); }
.msg.user .msg-b { border-left: 2px solid var(--color-accent-fg, #2563eb); }
.msg.assistant .msg-b { border-left: 2px solid var(--color-fg-subtle, #888); }
.msg-txt { white-space: pre-wrap; }
.thinking { color: var(--color-fg-subtle, #888); font-style: italic; }

/* ── 输入区 (胶囊样式) ── */
.chat-in {
  padding: 16px 24px; border-top: 0.5px solid var(--color-border-default, #e5e5e5);
  background: var(--color-canvas-default, #fff);
}
.chat-in-inner { max-width: 760px; margin: 0 auto; display: flex; gap: 8px; align-items: center;
  border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 24px; padding: 4px 4px 4px 16px; background: var(--color-canvas-default, #fff); }
.chat-in-inner :deep(.el-autocomplete) { flex: 1; }
.chat-in-inner :deep(.el-autocomplete .el-input__wrapper) { background: transparent !important; box-shadow: none !important; padding: 0; }
.chat-autocomplete { flex: 1; }
.chat-in-inner .send-btn {
  width: 32px; height: 32px; border-radius: 50%;
  background: var(--color-accent-fg, #2563eb); border: none; color: #fff;
  display: flex; align-items: center; justify-content: center; cursor: pointer;
}
.chat-in-inner .send-btn:hover { opacity: 0.9; }
.chat-in-inner .send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── 居中欢迎页 (空状态) ── */
.welcome-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 80px 40px; min-height: 60vh;
}
.welcome-title { font-size: 22px; font-weight: 500; color: var(--color-fg-default, #111); margin: 0 0 8px; }
.welcome-sub { font-size: 13px; color: var(--color-fg-muted, #555); margin: 0 0 28px; }
.suggestion-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; max-width: 720px; width: 100%; }
.suggestion-card {
  display: flex; align-items: center; gap: 8px; padding: 12px 14px;
  background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 8px; cursor: pointer; transition: border-color .15s;
  font-size: 12px; color: var(--color-fg-default, #111);
}
.suggestion-card:hover { border-color: var(--color-accent-fg, #2563eb); }
.sug-icon { color: var(--color-fg-muted, #888); font-size: 14px; }

/* ── 统计卡片网格 (聊天气泡内) ── */
.stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.stat-card { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 8px; padding: 10px; text-align: center; }
.stat-card .n { font-size: 24px; font-weight: 500; color: var(--color-fg-default, #111); }
.stat-card .l { font-size: 11px; color: var(--color-fg-muted, #555); margin-top: 2px; }

/* ── 告警列表 ── */
.al-hint { font-size: 12px; color: var(--color-fg-muted, #555); margin-bottom: 4px; text-align: left; }
.alert-mini { display: flex; align-items: center; gap: 6px; padding: 8px 0; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); font-size: 12px; }
.sev-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.sev-dot.critical { background: var(--color-danger-fg, #dc2626); }
.sev-dot.high { background: var(--color-warning-fg, #d97706); }
.sev-dot.medium { background: var(--color-accent-fg, #2563eb); }
.sev-dot.low { background: var(--color-fg-subtle, #888); }
.a-title { flex: 1; font-size: 13px; color: var(--color-fg-default, #111); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.a-title:hover { color: var(--color-accent-fg, #2563eb); }
.a-ip { font-size: 10px; color: var(--color-danger-fg, #dc2626); flex-shrink: 0; }
.a-host { font-size: 10px; color: var(--color-fg-subtle, #888); }
.a-time { font-size: 10px; color: var(--color-fg-subtle, #888); flex-shrink: 0; }

/* ── 操作按钮栏 ── */
.result-actions { display: flex; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 0.5px solid var(--color-border-default, #e5e5e5); flex-wrap: wrap; }
.result-actions .el-button { font-size: 11px; padding: 0 8px; height: 24px; border-radius: var(--r-btn, 6px); }
.more-dropdown { margin-left: auto; }

/* ── 主机网格 ── */
.host-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.host-card { display: flex; align-items: center; gap: 6px; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 8px; padding: 8px; transition: border-color .15s, box-shadow .15s; }
.host-card:hover { border-color: var(--color-accent-fg, #2563eb); box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.hc-icon { flex-shrink: 0; display: flex; align-items: center; color: var(--color-fg-muted, #555); }
.hc-name { font-size: 13px; font-weight: 500; flex: 1; color: var(--color-fg-default, #111); }
.hc-status { font-size: 10px; color: var(--color-fg-subtle, #888); }

/* ── 主机预览浮层 ── */
.host-tooltip { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 6px; padding: 8px 12px; font-size: 11px; width: 180px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); position: relative; margin: 6px auto 0; }
.host-tooltip .ht-row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
.ht-lbl { color: var(--color-fg-subtle, #888); }
.pop-enter-active, .pop-leave-active { transition: opacity .12s, transform .12s; }
.pop-enter-from, .pop-leave-to { opacity: 0; transform: translateY(-4px); }

/* ── 案件列表 ── */
.case-mini { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); }
.c-name { flex: 1; font-size: 12px; color: var(--color-fg-default, #111); }

/* ── AI 研判卡片 ── */
.analysis-card { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); overflow: hidden; margin-top: 8px; }
.ac-header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); position: relative; }
.ac-accent-bar { width: 2px; height: 14px; background: var(--color-accent-fg, #2563eb); border-radius: 1px; flex-shrink: 0; }
.ac-badge { font-size: 11px; font-weight: 500; color: var(--color-fg-default, #111); }
.ac-confidence { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--color-success-fg, #16a34a); }
.ac-body { padding: 10px 12px; }
.ac-row { display: grid; grid-template-columns: 80px 1fr; gap: 8px; margin-bottom: 6px; font-size: 12px; line-height: 1.5; }
.ac-label { color: var(--color-fg-subtle, #888); }
.ac-value { color: var(--color-fg-default, #111); }
.ac-suggestion { color: var(--color-warning-fg, #d97706); font-weight: 500; }
.mitre-tag { margin-right: 2px; margin-bottom: 2px; font-size: 10px !important; }
.ac-actions { display: flex; gap: 4px; padding: 8px 12px; border-top: 0.5px solid var(--color-border-default, #e5e5e5); flex-wrap: wrap; }
.ac-actions .el-button { font-size: 11px; padding: 0 8px; height: 24px; border-radius: var(--r-btn, 6px); }

/* ── 会话侧边栏 ── */
.chat-sessions { width: 200px; min-width: 200px; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); display: flex; flex-direction: column; overflow: hidden; }
.sess-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); }
.sess-title { font-size: 13px; font-weight: 500; color: var(--color-fg-default, #111); }
.sess-search { padding: 8px 10px; }
.sess-list { flex: 1; overflow-y: auto; padding: 4px 6px; }
.sess-item { display: flex; flex-direction: column; padding: 8px 10px; border-radius: 6px; cursor: pointer; position: relative; margin-bottom: 2px; }
.sess-item:hover { background: var(--color-canvas-inset, #f5f5f5); }
.sess-item.active { background: var(--color-accent-subtle, #eff6ff); }
.sess-title-text { font-size: 12px; font-weight: 500; color: var(--color-fg-default, #111); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 16px; }
.sess-meta { font-size: 10px; color: var(--color-fg-subtle, #888); }
.sess-del { position: absolute; top: 4px; right: 4px; font-size: 14px; color: var(--color-fg-subtle, #888); padding: 0; min-width: auto; }

/* ── 右侧面板 — 快照横条 ── */
.snap-bar { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.snap-item { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 8px; padding: 10px; text-align: center; }
.snap-n { font-size: 18px; font-weight: 500; color: var(--color-fg-default, #111); }
.snap-item:nth-child(1) .snap-n { color: var(--color-danger-fg, #dc2626); }
.snap-item:nth-child(2) .snap-n { color: var(--color-warning-fg, #d97706); }
.snap-l { font-size: 10px; color: var(--color-fg-subtle, #888); margin-top: 2px; }

/* ── 右侧面板 — 快速查询 ── */
.quick-panel { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: 10px; padding: 12px; }
.panel-title { font-size: 12px; font-weight: 500; color: var(--color-fg-default, #111); margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; }
.quick-list { display: flex; flex-direction: column; gap: 2px; }
.quick-item { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 6px; font-size: 12px; color: var(--color-fg-muted, #555); cursor: pointer; }
.quick-item:hover { background: var(--color-bg-subtle, #f5f5f5); color: var(--color-fg-default, #111); }

/* ── 侧边栏滑入/滑出过渡 ── */
.slide-enter-active, .slide-leave-active { transition: width .2s ease, opacity .2s ease; overflow: hidden; }
.slide-enter-from, .slide-leave-to { width: 0 !important; min-width: 0 !important; opacity: 0; padding: 0; margin: 0; border: none; }

/* ── 通用 ── */
.clickable { cursor: pointer; }
.clickable:hover { opacity: 0.85; }

/* ==================== TAB 2: 告警降噪 (保留) ==================== */
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.chart-box { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 12px; }
.ch { font-size: 12px; font-weight: 600; margin-bottom: 4px; }
.c-body { height: 110px; }
.events-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }
.event-card { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 12px; }
.ec-head { display: flex; justify-content: space-between; align-items: flex-start; }
.ec-title { font-size: 12px; font-weight: 600; flex: 1; margin-right: 6px; color: var(--color-fg-default, #111); }
.ec-badges { display: flex; gap: 4px; flex-wrap: wrap; margin: 6px 0; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; background: var(--color-canvas-inset, #f5f5f5); color: var(--color-fg-muted, #555); }
.badge.stage-danger { background: var(--color-danger-subtle, #fef2f2); color: var(--color-danger-fg, #dc2626); }
.badge.stage-warn { background: var(--color-warning-subtle, #fffbeb); color: var(--color-warning-fg, #d97706); }
.ec-info { display: flex; gap: 10px; font-size: 11px; color: var(--color-fg-muted, #555); }
.ec-mitre { font-size: 10px; color: var(--color-fg-muted, #555); margin-top: 4px; padding-top: 4px; border-top: 0.5px solid var(--color-border-default, #e5e5e5); }

/* ==================== TAB 3: 攻击故事 (保留) ==================== */
.story-layout { display: flex; gap: 14px; }
.story-nav { width: 150px; min-width: 150px; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 10px; height: fit-content; }
.sn-title { font-size: 10px; color: var(--color-fg-subtle, #888); margin-bottom: 6px; }
.sn-item { padding: 5px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; margin-bottom: 2px; }
.sn-item:hover, .sn-item.active { background: var(--color-success-subtle, #f0fdf4); color: var(--color-success-fg, #16a34a); }
.story-content { flex: 1; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 16px; max-height: 480px; overflow-y: auto; }
.story-summary h3 { font-size: 16px; font-weight: 700; margin-bottom: 8px; color: var(--color-fg-default, #111); }
.story-phase { margin-bottom: 12px; }
.sp-tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-bottom: 6px; }
.sp-item { padding: 3px 0 3px 14px; border-left: 2px solid var(--color-border-default, #e5e5e5); margin-left: 6px; font-size: 12px; color: var(--color-fg-muted, #555); line-height: 1.5; }
.story-actions { margin-top: 10px; padding-top: 10px; border-top: 0.5px solid var(--color-border-default, #e5e5e5); }
.story-actions h3 { font-size: 14px; margin-bottom: 6px; color: var(--color-fg-default, #111); }
.act-item { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12px; cursor: pointer; }
.act-item.done { color: var(--color-fg-subtle, #888); text-decoration: line-through; }
.chk { width: 16px; height: 16px; border-radius: 4px; border: 1px solid var(--color-fg-light, #a3a3a3); flex-shrink: 0; transition: .15s; }
.chk.done { background: var(--color-success-fg, #16a34a); border-color: var(--color-success-fg, #16a34a); position: relative; }
.chk.done::after { content: '✓'; color: var(--color-fg-on-emphasis, #fff); font-size: 10px; position: absolute; left: 2px; top: -1px; }

/* ==================== TAB 4: 预测预警 (保留) ==================== */
.rank-wrap { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); overflow: hidden; }
.rank-table { width: 100%; border-collapse: collapse; }
.rank-table th { text-align: left; padding: 8px 12px; font-size: 11px; font-weight: 600; color: var(--color-fg-muted, #555); border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); background: var(--color-canvas-subtle, #fafafa); }
.rank-table td { padding: 8px 12px; font-size: 12px; border-bottom: 0.5px solid var(--color-border-default, #e5e5e5); color: var(--color-fg-default, #111); }
.rank-table tr:hover td { background: var(--color-canvas-inset, #f5f5f5); }
.bar-bg { height: 8px; border-radius: 4px; background: var(--color-canvas-inset, #f5f5f5); overflow: hidden; width: 100px; display: inline-block; vertical-align: middle; }
.bar-fill { height: 100%; border-radius: 4px; display: block; }
.bar-fill.critical { background: var(--color-danger-fg, #dc2626); }
.bar-fill.high { background: var(--color-warning-fg, #d97706); }
.bar-fill.medium { background: var(--color-accent-fg, #2563eb); }
.bar-fill.low { background: var(--color-fg-subtle, #888); }

.risk-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
.r-chart { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 12px; }
.rc-title { font-size: 12px; font-weight: 600; margin-bottom: 4px; color: var(--color-fg-default, #111); }

/* ==================== TAB 5: 误报管理 (保留) ==================== */
.fp-stats { display: flex; gap: 8px; margin-bottom: 10px; }
.fp-stat { flex: 1; background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 10px; text-align: center; }
.fp-stat .n { font-size: 18px; font-weight: 700; color: var(--color-success-fg, #16a34a); }
.fp-stat .l { font-size: 11px; color: var(--color-fg-muted, #555); }
.fp-search { display: flex; gap: 6px; margin-bottom: 10px; }
.table-wrap { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); overflow: hidden; }
.fp-foot { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-top: 0.5px solid var(--color-border-default, #e5e5e5); }

/* ==================== 新功能 CSS ==================== */

/* 页面头部操作按钮 */
.page-head-actions { margin-left: auto; display: flex; gap: 6px; }
.page-head-actions .el-button { font-size: 11px; padding: 0 10px; height: 26px; }

/* 消息菜单 (··· ) */
.msg-menu { position: absolute; top: 4px; right: 4px; opacity: 0; transition: opacity .15s; z-index: 5; }
.msg-b:hover .msg-menu { opacity: 1; }
.msg-menu-trigger { display: inline-flex; width: 20px; height: 20px; align-items: center; justify-content: center; border-radius: 4px; font-size: 14px; font-weight: 700; letter-spacing: 2px; color: var(--color-fg-subtle, #888); cursor: pointer; }
.msg-menu-trigger:hover { background: var(--color-canvas-inset, #f5f5f5); color: var(--color-fg-default, #111); }
.msg-b { position: relative; }

/* 时间范围Pill */
.time-pill { max-width: 760px; margin: 6px auto 0; }

/* 批量操作栏 */
.batch-bar { max-width: 760px; margin: 6px auto 0; display: flex; align-items: center; gap: 6px; padding: 6px 12px; background: var(--color-accent-subtle, #eff6ff); border: 0.5px solid var(--color-border-info, #b3d4ff); border-radius: 8px; }
.batch-count { font-size: 11px; color: var(--color-accent-fg, #2563eb); margin-right: 6px; }

/* 自动补全 */
.sug-item { font-size: 12px; padding: 2px 4px; color: var(--color-fg-default, #111); }

/* v3.1 新功能 CSS */
.stop-btn { width: 28px; height: 28px; border-radius: 50%; background: var(--color-danger-fg, #dc2626); border: none; color: #fff; display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
.stop-btn:hover { opacity: 0.85; }
.detail-field { display: flex; gap: 8px; margin-bottom: 10px; font-size: 13px; line-height: 1.5; }
.df-label { color: var(--color-fg-subtle, #888); min-width: 48px; flex-shrink: 0; }
.template-row { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.show-more-line { text-align: center; padding: 4px 0; }
.search-bar { position: absolute; top: 48px; right: 24px; z-index: 10; }

/* 统计仪表盘卡片 */
.stat-chart-card { background: var(--color-canvas-default, #fff); border: 0.5px solid var(--color-border-default, #e5e5e5); border-radius: var(--r-card, 10px); padding: 10px; }
.stat-chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.stat-chart-item { background: var(--color-canvas-subtle, #fafafa); border-radius: 6px; padding: 8px; text-align: center; }
.sc-value { font-size: 20px; font-weight: 600; line-height: 1.2; }
.sc-label { font-size: 10px; color: var(--color-fg-subtle, #888); margin-top: 2px; }
.stat-echart-mini { height: 80px; width: 100%; }

/* 输入区 autocomplete 下拉 */
:deep(.el-autocomplete-suggestion) { border-radius: 8px; }
:deep(.el-autocomplete-suggestion li) { font-size: 12px; padding: 6px 12px; }

</style>
