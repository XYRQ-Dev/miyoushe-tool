<template>
  <div class="login-page">
    <div class="bg-decoration">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="grid-glow"></div>
    </div>

    <div class="login-shell">
      <section class="login-brand-panel">
        <h1>米游社自动签到助手</h1>
        <p class="brand-desc">一站式管理您的游戏账号、签到状态与抽卡记录。</p>
        <div class="brand-points">
          <div class="brand-point">
            <span class="point-dot"></span>
            <span>实时掌控账号状态，及时处理登录失效与异常。</span>
          </div>
          <div class="brand-point">
            <span class="point-dot"></span>
            <span>全自动执行每日签到，支持快捷兑换与抽卡分析。</span>
          </div>
          <div class="brand-point">
            <span class="point-dot"></span>
            <span>灵活的权限与通知配置，确保任务流转稳定可靠。</span>
          </div>
        </div>
      </section>

      <section class="login-card">
        <div class="logo-area">
          <div class="logo-icon">
            <el-icon :size="30"><Star /></el-icon>
          </div>
          <div>
            <h2>登录与注册</h2>
            <p>欢迎使用，请登录或注册您的账号。</p>
          </div>
        </div>

        <el-tabs v-model="activeTab" class="login-tabs">
          <el-tab-pane label="登录" name="login">
            <el-form
              ref="loginFormRef"
              :model="loginForm"
              :rules="loginRules"
              @submit.prevent="handleLogin"
            >
              <el-form-item prop="username">
                <el-input
                  v-model="loginForm.username"
                  placeholder="用户名"
                  :prefix-icon="User"
                  size="large"
                />
              </el-form-item>
              <el-form-item prop="password">
                <el-input
                  v-model="loginForm.password"
                  type="password"
                  placeholder="密码"
                  :prefix-icon="Lock"
                  size="large"
                  show-password
                  @keyup.enter="handleLogin"
                />
              </el-form-item>
              <el-button
                type="primary"
                size="large"
                class="submit-btn"
                :loading="loading"
                @click="handleLogin"
              >
                登录
              </el-button>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form
              ref="registerFormRef"
              :model="registerForm"
              :rules="registerRules"
              @submit.prevent="handleRegister"
            >
              <el-form-item prop="username">
                <el-input
                  v-model="registerForm.username"
                  placeholder="用户名（3-50 字符）"
                  :prefix-icon="User"
                  size="large"
                />
              </el-form-item>
              <el-form-item prop="password">
                <el-input
                  v-model="registerForm.password"
                  type="password"
                  placeholder="密码（至少 6 位）"
                  :prefix-icon="Lock"
                  size="large"
                  show-password
                />
              </el-form-item>
              <el-form-item prop="confirmPassword">
                <el-input
                  v-model="registerForm.confirmPassword"
                  type="password"
                  placeholder="确认密码"
                  :prefix-icon="Lock"
                  size="large"
                  show-password
                  @keyup.enter="handleRegister"
                />
              </el-form-item>
              <el-button
                type="primary"
                size="large"
                class="submit-btn"
                :loading="loading"
                @click="handleRegister"
              >
                注册
              </el-button>
            </el-form>
            <p class="hint-text">首个注册用户将自动成为管理员</p>
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, Star } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const activeTab = ref('login')

const loginFormRef = ref()
const registerFormRef = ref()

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', password: '', confirmPassword: '' })

const loginRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const validateConfirm = (rule: any, value: string, callback: any) => {
  if (value !== registerForm.password) {
    callback(new Error('两次密码不一致'))
  } else {
    callback()
  }
}

const registerRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 50, message: '用户名长度 3-50 字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' },
  ],
}

async function handleLogin() {
  await loginFormRef.value?.validate()
  loading.value = true
  try {
    await userStore.login(loginForm.username, loginForm.password)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e: any) {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  await registerFormRef.value?.validate()
  loading.value = true
  try {
    await userStore.register(registerForm.username, registerForm.password)
    ElMessage.success('注册成功，请登录')
    activeTab.value = 'login'
    loginForm.username = registerForm.username
    loginForm.password = ''
  } catch (e: any) {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-app-accent), var(--bg-app);
  position: relative;
  overflow: hidden;
  padding: 24px;
}

.bg-decoration {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(6px);
}

.orb-1 {
  width: 520px;
  height: 520px;
  background: radial-gradient(circle, rgba(56, 189, 248, 0.18), transparent 68%);
  top: -160px;
  right: -80px;
  animation: float 10s ease-in-out infinite;
}

.orb-2 {
  width: 440px;
  height: 440px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.16), transparent 70%);
  bottom: -140px;
  left: -120px;
  animation: float 12s ease-in-out infinite reverse;
}

.grid-glow {
  position: absolute;
  inset: 8% 12%;
  border-radius: 36px;
  border: 1px solid var(--border-soft);
  background:
    linear-gradient(var(--border-soft) 1px, transparent 1px),
    linear-gradient(90deg, var(--border-soft) 1px, transparent 1px);
  background-size: 34px 34px;
  mask-image: radial-gradient(circle at center, black 48%, transparent 82%);
}

@keyframes float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-22px) scale(1.04); }
}

.login-shell {
  position: relative;
  z-index: 1;
  width: min(1120px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1fr) 440px;
  gap: 22px;
  align-items: stretch;
}

.login-brand-panel,
.login-card {
  border-radius: 28px;
  border: 1px solid var(--border-soft);
  box-shadow: var(--shadow-sidebar);
  backdrop-filter: blur(20px);
}

.login-brand-panel {
  padding: 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background:
    radial-gradient(circle at top right, rgba(56, 189, 248, 0.2), transparent 34%),
    linear-gradient(180deg, rgba(11, 25, 48, 0.92), rgba(13, 31, 58, 0.84));
  color: #e7f0fb;
}

.login-brand-panel h1 {
  margin: 16px 0 0;
  font-size: 38px;
  line-height: 1.1;
  font-weight: 800;
}

.brand-desc {
  margin: 18px 0 0;
  max-width: 480px;
  line-height: 1.85;
  color: rgba(231, 240, 251, 0.82);
}

.brand-points {
  margin-top: 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.brand-point {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  line-height: 1.75;
  color: rgba(231, 240, 251, 0.88);
}

.point-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(135deg, #38bdf8 0%, #6366f1 100%);
  margin-top: 8px;
  flex: 0 0 auto;
}

.login-card {
  background: var(--bg-elevated);
  padding: 34px;
}

.logo-area {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 26px;
}

.logo-icon {
  width: 56px;
  height: 56px;
  background: var(--bg-primary);
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex: 0 0 auto;
  box-shadow: 0 16px 28px rgba(37, 99, 235, 0.22);
}

.logo-area h2 {
  margin: 10px 0 0;
  font-size: 24px;
  font-weight: 800;
  color: var(--text-primary);
}

.logo-area p {
  margin: 10px 0 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.login-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
  border-radius: 14px;
  height: 48px;
  font-size: 16px;
}

@media (max-width: 980px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-brand-panel {
    padding: 30px;
  }

  .login-brand-panel h1 {
    font-size: 30px;
  }
}

@media (max-width: 640px) {
  .login-page {
    padding: 14px;
  }

  .login-card,
  .login-brand-panel {
    padding: 24px;
  }

  .logo-area {
    flex-direction: column;
  }
}
</style>
