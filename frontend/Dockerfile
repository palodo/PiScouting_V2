# Construye la web (Vite) y la sirve con Caddy, que además hace de proxy a /api.
# Sin VITE_API_BASE -> la web llama a "/api" en el mismo origen (a través de Caddy).
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
