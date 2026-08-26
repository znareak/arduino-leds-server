# 📡 Conexión del Arduino al Servidor WebSocket (Python / MicroPython)

## 🔌 Datos de conexión

| Parámetro         | Valor                           |
| ----------------- | ------------------------------- |
| **URL WebSocket** | `wss://arduino.libardo-apps.es` |
| **Puerto**        | `443` (HTTPS estándar)          |
| **Protocolo**     | WebSocket seguro (WSS)          |

## 📋 Protocolo de comunicación

El protocolo es **mínimo y textual**. No se usa JSON para los comandos, solo caracteres ASCII crudos.

### 1. Registro inicial

Al conectarse por WebSocket, el Arduino debe enviar **lo primero**:

```
arduino
```

Esto identifica al cliente como Arduino ante el servidor. Si no se envía en los primeros 5 segundos, el servidor cierra la conexión.

### 2. Recepción de comandos

Una vez registrado, el Arduino recibirá **un único carácter ASCII** cada vez que se pulse un botón en el frontend:

| Carácter | ASCII (dec) | ASCII (hex) | Acción sugerida               |
| -------- | ----------- | ----------- | ----------------------------- |
| `a`      | `97`        | `0x61`      | Acción A (ej: encender LED 1) |
| `s`      | `115`       | `0x73`      | Acción S (ej: encender LED 2) |
| `d`      | `100`       | `0x64`      | Acción D (ej: encender LED 3) |

> ⚠️ Los caracteres se envían en **minúscula**. No llegarán mayúsculas ni otros caracteres.

### 3. Respuesta del Arduino al servidor (opcional)

El Arduino puede enviar **cualquier texto** de vuelta al servidor, y este lo reenviará a todos los frontends conectados. Útil para confirmar acciones o enviar datos de sensores:

```
LED_A_ON
LED_A_OFF
TEMP:24.5
```

## 💻 Ejemplo MicroPython (ESP32 / ESP8266 / Pico W)

### Opción A — Con `uwebsockets` (red local, sin SSL)

```python
import network, time
from uwebsockets import client

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("TU_WIFI", "TU_PASSWORD")
while not wlan.isconnected():
    time.sleep(0.5)
print("WiFi OK:", wlan.ifconfig()[0])

ws = client.connect("ws://192.168.1.50:3000")  # IP local

# 1) REGISTRO obligatorio
ws.send("arduino")

# 2) Escuchar comandos
while True:
    try:
        cmd = ws.recv()  # "a", "s", o "d"
        if cmd:
            print(f"Comando: {cmd}")

            if cmd == "a":
                ws.send("LED_A_ON")   # confirmar al frontend
            elif cmd == "s":
                ws.send("LED_S_ON")
            elif cmd == "d":
                ws.send("LED_D_ON")
    except OSError:
        print("Conexión perdida. Reintentando...")
        time.sleep(3)
        ws = client.connect("ws://192.168.1.50:3000")
        ws.send("arduino")
```

### Opción B — Con `websocket-client` (Python en PC / Raspberry Pi OS)

```bash
pip install websocket-client
```

```python
import websocket

def on_message(ws, message):
    cmd = message  # "a", "s", o "d"
    print(f"Comando: {cmd} (ASCII {ord(cmd)})")

    if cmd == "a":
        print("→ Acción A")
        ws.send("LED_A_ON")
    elif cmd == "s":
        print("→ Acción S")
        ws.send("LED_S_ON")
    elif cmd == "d":
        print("→ Acción D")
        ws.send("LED_D_ON")

def on_open(ws):
    print("Conectado!")
    ws.send("arduino")  # ← REGISTRO obligatorio

def on_close(ws, status, msg):
    print(f"Desconectado ({status}). Reintentando en 3s...")
    import time; time.sleep(3)
    iniciar()

def on_error(ws, error):
    print(f"Error: {error}")

def iniciar():
    ws = websocket.WebSocketApp(
        "wss://arduino.libardo-apps.es",
        on_open=on_open,
        on_message=on_message,
        on_close=on_close,
        on_error=on_error,
    )
    ws.run_forever()

iniciar()
```

## 📊 Formato de datos — RESUMEN

### Lo que el Arduino ENVÍA al servidor:

| Mensaje       | Formato | Cuándo                                   |
| ------------- | ------- | ---------------------------------------- |
| `"arduino"`   | `str`   | Nada más conectarse (**obligatorio**)    |
| `"LED_A_ON"`  | `str`   | Después de ejecutar comando (opcional)   |
| `"TEMP:24.5"` | `str`   | Para enviar datos de sensores (opcional) |

### Lo que el Arduino RECIBE del servidor:

| Mensaje | Tipo Python | Longitud | Cuándo                |
| ------- | ----------- | -------- | --------------------- |
| `"a"`   | `str`       | 1        | Usuario pulsa botón A |
| `"s"`   | `str`       | 1        | Usuario pulsa botón S |
| `"d"`   | `str`       | 1        | Usuario pulsa botón D |

## 🔄 Flujo completo

```
Arduino                    Servidor                   Frontend (web)
   │                          │                           │
   │── WS connect ──────────▶│                           │
   │── "arduino" ───────────▶│                           │
   │                          │── "arduino_connected" ──▶│  (LED verde)
   │                          │                           │
   │                          │◀── "a" ──────────────────│  (usuario pulsa A)
   │◀── "a" ────────────────│                           │
   │── "LED_A_ON" ──────────▶│                           │
   │                          │── "RX: LED_A_ON" ───────▶│  (aparece en terminal)
```

## 🧪 Probar sin Arduino (Python rápido)

```bash
pip install websocket-client
```

```python
import websocket

def on_msg(ws, msg): print(f"RECIBIDO: {msg}")
def on_open(ws): ws.send("arduino"); print("Registrado")

ws = websocket.WebSocketApp(
    "wss://arduino.libardo-apps.es",
    on_open=on_open,
    on_message=on_msg,
)
ws.run_forever()
```

O desde el navegador (F12 → Consola):

```javascript
const ws = new WebSocket("wss://arduino.libardo-apps.es");
ws.onopen = () => ws.send("arduino");
ws.onmessage = (e) => console.log("Recibido:", e.data);
```

## ⚠️ Notas importantes

1. **Siempre enviar `arduino` como primer mensaje** tras conectarse, o el servidor cerrará la conexión a los 5 segundos.
2. **Mantén la conexión viva**: el servidor envía un ping cada 30 segundos. La librería WebSocket del Arduino debería responder con pong automáticamente.
3. **Si se corta la conexión**, reconecta automáticamente. La mayoría de librerías tienen `setReconnectInterval()`.
4. **No es necesario enviar keep-alives manualmente**; el servidor se encarga.
5. **Solo llegan 3 caracteres posibles**: `a`, `s`, `d`. Cualquier otra cosa que envíe el frontend es filtrada por el servidor.
