import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时 /api 与 /static 代理到本地 FastAPI 服务（uv run tep-web，默认 127.0.0.1:8000）。
// 构建产物直接输出到后端静态目录，供便携版发布流程打包。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/static": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "../../src/te_platform/web/dist",
    emptyOutDir: true,
  },
});
