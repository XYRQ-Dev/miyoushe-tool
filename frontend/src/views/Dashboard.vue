<template>
  <div class="dashboard">
    <!-- 统计卡片 -->
    <div class="stat-cards">
      <div class="stat-card" style="--accent: #6366f1">
        <div class="stat-icon">
          <el-icon :size="24"><User /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.total_accounts || 0 }}</div>
          <div class="stat-label">绑定账号</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #10b981">
        <div class="stat-icon">
          <el-icon :size="24"><CircleCheck /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.signed_today || 0 }}</div>
          <div class="stat-label">今日已签</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #ef4444">
        <div class="stat-icon">
          <el-icon :size="24"><CircleClose /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.failed_today || 0 }}</div>
          <div class="stat-label">签到失败</div>
        </div>
      </div>

      <div class="stat-card" style="--accent: #f59e0b">
        <div class="stat-icon">
          <el-icon :size="24"><Warning /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ status.pending || 0 }}</div>
          <div class="stat-label">待签到</div>
        </div>
      </div>
    </div>

    <!-- 操作区域 -->
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

    <!-- 签到结果 -->
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

    <!-- 签到日历 -->
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
import { ref, computed, onMounted } from 'vue'
import {
  User, CircleCheck, CircleClose, Warning, Refresh,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { taskApi, logApi } from '../api'
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

async function loadData() {
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
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
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
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
}

.result-card, .calendar-card {
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
</style>
