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
  },
  '/lt': {
    target: languagetool,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/lt/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: { proxy },
  preview: { proxy },
})
