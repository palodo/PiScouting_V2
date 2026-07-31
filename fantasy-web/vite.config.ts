import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// App independiente del fantasy. Corre en el 5174 (el scouting usa el 5173) y habla con
// el mismo backend FastAPI del 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: true, // accesible desde el móvil en la red local
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
