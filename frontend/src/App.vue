<template>
  <div :class="{ dark: isDark }">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useUserStore } from './stores/user'

const userStore = useUserStore()
const isDark = computed(() => userStore.darkMode)
</script>

<style>
/* 全局基础样式 */
:root {
  --primary-color: #6366f1;
  --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  --bg-color: #f5f7fa;
  --card-bg: #ffffff;
  --text-primary: #1f2937;
  --text-secondary: #6b7280;
  --border-color: #e5e7eb;
  --success-color: #10b981;
  --danger-color: #ef4444;
  --warning-color: #f59e0b;
  --info-color: #6b7280;
}

html.dark {
  --bg-color: #0f172a;
  --card-bg: #1e293b;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --border-color: #334155;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background-color: var(--bg-color);
  color: var(--text-primary);
  transition: background-color 0.3s, color 0.3s;
}

#app {
  min-height: 100vh;
}
</style>
