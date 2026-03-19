<template>
  <div class="app-root">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useUserStore } from './stores/user'

const userStore = useUserStore()
const isDark = computed(() => userStore.darkMode)

watchEffect(() => {
  // 主题开关需要始终落在 html 根节点上，Element Plus 暗色变量和各页面的 :global(html.dark)
  // 都依赖这个约定。如果只在局部容器挂 class，会造成“局部看起来切了，组件变量却没同步”的半暗色状态。
  document.documentElement.classList.toggle('dark', isDark.value)
})
</script>
