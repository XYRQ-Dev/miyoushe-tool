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
          <div v-if="day.total > 0" class="day-count">
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
import { logApi, taskApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

const status = ref<any>({})
const calendar = ref<any[]>([])
const checkinResults = ref<any[]>([])
const summary = ref({ success: 0, failed: 0, already_signed: 0, risk: 0, total: 0 })
const executing = ref(false)

const summaryType = computed(() => {
  if (summary.value.failed > 0) return 'danger'
  if (summary.value.risk > 0) return 'warning'
  return 'success'
})

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
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
    ElMessage.success(`签到完成：成功 ${data.success}，失败 ${data.failed}`)
    await loadData()
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
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
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
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 640px) {
  .stat-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .action-bar {
    flex-direction: column;
  }

  .calendar-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .stat-cards {
    grid-template-columns: 1fr;
  }
}
</style>

