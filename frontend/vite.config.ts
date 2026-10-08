import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

/**
 * Режим api (npm run dev:api): интерфейс обращается к /api/search, а dev-сервер Vite
 * передаёт запросы /api/* бэкенду на http://127.0.0.1:8000 и срезает префикс /api
 * (/api/search → /search). Браузер видит один адрес, поэтому CORS в бэкенде не нужен.
 * Если бэкенд не запущен, прокси отвечает ошибкой 5xx и интерфейс показывает «Сервис недоступен».
 */
const apiProxy: Record<string, ProxyOptions> = {
  '/api': {
    target: 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
})
