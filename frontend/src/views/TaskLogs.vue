<template>
  <div class="app-page logs-page">
    <el-card class="filter-card filter-panel" shadow="never">
      <el-form inline size="small">
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 140px">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="已签到" value="already_signed" />
            <el-option label="风控" value="risk" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            style="width: 250px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" round @click="loadLogs">查询</el-button>
          <el-button :icon="RefreshLeft" round @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="table-card data-table-card" shadow="never">
      <template #header>
        <div class="section-head">
          <div>
            <div class="section-title">执行记录</div>
            <div class="section-desc">按时间、账号、游戏和执行结果查看最近的签到落库情况。</div>
          </div>
          <div class="soft-chip">共 {{ pagination.total }} 条</div>
        </div>
      </template>

      <el-table :data="logs" v-loading="loading" stripe style="width: 100%" table-layout="auto">
        <el-table-column label="时间" prop="executed_at" :min-width="compactMode ? 150 : 180">
          <template #default="{ row }">
            {{ formatTime(row.executed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="账号" prop="account_nickname" :min-width="compactMode ? 110 : 140" show-overflow-tooltip />
        <el-table-column label="游戏" :min-width="compactMode ? 100 : 120">
          <template #default="{ row }">
            {{ getGameName(row.game_biz) }}
          </template>
        </el-table-column>
        <el-table-column v-if="!compactMode" label="角色" prop="game_nickname" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" :width="compactMode ? 92 : 108" align="center">
          <template #default="{ row }">
            <StatusBadge :status="row.status" :compact="compactMode" />
          </template>
        </el-table-column>
        <el-table-column label="详情" :min-width="compactMode ? 240 : 320">
          <template #default="{ row }">
            <div class="log-message">
              <div v-if="compactMode && row.game_nickname" class="message-meta">
                角色：{{ row.game_nickname }}
              </div>
              <div class="message-text">{{ row.message || '-' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="!compactMode" label="签到天数" prop="total_sign_days" width="100">
          <template #default="{ row }">
            {{ row.total_sign_days || '-' }}
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :total="pagination.total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @size-change="loadLogs"
          @current-change="loadLogs"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { Search, RefreshLeft } from '@element-plus/icons-vue'
import { logApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'
import { getGameName } from '../constants/game'

const logs = ref<any[]>([])
const loading = ref(false)
const dateRange = ref<string[]>([])

const filters = reactive({
  status: '',
})

const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0,
})

const compactMode = ref(false)

function formatTime(dt: string) {
  return new Date(dt).toLocaleString('zh-CN')
}

function updateLayoutMode() {
  compactMode.value = window.innerWidth < 1100
}

async function loadLogs() {
  loading.value = true
  try {
    const params: any = {
      page: pagination.page,
      page_size: pagination.pageSize,
    }
    if (filters.status) params.status = filters.status
    if (dateRange.value?.length === 2) {
      params.date_start = dateRange.value[0]
      params.date_end = dateRange.value[1]
    }

    const { data } = await logApi.list(params)
    logs.value = data.logs
    pagination.total = data.total
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.status = ''
  dateRange.value = []
  pagination.page = 1
  loadLogs()
}

onMounted(loadLogs)
onMounted(() => {
  updateLayoutMode()
  window.addEventListener('resize', updateLayoutMode)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateLayoutMode)
})
</script>

<style scoped>
.logs-page {
  width: 100%;
  gap: 12px !important; /* Increased from 4px to 12px for better breathing room */
}

.logs-page :deep(.filter-card.filter-panel) {
  margin-bottom: 0;
  border-radius: 16px;
  padding: 0 !important; /* Force remove the 20px padding from app-theme.css */
}

.logs-page :deep(.filter-card.filter-panel .el-card__body) {
  padding: 12px 24px !important;
  width: 100%;
  display: flex;
  align-items: center;
}

.filter-card :deep(.el-form) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.filter-card :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 0;
  display: flex;
  align-items: center;
}

.filter-card :deep(.el-form-item__label) {
  padding-right: 8px;
  line-height: normal;
  display: flex;
  align-items: center;
  margin-bottom: 0;
}

.filter-card :deep(.el-form-item__content) {
  line-height: normal;
  display: flex;
  align-items: center;
}

.table-card {
  overflow: hidden;
  border-radius: 20px;
}

.pagination {
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
}

.log-message {
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.5;
}

.message-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.message-text {
  white-space: normal;
  word-break: break-word;
}

@media (max-width: 768px) {
  .logs-page {
    width: 100%;
  }

  .filter-card :deep(.el-form) {
    display: flex;
    flex-wrap: wrap;
  }

  .filter-card :deep(.el-form-item) {
    margin-right: 12px;
    margin-bottom: 12px;
  }

  .pagination {
    justify-content: center;
  }
}
</style>
