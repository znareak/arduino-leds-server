// Prueba local del flujo de sensores:
//   - Cliente "arduino" que envía tramas binarias de 2 bytes (como picfpgaADC.py)
//   - Cliente "frontend" que muestra qué eventos recibe
// Uso: node test-ws.mjs  (con el servidor corriendo en ws://localhost:3000)
import WebSocket from "ws";

const URL = process.env.WS_URL || "ws://localhost:3000";
const dur = parseInt(process.env.DURATION || "8000", 10);

let t = 500;
let frames = 0;

// --- Frontend simulado ---
const frontend = new WebSocket(URL);
frontend.on("open", () => {
  console.log("[FE] conectado → registro como 'frontend'");
  frontend.send("frontend");
});
frontend.on("message", (d) => {
  const txt = d.toString();
  try {
    const m = JSON.parse(txt);
    if (m.event === "sensores") {
      console.log(`[FE] evento sensores #${++frames}: ${m.canales.map((c) => c.valor).join(",")}`);
    } else if (m.event === "registered" || m.event === "server_info") {
      console.log(
        `[FE] ${m.event}: arduinoOnline=${m.arduinoOnline} sensoresOnline=${m.sensoresOnline} sensores=${m.sensores.map((c) => c.valor).join(",")}`,
      );
    } else {
      console.log(`[FE] ${m.event}`);
    }
  } catch {
    console.log("[FE] binario?", Buffer.isBuffer(d) ? d.length : typeof d);
  }
});
frontend.on("close", () => console.log("[FE] cerrado"));

// --- Arduino simulado (mismo protocolo que picfpgaADC.py) ---
const arduino = new WebSocket(URL);
arduino.on("open", () => {
  console.log("[AR] conectado → registro 'arduino' + snapshot JSON");
  arduino.send("arduino");
  arduino.send(JSON.stringify({ canales: [10, 20, 30, 40] }));
  // Tramas binarias cada 5 ms (≈200/s, como la FPGA real a alta velocidad)
  setInterval(() => {
    t = (t + 137) % 1024;
    const ch = Math.floor(t / 250) % 4;
    const b1 = 0x80 | (ch << 5) | ((t >> 5) & 0x1f);
    const b2 = t & 0x1f;
    arduino.send(Buffer.from([b1, b2]));
  }, 5);
});
arduino.on("message", (d) => console.log(`[AR] recibe del servidor: ${d.toString().slice(0, 80)}`));
arduino.on("close", () => console.log("[AR] cerrado"));
arduino.on("error", (e) => console.log("[AR] error:", e.message));

setTimeout(() => {
  console.log(
    `\n--- Resultado: el frontend recibió ${frames} eventos 'sensores' en ${dur / 1000}s ---`,
  );
  process.exit(frames > 0 ? 0 : 1);
}, dur);
