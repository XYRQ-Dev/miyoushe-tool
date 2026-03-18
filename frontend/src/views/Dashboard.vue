<template>
  <div class="dashboard">
    <div class="stat-cards">
      <div class="stat-card" style="--accent: #2563eb">
        <div class="stat-icon">
          <el-icon :size="24"><User /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.total_accounts || 0 }}</div>
          <div class="stat-label">绑定账号</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #0f9f6e">
        <div class="stat-icon">
          <el-icon :size="24"><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.signed_today || 0 }}</div>
          <div class="stat-label">今日已签</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #dc2626">
        <div class="stat-icon">
          <el-icon :size="24"><CircleClose /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.failed_today || 0 }}</div>
          <div class="stat-label">签到失败</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #d97706">
        <div class="stat-icon">
          <el-icon :size="24"><Warning /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.pending || 0 }}</div>
          <div class="stat-label">待签到</div>
        </div>
      </div>
    </div>

    <div class="action-bar">
      <el-button
        type="primary"
        :icon="Refresh"
        :loading="executing"
        @click="handleExecute"
        round
      >
        立即签到
      </el-button>
      <el-button :icon="Refresh" @click="loadData" round>刷新</el-button>
    </div>

    <section class="notes-panel">
      <div class="notes-shell">
        <div class="notes-hero">
          <div class="notes-copy">
            <p class="notes-kicker">Realtime Notes</p>
            <h3>实时便笺面板</h3>
            <p class="notes-desc">
              在仪表盘直接查看体力、委托和资源恢复情况。首版聚合原神与星穹铁道角色状态，
              让首页从“只看签到”升级为“顺手看资产”。
            </p>
          </div>
          <div class="notes-summary">
            <div class="summary-pill summary-pill-available">
              <span class="summary-pill-label">可用卡片</span>
              <span class="summary-pill-value">{{ noteSummary.available_cards }}</span>
            </div>
            <div class="summary-pill summary-pill-failed">
              <span class="summary-pill-label">异常卡片</span>
              <span class="summary-pill-value">{{ noteSummary.failed_cards }}</span>
            </div>
          </div>
        </div>

        <el-card class="notes-card" shadow="never">
          <template #header>
            <div class="notes-header">
              <div>
                <div class="notes-title">按账号查看实时状态</div>
                <div class="notes-subtitle">当前展示该账号下所有已接入便笺的游戏角色。</div>
              </div>
              <div class="notes-actions">
                <el-select
                  v-model="selectedNoteAccountId"
                  class="notes-account-select"
                  placeholder="请选择账号"
                  filterable
                  :disabled="notesLoading || !noteAccounts.length"
                  @change="handleNoteAccountChange"
                >
                  <el-option
                    v-for="account in noteAccounts"
                    :key="account.id"
                    :label="formatNoteAccountLabel(account)"
                    :value="account.id"
                  />
                </el-select>
                <el-button :icon="Refresh" :loading="notesLoading" @click="loadNotesPanel">
                  刷新便笺
                </el-button>
              </div>
            </div>
          </template>

          <el-skeleton :loading="notesLoading" animated :rows="8">
            <template #default>
              <el-empty
                v-if="!noteAccounts.length"
                description="当前还没有支持实时便笺的账号，先完成一次账号导入"
                :image-size="84"
              />
              <el-empty
                v-else-if="!selectedNoteAccountId"
                description="请选择一个账号查看实时便笺"
                :image-size="84"
              />
              <el-empty
                v-else-if="!noteCards.length"
                description="当前账号下暂无可展示的实时便笺角色"
                :image-size="84"
              />
              <div v-else class="notes-grid">
                <article
                  v-for="card in noteCards"
                  :key="`${card.game}-${card.role_id}`"
                  class="note-card"
                  :class="[`note-card-${card.game}`, `note-card-${card.status}`]"
                >
                  <div class="note-card-head">
                    <div>
                      <div class="note-game-row">
                        <span class="note-game-chip">{{ card.game_name }}</span>
                        <el-tag size="small" round :type="getNoteStatusType(card.status)">
                          {{ getNoteStatusText(card.status) }}
                        </el-tag>
                      </div>
                      <div class="note-role-name">{{ card.role_nickname || card.role_uid }}</div>
                      <div class="note-role-meta">
                        UID {{ card.role_uid }}
                        <span v-if="card.region"> · {{ card.region }}</span>
                        <span v-if="card.level"> · Lv.{{ card.level }}</span>
                      </div>
                    </div>
                    <div class="note-updated">
                      {{ card.updated_at ? `更新于 ${card.updated_at}` : '等待最新状态' }}
                    </div>
                  </div>

                  <div v-if="card.status !== 'available'" class="note-error">
                    <el-icon><Warning /></el-icon>
                    <span>{{ card.message || '当前无法获取便笺信息' }}</span>
                  </div>

                  <div v-else class="note-metrics">
                    <div
                      v-for="metric in card.metrics"
                      :key="metric.key"
                      class="note-metric"
                      :class="`tone-${metric.tone}`"
                    >
                      <div class="note-metric-label">{{ metric.label }}</div>
                      <div class="note-metric-value">{{ metric.value }}</div>
                      <div class="note-metric-detail">{{ metric.detail || '当前无额外说明' }}</div>
                    </div>
                  </div>
                </article>
              </div>
            </template>
          </el-skeleton>
        </el-card>
      </div>
    </section>

    <el-card v-if="checkinResults.length" class="result-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>签到结果</span>
          <el-tag :type="summaryType" size="small">
            成功 {{ summary.success }} / 失败 {{ summary.failed }}
          </el-tag>
        </div>
      </template>
      <div class="result-list">
        <div
          v-for="(result, idx) in checkinResults"
          :key="idx"
          class="result-item"
        >
          <StatusBadge :status="result.status" />
          <span class="result-message">{{ result.message }}</span>
          <span v-if="result.total_sign_days" class="sign-days">
            累计 {{ result.total_sign_days }} 天
          </span>
        </div>
      </div>
    </el-card>

    <el-card class="calendar-card" shadow="never">
      <template #header>
        <span>最近 7 天签到记录</span>
      </template>
      <div class="calendar-grid">
        <div
          v-for="day in calendar"
          :key="day.date"
          class="calendar-day"
          :class="{
            'day-success': day.success > 0 && day.failed === 0,
            'day-partial': day.success > 0 && day.failed > 0,
            'day-failed': day.total > 0 && day.success === 0,
            'day-empty': day.total === 0,
          }"
        >
          <div class="day-date">{{ formatDate(day.date) }}</div>
          <div class="day-status">
            <template v-if="day.total > 0">
              <el-icon v-if="day.failed === 0"><CircleCheck /></el-icon>
              <el-icon v-else><Warning /></el-icon>
            </template>
            <span v-else class="day-dash">-</span>
          </div>
          <div class="day-count" v-if="day.total > 0">
            {{ day.success }}/{{ day.total }}
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  User, CircleCheck, CircleClose, Warning, Refresh,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { logApi, notesApi, taskApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

type NoteAccount = {
  id: number
  nickname?: string
  mihoyo_uid?: string
  supported_games: string[]
}

type NoteMetric = {
  key: string
  label: string
  value: string
  detail?: string | null
  tone: string
}

type NoteCard = {
  role_id: number
  game: string
  game_name: string
  game_biz: string
  role_uid: string
  role_nickname?: string | null
  region?: string | null
  level?: number | null
  status: string
  message?: string | null
  updated_at?: string | null
  metrics: NoteMetric[]
}

const status = ref<any>({})
const calendar = ref<any[]>([])
const checkinResults = ref<any[]>([])
const summary = ref({ success: 0, failed: 0, already_signed: 0, risk: 0, total: 0 })
const executing = ref(false)

const noteAccounts = ref<NoteAccount[]>([])
const selectedNoteAccountId = ref<number | null>(null)
const notesLoading = ref(false)
const noteSummary = ref({
  account_id: 0,
  account_name: '',
  total_cards: 0,
  available_cards: 0,
  failed_cards: 0,
  cards: [] as NoteCard[],
})

const noteCards = computed(() => noteSummary.value.cards || [])

const summaryType = computed(() => {
  if (summary.value.failed > 0) return 'danger'
  if (summary.value.risk > 0) return 'warning'
  return 'success'
})

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function formatNoteAccountLabel(account: NoteAccount) {
  const primary = account.nickname || account.mihoyo_uid || `账号 #${account.id}`
  const games = account.supported_games.join(' / ')
  return `${primary}${games ? ` · ${games}` : ''}`
}

function getNoteStatusText(statusText: string) {
  if (statusText === 'available') return '可用'
  if (statusText === 'invalid_cookie') return '登录失效'
  return '查询失败'
}

function getNoteStatusType(statusText: string) {
  if (statusText === 'available') return 'success'
  if (statusText === 'invalid_cookie') return 'warning'
  return 'danger'
}

function resetNoteSummary() {
  noteSummary.value = {
    account_id: 0,
    account_name: '',
    total_cards: 0,
    available_cards: 0,
    failed_cards: 0,
    cards: [],
  }
}

async function loadDashboardSummary() {
  try {
    const [statusRes, calRes] = await Promise.all([
      taskApi.getStatus(),
      logApi.getCalendar(7),
    ])
    status.value = statusRes.data
    calendar.value = calRes.data.calendar.reverse()
  } catch (e) {
    // 错误已在拦截器中处理
  }
}

async function loadNotesSummary() {
  if (!selectedNoteAccountId.value) {
    resetNoteSummary()
    return
  }

  try {
    const { data } = await notesApi.getSummary({
      account_id: selectedNoteAccountId.value,
    })
    noteSummary.value = data
  } catch (e) {
    resetNoteSummary()
  }
}

async function loadNotesPanel() {
  notesLoading.value = true
  try {
    const { data } = await notesApi.getAccounts()
    noteAccounts.value = data.accounts || []

    if (!noteAccounts.value.length) {
      selectedNoteAccountId.value = null
      resetNoteSummary()
      return
    }

    const selectedStillExists = noteAccounts.value.some((account) => account.id === selectedNoteAccountId.value)
    if (!selectedStillExists) {
      selectedNoteAccountId.value = noteAccounts.value[0].id
    }

    await loadNotesSummary()
  } catch (e) {
    noteAccounts.value = []
    selectedNoteAccountId.value = null
    resetNoteSummary()
  } finally {
    notesLoading.value = false
  }
}

async function handleNoteAccountChange() {
  notesLoading.value = true
  try {
    await loadNotesSummary()
  } finally {
    notesLoading.value = false
  }
}

async function loadData() {
  await Promise.all([
    loadDashboardSummary(),
    loadNotesPanel(),
  ])
}

async function handleExecute() {
  executing.value = true
  try {
    const { data } = await taskApi.execute()
    summary.value = data
    checkinResults.value = data.results || []
    ElMessage.success(`签到完成：成功 ${data.success}，失败 ${data.failed}`)
    await loadData()
  } catch (e) {
    // 错误已在拦截器中处理
  } finally {
    executing.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--card-bg);
  border-radius: 16px;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.09);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.action-bar {
  margin-bottom: 24px;
  display: flex;
  gap: 12px;
}

.action-bar .el-button--primary {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 45%, #0f766e 100%);
  border: none;
}

.notes-panel {
  margin-bottom: 24px;
}

.notes-shell {
  position: relative;
  padding: 1px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.18), transparent 35%),
    radial-gradient(circle at top right, rgba(13, 148, 136, 0.22), transparent 38%),
    linear-gradient(135deg, rgba(37, 99, 235, 0.16), rgba(13, 148, 136, 0.14));
}

.notes-shell::before {
  content: '';
  position: absolute;
  inset: 14px;
  border-radius: 22px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.78), rgba(255, 255, 255, 0.52)),
    radial-gradient(circle at top, rgba(255, 255, 255, 0.6), transparent 50%);
  pointer-events: none;
}

.notes-hero,
.notes-card {
  position: relative;
  z-index: 1;
}

.notes-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 28px 16px;
}

.notes-kicker {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #0f766e;
}

.notes-copy h3 {
  margin: 0;
  font-size: 28px;
  line-height: 1.15;
  color: #0f172a;
}

.notes-desc {
  margin: 12px 0 0;
  max-width: 720px;
  color: #475569;
  line-height: 1.75;
}

.notes-summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-pill {
  min-width: 126px;
  padding: 14px 16px;
  border-radius: 18px;
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.75);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.summary-pill-available {
  background: linear-gradient(135deg, rgba(220, 252, 231, 0.96), rgba(187, 247, 208, 0.88));
}

.summary-pill-failed {
  background: linear-gradient(135deg, rgba(255, 237, 213, 0.96), rgba(254, 215, 170, 0.88));
}

.summary-pill-label {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.summary-pill-value {
  display: block;
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}

.notes-card {
  margin: 0 18px 18px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.88);
  background: rgba(255, 255, 255, 0.74);
  box-shadow: 0 20px 40px rgba(15, 23, 42, 0.08);
}

.notes-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.notes-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.notes-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: #64748b;
}

.notes-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.notes-account-select {
  width: 280px;
}

.notes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.note-card {
  position: relative;
  overflow: hidden;
  min-height: 244px;
  padding: 20px;
  border-radius: 22px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(248, 250, 252, 0.92));
}

.note-card::after {
  content: '';
  position: absolute;
  inset: auto -30px -60px auto;
  width: 170px;
  height: 170px;
  border-radius: 999px;
  opacity: 0.2;
  pointer-events: none;
}

.note-card-genshin::after {
  background: radial-gradient(circle, #34d399 0%, transparent 70%);
}

.note-card-starrail::after {
  background: radial-gradient(circle, #60a5fa 0%, transparent 70%);
}

.note-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.note-game-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.note-game-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 28px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.note-role-name {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.note-role-meta {
  margin-top: 6px;
  font-size: 12px;
  color: #64748b;
}

.note-updated {
  text-align: right;
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.note-error {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(248, 113, 113, 0.08);
  color: #b91c1c;
  line-height: 1.6;
}

.note-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.note-metric {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  background: rgba(255, 255, 255, 0.78);
}

.note-metric-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.note-metric-value {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.15;
}

.note-metric-detail {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
  line-height: 1.5;
}

.tone-warning {
  background: linear-gradient(180deg, rgba(255, 251, 235, 0.96), rgba(255, 247, 237, 0.96));
  border-color: rgba(251, 191, 36, 0.32);
}

.tone-warning .note-metric-value {
  color: #b45309;
}

.tone-success {
  background: linear-gradient(180deg, rgba(240, 253, 244, 0.96), rgba(236, 253, 245, 0.96));
  border-color: rgba(34, 197, 94, 0.28);
}

.tone-success .note-metric-value {
  color: #15803d;
}

.tone-info {
  background: linear-gradient(180deg, rgba(239, 246, 255, 0.96), rgba(240, 249, 255, 0.96));
  border-color: rgba(59, 130, 246, 0.26);
}

.tone-info .note-metric-value {
  color: #1d4ed8;
}

.result-card,
.calendar-card {
  margin-bottom: 24px;
  border-radius: 16px;
  border: 1px solid var(--border-color);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
}

.result-item:last-child {
  border-bottom: none;
}

.result-message {
  flex: 1;
  color: var(--text-primary);
}

.sign-days {
  font-size: 13px;
  color: var(--text-secondary);
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}

.calendar-day {
  text-align: center;
  padding: 12px 8px;
  border-radius: 12px;
  background: var(--bg-color);
  transition: background 0.2s;
}

.day-date {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.day-status {
  font-size: 20px;
  margin: 4px 0;
}

.day-success { color: #10b981; }
.day-success .day-status { color: #10b981; }
.day-partial { color: #f59e0b; }
.day-partial .day-status { color: #f59e0b; }
.day-failed { color: #ef4444; }
.day-failed .day-status { color: #ef4444; }
.day-empty { opacity: 0.5; }

.day-dash {
  font-size: 16px;
  color: var(--text-secondary);
}

.day-count {
  font-size: 11px;
  color: var(--text-secondary);
}

@media (max-width: 900px) {
  .notes-hero {
    padding: 22px 20px 12px;
  }

  .notes-card {
    margin: 0 12px 12px;
  }

  .note-card-head {
    flex-direction: column;
  }

  .note-updated {
    text-align: left;
  }
}

@media (max-width: 768px) {
  .stat-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .action-bar,
  .notes-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .notes-account-select {
    width: 100%;
  }

  .note-metrics {
    grid-template-columns: 1fr;
  }

  .calendar-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 560px) {
  .stat-cards,
  .notes-grid,
  .calendar-grid {
    grid-template-columns: 1fr;
  }

  .notes-copy h3 {
    font-size: 24px;
  }
}
</style>
