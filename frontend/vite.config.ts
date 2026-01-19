import { defineConfig } from "vite";
import preact from "@preact/preset-vite";

export default defineConfig({
  plugins: [preact()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:7777",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:7777",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
