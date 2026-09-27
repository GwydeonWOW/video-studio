import path from "node:path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// La API vive en el mismo servicio (un contenedor en Coolify): en dev se
// proxy a uvicorn local, en producción el backend sirve este dist/.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/a": "http://127.0.0.1:8000",
    },
  },
  build: { outDir: "dist", sourcemap: false },
})
