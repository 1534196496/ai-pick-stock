import { defineConfig } from '@hey-api/openapi-ts';

/** 从已评审的后端契约生成 Fetch SDK 与 TypeScript 模型。 */
export default defineConfig({
  input: '../api/openapi.json',
  output: {
    clean: true,
    path: 'src/api/generated',
  },
});
