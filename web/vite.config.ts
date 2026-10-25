import { defineConfig } from "vitest/config";

// PD-28: no Vite plugins and no dev-server proxy. The build goes straight into
// the folder the manager serves from its own origin (#6, REQ-118); `npm run`
// always starts in web/, so the relative path is stable.
export default defineConfig({
  build: {
    outDir: "../manager/bitscan_manager/webui",
    emptyOutDir: true,
    assetsDir: "assets",
    // CSP `default-src 'self'` (TS §6.3) blocks data: URLs, so no asset is
    // inlined; every asset is a same-origin file under /assets/.
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
  },
});
