<template>
  <div class="page-container">
    <!-- 主机信息 -->
    <div class="card-box">
      <div class="flex-between mb-20">
        <h2 class="page-title">主机详情</h2>
        <div>
          <el-button @click="agentDialogRef?.show()">下载 Agent</el-button>
          <el-button @click="importDialogRef?.show()">导入 JSON</el-button>
          <el-button size="small" @click="showImportLog = true">
            <el-icon><Upload /></el-icon> 导入日志
          </el-button>
          <el-button type="primary" :loading="analyzing" @click="handleAnalyze">分析</el-button>
          <el-button
            :icon="Search"
            :loading="triageSubmitting"
            @click="openTriageDialog"
          >
            发起取证
          </el-button>
          <el-button
            v-if="aiEnabled !== null"
            :disabled="!aiEnabled"
            @click="handleAiAnalyze"
          >
            <el-icon><Cpu /></el-icon> AI 分析
          </el-button>
          <el-button @click="$router.push(`/hosts/${hostId}/report`)">查看报告</el-button>
          <el-button @click="$router.back()">返回</el-button>
        </div>
      </div>
      <el-descriptions :column="3" border v-loading="loading">
        <el-descriptions-item label="主机名">{{ host?.hostname }}</el-descriptions-item>
        <el-descriptions-item label="IP 地址">{{ host?.ip_address || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="系统类型">{{ host?.os_type || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="系统版本">{{ host?.os_version || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(host?.status)" size="small" effect="plain" class="status-tag">{{ statusLabel(host?.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="风险等级">
          <RiskBadge v-if="analysis" :level="analysis.risk_level" />
          <span v-else>未分析</span>
        </el-descriptions-item>
        <el-descriptions-item label="Agent 版本">{{ host?.agent_version || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="采集时间">{{ host?.collection_time || 'N/A' }}</el-descriptions-item>
        <el-descriptions-item label="风险分数">
          <span v-if="analysis">{{ analysis.risk_score }} / 100</span>
          <span v-else>N/A</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 分析摘要 -->
    <div v-if="analysis" class="card-box">
      <div class="section-header" @click="summaryCollapsed = !summaryCollapsed">
        <h3 class="mb-0">分析摘要</h3>
        <el-button link type="primary" size="small">{{ summaryCollapsed ? '展开' : '收起' }}</el-button>
      </div>
      <el-alert v-show="!summaryCollapsed" :type="alertType" :closable="false" class="mt-8">
        {{ analysis.summary }}
      </el-alert>
    </div>

    <!-- 知识匹配（RAG 语义检索结果） -->
    <div v-if="knowledgeHits.length" class="card-box">
      <div class="section-header" @click="knowledgeCollapsed = !knowledgeCollapsed">
        <h3 class="mb-0" style="display:flex;align-items:center;gap:8px">
          知识匹配
          <el-tag size="small" effect="plain" class="status-tag">RAG 语义检索</el-tag>
          <span class="kh-subtle-hint">共 {{ knowledgeHits.length }} 条语义命中</span>
        </h3>
        <el-button link type="primary" size="small">{{ knowledgeCollapsed ? '展开' : '收起' }}</el-button>
      </div>
      <div v-show="!knowledgeCollapsed" class="kh-grid mt-8">
        <div
          v-for="(kh, i) in knowledgeHits"
          :key="i"
          class="kh-card"
          :class="{ 'kh-needs-review': kh.needs_review }"
          @click="showKnowledgePopup(kh)"
        >
          <div class="kh-header">
            <el-tag :type="kh.confidence === 'high' ? 'danger' : kh.confidence === 'medium' ? 'warning' : 'info'" size="small" effect="plain">
              {{ kh.confidence === 'high' ? '高置信' : kh.confidence === 'medium' ? '中置信' : '低置信' }}
            </el-tag>
            <el-tag v-if="kh.severity" size="small" effect="plain" style="margin-left:4px">{{ kh.severity }}</el-tag>
            <el-tag v-if="kh.needs_review" size="small" effect="plain" class="status-tag" style="margin-left:4px">需复核</el-tag>
            <span class="kh-title">{{ kh.title }}</span>
          </div>
          <div class="kh-desc" v-if="kh.description">{{ kh.description }}</div>
          <div class="kh-meta" v-if="kh.match_reason">
            <span>匹配原因：{{ kh.match_reason }}</span>
            <span v-if="kh.semantic_score !== undefined" style="margin-left:12px">相似度：{{ (kh.semantic_score * 100).toFixed(1) }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 页签 -->
    <div class="card-box">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="主机画像" name="profile">
          <div class="tab-toolbar">
            <span class="tab-hint">主机画像概览</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('profile')"
            >
              AI 分析
            </el-button>
          </div>
          <ProfileCard :profile="profile" />
        </el-tab-pane>
        <el-tab-pane label="进程树" name="tree">
          <div class="tab-toolbar">
            <span class="tab-hint">进程树视图</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('process_list')"
            >
              AI 分析
            </el-button>
          </div>
          <ProcessTreeView
            v-if="activeTab === 'tree'"
            :tree-data="processTree"
            :abnormal-pids="abnormalPidsForTree"
          />
        </el-tab-pane>
        <el-tab-pane label="异常进程" name="processes">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ abnormalProcesses.length }} 条异常进程</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('abnormal_processes')"
            >
              AI 分析
            </el-button>
          </div>
          <ProcessStatsCards :data="abnormalProcesses" />
          <AbnormalProcessTable
            :data="abnormalProcesses"
            @view-detail="handleViewDetail"
            @knowledge-click="showKnowledgePopup"
            style="margin-top: 16px"
          />
        </el-tab-pane>
        <el-tab-pane label="可疑外连" name="connections">
          <div class="flex-between mb-10">
            <span class="tab-hint">共 {{ suspiciousConnections.length }} 条可疑外连</span>
            <div class="flex-center" style="gap: 8px">
              <el-button
                :disabled="!aiEnabled || host?.status === 'pending'"
                @click="handleModuleAiAnalyze('connections')"
              >
                AI 分析
              </el-button>
              <el-button
                :loading="enriching"
                @click="handleEnrichConns"
              >
                一键威胁情报检测
              </el-button>
            </div>
          </div>
          <SuspiciousConnTable :data="suspiciousConnections" @knowledge-click="showKnowledgePopup" />
        </el-tab-pane>
        <el-tab-pane label="网络连接" name="network">
          <NetworkConnectionTable :host-id="Number(hostId)" :data="networkConnections" @refresh="loadAllResults" />
        </el-tab-pane>
        <el-tab-pane label="文件哈希" name="filehash">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ fileHashes.length }} 条文件哈希</span>
          </div>
          <FileHashTable :data="fileHashes" />
        </el-tab-pane>
        <el-tab-pane label="持久化痕迹" name="persistence">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ persistenceItems.length }} 条持久化痕迹</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('persistence')"
            >
              AI 分析
            </el-button>
          </div>
          <PersistenceTable :data="persistenceItems" :host-id="Number(hostId)" />
        </el-tab-pane>
        <el-tab-pane label="可疑启动项" name="startup">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ startupItems.length }} 条可疑启动项</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('startup')"
            >
              AI 分析
            </el-button>
          </div>
          <SuspiciousStartupTable :data="startupItems" />
        </el-tab-pane>
        <el-tab-pane label="IOC 命中" name="ioc">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ iocHits.length }} 条IOC命中</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('ioc')"
            >
              AI 分析
            </el-button>
          </div>
          <IocTable :data="iocHits" />
        </el-tab-pane>
        <el-tab-pane label="融合检测" name="fusion">
          <div class="tab-toolbar">
            <span class="tab-hint">跨维度融合检测统一视图</span>
            <div class="toolbar-right">
              <el-input v-model="fusionSearch" placeholder="搜索关键字..." size="small" clearable style="width:200px" :prefix-icon="Search" />
              <el-select v-model="fusionFilter" size="small" style="width:120px;margin-left:8px" clearable placeholder="严重度">
                <el-option label="全部" value="" />
                <el-option label="Critical" value="critical" />
                <el-option label="High" value="high" />
                <el-option label="Medium" value="medium" />
                <el-option label="Low" value="low" />
              </el-select>
              <el-select v-model="fusionTypeFilter" size="small" style="width:120px;margin-left:8px" clearable placeholder="类型">
                <el-option label="全部" value="" />
                <el-option label="融合事件" value="incident" />
                <el-option label="WebShell" value="webshell" />
                <el-option label="内存码" value="memory_shell" />
                <el-option label="语义检测" value="knowledge" />
              </el-select>
              <span class="fusion-stats">
                共 {{ filteredFusionItems.length }} 条
              </span>
            </div>
          </div>
          <el-empty
            v-if="!hasFusionData"
            description="本次分析未产出融合检测结果"
            :image-size="48"
          />
          <template v-else>
            <el-collapse v-model="fusionActiveNames" class="fusion-collapse">
              <!-- 融合事件 -->
              <el-collapse-item v-if="filteredIncidents.length" name="incidents">
                <template #title>
                  <div class="collapse-title">
                    <el-tag effect="plain" class="status-tag" size="small">融合事件</el-tag>
                    <span>{{ filteredIncidents.length }} 条</span>
                  </div>
                </template>
                <IncidentPanel :data="filteredIncidents" @jump-finding="handleJumpFinding" />
              </el-collapse-item>

              <!-- WebShell -->
              <el-collapse-item v-if="filteredWebshells.length" name="webshells">
                <template #title>
                  <div class="collapse-title">
                    <el-tag effect="plain" class="status-tag" size="small">WebShell</el-tag>
                    <span>{{ filteredWebshells.length }} 条</span>
                  </div>
                </template>
                <WebShellPanel :data="filteredWebshells" @knowledge-click="showKnowledgePopup" />
              </el-collapse-item>

              <!-- 内存码 -->
              <el-collapse-item v-if="filteredMemoryShells.length" name="memory_shells">
                <template #title>
                  <div class="collapse-title">
                    <el-tag effect="plain" class="status-tag" size="small">内存码</el-tag>
                    <span>{{ filteredMemoryShells.length }} 条</span>
                  </div>
                </template>
                <MemoryShellPanel :data="filteredMemoryShells" @view-tree="handleViewTreeByPid" @knowledge-click="showKnowledgePopup" />
              </el-collapse-item>

              <!-- 语义检测 — 带点击交互 -->
              <el-collapse-item v-if="filteredKnowledgeHits.length" name="knowledge_hits">
                <template #title>
                  <div class="collapse-title">
                    <el-tag effect="plain" class="status-tag" size="small">语义检测</el-tag>
                    <span>{{ filteredKnowledgeHits.length }} 条</span>
                  </div>
                </template>
                <el-table :data="filteredKnowledgeHits" size="small" stripe @row-click="(row) => showKnowledgePopup(row)">
                  <el-table-column prop="title" label="命中规则" min-width="180" />
                  <el-table-column prop="evidence_type" label="证据类型" width="100">
                    <template #default="{ row }">
                      <el-tag size="small" effect="plain">{{ evidenceTypeLabel(row.evidence_type) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="evidence_key" label="证据标识" width="140" show-overflow-tooltip />
                  <el-table-column prop="confidence" label="置信度" width="90">
                    <template #default="{ row }">
                      <el-tag :type="confTag(row.confidence)" size="small" effect="plain">{{ row.confidence }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="severity" label="严重度" width="80">
                    <template #default="{ row }">
                      <el-tag :type="sevTag(row.severity)" size="small" effect="plain">{{ row.severity }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="需复核" width="70">
                    <template #default="{ row }">
                      <span v-if="row.needs_review" class="needs-review-text">待复核</span>
                      <span v-else class="review-passed-text">已复核</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-tab-pane>
        <el-tab-pane label="时间线" name="timeline">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ timelineEvents.length }} 条时间线事件</span>
            <div class="flex-center" style="gap: 8px">
              <el-button
                size="small"
                :disabled="!aiEnabled || host?.status === 'pending'"
                @click="handleModuleAiAnalyze('timeline')"
              >
                AI 分析
              </el-button>
              <el-button size="small" @click="showCompare = true">对比模式</el-button>
              <el-button size="small" @click="handleExportCsv">导出 CSV</el-button>
              <el-button size="small" @click="handleExportPdf">导出 PDF</el-button>
              <el-button size="small" @click="warRoomActive = true">作战视图</el-button>
            </div>
          </div>
          <SummaryStatsBar :host-id="hostId" :stats="timelineStats" @stats-loaded="handleTimelineStatsLoaded" />
          <TimelineFilterBar v-if="activeTab === 'timeline'" :host-id="hostId" @filter-change="handleTimelineFilter" />
          <TimelineChart
            v-if="activeTab === 'timeline'"
            :events="filteredTimelineEvents"
            :stats="timelineStats"
            :adaptive-mode="true"
            :show-sla-line="true"
          />
          <KillChainView v-if="activeTab === 'timeline'" :events="timelineEvents" />
          <EventTable
            :events="filteredTimelineEvents"
            :loading="timelineLoading"
            @row-click="handleTimelineRowClick"
          >
            <template #toolbar>
              <el-button size="small" @click="handleExportCsv">导出 CSV</el-button>
              <el-button size="small" @click="handleExportPdf">导出 PDF</el-button>
            </template>
          </EventTable>
          <EventDetailDrawer
            :event="selectedEvent"
            :visible="drawerVisible"
            :audit-logs="eventAuditLogs"
            @close="drawerVisible = false"
            @status-updated="handleEventStatusUpdate"
          />
          <!-- 对比弹窗 -->
          <el-dialog v-model="showCompare" title="多主机时间线对比" width="90%" top="5vh" destroy-on-close>
            <TimelineCompare :available-hosts="compareHosts" />
          </el-dialog>
          <!-- 作战视图模式 -->
          <WarRoomMode
            v-if="warRoomActive"
            :events="timelineEvents"
            :host-id="Number(hostId)"
            :active="warRoomActive"
            @close="warRoomActive = false"
          />
          <!-- 攻击链 DAG -->
          <AttackChainDag
            v-if="aiReportAttackChain"
            :attack-chain="aiReportAttackChain"
          />
        </el-tab-pane>
        <el-tab-pane label="用户账户" name="users">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ users.length }} 个用户账户</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('users')"
            >
              AI 分析
            </el-button>
          </div>
          <UsersTable :data="users" />
        </el-tab-pane>
        <el-tab-pane label="系统服务" name="services">
          <div class="tab-toolbar">
            <span class="tab-hint">
              共 {{ services.length }} 个服务
              <el-tag v-if="serviceRisk && serviceRisk.summary" size="small" effect="plain" class="status-tag" style="margin-left:8px">
                {{ serviceRisk.summary.high_risk_count }} 个高风险
              </el-tag>
            </span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('services')"
            >
              AI 分析
            </el-button>
          </div>
          <ServicesTable :data="services" :service-risk="serviceRisk" />
        </el-tab-pane>
        <el-tab-pane label="USB 记录" name="usb">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ usb.length }} 条USB记录</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('usb')"
            >
              AI 分析
            </el-button>
          </div>
          <UsbTable :data="usb" />
        </el-tab-pane>
        <el-tab-pane label="远程工具" name="remote_control">
          <div class="tab-toolbar">
            <span class="tab-hint">共 {{ remoteControl.length }} 条远程工具记录</span>
            <el-button
              :disabled="!aiEnabled || host?.status === 'pending'"
              @click="handleModuleAiAnalyze('remote_control')"
            >
              AI 分析
            </el-button>
          </div>
          <RemoteControlTable :data="remoteControl" />
        </el-tab-pane>
        <el-tab-pane label="知识库" name="knowledge">
          <HostKnowledgeTab :host-id="hostId" />
        </el-tab-pane>
        <el-tab-pane label="导入记录" name="import-logs">
          <ImportHistoryTab v-if="activeTab === 'import-logs'" :host-id="Number(hostId)" />
        </el-tab-pane>
        <el-tab-pane label="动态取证" name="triage">
          <div class="tab-toolbar">
            <span class="tab-hint">
              动态取证任务（方案 A：daemon 轮询执行）
              <el-tag v-if="triageActiveCount" size="small" type="warning" effect="plain" class="status-tag" style="margin-left:8px">
                {{ triageActiveCount }} 个任务进行中
              </el-tag>
            </span>
            <div class="flex-center" style="gap:8px">
              <el-button size="small" :loading="triageLoading" @click="loadTriageTasks">刷新</el-button>
              <el-button size="small" type="primary" :loading="triageSubmitting" @click="openTriageDialog">发起取证</el-button>
            </div>
          </div>
          <el-empty v-if="!triageTasks.length" description="暂无动态取证任务，点击「发起取证」向常驻 daemon 下发定向取证指令" :image-size="56" />
          <el-table v-else :data="triageTasks" size="small" stripe>
            <el-table-column prop="id" label="任务ID" width="80" />
            <el-table-column label="取证范围" min-width="200">
              <template #default="{ row }">
                <el-tag v-for="s in (row.scope || [])" :key="s" size="small" effect="plain" class="status-tag" style="margin-right:4px">
                  {{ triageScopeLabel(s) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="triageStatusType(row.status)" size="small" effect="plain">
                  {{ triageStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="下发时间" width="170">
              <template #default="{ row }">{{ row.created_at || '—' }}</template>
            </el-table-column>
            <el-table-column prop="finished_at" label="完成时间" width="170">
              <template #default="{ row }">{{ row.finished_at || '—' }}</template>
            </el-table-column>
            <el-table-column label="取证汇总" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.error" style="color:var(--color-danger-fg)">{{ row.error }}</span>
                <span v-else-if="row.summary">{{ triageSummaryText(row.summary) }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 进程详情面板 -->
    <ProcessDetailPanel
      :visible="detailPanelVisible"
      :process-info="selectedProcess"
      @update:visible="detailPanelVisible = $event"
    />

    <HostImportDialog ref="importDialogRef" :host-id="Number(hostId)" @success="onImportSuccess" />
    <LogImportDialog :visible="showImportLog" :host-id="Number(hostId)" @update:visible="showImportLog = $event" @imported="onLogImported" />
    <AgentDownloadDialog ref="agentDialogRef" />
    <AiAnalysisDialog ref="aiDialogRef" />
    <KnowledgeDetailPopup v-model:visible="knowledgePopupVisible" :entry-ref="knowledgePopupRef" :hit-meta="knowledgePopupMeta" />

    <!-- 动态取证：范围选择 -->
    <el-dialog v-model="triageDialogVisible" title="发起动态取证" width="520px" :close-on-click-modal="false">
      <div class="triage-tip">
        向该主机的常驻 daemon 下发定向取证指令，daemon 将在下次轮询（≤30s）时执行并回传结果。
        取证结果以 <code>source='triage'</code> 追加写入，不会覆盖既有快照数据。
      </div>
      <el-checkbox-group v-model="triageScopeForm">
        <div v-for="opt in triageScopeOptions" :key="opt.value" class="triage-opt">
          <el-checkbox :value="opt.value">
            <span class="triage-opt-label">{{ opt.label }}</span>
            <span class="triage-opt-desc">{{ opt.desc }}</span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="triageDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="triageSubmitting" @click="submitTriage">确认下发</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick, defineAsyncComponent } from 'vue'
import { Search, Upload } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import hostsApi from '@/api/hosts'
import analysisApi from '@/api/analysis'
import triageApi, { TRIAGE_SCOPE_OPTIONS, DEFAULT_TRIAGE_SCOPE } from '@/api/triage'
import RiskBadge from '@/components/RiskBadge.vue'
import ProfileCard from '@/components/ProfileCard.vue'
import AbnormalProcessTable from '@/components/AbnormalProcessTable.vue'
import SuspiciousConnTable from '@/components/SuspiciousConnTable.vue'
import NetworkConnectionTable from '@/components/NetworkConnectionTable.vue'
import FileHashTable from '@/components/FileHashTable.vue'
import PersistenceTable from '@/components/PersistenceTable.vue'
import SuspiciousStartupTable from '@/components/SuspiciousStartupTable.vue'
import IocTable from '@/components/IocTable.vue'
import TimelineChart from '@/components/TimelineChart.vue'
import SummaryStatsBar from '@/components/SummaryStatsBar.vue'
import TimelineFilterBar from '@/components/timeline/TimelineFilterBar.vue'
import EventTable from '@/components/timeline/EventTable.vue'
import EventDetailDrawer from '@/components/timeline/EventDetailDrawer.vue'
import KillChainView from '@/components/timeline/KillChainView.vue'
import TimelineCompare from '@/components/timeline/TimelineCompare.vue'
import WarRoomMode from '@/components/timeline/WarRoomMode.vue'
import AttackChainDag from '@/components/timeline/AttackChainDag.vue'
import UsersTable from '@/components/UsersTable.vue'
import ServicesTable from '@/components/ServicesTable.vue'
import UsbTable from '@/components/UsbTable.vue'
import RemoteControlTable from '@/components/RemoteControlTable.vue'
import HostImportDialog from '@/components/HostImportDialog.vue'
import AgentDownloadDialog from '@/components/AgentDownloadDialog.vue'
import AiAnalysisDialog from '@/components/AiAnalysisDialog.vue'
import ProcessTreeChart from '@/components/ProcessTreeChart.vue'
import ProcessDetailPanel from '@/components/ProcessDetailPanel.vue'
import ProcessStatsCards from '@/components/ProcessStatsCards.vue'
import HostKnowledgeTab from '@/components/HostKnowledgeTab.vue'
// #20: 大型面板改为懒加载
const WebShellPanel = defineAsyncComponent(() => import('@/components/WebShellPanel.vue'))
const MemoryShellPanel = defineAsyncComponent(() => import('@/components/MemoryShellPanel.vue'))
const ProcessTreeView = defineAsyncComponent(() => import('@/components/ProcessTreeView.vue'))
import IncidentPanel from '@/components/ai/IncidentPanel.vue'
import KnowledgeDetailPopup from '@/components/KnowledgeDetailPopup.vue'
import LogImportDialog from '@/components/LogImportDialog.vue'
import ImportHistoryTab from '@/components/ImportHistoryTab.vue'
import { getAiConfig } from '@/api/ai'

const route = useRoute()
const hostId = route.params.id

const host = ref(null)
const analysis = ref(null)
const profile = ref(null)
const loading = ref(false)
const analyzing = ref(false)
const enriching = ref(false)
const activeTab = ref('profile')
const summaryCollapsed = ref(false)
const knowledgeCollapsed = ref(false)

// 切换到「时间线」Tab 时自动收起分析摘要和知识匹配，给图表腾出首屏空间
watch(activeTab, (tab) => {
  if (tab === 'timeline') {
    summaryCollapsed.value = true
    knowledgeCollapsed.value = true
  }
}, { immediate: true })

const abnormalProcesses = ref([])
const suspiciousConnections = ref([])
const persistenceItems = ref([])
const startupItems = ref([])
const iocHits = ref([])
const timelineEvents = ref([])
const users = ref([])
const services = ref([])
const usb = ref([])
const remoteControl = ref([])
const networkConnections = ref([])
const fileHashes = ref([])
const wmiSubscriptions = ref([])
const registryKeys = ref([])
const serviceRisk = ref(null)

const timelineStats = ref(null)
const timelineLoading = ref(false)
const filteredTimelineEvents = ref([])
const selectedEvent = ref(null)
const drawerVisible = ref(false)
const eventAuditLogs = ref([])
const filterParams = ref({})
const showCompare = ref(false)
const warRoomActive = ref(false)

// 新增：进程树相关数据
const processTree = ref({})
const abnormalPidsForTree = ref([])
const selectedProcess = ref(null)
const detailPanelVisible = ref(false)

const importDialogRef = ref(null)
const showImportLog = ref(false)
const agentDialogRef = ref(null)
const aiDialogRef = ref(null)
const aiEnabled = ref(null) // null=未加载, true=开启, false=关闭

// ── 动态取证（Phase 2 / 方案 A 轮询） ──
const triageScopeOptions = TRIAGE_SCOPE_OPTIONS
const triageTasks = ref([])
const triageLoading = ref(false)
const triageSubmitting = ref(false)
const triageDialogVisible = ref(false)
const triageScopeForm = ref([...DEFAULT_TRIAGE_SCOPE])
let triagePollTimer = null

// ── 知识详情弹窗 ──
const knowledgePopupVisible = ref(false)
const knowledgePopupRef = ref('')
const knowledgePopupMeta = ref({})

function showKnowledgePopup(kh) {
  // 支持两种调用方式：
  // 1. 从知识匹配卡片传入完整 kh 对象
  // 2. 从子组件 @knowledge-click 事件传入 entryRef 字符串
  if (typeof kh === 'object' && kh !== null) {
    if (!kh.entry_ref || kh.entry_ref === 'unknown') return
    knowledgePopupRef.value = kh.entry_ref
    knowledgePopupMeta.value = kh
  } else {
    const entryRef = kh
    if (!entryRef || entryRef === 'unknown') return
    knowledgePopupRef.value = entryRef
    knowledgePopupMeta.value = {}
  }
  knowledgePopupVisible.value = true
}

// ── 模块 AI 分析映射 ──
const MODULE_TAB_MAP = {
  profile: 'profile',
  tree: 'process_list',
  processes: 'abnormal_processes',
  connections: 'connections',
  persistence: 'persistence',
  startup: 'startup',
  ioc: 'ioc',
  timeline: 'timeline',
  users: 'users',
  services: 'services',
  usb: 'usb',
  remote_control: 'remote_control',
}

const TAB_DATA_LABEL = {
  profile: '',
  tree: '',
  processes: '条异常进程',
  connections: '条可疑外连',
  persistence: '条持久化痕迹',
  startup: '条可疑启动项',
  ioc: '条IOC命中',
  timeline: '条时间线事件',
  users: '个用户账户',
  services: '个系统服务',
  usb: '条USB记录',
  remote_control: '条远程工具记录',
  network: '条网络连接',
  filehash: '条文件哈希',
  knowledge: '',
}

const alertType = computed(() => {
  const map = {
    critical: 'error',
    high: 'error',
    medium: 'warning',
    low: 'info',
    info: 'info'
  }
  return map[analysis.value?.risk_level] || 'info'
})

onMounted(() => {
  loadHost()
  loadAnalysis()
  loadAiStatus()
  loadTriageTasks()
})

onUnmounted(() => {
  stopTriagePolling()
})

async function loadHost() {
  loading.value = true
  try {
    const res = await hostsApi.get(hostId)
    host.value = res.data
  } catch (error) {
    // handled
  } finally {
    loading.value = false
  }
}

async function loadAnalysis() {
  try {
    const res = await analysisApi.getAnalysis(hostId)
    analysis.value = res.data
    if (res.data) {
      loadProfile()
      loadAllResults()
    }
  } catch (error) {
    // handled
  }
}

async function loadProfile() {
  try {
    const res = await analysisApi.getProfile(hostId)
    profile.value = res.data
  } catch (error) {
    // handled
  }
}

async function loadAllResults() {
  // Phase 1: Core analysis results — all must succeed
  try {
    const [procRes, connRes, persRes, startupRes, iocRes, tlRes] = await Promise.all([
      analysisApi.getAbnormalProcesses(hostId),
      analysisApi.getSuspiciousConnections(hostId),
      analysisApi.getPersistence(hostId),
      analysisApi.getStartupItems(hostId),
      analysisApi.getIocHits(hostId),
      analysisApi.getTimeline(hostId)
    ])
    abnormalProcesses.value = procRes.data
    suspiciousConnections.value = connRes.data
    persistenceItems.value = persRes.data
    startupItems.value = startupRes.data
    iocHits.value = iocRes.data
    timelineEvents.value = tlRes.data || []
    filteredTimelineEvents.value = tlRes.data || []

    // 提取异常 PID 列表用于进程树
    abnormalPidsForTree.value = abnormalProcesses.value.map(p => p.pid)
  } catch (error) {
    // handled by axios interceptor
  }

  // Phase 2: Process tree data（请求增强字段 enrich=1，向后兼容旧组件/旧 API）
  try {
    const treeRes = await analysisApi.getProcessTree(hostId, { enrich: 1 })
    processTree.value = treeRes.data
  } catch (error) {
    processTree.value = {}
    ElMessage.error('进程树数据加载失败')
  }

  // Phase 3: Collection data tabs — tolerate 404, show empty lists on failure
  try { users.value = (await analysisApi.getUsers(hostId)).data } catch (e) { users.value = [] }
  try { services.value = (await analysisApi.getServices(hostId)).data } catch (e) { services.value = [] }
  try { serviceRisk.value = (await analysisApi.getServiceRisk(hostId)).data } catch (e) { serviceRisk.value = null }
  try { usb.value = (await analysisApi.getUsb(hostId)).data } catch (e) { usb.value = [] }
  try { remoteControl.value = (await analysisApi.getRemoteControl(hostId)).data } catch (e) { remoteControl.value = [] }

  // Phase 4: New data collection tabs (P1-2, P1-3, P1-5, P1-6)
  await Promise.allSettled([
    analysisApi.getNetworkConnections(hostId).then(r => { networkConnections.value = r.data || [] }).catch(() => { networkConnections.value = [] }),
    analysisApi.getFileHashes(hostId).then(r => { fileHashes.value = r.data || [] }).catch(() => { fileHashes.value = [] }),
    analysisApi.getWmiSubscriptions(hostId).then(r => { wmiSubscriptions.value = r.data || [] }).catch(() => { wmiSubscriptions.value = [] }),
    analysisApi.getRegistryKeys(hostId).then(r => { registryKeys.value = r.data || [] }).catch(() => { registryKeys.value = [] }),
  ])

}

async function handleAnalyze() {
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  analyzing.value = true
  try {
    await analysisApi.analyze(hostId)
    ElMessage.success('分析完成')
    await loadHost()
    await loadAnalysis()
  } catch (error) {
    // handled
  } finally {
    analyzing.value = false
  }
}

async function reloadConnections() {
  try {
    const res = await analysisApi.getSuspiciousConnections(hostId)
    suspiciousConnections.value = res.data || []
  } catch (error) {
    // handled by axios interceptor
  }
}

async function handleEnrichConns() {
  enriching.value = true
  try {
    const res = await analysisApi.enrichSuspiciousConnections(hostId)
    const s = res.data || {}
    const parts = [`检测公网 IP ${s.public || 0} 个`]
    if (s.malicious) parts.push(`恶意 ${s.malicious}`)
    if (s.suspicious) parts.push(`可疑 ${s.suspicious}`)
    if (s.skipped_private) parts.push(`私网跳过 ${s.skipped_private}`)
    if (s.errors && s.errors.length) parts.push(`失败 ${s.errors.length}`)
    ElMessage.success('威胁情报检测完成：' + parts.join('，'))
    // 刷新列表以展示最新威胁情报标签
    await reloadConnections()
    if (activeTab.value !== 'connections') {
      activeTab.value = 'connections'
    }
  } catch (error) {
    // handled by axios interceptor
  } finally {
    enriching.value = false
  }
}

async function loadAiStatus() {
  try {
    const res = await getAiConfig()
    aiEnabled.value = res.data?.config?.enabled === 1
  } catch (error) {
    aiEnabled.value = null
  }
}

function handleAiAnalyze() {
  if (aiEnabled.value === null || aiEnabled.value === false) {
    ElMessage.warning('AI 分析功能未开启，请先在配置页面开启')
    return
  }
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  aiDialogRef.value?.show(Number(hostId))
}

/** 获取 tab 的数据计数 */
function getTabDataCount(tabName) {
  const map = {
    profile: null,
    tree: null,
    processes: abnormalProcesses.value?.length,
    connections: suspiciousConnections.value?.length,
    persistence: persistenceItems.value?.length,
    startup: startupItems.value?.length,
    ioc: iocHits.value?.length,
    timeline: timelineEvents.value?.length,
    users: users.value?.length,
    services: services.value?.length,
    usb: usb.value?.length,
    remote_control: remoteControl.value?.length,
    network: networkConnections.value?.length,
    filehash: fileHashes.value?.length,
  }
  return map[tabName] ?? null
}

/** 模块 AI 分析 */
function handleModuleAiAnalyze(moduleType) {
  if (aiEnabled.value === null || aiEnabled.value === false) {
    ElMessage.warning('AI 分析功能未开启，请先在配置页面开启')
    return
  }
  if (host.value?.status === 'pending') {
    ElMessage.warning('请先导入采集数据')
    return
  }
  aiDialogRef.value?.show(Number(hostId), host.value?.hostname || '', 'module', moduleType)
}

function onImportSuccess() {
  loadHost()
}

function onLogImported(data) {
  // 日志导入完成后切换到导入记录标签页查看结果
  if (data?.status === 'completed' || data?.status === 'processing') {
    nextTick(() => {
      activeTab.value = 'import-logs'
    })
  }
}

// ── 动态取证（Phase 2 / 方案 A 轮询） ──
function openTriageDialog() {
  triageScopeForm.value = [...DEFAULT_TRIAGE_SCOPE]
  triageDialogVisible.value = true
}

async function loadTriageTasks() {
  triageLoading.value = true
  try {
    const res = await triageApi.list(hostId)
    triageTasks.value = res.data || []
    // 仍有进行中任务则继续保持轮询
    if (triageActiveCount.value > 0) {
      ensureTriagePolling()
    } else {
      stopTriagePolling()
    }
  } catch (e) {
    triageTasks.value = []
  } finally {
    triageLoading.value = false
  }
}

async function submitTriage() {
  const scope = (triageScopeForm.value || []).filter(s => DEFAULT_TRIAGE_SCOPE.includes(s))
  if (!scope.length) {
    ElMessage.warning('请至少选择一个取证范围')
    return
  }
  triageSubmitting.value = true
  try {
    await triageApi.create(hostId, scope)
    ElMessage.success('取证任务已下发，daemon 将在 ≤30s 内执行')
    triageDialogVisible.value = false
    await loadTriageTasks()
    activeTab.value = 'triage'
    ensureTriagePolling()
  } catch (e) {
    // 由 axios 拦截器统一提示
  } finally {
    triageSubmitting.value = false
  }
}

function ensureTriagePolling() {
  if (triagePollTimer) return
  triagePollTimer = setInterval(() => {
    if (triageActiveCount.value === 0) {
      stopTriagePolling()
      return
    }
    loadTriageTasks()
  }, 5000)
}

function stopTriagePolling() {
  if (triagePollTimer) {
    clearInterval(triagePollTimer)
    triagePollTimer = null
  }
}

const triageActiveCount = computed(() =>
  triageTasks.value.filter(t => t.status === 'pending' || t.status === 'running').length
)

function triageScopeLabel(s) {
  const map = { file_hashes: '文件哈希', network: '实时网络连接', process_subtree: '进程子树' }
  return map[s] || s
}

function triageStatusType(status) {
  const map = { pending: 'info', running: 'warning', done: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function triageStatusLabel(status) {
  const map = { pending: '待执行', running: '执行中', done: '已完成', failed: '失败' }
  return map[status] || status
}

function triageSummaryText(summary) {
  if (!summary || typeof summary !== 'object') return '—'
  const parts = []
  if (summary.file_hashes != null) parts.push(`文件哈希 ${summary.file_hashes}`)
  if (summary.network_connections != null) parts.push(`网络连接 ${summary.network_connections}`)
  if (summary.process_events != null) parts.push(`进程事件 ${summary.process_events}`)
  return parts.length ? parts.join('，') : '已回传'
}

/** 异常进程表格查看详情事件（进程树改用 ProcessTreeView 内部详情面板，不再联动此处） */
function handleViewDetail(row) {
  selectedProcess.value = row
  detailPanelVisible.value = true
}

/** 内存码面板 PID 点击 → 跳转进程树 Tab（后续可按 pid 高亮节点） */
function handleViewTreeByPid(_pid) {
  activeTab.value = 'tree'
}

/** 融合事件「关联发现」点击 → 按类型跳转到对应面板 */
function handleJumpFinding(rf) {
  const label = typeof rf === 'string' ? rf : (rf?.type || rf?.ref || rf?.label || '')
  const s = String(label).toLowerCase()
  if (s.includes('webshell') || s.includes('web_shell') || s.includes('memory') || s.includes('内存')) {
    activeTab.value = 'fusion'
  } else if (s.includes('ioc')) {
    activeTab.value = 'ioc'
  } else if (s.includes('process') || s.includes('进程')) {
    activeTab.value = 'processes'
  } else {
    activeTab.value = 'processes'
  }
}

function handleTabChange(_tabName) {
  // v-if 已确保组件仅在 Tab 可见时挂载，ECharts 在 onMounted 中初始化即可获得正确容器尺寸
  // TimelineChart: echarts.init + window.resize listener
  // ProcessTreeChart: vue-echarts autoresize (ResizeObserver)
  // 无需在此处触发 window.resize
}

function handleTimelineStatsLoaded(statsData) {
  timelineStats.value = statsData
}

// ── 时间线过滤 ──
async function handleTimelineFilter(params) {
  filterParams.value = params
  timelineLoading.value = true
  try {
    const apiParams = {}
    if (params.start) apiParams.start = params.start
    if (params.end) apiParams.end = params.end
    if (params.eventTypes && params.eventTypes.length > 0) {
      apiParams.event_types = params.eventTypes.join(',')
    }
    if (params.severities && params.severities.length > 0) {
      apiParams.severity = params.severities.join(',')
    }
    const res = await analysisApi.getTimeline(hostId, apiParams)
    filteredTimelineEvents.value = res.data || []
  } catch (e) {
    filteredTimelineEvents.value = timelineEvents.value
  } finally {
    timelineLoading.value = false
  }
}

// ── 表格行点击 ──
function handleTimelineRowClick(event) {
  selectedEvent.value = event
  drawerVisible.value = true
  eventAuditLogs.value = []
}

// ── 事件状态更新 ──
async function handleEventStatusUpdate({ eventId, status, resolution }) {
  try {
    await analysisApi.updateTimelineEvent(eventId, { status, resolution, operator: 'admin' })
    ElMessage.success('状态更新成功')
    drawerVisible.value = false
    // 刷新数据
    await loadAllResults()
  } catch (e) {
    ElMessage.error('状态更新失败')
  }
}

// ── 导出 CSV ──
function handleExportCsv() {
  const params = new URLSearchParams()
  if (filterParams.value.start) params.append('start', filterParams.value.start)
  if (filterParams.value.end) params.append('end', filterParams.value.end)
  if (filterParams.value.eventTypes?.length) params.append('event_types', filterParams.value.eventTypes.join(','))
  if (filterParams.value.severities?.length) params.append('severity', filterParams.value.severities.join(','))
  const url = `${import.meta.env.VITE_API_BASE || ''}/api/analysis/timeline/${hostId}/export/csv?${params.toString()}`
  window.open(url, '_blank')
}

// ── 导出 PDF ──
async function handleExportPdf() {
  try {
    const params = new URLSearchParams()
    if (filterParams.value.start) params.append('start', filterParams.value.start)
    if (filterParams.value.end) params.append('end', filterParams.value.end)
    const url = `${import.meta.env.VITE_API_BASE || ''}/api/analysis/timeline/${hostId}/export/pdf?${params.toString()}`
    const response = await fetch(url, { headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` } })
    const blob = await response.blob()
    const downloadUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = downloadUrl
    a.download = `timeline_${hostId}.pdf`
    a.click()
    URL.revokeObjectURL(downloadUrl)
  } catch (e) {
    ElMessage.error('PDF 导出失败')
  }
}

// 对比主机列表（同一 case 下的主机）
const compareHosts = computed(() => {
  if (host.value) {
    return [{ id: Number(hostId), hostname: host.value.hostname }]
  }
  return []
})

// AI 报告中的 attack_chain（用于 AttackChainDag）
const aiReportAttackChain = computed(() => {
  return null // 从 AI 分析报告中获取，T04 完善
})

// ── 融合检测（WebShell / 内存码 / 融合事件）：取自 /analysis 响应的增量字段 ──
const webshells = computed(() => analysis.value?.webshells || [])
const memoryShells = computed(() => analysis.value?.memory_shells || [])
const incidents = computed(() => analysis.value?.incidents || [])
const knowledgeHits = computed(() => analysis.value?.knowledge_hits || [])
const hasFusionData = computed(
  () => !!(webshells.value.length || memoryShells.value.length || incidents.value.length || knowledgeHits.value.length)
)

// ── 融合检测筛选 ──
const fusionSearch = ref('')
const fusionFilter = ref('')
const fusionTypeFilter = ref('')
const fusionActiveNames = ref(['incidents', 'knowledge_hits'])  // 默认展开

function confTag(c) {
  return c === 'high' ? 'danger' : c === 'medium' ? 'warning' : 'info'
}
function sevTag(s) {
  const map = { critical: 'danger', high: 'danger', medium: 'warning', low: 'primary' }
  return map[s] || 'info'
}
function evidenceTypeLabel(t) {
  const map = { process: '进程', connection: '外连', webshell_ms: 'WebShell', memory_shell: '内存码', persistence: '持久化' }
  return map[t] || t
}

const filteredKnowledgeHits = computed(() => {
  let items = knowledgeHits.value
  const kw = fusionSearch.value.trim().toLowerCase()
  const sev = fusionFilter.value
  const type = fusionTypeFilter.value

  if (type && type !== 'knowledge') return []

  if (sev) {
    items = items.filter(h => (h.severity || '').toLowerCase() === sev)
  }
  if (kw) {
    items = items.filter(h =>
      (h.title || '').toLowerCase().includes(kw) ||
      (h.description || '').toLowerCase().includes(kw) ||
      (h.evidence_key || '').toLowerCase().includes(kw) ||
      (h.evidence_type || '').toLowerCase().includes(kw)
    )
  }
  return items
})

const filteredIncidents = computed(() => {
  const type = fusionTypeFilter.value
  if (type && type !== 'incident') return []
  return incidents.value
})

const filteredWebshells = computed(() => {
  const type = fusionTypeFilter.value
  if (type && type !== 'webshell') return []
  return webshells.value
})

const filteredMemoryShells = computed(() => {
  const type = fusionTypeFilter.value
  if (type && type !== 'memory_shell') return []
  return memoryShells.value
})

const filteredFusionItems = computed(() => {
  let count = 0
  const type = fusionTypeFilter.value
  if (!type || type === 'incident') count += incidents.value.length
  if (!type || type === 'webshell') count += webshells.value.length
  if (!type || type === 'memory_shell') count += memoryShells.value.length
  if (!type || type === 'knowledge') count += filteredKnowledgeHits.value.length
  return Array(count).fill(null)  // 只用作 count
})

function statusType(status) {
  const map = { pending: 'info', imported: 'warning', analyzed: 'success' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { pending: '待采集', imported: '已导入', analyzed: '已分析' }
  return map[status] || status
}
</script>

<style scoped>
/* ── Tab 工具栏 ── */
.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding: 6px 10px;
  background: var(--color-canvas-subtle);
  border-radius: 6px;
  border: 0.5px solid var(--color-border-default);
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
  user-select: none;
}
.section-header:hover { opacity: 0.8; }
.mt-8 { margin-top: 8px; }
.mb-0 { margin-bottom: 0; }
.tab-hint {
  font-size: 13px;
  color: var(--color-fg-muted);
}
.flex-center {
  display: flex;
  align-items: center;
}
.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
/* ── 融合检测 Tab ── */
.toolbar-right { display: flex; align-items: center; }
.fusion-collapse { border: none; }
.fusion-collapse :deep(.el-collapse-item__header) {
  font-weight: 500;
  font-size: 14px;
  padding: 8px 12px;
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  margin-bottom: 8px;
  background: var(--color-canvas-subtle);
}
.fusion-collapse :deep(.el-collapse-item__wrap) { border: none; padding: 0; }
.collapse-title { display: flex; align-items: center; gap: 10px; }

/* ── 知识匹配卡片 ── */
.kh-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.kh-card {
  border: 0.5px solid var(--color-border-default);
  border-radius: 6px;
  padding: 12px;
  background: var(--color-canvas-subtle);
  transition: box-shadow 0.2s;
  cursor: pointer;
}
.kh-card:hover { box-shadow: 0 1px 4px var(--color-border-default); }
.kh-card.kh-needs-review { border-color: var(--color-fg-subtle); background: var(--color-canvas-subtle); }
.kh-header { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.kh-title { font-weight: 500; font-size: 14px; margin-left: 4px; }
.kh-desc { color: var(--color-fg-muted); font-size: 12px; margin-top: 6px; }
.kh-meta { color: var(--color-fg-subtle); font-size: 11px; margin-top: 4px; }

/* ── 辅助文本 ── */
.kh-subtle-hint {
  font-size: 13px;
  color: var(--color-fg-subtle);
  font-weight: 400;
}
.fusion-stats {
  margin-left: 12px;
  color: var(--color-fg-subtle);
  font-size: 12px;
}
.needs-review-text {
  color: var(--color-fg-subtle);
  font-size: 12px;
}
.review-passed-text {
  color: var(--color-fg-muted);
  font-size: 12px;
}

/* ===== HostDetail IR 设计规范覆盖 ===== */
.page-container {
  padding: 16px;
  background: var(--color-canvas-subtle, #fafafa);
  min-height: calc(100vh - 56px);
}
.card-box {
  background: var(--color-canvas-default, #fff);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 12px;
}
.page-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--color-fg-default, #111);
  margin: 0;
}
.flex-between { display: flex; justify-content: space-between; align-items: center; }

/* 状态 tag 浅色 */
.status-tag {
  border: none !important;
  background: transparent !important;
  padding: 0 6px !important;
  font-size: 11px !important;
  font-weight: 500 !important;
}

/* descriptions 弱化 */
.card-box :deep(.el-descriptions__label) {
  color: var(--color-fg-subtle, #888);
  font-size: 12px;
  font-weight: 400;
}
.card-box :deep(.el-descriptions__content) {
  font-size: 13px;
  font-weight: 400;
  color: var(--color-fg-default, #111);
}

/* 表格/卡片弱化 */
.card-box :deep(.el-card) {
  border: 0.5px solid var(--color-border-default) !important;
  border-radius: 10px !important;
}
.card-box :deep(.el-card__header) {
  font-size: 13px;
  font-weight: 500;
  border-bottom: 0.5px solid var(--color-border-default);
  padding: 14px 20px;
}
/* 仅作用于 .card-box 直接子级的 el-card，避免穿透到 SummaryStatsBar
   等子组件内部的统计卡，把统计卡撑高 */
.card-box > :deep(.el-card > .el-card__body) {
  padding: 16px 20px;
}

/* 按钮圆角 */
.el-button {
  border-radius: 6px;
  font-weight: 500;
}

/* ── 动态取证弹窗 ── */
.triage-tip {
  font-size: 12px;
  color: var(--color-fg-muted, #666);
  background: var(--color-canvas-subtle, #f6f8fa);
  border: 0.5px solid var(--color-border-default, #e5e5e5);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 14px;
  line-height: 1.6;
}
.triage-tip code {
  background: rgba(110, 119, 129, 0.12);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
}
.triage-opt {
  margin-bottom: 10px;
}
.triage-opt :deep(.el-checkbox) {
  align-items: flex-start;
  height: auto;
}
.triage-opt-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-fg-default, #111);
}
.triage-opt-desc {
  display: block;
  font-size: 12px;
  color: var(--color-fg-muted, #666);
  margin-top: 2px;
  line-height: 1.5;
}
</style>
