// Prueba end-to-end del generador de ondas:
//   arduino simulado (recibe comandos) + frontend que envía {"cmd":"onda",...}
import WebSocket from "ws";

const URL = process.env.WS_URL || "ws://localhost:3000";

const arduino = new WebSocket(URL);
arduino.on("open", () => arduino.send("arduino"));
arduino.on("message", (d) => {
  const t = d.toString();
  if (t.includes('"cmd"')) console.log("[AR] recibe comando:", t);
});

const fe = new WebSocket(URL);
fe.on("open", () => {
  fe.send("frontend");
  setTimeout(() => {
    console.log('→ enviando {"cmd":"onda","onda":2,"frecuencia":33}');
    fe.send(JSON.stringify({ cmd: "onda", onda: 2, frecuencia: 33 }));
  }, 500);
});
fe.on("message", (d) => {
  try {
    const m = JSON.parse(d.toString());
    if (m.event === "generador") console.log("[FE] broadcast generador:", JSON.stringify(m));
    if (m.event === "sent_cmd" && m.data === "onda")
      console.log("[FE] ack sent_cmd:", JSON.stringify(m));
    if (m.event === "registered" && m.generador)
      console.log("[FE] registered.generador:", JSON.stringify(m.generador));
  } catch {
    /* binario */
  }
});

setTimeout(() => {
  console.log("\n--- Fin de la prueba ---");
  process.exit(0);
}, 3000);
