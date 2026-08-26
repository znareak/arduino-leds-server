# 🐳 Guía Docker — Arduino LED Server

Guía completa para construir la imagen, subirla a Docker Hub y usarla.

---

## 📋 Requisitos previos

| Herramienta                        | Versión | Verificar                                |
| ---------------------------------- | ------- | ---------------------------------------- |
| Docker                             | 20+     | `docker --version`                       |
| Docker Buildx (opcional, para ARM) | —       | `docker buildx version`                  |
| Cuenta de Docker Hub               | —       | [hub.docker.com](https://hub.docker.com) |

---

## 🔨 1. Construir la imagen

Desde la raíz del proyecto:

```bash
# Build para tu arquitectura actual (PC Intel/AMD)
docker build -t znareak/arduino-leds-server:latest .

# Build para Raspberry Pi 4 (ARM64) desde PC
docker buildx build --platform linux/arm64 \
  -t znareak/arduino-leds-server:latest \
  --push .

# Build multi-arquitectura (PC + Raspberry Pi en una sola imagen)
docker buildx build --platform linux/amd64,linux/arm64 \
  -t znareak/arduino-leds-server:latest \
  --push .
```

> 💡 **Solo la primera vez** con buildx: `docker buildx create --name multiarch --use`

---

## ☁️ 2. Subir a Docker Hub

```bash
# Loguearse (una sola vez)
docker login

# Subir la imagen
docker push znareak/arduino-leds-server:latest

# Opcional: subir también con versión
docker tag znareak/arduino-leds-server:latest znareak/arduino-leds-server:v1.0.0
docker push znareak/arduino-leds-server:v1.0.0
```

Verificar en: [`hub.docker.com/r/znareak/arduino-leds-server`](https://hub.docker.com/r/znareak/arduino-leds-server)

---

## 🚀 3. Usar la imagen

### 🔧 Variables de entorno

| Variable     | Obligatoria | Default                 | Descripción                       |
| ------------ | :---------: | ----------------------- | --------------------------------- |
| `PORT`       |     ❌      | `3000`                  | Puerto HTTP + WebSocket interno   |
| `PUBLIC_URL` |     ⚠️      | `http://localhost:3000` | URL pública para mostrar en la UI |

> ⚠️ **Siempre configura `PUBLIC_URL`** con tu dominio o IP real, si no la UI mostrará `localhost`.

### Opción A — Docker run (rápido)

```bash
# Local / red LAN
docker run -d \
  --name arduino-server \
  -p 3000:3000 \
  -e PUBLIC_URL=http://192.168.1.50:3000 \
  --restart unless-stopped \
  znareak/arduino-leds-server:latest

# Con dominio HTTPS (detrás de un reverse proxy)
docker run -d \
  --name arduino-server \
  -p 3000:3000 \
  -e PUBLIC_URL=https://arduino.midominio.com \
  --restart unless-stopped \
  znareak/arduino-leds-server:latest
```

### Opción B — docker-compose

Crear `docker-compose.yml`:

```yaml
services:
  arduino-server:
    image: znareak/arduino-leds-server:latest
    container_name: arduino-leds-server
    ports:
      - "3000:3000"
    environment:
      - PORT=3000
      - PUBLIC_URL=https://arduino.midominio.com
      - NODE_ENV=production
    restart: unless-stopped
```

Arrancar:

```bash
docker-compose up -d
```

### Opción C — Raspberry Pi 4 (ARM64)

```bash
# La imagen multi-arch se descarga automáticamente correcta
docker run -d \
  --name arduino-server \
  -p 3000:3000 \
  -e PUBLIC_URL=http://192.168.1.50:3000 \
  --restart unless-stopped \
  znareak/arduino-leds-server:latest
```

### Opción D — Coolify / plataformas PaaS

| Campo          | Valor                              |
| -------------- | ---------------------------------- |
| Docker Image   | `znareak/arduino-leds-server`      |
| Tag            | `latest`                           |
| Container Port | `3000`                             |
| Environment    | `PUBLIC_URL=https://tudominio.com` |
|                | `PORT=3000`                        |

---

## 🧪 Verificar que funciona

```bash
# Ver logs
docker logs -f arduino-server

# Health check
curl http://localhost:3000/health
# → {"status":"ok"}

# Debug de archivos
curl http://localhost:3000/debug

# Abrir la web
# http://localhost:3000
```

---

## 🛠️ Comandos útiles

```bash
# Ver contenedores corriendo
docker ps

# Parar
docker stop arduino-server

# Borrar
docker rm -f arduino-server

# Ver logs en tiempo real
docker logs -f arduino-server

# Actualizar a la última versión
docker pull znareak/arduino-leds-server:latest
docker rm -f arduino-server
# (volver a ejecutar el docker run de arriba)
```

---

## 🔄 Flujo completo de publicación

```
1. Editar código
   ↓
2. docker build -t znareak/arduino-leds-server:latest .
   ↓
3. Probar local: docker run -p 3000:3000 ...
   ↓
4. docker login
   ↓
5. docker push znareak/arduino-leds-server:latest
   ↓
6. En el servidor: docker pull + docker run
```

---

## 📡 Después de desplegar

Consulta el documento `ARDUINO_CONEXION.md` para conectar el Arduino al servidor WebSocket.
