# Construye la web del fantasy (Vite) y la sirve con Caddy, que hace de proxy a /api.
# Sin VITE_API_BASE -> la web llama a "/api" en el mismo origen (a través de Caddy).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
