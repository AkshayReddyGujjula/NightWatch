import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard is a read-only projection of committed control-plane evidence.
// Live views must be served with `Cache-Control: no-store` by control_asgi; the
// static bundle itself carries no data and no credentials.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: false },
});
