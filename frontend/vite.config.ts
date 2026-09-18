import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
    }),
    Components({
      resolvers: [ElementPlusResolver()],
    }),
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // 本地开发代理必须与当前后端标准端口保持一致。
        // 一旦这里漂移到 8001 之类的临时端口，前端页面本身仍能打开，
        // 但所有登录/鉴权请求都会在代理层直接拒连，表现成“登录不上且后端无业务日志”。
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        // WebSocket 也要跟随同一个后端端口，否则扫码登录等长连接能力会出现“页面正常、连接失败”的隐蔽分叉。
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
