/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The read API (backend/app/readapi) serves /v1 on 127.0.0.1:8090. In development
// the dev server proxies /v1 there, so the browser never needs CORS and the
// client never holds a credential (the API has none to give).
const API = process.env.PRAJNA_API_URL ?? "http://127.0.0.1:8090";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": { target: API, changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/v1": { target: API, changeOrigin: false } } },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("lightweight-charts") || id.includes("fancy-canvas")) return "charts";
          if (id.includes("@tanstack")) return "query";
          if (/node_modules\/(react|react-dom|react-router|scheduler)\//.test(id)) return "react";
          return undefined;
        },
      },
    },
  },
  define: { __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? "0.0.0") },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.tsx"],
    env: { VITE_API_BASE: "http://localhost/v1" },
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
