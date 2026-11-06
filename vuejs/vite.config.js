import { fileURLToPath, URL } from 'node:url'
import path from 'node:path'
import { rm } from 'node:fs/promises'
import { defineConfig } from 'vite'
import { resolve } from 'path'
import vue from '@vitejs/plugin-vue'
import { execSync } from 'child_process';
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  base: mode === 'production' ? './' : '/',
  plugins: [
    vue(), 
    vueDevTools(),
   {
      name: "Cleaning assets folder",
     async buildStart() {
       await rm(resolve(import.meta.dirname, '../backend/static/assets'), { recursive: true, force: true });
     }
    }
  ],
  build: {
    outDir: path.resolve(import.meta.dirname, '../backend/static'),
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
