import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

const backend = 'http://127.0.0.1:8000'
const languagetool = 'http://127.0.0.1:8010'

const proxy = {
  '/api': {
    target: backend,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
    timeout: 600000,
    proxyTimeout: 600000,
  },
  '/lt': {
    target: languagetool,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/lt/, ''),
    timeout: 120000,
    proxyTimeout: 120000,
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: { proxy },
  preview: { proxy },
})
