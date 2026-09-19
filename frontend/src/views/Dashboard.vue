<template>
  <div class="app-page dashboard">
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
          <div class="stat-label">今日已签角色</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #dc2626">
        <div class="stat-icon">
          <el-icon :size="24"><CircleClose /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.failed_today || 0 }}</div>
          <div class="stat-label">今日失败角色</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #d97706">
        <div class="stat-icon">
          <el-icon :size="24"><Warning /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.risk_today || 0 }}</div>
          <div class="stat-label">今日风控角色</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #64748b">
        <div class="stat-icon">
          <el-icon :size="24"><Clock /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.pending || 0 }}</div>
          <div class="stat-label">待签角色</div>
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

    <el-card v-if="checkinResults.length" class="result-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>签到结果</span>
          <el-tag :type="summaryType" size="small">
            成功 {{ summary.success }} / 失败 {{ summary.failed }}
            <template v-if="summary.risk"> / 风控 {{ summary.risk }}</template>
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
          <span v-if="formatReward(result.reward_name, result.reward_cnt)" class="sign-days">
            {{ formatReward(result.reward_name, result.reward_cnt) }}
          </span>
          <span v-if="result.total_sign_days" class="sign-days">
            累计 {{ result.total_sign_days }} 天
          </span>
        </div>
      </div>
    </el-card>

    <el-card class="calendar-card" shadow="never">
      <template #header>
        <span>最近 7 天签到记录（成功次数/总次数）</span>
      </template>
      <div class="calendar-grid">
        <div
          v-for="day in calendar"
          :key="day.date"
          class="calendar-day"
          :class="calendarDayClass(day)"
        >
          <div class="day-date">{{ formatDate(day.date) }}</div>
          <div class="day-status">
            <template v-if="day.total > 0">
              <el-icon v-if="day.failed === 0 && !(day.risk > 0)"><CircleCheck /></el-icon>
              <el-icon v-else><Warning /></el-icon>
            </template>
            <span v-else class="day-dash">-</span>
          </div>
          <div v-if="day.total > 0" class="day-count">
            {{ day.success }}/{{ day.total }}
          </div>
        </div>
      </div>
    </el-card>

    <el-card class="calendar-card reward-card" shadow="never">
      <template #header>
        <div class="card-header reward-card-header">
          <div class="reward-header-copy">
            <span>本月奖励</span>
            <span v-if="todayRewardText" class="reward-today-text">{{ todayRewardText }}</span>
          </div>
          <div class="reward-filters">
            <el-select
              v-if="rewardGameOptions.length > 1"
              v-model="rewardGame"
              placeholder="游戏"
              style="width: 160px"
              @change="onRewardGameChange"
            >
              <el-option
                v-for="option in rewardGameOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-select
              v-if="rewardRoles.length > 1"
              v-model="rewardRoleId"
              placeholder="角色"
              style="width: 180px"
              @change="loadRewardCalendar"
            >
              <el-option
                v-for="role in rewardRoles"
                :key="role.game_role_id"
                :label="roleLabel(role)"
                :value="role.game_role_id"
              />
            </el-select>
          </div>
        </div>
      </template>

      <el-empty
        v-if="!rewardCalendar.catalog_available"
        :description="rewardEmptyDescription"
      />

      <div v-else class="reward-month">
        <div class="reward-month-grid">
          <div v-for="label in WEEKDAYS" :key="label" class="reward-weekday">{{ label }}</div>
          <div
            v-for="(cell, idx) in rewardMonthCells"
            :key="idx"
            class="calendar-day reward-day"
            :class="rewardDayClass(cell)"
          >
            <template v-if="cell">
              <div class="day-date">{{ cell.day }}</div>
              <img
                v-if="cell.icon"
                class="reward-icon"
                :src="cell.icon"
                alt=""
                referrerpolicy="no-referrer"
                @error="hideBrokenIcon"
              >
              <div class="day-count reward-name" :title="formatReward(cell.name, cell.cnt)">
                {{ cell.name || '—' }}
              </div>
              <div v-if="cell.cnt" class="day-count">×{{ cell.cnt }}</div>
            </template>
          </div>
        </div>
        <div class="reward-note">物品按官方当月排期展示；已领 / 漏签按本平台东八区记录标记。</div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  User, CircleCheck, CircleClose, Warning, Refresh, Clock,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { logApi, taskApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import { CHECKIN_GAME_FILTER_LABELS, getGameFamily } from '../constants/game'
import { formatMonthDay } from '../utils/datetime'
import { formatReward } from '../utils/reward'

type RewardItem = {
  day: number
  name?: string
  cnt?: number
  icon?: string | null
  status: string
}

type RewardRole = {
  game_role_id: number
  account_nickname?: string | null
  game_nickname?: string | null
}

type RewardGameOption = {
  game: string
  catalog_available?: boolean
  role_count?: number
}

type RewardCalendar = {
  month?: string
  today?: string
  game?: string | null
  game_role_id?: number | null
  catalog_available?: boolean
  today_claimed?: boolean
  today_reward?: RewardItem | null
  awards?: RewardItem[]
  first_weekday?: number
  roles?: RewardRole[]
  games?: RewardGameOption[]
  empty_reason?: string | null
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const status = ref<any>({})
const calendar = ref<any[]>([])
const checkinResults = ref<any[]>([])
const summary = ref({ success: 0, failed: 0, already_signed: 0, risk: 0, total: 0 })
const executing = ref(false)
const rewardCalendar = ref<RewardCalendar>({})
const rewardGame = ref('')
const rewardRoleId = ref<number | null>(null)

const rewardRoles = computed(() => rewardCalendar.value.roles || [])

const rewardGameOptions = computed(() =>
  (rewardCalendar.value.games || []).map((item) => {
    const name = CHECKIN_GAME_FILTER_LABELS[item.game] || item.game
    return {
      value: item.game,
      label: item.catalog_available ? name : `${name}（未签到）`,
    }
  }),
)

const rewardEmptyDescription = computed(() => {
  const reason = rewardCalendar.value.empty_reason
  if (reason === 'no_account' || reason === 'no_games') {
    return '绑定账号并完成一次签到后即可看到本月奖励'
  }
  if (reason === 'no_role') {
    return '当前账号没有这款游戏的签到角色'
  }
  return '完成一次该游戏签到后即可看到本月奖励'
})

const todayRewardText = computed(() => {
  const reward = rewardCalendar.value.today_reward
  const label = formatReward(reward?.name, reward?.cnt)
  if (!label) return ''
  return rewardCalendar.value.today_claimed ? `今日已领取：${label}` : `今日待领取：${label}`
})

const rewardMonthCells = computed<(RewardItem | null)[]>(() => {
  const blanks = Array.from({ length: rewardCalendar.value.first_weekday || 0 }, () => null)
  return [...blanks, ...(rewardCalendar.value.awards || [])]
})

const summaryType = computed(() => {
  if (summary.value.failed > 0) return 'danger'
  if (summary.value.risk > 0) return 'warning'
  return 'success'
})

function formatDate(dateStr: string) {
  return formatMonthDay(dateStr)
}

function calendarDayClass(day: { success: number; failed: number; risk?: number; total: number }) {
  const risk = day.risk || 0
  if (day.total === 0) return 'day-empty'
  if (day.success > 0 && day.failed === 0 && risk === 0) return 'day-success'
  if (day.success > 0 && (day.failed > 0 || risk > 0)) return 'day-partial'
  if (day.failed > 0) return 'day-failed'
  if (risk > 0) return 'day-risk'
  return 'day-failed'
}

function roleLabel(role: RewardRole) {
  const nickname = role.game_nickname || `角色#${role.game_role_id}`
  return role.account_nickname ? `${nickname} · ${role.account_nickname}` : nickname
}

function hideBrokenIcon(event: Event) {
  const image = event.target as HTMLImageElement
  image.style.display = 'none'
}

function rewardDayClass(cell: RewardItem | null) {
  if (!cell) return 'day-empty'
  if (cell.status === 'claimed') return 'day-success'
  if (cell.status === 'missed') return 'day-failed'
  if (cell.status === 'today') {
    return rewardCalendar.value.today_claimed ? 'day-success day-today' : 'day-today'
  }
  return 'day-empty'
}

function buildCheckinToast(data: { success: number; failed: number; risk?: number }) {
  const parts = [`成功 ${data.success}`, `失败 ${data.failed}`]
  if (data.risk) {
    parts.push(`风控 ${data.risk}`)
  }
  return `签到完成：${parts.join('，')}`
}

async function loadRewardCalendar() {
  try {
    const params: { game?: string; game_role_id?: number } = {}
    if (rewardGame.value) params.game = rewardGame.value
    if (rewardRoleId.value) params.game_role_id = rewardRoleId.value
    const { data } = await logApi.getRewards(params)
    rewardCalendar.value = data || {}
    if (data?.game) rewardGame.value = data.game
    if (data?.game_role_id) rewardRoleId.value = data.game_role_id
  } catch (e) {
    void e
  }
}

function onRewardGameChange() {
  rewardRoleId.value = null
  loadRewardCalendar()
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
    // 错误已在拦截器中统一处理，这里只负责保持仪表盘状态稳定。
  }
  await loadRewardCalendar()
}

async function loadData() {
  await loadDashboardSummary()
}

async function handleExecute() {
  executing.value = true
  try {
    const { data } = await taskApi.execute()
    summary.value = data
    checkinResults.value = data.results || []
    ElMessage.success(buildCheckinToast(data))
    await loadData()
    if (!rewardCalendar.value.catalog_available) {
      const hit = (checkinResults.value || []).find(
        (item: { reward_name?: string; game_biz?: string; game_role_id?: number }) =>
          item.reward_name && getGameFamily(item.game_biz),
      )
      const family = hit ? getGameFamily(hit.game_biz) : ''
      if (hit && family && family !== rewardGame.value) {
        rewardGame.value = family
        rewardRoleId.value = hit.game_role_id || null
        await loadRewardCalendar()
      }
    }
  } catch (e) {
    // 错误已在拦截器中统一处理。
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
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-4);
}

.stat-card {
  background: var(--bg-elevated);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  box-shadow: var(--shadow-soft);
  border: 1px solid var(--border-soft);
  transition: all var(--transition-medium);
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-medium);
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}

.stat-value {
  font-size: 26px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
  margin-top: 2px;
}

.action-bar {
  display: flex;
  gap: var(--space-3);
  margin: var(--space-2) 0;
}

.result-card,
.calendar-card {
  border-radius: var(--radius-lg);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.result-list {
  display: flex;
  flex-direction: column;
}

.result-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border-soft);
}

.result-item:last-child {
  border-bottom: none;
}

.result-message {
  flex: 1;
  font-size: 14px;
  color: var(--text-primary);
}

.sign-days {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: var(--space-3);
}

.calendar-day {
  text-align: center;
  padding: var(--space-3) var(--space-2);
  border-radius: var(--radius-md);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  transition: all var(--transition-fast);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.reward-card-header {
  gap: var(--space-3);
  flex-wrap: wrap;
}

.reward-header-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.reward-today-text {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.reward-filters {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.reward-month-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: var(--space-2);
}

.reward-weekday {
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-tertiary);
  padding-bottom: 4px;
}

.reward-day {
  min-height: 84px;
  padding: var(--space-2) 4px;
}

.reward-day.day-today {
  border-color: var(--brand-primary);
}

.reward-icon {
  width: 20px;
  height: 20px;
  object-fit: contain;
  margin-bottom: 4px;
}

.reward-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reward-note {
  margin-top: var(--space-3);
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.day-date {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-tertiary);
  margin-bottom: 6px;
}

.day-status {
  font-size: 18px;
  margin-bottom: 6px;
}

.day-success {
  color: var(--text-success);
  background: var(--bg-success-soft);
  border-color: var(--border-success-soft);
}

.day-partial {
  color: var(--text-warning);
  background: var(--bg-warning-soft);
  border-color: var(--border-warning-soft);
}

.day-failed {
  color: var(--text-danger);
  background: var(--bg-danger-soft);
  border-color: var(--border-danger-soft);
}

.day-risk {
  color: var(--text-warning);
  background: var(--bg-warning-soft);
  border-color: var(--border-warning-soft);
}

.day-empty {
  opacity: 0.6;
}

.day-dash {
  font-size: 14px;
  color: var(--text-tertiary);
}

.day-count {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-tertiary);
}

@media (max-width: 1024px) {
  .calendar-grid {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: var(--space-2);
    scroll-snap-type: x mandatory;
    gap: var(--space-3);
  }
  
  .calendar-grid .calendar-day {
    flex: 0 0 calc(25% - var(--space-3) * 3 / 4);
    scroll-snap-align: start;
  }
}

@media (max-width: 640px) {
  .reward-day .reward-icon {
    display: none;
  }

  .reward-day {
    min-height: 64px;
    padding: var(--space-1) 2px;
  }

  .reward-name {
    display: none;
  }

  .stat-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3);
  }

  .stat-card {
    padding: var(--space-3);
    gap: var(--space-2);
    align-items: center;
  }

  .stat-icon {
    width: 32px;
    height: 32px;
    flex-shrink: 0;
  }

  .stat-value {
    font-size: 18px;
  }

  .stat-label {
    font-size: 12px;
  }

  .action-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .action-bar .el-button {
    width: 100%;
    margin-left: 0 !important;
  }

  .calendar-grid .calendar-day {
    flex: 0 0 calc(33.333% - var(--space-3) * 2 / 3);
  }

  .reward-card-header {
    flex-direction: column;
    align-items: stretch;
  }

  .reward-filters .el-select {
    width: 100% !important;
  }
}

@media (max-width: 480px) {
  .calendar-grid .calendar-day {
    flex: 0 0 calc(50% - var(--space-3) / 2);
  }
}
</style>

