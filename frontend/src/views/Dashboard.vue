<template>
  <div class="app-page dashboard">
    <section class="page-toolbar">
      <div class="page-title-group">
        <div class="page-kicker">Operational Surface</div>
        <h2 class="page-title">仪表盘</h2>
        <p class="page-desc">快速查看今日签到状态，并按账号查看实时便笺信息。</p>
      </div>
    </section>

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

    <section v-if="hasNotesAccess" class="notes-panel">
      <div class="notes-shell">
        <div class="notes-hero">
          <div class="notes-copy">
            <p class="notes-kicker">Realtime Notes</p>
            <h3>实时便笺面板</h3>
            <p class="notes-desc">
              在首页直接查看体力、委托和资源恢复情况，方便你在签到之外顺手确认角色状态。
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
                description="还没有可查看便笺的账号，先导入一个账号"
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

                  <div
                    v-if="card.status !== 'available'"
                    class="note-notice"
                    :class="`note-notice-${getNoteNoticeTone(card.status)}`"
                  >
                    <el-icon><Warning /></el-icon>
                    <span>{{ card.message || '暂时无法获取便笺信息' }}</span>
                  </div>

                  <div v-else class="note-content">
                    <div v-if="card.detail_kind === 'genshin'" class="note-detail-stack">
                      <div
                        v-for="item in getGenshinDetailItems(card)"
                        :key="item.label"
                        class="note-detail-item"
                      >
                        <div class="note-detail-label">{{ item.label }}</div>
                        <div class="note-detail-value">{{ item.value }}</div>
                        <div class="note-detail-meta">{{ item.detail }}</div>
                      </div>
                    </div>
                    <div v-else-if="card.detail_kind === 'starrail'" class="note-detail-stack">
                      <div
                        v-for="item in getStarrailDetailItems(card)"
                        :key="item.label"
                        class="note-detail-item"
                      >
                        <div class="note-detail-label">{{ item.label }}</div>
                        <div class="note-detail-value">{{ item.value }}</div>
                        <div class="note-detail-meta">{{ item.detail }}</div>
                      </div>
                    </div>
                    <div v-else-if="card.detail_kind === 'zzz'" class="note-detail-stack">
                      <div
                        v-for="item in getZzzDetailItems(card)"
                        :key="item.label"
                        class="note-detail-item"
                      >
                        <div class="note-detail-label">{{ item.label }}</div>
                        <div class="note-detail-value">{{ item.value }}</div>
                        <div class="note-detail-meta">{{ item.detail }}</div>
                      </div>
                    </div>

                    <div class="note-metrics">
                      <div
                        v-for="metric in card.metrics"
                        :key="metric.key"
                        class="note-metric"
                        :class="`tone-${metric.tone}`"
                      >
                        <div class="note-metric-label">{{ metric.label }}</div>
                        <div class="note-metric-value">{{ metric.value }}</div>
                        <div class="note-metric-detail">{{ metric.detail || '暂无额外说明' }}</div>
                      </div>
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
import { useRoute } from 'vue-router'
import {
  User, CircleCheck, CircleClose, Warning, Refresh,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { logApi, notesApi, taskApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import { useUserStore } from '../stores/user'
import type {
  GenshinNoteCard,
  NoteAccount,
  NoteCard,
  NoteSummaryResponse,
  StarrailNoteCard,
  ZzzNoteCard,
} from '../types/notes'
import { resolveRouteAccountPrefill } from '../utils/accountRoutePrefill'
import { hasMenuAccess } from '../utils/menuVisibility'
import {
  getNoteNoticeTone,
  getNoteStatusText,
  getNoteStatusType,
} from '../utils/noteStatus'

type NoteDetailItem = {
  label: string
  value: string
  detail: string
}

const status = ref<any>({})
const calendar = ref<any[]>([])
const checkinResults = ref<any[]>([])
const summary = ref({ success: 0, failed: 0, already_signed: 0, risk: 0, total: 0 })
const executing = ref(false)
const route = useRoute()
const userStore = useUserStore()

const noteAccounts = ref<NoteAccount[]>([])
const selectedNoteAccountId = ref<number | null>(null)
const notesLoading = ref(false)
const routeAccountPrefillConsumed = ref(false)
const noteSummary = ref<NoteSummaryResponse>({
  schema_version: 2,
  provider: 'genshin.py',
  account_id: 0,
  account_name: '',
  total_cards: 0,
  available_cards: 0,
  failed_cards: 0,
  cards: [] as NoteCard[],
})

const noteCards = computed(() => noteSummary.value.cards || [])
const hasNotesAccess = computed(() => hasMenuAccess('notes', userStore.visibleMenuKeys))

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

function resetNoteSummary() {
  noteSummary.value = {
    schema_version: 2,
    provider: 'genshin.py',
    account_id: 0,
    account_name: '',
    total_cards: 0,
    available_cards: 0,
    failed_cards: 0,
    cards: [],
  }
}

  function formatSecondsText(seconds: number) {
    if (!seconds) return '已完成'
    const totalMinutes = Math.max(0, Math.floor(seconds / 60))
    const hours = Math.floor(totalMinutes / 60)
    const minutes = totalMinutes % 60
    if (hours > 0) return `${hours}小时${minutes}分钟`
    return `${minutes}分钟`
  }

  function formatRecoveryDetail(seconds: number, suffix: string, fallback: string) {
    if (!seconds) {
      // 0 秒表示目标已经达成，不能继续把“状态”词当时长与“约 … 后”拼接，否则会出现不自然文案
      return fallback
    }
    return `约 ${formatSecondsText(seconds)} ${suffix}`
  }

function isGenshinCard(card: NoteCard): card is GenshinNoteCard {
  const detail = card.detail as GenshinNoteCard['detail'] | undefined
  return card.detail_kind === 'genshin' && typeof detail?.current_resin === 'number'
}

function isStarrailCard(card: NoteCard): card is StarrailNoteCard {
  const detail = card.detail as StarrailNoteCard['detail'] | undefined
  return card.detail_kind === 'starrail' && typeof detail?.current_stamina === 'number'
}

function isZzzCard(card: NoteCard): card is ZzzNoteCard {
  const detail = card.detail as ZzzNoteCard['detail'] | undefined
  return card.detail_kind === 'zzz' && typeof detail?.battery_charge?.current === 'number'
}

function getGenshinDetailItems(card: NoteCard): NoteDetailItem[] {
  if (!isGenshinCard(card)) return []
  return [
      {
        label: '树脂恢复',
        value: `${card.detail.current_resin}/${card.detail.max_resin}`,
        detail: formatRecoveryDetail(
          card.detail.remaining_resin_recovery_seconds,
          '后回满',
          '已回满',
        ),
      },
      {
        label: '洞天宝钱',
        value: `${card.detail.current_realm_currency}/${card.detail.max_realm_currency}`,
        detail: formatRecoveryDetail(
          card.detail.remaining_realm_currency_recovery_seconds,
          '后接近上限',
          '已接近上限',
        ),
      },
    {
      label: '委托与周本',
      value: `${card.detail.completed_commissions}/${card.detail.max_commissions}`,
      detail: `周本减半 ${card.detail.remaining_weekly_discounts}/${card.detail.max_weekly_discounts}`,
    },
  ]
}

function getStarrailDetailItems(card: NoteCard): NoteDetailItem[] {
  if (!isStarrailCard(card)) return []
  const weeklyPoints = card.detail.have_bonus_synchronicity_points
    ? `${card.detail.current_bonus_synchronicity_points}/${card.detail.max_bonus_synchronicity_points}`
    : `${card.detail.current_rogue_score}/${card.detail.max_rogue_score}`
  return [
      {
        label: '开拓力恢复',
        value: `${card.detail.current_stamina}/${card.detail.max_stamina}`,
        detail: formatRecoveryDetail(
          card.detail.remaining_stamina_recovery_seconds,
          '后回满',
          '已回满',
        ),
      },
    {
      label: '后备开拓力',
      value: String(card.detail.current_reserve_stamina),
      detail: card.detail.is_reserve_stamina_full ? '当前已满' : '仍可继续累积',
    },
    {
      label: '周常进度',
      value: weeklyPoints,
      detail: `派遣完成 ${card.detail.finished_expeditions}/${card.detail.total_expedition_num}`,
    },
  ]
}

function getZzzDetailItems(card: NoteCard): NoteDetailItem[] {
  if (!isZzzCard(card)) return []
  return [
      {
        label: '电量恢复',
        value: `${card.detail.battery_charge.current}/${card.detail.battery_charge.max}`,
        detail: formatRecoveryDetail(
          card.detail.battery_charge.seconds_till_full,
          '后回满',
          '已回满',
        ),
      },
    {
      label: '活跃度',
      value: `${card.detail.engagement.current}/${card.detail.engagement.max}`,
      detail: card.detail.scratch_card_completed ? '今日刮刮卡已完成' : '今日刮刮卡未完成',
    },
    {
      label: '店铺与周常',
      value: card.detail.video_store_state || '未知状态',
      detail: card.detail.weekly_task
        ? `周常 ${card.detail.weekly_task.cur_point}/${card.detail.weekly_task.max_point}`
        : '暂无周常进度',
    },
  ]
}

function resetNotesPanelState() {
  // 功能开关关闭时必须主动清空前端便笺状态，而不能只依赖 v-if 隐藏视图；
  // 否则上一次已加载的账号、卡片和汇总数据会残留在内存里，后续排查“明明关闭了 why 还有旧便笺数据”时会产生误导。
  noteAccounts.value = []
  selectedNoteAccountId.value = null
  routeAccountPrefillConsumed.value = false
  notesLoading.value = false
  resetNoteSummary()
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

    const prefillResult = resolveRouteAccountPrefill(route.query.account_id, {
      consumed: routeAccountPrefillConsumed.value,
      availableAccountIds: noteAccounts.value.map((account) => account.id),
    })
    routeAccountPrefillConsumed.value = prefillResult.consumed

    if (!noteAccounts.value.length) {
      // 即使当前还没有可用账号，也必须在首次落地时消费掉 query 上下文，
      // 否则用户稍后导入账号或刷新页面时，旧 account_id 会再次覆盖页面内手动选择。
      selectedNoteAccountId.value = null
      resetNoteSummary()
      return
    }

    if (prefillResult.preferredAccountId !== null) {
      // 允许健康中心等聚合页把账号上下文直接带入首页便笺面板，避免跨页后二次选择。
      selectedNoteAccountId.value = prefillResult.preferredAccountId
    } else if (!noteAccounts.value.some((account) => account.id === selectedNoteAccountId.value)) {
      selectedNoteAccountId.value = noteAccounts.value[0].id
    }

    await loadNotesSummary()
  } catch (e) {
    resetNotesPanelState()
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
  await loadDashboardSummary()

  if (hasNotesAccess.value) {
    await loadNotesPanel()
  } else {
    resetNotesPanelState()
  }
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
  width: 100%;
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

.note-notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  border-radius: 16px;
  line-height: 1.6;
}

.note-notice-error {
  background: rgba(248, 113, 113, 0.08);
  color: #b91c1c;
}

.note-notice-warning {
  background: rgba(251, 191, 36, 0.12);
  color: #b45309;
}

.note-content {
  display: grid;
  gap: 14px;
}

.note-detail-stack {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.note-detail-item {
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(203, 213, 225, 0.78);
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(241, 245, 249, 0.96));
}

.note-detail-label {
  font-size: 12px;
  color: #64748b;
}

.note-detail-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.note-detail-meta {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
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

  .note-detail-stack,
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
