import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// FEATURE_TEST_MODULES permits isolated verification before the root scaffold lands.
const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(process.env.FEATURE_TEST_MODULES
  ? resolve(process.env.FEATURE_TEST_MODULES, '../package.json') : import.meta.url);
const { default: vue } = await import(pathToFileURL(require.resolve('@vitejs/plugin-vue')).href);
export default {
  root: resolve(here, '../../../..'),
  plugins: [vue()],
  resolve: {
    alias: [
      { find: /.*\/api\/client$/, replacement: resolve(here, 'core-stub.ts') },
      { find: /.*\/app\/(state|dialogs)$/, replacement: resolve(here, 'core-stub.ts') },
      { find: /^vue$/, replacement: require.resolve('vue/dist/vue.esm-bundler.js') },
      { find: /^@vue\/test-utils$/, replacement: require.resolve('@vue/test-utils') },
      { find: /^vitest$/, replacement: resolve(dirname(require.resolve('vitest/package.json')), 'dist/index.js') },
    ],
    dedupe: ['vue'],
  },
  test: { environment: 'jsdom', include: ['src/features/data-entry/tests/*.test.ts'], restoreMocks: true },
};
