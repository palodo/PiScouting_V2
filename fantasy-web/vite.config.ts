import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// App independiente del fantasy. Corre en el 5174 (el scouting usa el 5173) y habla con
// el mismo backend FastAPI del 8000.
// GitHub Pages sirve el sitio en /<repo>/, no en la raíz. Con VITE_BASE se construye para
// ese subdirectorio; sin ella (local, Cloudflare, Vercel) se queda en "/" como siempre.
const base = process.env.VITE_BASE || "/";

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 5174,
    host: true, // accesible desde el móvil en la red local
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
