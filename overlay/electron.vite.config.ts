import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "electron-vite";

// Two windows: the transparent overlay and the Control Center. Each has its own page and preload,
// so the overlay never gets the Control Center's powers.
export default defineConfig({
  main: {},
  preload: {
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, "src/preload/index.ts"),
          control: resolve(__dirname, "src/preload/control.ts"),
        },
      },
    },
  },
  renderer: {
    plugins: [react()],
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, "src/renderer/index.html"),
          control: resolve(__dirname, "src/renderer/control.html"),
        },
      },
    },
  },
});
