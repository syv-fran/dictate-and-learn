import { fileURLToPath, URL } from 'node:url'

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
    {
      name: 'tar-gz',
      apply: 'build', //production build?  make tgz ready to copy out of container
      closeBundle() {
        execSync('tar -czf dist.tar.gz -C dist .');
      }
    }
  ],

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
}))
