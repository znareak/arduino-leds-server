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
// Estado de los sensores: 4 canales ADC (0-1023 → 0-5V)
// ---------------------------------------------------------------------------

const NUM_CANALES = 4;
const VREF = 5.0;
const canales = Array.from({ length: NUM_CANALES }, () => ({
  valor: 0,
  voltaje: 0,
  actualizado: 0,
}));
let sensoresActivos = false; // true cuando llega al menos una lectura válida
let lastArduinoFrame = 0; // timestamp de la última trama recibida del Arduino

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
    sensoresOnline: sensoresActivos,
    sensores: canales.map((c) => ({
      valor: c.valor,
      voltaje: c.voltaje,
      actualizado: c.actualizado,
    })),
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
      try {
        ws.send(data);
      } catch {
        // cliente murió a mitad de envío: se eliminará en su evento close
      }
    }
  }
}

// Reenviar frames binarios (video JPEG) intactos a los frontends
function broadcastBinaryToFrontends(data: Buffer): void {
  for (const ws of frontendClients) {
    if (ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(data);
      } catch {
        // cliente murió a mitad de envío: se eliminará en su evento close
      }
    }
  }
}

function broadcastServerInfo(): void {
  broadcastToFrontends(getServerInfo());
}

// ---------------------------------------------------------------------------
// Sensores: estado + parseo de tramas que envía el Arduino
// ---------------------------------------------------------------------------

function setCanal(idx: number, valor: number): void {
  if (!Number.isFinite(idx) || idx < 0 || idx >= NUM_CANALES || !Number.isFinite(valor)) return;
  const v = Math.max(0, Math.min(1023, Math.round(valor)));
  canales[idx].valor = v;
  canales[idx].voltaje = Number(((v / 1023) * VREF).toFixed(3));
  canales[idx].actualizado = Date.now();
}

let lastSensoresBroadcast = 0;
const SENSORES_BROADCAST_MS = 50; // máx. ~20 broadcast/s (el FPGA envía miles de tramas/s)

function broadcastSensores(): void {
  const now = Date.now();
  if (now - lastSensoresBroadcast < SENSORES_BROADCAST_MS) return;
  lastSensoresBroadcast = now;
  broadcastToFrontends(
    JSON.stringify({
      event: "sensores",
      canales: canales.map((c) => ({
        valor: c.valor,
        voltaje: c.voltaje,
        actualizado: c.actualizado,
      })),
    }),
  );
}

/**
 * Interpreta un mensaje de texto del Arduino como lectura de sensores.
 * Formatos aceptados:
 *   {"canales":[v0,v1,v2,v3]}   → actualiza todos los canales
 *   [v0,v1,v2,v3]                → ídem (array JSON)
 *   {"canal":0,"valor":512}      → actualiza un canal
 *   {"ch0":512,"ch1":300,...}    → actualiza por clave ch0..ch3 / c0..c3
 *   512,300,10,800               → CSV de valores (mínimo 2 números)
 *   0:512  /  C0:512             → actualiza un canal
 */
function parseSensores(
  text: string,
): { canales?: number[]; canal?: number; valor?: number } | null {
  const t = text.trim();
  if (!t) return null;

  // 1) JSON
  try {
    const json = JSON.parse(t);
    if (Array.isArray(json)) {
      const nums = json.map(Number);
      if (nums.length > 0) return { canales: nums };
    }
    if (json && typeof json === "object") {
      if (Array.isArray(json.canales)) {
        return { canales: json.canales.map(Number) };
      }
      if (typeof json.canal === "number" && typeof json.valor === "number") {
        return { canal: json.canal, valor: json.valor };
      }
      const claves = ["ch0", "ch1", "ch2", "ch3", "c0", "c1", "c2", "c3"];
      const nums: (number | null)[] = [null, null, null, null];
      let alguno = false;
      claves.forEach((k, i) => {
        if (typeof json[k] === "number") {
          nums[i % 4] = json[k];
          alguno = true;
        }
      });
      if (alguno) return { canales: nums.map((n) => (n === null ? 0 : n)) };
    }
  } catch {
    // no es JSON → probar formatos de texto
  }

  // 2) "0:512" / "C0:512" → un solo canal
  const m = t.match(/^c?(\d):(\d+)$/i);
  if (m) return { canal: parseInt(m[1], 10), valor: parseInt(m[2], 10) };

  // 3) CSV: solo números separados por coma/espacio/punto y coma
  if (/^[\d\s,;]+$/.test(t)) {
    const nums = t
      .split(/[\s,;]+/)
      .filter((x) => x !== "")
      .map(Number);
    if (nums.length >= 2) return { canales: nums };
  }

  return null;
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

    // Sensores: trama binaria de 2 bytes del Arduino (mismo formato del script serial:
    // b1 = 1cccxxxxx, b2 = 0yyyyy → canal = bits 6-5, valor = xxxxxyyyyy)
    if (isBinary && clientType === "arduino") {
      lastArduinoFrame = Date.now();
      const buf = raw as Buffer;
      for (let i = 0; i + 1 < buf.length; i += 2) {
        const b1 = buf[i];
        const b2 = buf[i + 1];
        if ((b1 & 0x80) !== 0 && (b2 & 0x80) === 0) {
          const chId = (b1 >> 5) & 0x03;
          const adcVal = ((b1 & 0x1f) << 5) | (b2 & 0x1f);
          setCanal(chId, adcVal);
          sensoresActivos = true;
        }
      }
      broadcastSensores();
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
        lastArduinoFrame = Date.now();
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
            sensoresOnline: sensoresActivos,
            sensores: canales.map((c) => ({
              valor: c.valor,
              voltaje: c.voltaje,
              actualizado: c.actualizado,
            })),
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

    // Arduino → Backend: si es una lectura de sensores, actualizar el estado;
    // además, reenviar el mensaje crudo a los frontends (para el log)
    if (clientType === "arduino") {
      lastArduinoFrame = Date.now();
      console.log(`📥 Arduino: ${text}`);
      const parsed = parseSensores(text);
      if (parsed) {
        sensoresActivos = true;
        if (parsed.canales) {
          parsed.canales.forEach((v, i) => setCanal(i, v));
        } else if (parsed.canal !== undefined && parsed.valor !== undefined) {
          setCanal(parsed.canal, parsed.valor);
        }
        broadcastSensores();
      }
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
      sensoresActivos = false;
      lastArduinoFrame = 0;
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

// Heartbeat de estado a los frontends cada 30s: permite a la web detectar
// conexiones muertas aunque no haya tráfico de sensores
setInterval(() => {
  broadcastServerInfo();
}, 30000);

// Watchdog: si el Arduino deja de enviar tramas, marcar sensores como inactivos
setInterval(() => {
  if (sensoresActivos && Date.now() - lastArduinoFrame > 10000) {
    sensoresActivos = false;
    console.log("⏱️ Sin tramas del Arduino en 10s → sensores marcados como inactivos");
    broadcastServerInfo();
  }
}, 5000);

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
  console.log('║   3. Sensores: {"canales":[v0,v1,v2,v3]} / 0:512 ║');
  console.log("╚══════════════════════════════════════════════════╝");
});
