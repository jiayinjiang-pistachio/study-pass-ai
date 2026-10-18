import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/index.scss'
import App from './App.vue'
import router from './router'

async function bootstrap(): Promise<void> {
  // 仅开发环境启用 Mock.js 请求拦截（生产构建时该分支会被移除）
  if (import.meta.env.DEV) {
    await import('./mock')
  }

  createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
}

void bootstrap()
