import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages sirve esta app en /<repo>/scouting/, no en la raíz. Con VITE_BASE se
// construye para ese subdirectorio; sin ella (local, Cloudflare, Vercel) se queda en "/".
// Mismo convenio que fantasy-web.
const base = process.env.VITE_BASE || "/";

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5173,
    host: true, // accesible desde la red local (para abrir la web en el móvil)
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
