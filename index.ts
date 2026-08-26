import express from "express";
import http from "http";
import { WebSocketServer, WebSocket } from "ws";
import path from "path";

// ---------------------------------------------------------------------------
// Express + HTTP
// ---------------------------------------------------------------------------

const app = express();
const PORT = process.env.PORT ? parseInt(process.env.PORT) : 3000;
const PUBLIC_URL = process.env.PUBLIC_URL || `http://localhost:${PORT}`;
const WS_URL = PUBLIC_URL.replace(/^http/, "ws");

// Carpeta de archivos estáticos (funciona tanto en dev como en prod compilado)
const publicPath = path.join(__dirname, "public");
app.use(express.static(publicPath));

// Ruta raíz explícita (por si express.static falla)
app.get("/", (_req, res) => {
  res.sendFile(path.join(publicPath, "index.html"));
});

// Health check para Docker
app.get("/health", (_req, res) => {
  res.json({ status: "ok", pid: process.pid });
});

// Debug: ver qué archivos hay en publicPath
app.get("/debug", (_req, res) => {
  const fs = require("fs");
  try {
    const files = fs.readdirSync(publicPath);
    res.json({
      publicPath,
      __dirname,
      cwd: process.cwd(),
      files,
      indexExists: fs.existsSync(path.join(publicPath, "index.html")),
    });
  } catch (e: any) {
    res.status(500).json({ error: e.message, publicPath, __dirname, cwd: process.cwd() });
  }
});

const server = http.createServer(app);

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

const wss = new WebSocketServer({ server });

// Conexión del carro ESP32-CAM
let carroWs: WebSocket | null = null;
let carroNombre = "";
let videoFrames = 0; // contador de frames de video recibidos
// Conexión del Arduino genérico
let arduinoWs: WebSocket | null = null;
// Guardamos todas las conexiones del frontend
const frontendClients = new Set<WebSocket>();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getServerInfo() {
  return JSON.stringify({
    event: "server_info",
    url: PUBLIC_URL,
    wsUrl: WS_URL,
    port: PORT,
    carroOnline: carroWs !== null && carroWs.readyState === WebSocket.OPEN,
    carroNombre: carroNombre || null,
    arduinoOnline: arduinoWs !== null && arduinoWs.readyState === WebSocket.OPEN,
    frontendsOnline: frontendClients.size,
  });
}

function sendToCarro(data: string): boolean {
  if (carroWs && carroWs.readyState === WebSocket.OPEN) {
    carroWs.send(data);
    return true;
  }
  return false;
}

function sendToArduino(data: string): boolean {
  if (arduinoWs && arduinoWs.readyState === WebSocket.OPEN) {
    arduinoWs.send(data);
    return true;
  }
  return false;
}

function broadcastToFrontends(data: string): void {
  for (const ws of frontendClients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }
}

// Reenviar frames binarios (video JPEG) intactos a los frontends
function broadcastBinaryToFrontends(data: Buffer): void {
  for (const ws of frontendClients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  }
}

function broadcastServerInfo(): void {
  broadcastToFrontends(getServerInfo());
}

// ---------------------------------------------------------------------------
// Manejo de conexiones
// ---------------------------------------------------------------------------

wss.on("connection", (ws: WebSocket, req) => {
  console.log(`🔌 Nueva conexión: ${req.socket.remoteAddress}`);

  // El primer mensaje define el tipo de cliente
  let registered = false;
  let clientType: "frontend" | "carro" | "arduino" | null = null;

  ws.on("message", (raw, isBinary) => {
    // Video: frames binarios del carro → reenviar intactos a los frontends
    if (isBinary && clientType === "carro") {
      videoFrames++;
      if (videoFrames % 20 === 0) {
        console.log(
          `📹 Video: ${videoFrames} frames (${(raw as Buffer).length}B) → ${frontendClients.size} frontend(s)`,
        );
      }
      broadcastBinaryToFrontends(raw as Buffer);
      return;
    }

    const text = raw.toString().trim();

    // --- REGISTRO: el primer mensaje define el tipo de cliente ---
    if (!registered) {
      // 1) Carro ESP32-CAM: {"tipo":"hola","nombre":"carro1"}
      try {
        const json = JSON.parse(text);
        if (json.tipo === "hola" && json.nombre) {
          registered = true;
          clientType = "carro";
          // Siempre sobrescribir: cada reconexión genera un socket nuevo
          if (carroWs && carroWs !== ws) {
            carroWs.close();
          }
          carroWs = ws;
          carroNombre = String(json.nombre);
          console.log(`🚗 Carro conectado: ${carroNombre}`);
          broadcastToFrontends(JSON.stringify({ event: "carro_connected", nombre: carroNombre }));
          broadcastServerInfo();
          return;
        }
      } catch {
        // no es JSON, seguimos probando otros tipos
      }

      // 2) Arduino genérico: envía "arduino"
      if (text === "arduino") {
        registered = true;
        clientType = "arduino";
        if (arduinoWs && arduinoWs !== ws) {
          arduinoWs.close();
        }
        arduinoWs = ws;
        console.log(`🤖 Arduino conectado`);
        broadcastToFrontends(JSON.stringify({ event: "arduino_connected" }));
        broadcastServerInfo();
        return;
      }

      // 3) Frontend
      if (text === "frontend") {
        registered = true;
        clientType = "frontend";
        frontendClients.add(ws);
        console.log(`🖥️  Frontend conectado`);
        ws.send(
          JSON.stringify({
            event: "registered",
            carroOnline: carroWs !== null && carroWs.readyState === WebSocket.OPEN,
            carroNombre: carroNombre || null,
            arduinoOnline: arduinoWs !== null && arduinoWs.readyState === WebSocket.OPEN,
            url: PUBLIC_URL,
            wsUrl: WS_URL,
            port: PORT,
          }),
        );
        broadcastServerInfo();
        return;
      }

      // Mensaje de registro inválido
      ws.send(
        JSON.stringify({
          event: "error",
          message: 'Regístrate con {"tipo":"hola","nombre":"carro1"}, "arduino" o "frontend"',
        }),
      );
      return;
    }

    // --- Ya registrado: enrutar mensajes ---

    // Arduino → Backend: reenviar mensaje crudo a frontends
    if (clientType === "arduino") {
      console.log(`📥 Arduino: ${text}`);
      broadcastToFrontends(JSON.stringify({ event: "arduino_msg", data: text }));
      return;
    }

    // Carro → Backend: reenviar mensajes crudos a frontends
    // (el firmware solo envía el saludo "hola"; no hay telemetría)
    if (clientType === "carro") {
      console.log(`📥 Carro: ${text}`);
      broadcastToFrontends(JSON.stringify({ event: "carro_msg", data: text }));
      return;
    }

    // Frontend → comandos
    if (clientType === "frontend") {
      // ¿JSON con comando para el carro?
      try {
        const json = JSON.parse(text);
        if (json.cmd || json.var) {
          console.log(`📤 Frontend → Carro: ${text}`);
          const enviado = sendToCarro(text);
          ws.send(
            JSON.stringify({
              event: "sent_cmd",
              data: json.cmd || json.var,
              delivered: enviado,
            }),
          );
          return;
        }
      } catch {
        // no es JSON, es una tecla ASCII → Arduino
      }
      const lower = text.toLowerCase();
      console.log(`📤 Frontend → Arduino: "${lower}" (ASCII ${lower.charCodeAt(0)})`);
      const enviado = sendToArduino(lower);
      ws.send(
        JSON.stringify({
          event: "sent",
          key: lower,
          ascii: lower.charCodeAt(0),
          delivered: enviado,
        }),
      );
      return;
    }
  });

  ws.on("close", () => {
    if (ws === carroWs) {
      carroWs = null;
      carroNombre = "";
      console.log("🚗 Carro desconectado");
      broadcastToFrontends(JSON.stringify({ event: "carro_disconnected" }));
      broadcastServerInfo();
    } else if (ws === arduinoWs) {
      arduinoWs = null;
      console.log("🔌 Arduino desconectado");
      broadcastToFrontends(JSON.stringify({ event: "arduino_disconnected" }));
      broadcastServerInfo();
    } else {
      frontendClients.delete(ws);
      console.log("🔌 Frontend desconectado");
      broadcastServerInfo();
    }
  });

  ws.on("error", (err) => {
    console.error("❌ Error:", err.message);
  });
});

// ---------------------------------------------------------------------------
// Ping automático cada 30s para mantener vivas las conexiones
// ---------------------------------------------------------------------------

setInterval(() => {
  if (carroWs && carroWs.readyState === WebSocket.OPEN) {
    carroWs.ping();
  }
  if (arduinoWs && arduinoWs.readyState === WebSocket.OPEN) {
    arduinoWs.ping();
  }
  for (const ws of frontendClients) {
    if (ws.readyState === WebSocket.OPEN) {
      ws.ping();
    }
  }
}, 30000);

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

server.listen(PORT, () => {
  console.log("╔══════════════════════════════════════════════════╗");
  console.log("║   🔌  Servidor Carro ESP32 WebSocket            ║");
  console.log("║                                                  ║");
  console.log(`║   🌐  Frontend:  ${PUBLIC_URL}                  ║`);
  console.log(`║   📡  WebSocket: ${WS_URL}                  ║`);
  console.log("║                                                  ║");
  console.log("║   📋  Protocolo:                                 ║");
  console.log('║   1. Carro: {"tipo":"hola","nombre":"carro1"}    ║');
  console.log('║   2. Comandos: {"cmd":"adelante"}, etc.          ║');
  console.log("╚══════════════════════════════════════════════════╝");
});
