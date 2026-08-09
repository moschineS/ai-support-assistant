import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build straight into the API's static dir: FastAPI serves the SPA at /,
// so the reviewer runs exactly one process.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../api/app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});