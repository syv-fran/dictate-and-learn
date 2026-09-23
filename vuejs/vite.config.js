import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue';
import { execSync } from 'child_process';
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? './' : '/',
  plugins: [
    vue(), 
    vueDevTools(),
  ],
  build: {
    outDir: path.resolve(__dirname, '../backend/static'),
    emptyOutDir: false,
  }, 
  test: {
    environment: "jsdom",
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
}))
