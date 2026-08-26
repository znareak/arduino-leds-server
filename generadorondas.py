"""
Control del generador de ondas (FPGA) — serial + WebSocket
==========================================================
Envía el byte del generador por el puerto serie (CH340):

    byte = (onda << 6) | frecuencia      (onda: 0-3, frecuencia: 0-63)

Y se comunica con el servidor WebSocket en ambos sentidos:
  - Lo que cambias en esta ventana se envía al servidor → la web analiza
    el estado y lo dibuja en su gráfica.
  - Lo que cambias en la web llega aquí por WebSocket → se reenvía a la
    FPGA por el puerto serie.

Dependencias:
    pip install pyserial websocket-client
"""

import json
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial
import serial.tools.list_ports
import websocket

WS_URL = "wss://arduino.libardo-apps.es"  # Local: "ws://localhost:3000"
REINTENTO_WS = 3  # segundos entre reintentos de conexión al WS

estado = {"onda": 0, "frecuencia": 0}  # último estado enviado/recibido
aplicando_remoto = False  # evita bucles al sincronizar desde la web
ws = None  # conexión compartida con el hilo receptor
cola_envio = queue.Queue(maxsize=50)


# ---------------------------------------------------------------------------
# Puerto serie (comunicación con la FPGA)
# ---------------------------------------------------------------------------

def obtener_puertos():
    """Busca los puertos COM disponibles en la computadora."""
    puertos = serial.tools.list_ports.comports()
    return [puerto.device for puerto in puertos]


def enviar_byte_serial(onda, frecuencia):
    """Escribe el byte (onda << 6) | frecuencia en el puerto serie."""
    byte = (onda & 0x03) << 6 | (frecuencia & 0x3F)
    try:
        puerto = combo_puertos.get()
    except Exception:
        puerto = None
    if not puerto:
        lbl_estado.config(text="⚠️ Selecciona un puerto COM primero", fg="red")
        return False
    try:
        # Abrimos puerto, enviamos y cerramos automáticamente (115200 baudios)
        with serial.Serial(puerto, 115200, timeout=1) as ser:
            ser.write(bytes([byte]))
        lbl_estado.config(text=f"✅ Enviado: {bin(byte)}", fg="green")
        return True
    except Exception:
        lbl_estado.config(text=f"❌ Error al abrir {puerto} (¿puente picfpgaADC.py en uso?)", fg="red")
        return False


# ---------------------------------------------------------------------------
# WebSocket (envío a la web y recepción de cambios de la web)
# ---------------------------------------------------------------------------

def encolar_onda(onda=None, frecuencia=None):
    """Encuela el comando JSON hacia el servidor WebSocket."""
    if onda is None:
        onda = estado["onda"]
    if frecuencia is None:
        frecuencia = estado["frecuencia"]
    estado["onda"] = onda
    estado["frecuencia"] = frecuencia
    try:
        cola_envio.put_nowait(
            json.dumps({"cmd": "onda", "onda": onda, "frecuencia": frecuencia},
                       separators=(",", ":"))
        )
    except queue.Full:
        pass  # la cola va llena: el servidor ya tiene órdenes más recientes


def aplicar_estado(onda, frecuencia):
    """Actualiza los controles de la GUI sin reenviar el comando."""
    global aplicando_remoto
    aplicando_remoto = True
    var_onda.set(onda)
    var_frecuencia.set(frecuencia)
    estado["onda"] = onda
    estado["frecuencia"] = frecuencia
    root.after(100, _limpiar_remoto)


def _limpiar_remoto():
    global aplicando_remoto
    aplicando_remoto = False


def manejar_remoto(onda, frecuencia):
    """Cambio llegado desde la web: sincroniza controles y reenvía al FPGA."""
    ya_aplicado = (onda == estado["onda"] and frecuencia == estado["frecuencia"])
    aplicar_estado(onda, frecuencia)
    if not ya_aplicado:
        enviar_byte_serial(onda, frecuencia)


def _ack(delivered):
    byte = (estado["onda"] << 6) | estado["frecuencia"]
    if delivered:
        lbl_estado.config(
            text=f"✅ Servidor OK: {bin(byte)} (onda {estado['onda']}, freq {estado['frecuencia']})",
            fg="green",
        )
    else:
        lbl_estado.config(text="❌ El servidor no pudo entregar (Arduino no conectado)", fg="red")


def procesar_mensaje(raw):
    """Recibe eventos del servidor (hilo WS) y actualiza la GUI."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return
    if not isinstance(msg, dict):
        return
    evento = msg.get("event")
    try:
        if evento == "generador":
            root.after(0, lambda: manejar_remoto(int(msg.get("onda", 0)), int(msg.get("frecuencia", 0))))
        elif evento == "sent_cmd" and msg.get("data") == "onda":
            root.after(0, lambda: _ack(bool(msg.get("delivered", False))))
        elif evento == "registered" and isinstance(msg.get("generador"), dict):
            gen = msg["generador"]
            root.after(0, lambda: manejar_remoto(int(gen.get("onda", 0)), int(gen.get("frecuencia", 0))))
        elif evento == "server_info" and isinstance(msg.get("generador"), dict):
            gen = msg["generador"]
            root.after(0, lambda: aplicar_estado(int(gen.get("onda", 0)), int(gen.get("frecuencia", 0))))
    except Exception:
        pass  # la GUI pudo cerrarse mientras llegaba el mensaje


def hilo_websocket():
    """Mantiene la conexión WS: envía los comandos encolados y recibe eventos."""
    global ws
    while True:
        ws = None
        try:
            ws = websocket.WebSocket()
            ws.connect(WS_URL, timeout=10)
            ws.send("frontend")   # registro como frontend del protocolo
            ws.settimeout(None)   # los send no caducan (recv va en otro hilo)
            try:
                ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                ws.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass
            root.after(0, lambda: lbl_estado.config(text="🌐 Conectado al servidor", fg="green"))

            cerrado = threading.Event()

            def lector():
                try:
                    while not cerrado.is_set():
                        msg = ws.recv()  # bloqueante; auto-responde los pings
                        if not msg:
                            break       # el servidor cerró la conexión
                        procesar_mensaje(msg)
                except Exception:
                    pass
                finally:
                    cerrado.set()
                    try:
                        ws.shutdown()  # interrumpe el envío del hilo principal
                    except Exception:
                        try:
                            ws.sock.shutdown(socket.SHUT_RDWR)
                        except Exception:
                            pass

            threading.Thread(target=lector, daemon=True).start()

            while not cerrado.is_set():
                try:
                    msg = cola_envio.get(timeout=0.2)
                    ws.send(msg)
                except queue.Empty:
                    pass
                except Exception:
                    cerrado.set()
                    raise
        except Exception as e:
            root.after(0, lambda: lbl_estado.config(text=f"🔌 Desconectado ({e}). Reintentando...", fg="orange"))
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        time.sleep(REINTENTO_WS)


# ---------------------------------------------------------------------------
# Interfaz gráfica (original + integración con el servidor)
# ---------------------------------------------------------------------------

_timer_envio = None


def enviar_datos(*_args):
    """Callback de los controles: envía al FPGA por serial y notifica a la web."""
    global _timer_envio
    if aplicando_remoto:
        return
    onda = var_onda.get()
    frecuencia = var_frecuencia.get()
    # 1) Directo al FPGA por el puerto serie
    enviar_byte_serial(onda, frecuencia)
    # 2) Notifica al servidor → la web actualiza su gráfica (debounce 50 ms)
    if _timer_envio is not None:
        root.after_cancel(_timer_envio)
    _timer_envio = root.after(50, lambda: encolar_onda(onda, frecuencia))


root = tk.Tk()
root.title("Control FPGA - CH340")
root.geometry("320x400")
root.resizable(False, False)
root.config(padx=20, pady=20)

var_onda = tk.IntVar(value=0)
var_frecuencia = tk.IntVar(value=0)

# 1. Selector de Puerto COM
tk.Label(root, text="1. Selecciona el Puerto COM:", font=("Arial", 10, "bold")).pack(anchor="w")
combo_puertos = ttk.Combobox(root, values=obtener_puertos(), state="readonly")
combo_puertos.pack(fill="x", pady=(5, 15))
if combo_puertos['values']:
    combo_puertos.current(0)  # Selecciona el primero por defecto

# 2. Selector de Onda (Radiobuttons)
tk.Label(root, text="2. Tipo de Onda:", font=("Arial", 10, "bold")).pack(anchor="w")
ondas = [
    ("Cuadrada (00)", 0),
    ("Triangular (01)", 1),
    ("Diente de Sierra (10)", 2),
    ("Senoidal (11)", 3),
]
for texto, valor in ondas:
    tk.Radiobutton(root, text=texto, variable=var_onda, value=valor,
                   command=enviar_datos).pack(anchor="w")

tk.Frame(root, height=15).pack()  # Espaciador

# 3. Control de Frecuencia (Slider)
tk.Label(root, text="3. Frecuencia (0 a 63):", font=("Arial", 10, "bold")).pack(anchor="w")
slider = tk.Scale(root, from_=0, to=63, orient="horizontal",
                  variable=var_frecuencia, command=enviar_datos)
slider.pack(fill="x", pady=(0, 15))

# 4. Etiqueta de Estado
lbl_estado = tk.Label(root, text="Conectando al servidor...", font=("Courier", 10))
lbl_estado.pack()

# Botón de refresco manual de puertos
tk.Button(root, text="Refrescar Puertos",
          command=lambda: combo_puertos.config(values=obtener_puertos())).pack(pady=10)

tk.Label(root, text="La web y esta ventana se sincronizan automáticamente.",
         font=("Arial", 8), fg="gray").pack()

# Hilo WebSocket (conexión + envío/recepción)
threading.Thread(target=hilo_websocket, daemon=True).start()

root.mainloop()