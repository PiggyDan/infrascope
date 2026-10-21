import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development, proxy API calls to the backend so the browser sees one origin
// (same as production, where nginx does the proxying). No CORS needed anywhere.
const apiTarget = process.env.INFRASCOPE_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
  build: {
    sourcemap: false,
  },
  test: {
    environment: "node",
  },
});
