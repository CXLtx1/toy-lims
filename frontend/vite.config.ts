import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

const backend = process.env.LIMS_DEV_BACKEND || 'http://127.0.0.1:5000';
export default defineConfig({
  plugins: [vue()],
  base: '/frontend/',
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(['/api', '/login', '/logout', '/setup', '/health', '/static'].map(path => [path, { target: backend, changeOrigin: false }])),
  },
  build: { manifest: true, sourcemap: false, target: 'es2022' },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
    setupFiles: ['./src/test-setup.ts'],
    restoreMocks: true,
    clearMocks: true,
  },
});
