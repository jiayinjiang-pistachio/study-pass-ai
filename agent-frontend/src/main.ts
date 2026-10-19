import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/index.scss'
import App from './App.vue'
import router from './router'

async function bootstrap(): Promise<void> {
  // 仅开发环境启用 Mock.js（生产构建时该分支会被移除）。
  // Mock.js 通过替换全局 XMLHttpRequest 拦截请求，请求层的 axios 固定 xhr adapter，
  // 因此必须在首个请求发出前完成加载。
  if (import.meta.env.DEV) {
    await import('./mock')
  }

  createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
}

void bootstrap()
