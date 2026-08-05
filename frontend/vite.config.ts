import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发代理：把 /api 转发到 FastAPI 后端，规避 CORS 并让前端代码全部用相对路径。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
