<template>
  <div class="logs-page">
    <!-- 筛选栏 -->
    <el-card class="filter-card" shadow="never">
      <el-form inline>
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
            style="width: 280px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="loadLogs">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 日志表格 -->
    <el-card class="table-card" shadow="never">
      <el-table :data="logs" v-loading="loading" stripe style="width: 100%" table-layout="auto">
        <el-table-column label="时间" prop="executed_at" :min-width="compactMode ? 150 : 180">
          <template #default="{ row }">
            {{ formatTime(row.executed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="账号" prop="account_nickname" :min-width="compactMode ? 110 : 140" show-overflow-tooltip />
        <el-table-column label="游戏" :min-width="compactMode ? 100 : 120">
          <template #default="{ row }">
            {{ gameNames[row.game_biz] || row.game_biz || '-' }}
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
import { Search } from '@element-plus/icons-vue'
import { logApi } from '../api'
import StatusBadge from '../components/StatusBadge.vue'

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

const gameNames: Record<string, string> = {
  hk4e_cn: '原神',
  hk4e_bilibili: '原神(B服)',
  hkrpg_cn: '星穹铁道',
  hkrpg_bilibili: '星铁(B服)',
  nap_cn: '绝区零',
  bh3_cn: '崩坏3',
}

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
  max-width: 1200px;
  margin: 0 auto;
}

.filter-card {
  margin-bottom: 16px;
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.filter-card :deep(.el-card__body) {
  padding: 16px 20px 0;
}

.table-card {
  border-radius: 12px;
  border: 1px solid var(--border-color);
}

.pagination {
  margin-top: 16px;
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
    max-width: none;
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
