import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so dist/ can be hosted from any sub-path (GitHub Pages, Vercel, file server).
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 800 },
});
