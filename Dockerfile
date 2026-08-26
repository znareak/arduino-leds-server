# =============================================================================
# Etapa 1: Builder — compila TypeScript a JavaScript
# =============================================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Instalar pnpm globalmente
RUN npm install -g pnpm

# Copiar archivos de dependencias primero (mejor cacheo de capas)
COPY package.json pnpm-lock.yaml* ./

# Instalar TODAS las dependencias (incluye devDependencies para compilar)
RUN pnpm install --frozen-lockfile

# Copiar el resto del código fuente
COPY tsconfig.json ./
COPY index.ts ./
COPY public/ ./public/

# Compilar TypeScript → JavaScript en /app/dist/
RUN pnpm run build

# =============================================================================
# Etapa 2: Producción — solo lo necesario para ejecutar
# =============================================================================
FROM node:20-alpine

WORKDIR /app

# Instalar pnpm globalmente
RUN npm install -g pnpm

# Crear usuario no-root por seguridad
RUN addgroup -g 1001 -S nodegroup && \
    adduser -S nodeuser -u 1001 -G nodegroup

# Copiar package.json y lockfile, instalar solo dependencias de producción
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile --prod && pnpm store prune

# Copiar el código compilado desde el builder
COPY --from=builder /app/dist ./dist

# Copiar archivos estáticos del frontend
COPY --from=builder /app/public ./dist/public

# Cambiar a usuario no-root
USER nodeuser

# Variables de entorno por defecto
ENV PORT=3000 \
    PUBLIC_URL=http://localhost:3000 \
    NODE_ENV=production

# Puerto expuesto
EXPOSE 3000

# Labels para Docker Hub
LABEL org.opencontainers.image.title="Arduino LED Server"
LABEL org.opencontainers.image.description="Servidor WebSocket para enviar comandos ASCII (a,s,d) a un Arduino desde un frontend web"
LABEL org.opencontainers.image.url="https://github.com/tuusuario/arduino-leds-server"
LABEL org.opencontainers.image.licenses="MIT"

# Arranque
CMD ["node", "dist/index.js"]
