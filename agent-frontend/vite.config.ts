import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv, type ProxyOptions } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiPrefix = env.VITE_API_PREFIX || '/api'
  const proxyTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

  const apiProxy: ProxyOptions = {
    target: proxyTarget,
    changeOrigin: true,
    secure: false,
  }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: Number(env.VITE_DEV_PORT) || 5173,
      cors: true,
      proxy: {
        [apiPrefix]: apiProxy,
      },
    },
    preview: {
      host: true,
      port: Number(env.VITE_PREVIEW_PORT) || 4173,
      cors: true,
      proxy: {
        [apiPrefix]: apiProxy,
      },
    },
  }
})
