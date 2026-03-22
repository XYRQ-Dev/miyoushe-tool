<template>
  <div class="login-page">
    <div class="bg-decoration">
      <div class="orb orb-1"></div>
      <div class="orb orb-2"></div>
      <div class="grid-glow"></div>
    </div>

    <div class="login-container">
      <!-- Left: Brand Section -->
      <section class="brand-section">
        <div class="brand-content">
          <div class="brand-header">
            <div class="brand-logo">
              <el-icon :size="32"><Star /></el-icon>
            </div>
            <h1>米游社自动签到助手</h1>
          </div>
          
          <p class="brand-tagline">一站式管理您的游戏账号、签到状态与抽卡记录。</p>
          
          <div class="brand-features">
            <div class="feature-item">
              <div class="feature-icon"><el-icon><Monitor /></el-icon></div>
              <div class="feature-text">
                <h3>时刻同步</h3>
                <p>实时掌控账号状态，及时处理登录失效与异常。</p>
              </div>
            </div>
            <div class="feature-item">
              <div class="feature-icon"><el-icon><Timer /></el-icon></div>
              <div class="feature-text">
                <h3>全自动执行</h3>
                <p>全自动执行每日签到，支持快捷兑换与抽卡分析。</p>
              </div>
            </div>
            <div class="feature-item">
              <div class="feature-icon"><el-icon><Lock /></el-icon></div>
              <div class="feature-text">
                <h3>安全稳定</h3>
                <p>加密存储 Cookie，确保您的账号安全万无一失。</p>
              </div>
            </div>
          </div>
        </div>
        
        <div class="brand-footer">
          <span>XYRQ-Dev Project</span>
          <span class="version">v2.0.0</span>
        </div>
      </section>

      <!-- Right: Form Section -->
      <section class="form-section">
        <div class="form-header">
          <h2>欢迎回来</h2>
          <p>请登录或注册您的管理账号</p>
        </div>

        <el-tabs v-model="activeTab" class="custom-tabs">
          <el-tab-pane label="登录" name="login">
            <el-form
              ref="loginFormRef"
              :model="loginForm"
              :rules="loginRules"
              class="auth-form"
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
              <div class="form-actions">
                <el-button
                  type="primary"
                  size="large"
                  class="submit-btn"
                  :loading="loading"
                  @click="handleLogin"
                >
                  立即登录
                </el-button>
              </div>
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="注册" name="register">
            <el-form
              ref="registerFormRef"
              :model="registerForm"
              :rules="registerRules"
              class="auth-form"
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
              <div class="form-actions">
                <el-button
                  type="primary"
                  size="large"
                  class="submit-btn"
                  :loading="loading"
                  @click="handleRegister"
                >
                  创建账号
                </el-button>
              </div>
            </el-form>
            <p class="hint-text">
              <el-icon><InfoFilled /></el-icon>
              首个注册用户将自动开启管理员权限
            </p>
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, Star, Monitor, Timer, InfoFilled } from '@element-plus/icons-vue'
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
  filter: blur(80px); /* 增加模糊度使光斑更柔和 */
}

.orb-1 {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.2), transparent 70%);
  top: -200px;
  right: -100px;
  animation: float 15s ease-in-out infinite;
}

.orb-2 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.15), transparent 70%);
  bottom: -150px;
  left: -150px;
  animation: float 18s ease-in-out infinite reverse;
}

.grid-glow {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle at 1px 1px, var(--border-soft) 1px, transparent 0);
  background-size: 40px 40px;
  mask-image: radial-gradient(circle at center, black, transparent 80%);
  opacity: 0.3;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -50px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(0.95); }
}

.login-container {
  position: relative;
  z-index: 10;
  width: min(1000px, 100%);
  min-height: 640px;
  display: flex;
  background: var(--bg-surface);
  border-radius: 32px;
  overflow: hidden;
  box-shadow: 0 24px 64px -12px rgba(0, 0, 0, 0.12);
  border: 1px solid var(--border-soft);
  animation: cardEnter 0.8s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes cardEnter {
  from { opacity: 0; transform: translateY(40px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

/* --- Brand Section Styles --- */
.brand-section {
  flex: 1.1;
  background: #0b1930; /* 默认深色背景，解决对比度问题 */
  background: linear-gradient(165deg, #0b1930 0%, #1a365d 100%);
  padding: 60px;
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
}

.brand-section::after {
  content: '';
  position: absolute;
  inset: 0;
  background: url("data:image/svg+xml,%3Csvg width='20' height='20' viewBox='0 0 20 20' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.03' fill-rule='evenodd'%3E%3Ccircle cx='3' cy='3' r='3'/%3E%3Ccircle cx='13' cy='13' r='3'/%3E%3C/g%3E%3C/svg%3E");
  pointer-events: none;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.brand-logo {
  width: 64px;
  height: 64px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #60a5fa;
  box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
}

.brand-header h1 {
  font-size: 28px;
  font-weight: 800;
  margin: 0;
  letter-spacing: -0.02em;
}

.brand-tagline {
  font-size: 16px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.7);
  margin-bottom: 48px;
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: 32px;
}

.feature-item {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.feature-icon {
  width: 44px;
  height: 44px;
  background: rgba(59, 130, 246, 0.15);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #60a5fa;
  font-size: 20px;
  flex-shrink: 0;
}

.feature-text h3 {
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 4px;
}

.feature-text p {
  font-size: 14px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.6);
  margin: 0;
}

.brand-footer {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.4);
  font-weight: 500;
  letter-spacing: 0.05em;
}

/* --- Form Section Styles --- */
.form-section {
  flex: 0.9;
  padding: 60px 50px;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
}

.form-header {
  margin-bottom: 32px;
}

.form-header h2 {
  font-size: 28px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.form-header p {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
}

.custom-tabs :deep(.el-tabs__header) {
  margin-bottom: 30px;
}

.custom-tabs :deep(.el-tabs__nav-wrap::after) {
  display: none;
}

.custom-tabs :deep(.el-tabs__item) {
  font-size: 16px;
  font-weight: 600;
  padding: 0 24px;
  height: 40px;
  line-height: 40px;
}

.auth-form {
  margin-top: 10px;
}

.auth-form :deep(.el-form-item) {
  margin-bottom: 24px;
}

.auth-form :deep(.el-input__wrapper) {
  padding-left: 15px;
  height: 52px;
}

.form-actions {
  margin-top: 32px;
}

.submit-btn {
  width: 100%;
  height: 52px;
  font-size: 16px;
  font-weight: 700;
  border-radius: 16px;
  background: var(--bg-primary);
  box-shadow: 0 12px 24px -6px rgba(37, 99, 235, 0.25);
}

.submit-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 16px 32px -6px rgba(37, 99, 235, 0.35);
}

.hint-text {
  margin-top: 24px;
  font-size: 13px;
  color: var(--text-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

/* --- Responsive Adjustments --- */
@media (max-width: 900px) {
  .login-container {
    flex-direction: column;
    min-height: auto;
    width: 480px;
    border-radius: 24px;
  }

  .brand-section {
    padding: 40px;
    flex: none;
  }

  .brand-tagline, .brand-features, .brand-footer {
    display: none;
  }

  .brand-header {
    margin-bottom: 0;
    justify-content: center;
  }

  .form-section {
    padding: 40px;
  }
}

@media (max-width: 520px) {
  .login-page {
    padding: 16px;
  }
  
  .login-container {
    width: 100%;
  }

  .form-section {
    padding: 32px 24px;
  }
}
</style>
