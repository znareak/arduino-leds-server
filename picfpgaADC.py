"""
Puente ADC (puerto serie) → Servidor WebSocket
==============================================
Lee 4 canales ADC (0-1023) del puerto serie con tramas de 2 bytes:

    Byte 1: 1cccxxxxx   (bit 7 = 1, bits 6-5 = canal 0-3, bits 4-0 = 5 bits altos)
    Byte 2: 0yyyyy      (bit 7 = 0, bits 4-0 = 5 bits bajos)
    valor = ((b1 & 0x1F) << 5) | (b2 & 0x1F)

Cada trama se reenvía intacta (mensaje binario) al servidor WebSocket,
registrándose como cliente "arduino". El servidor decodifica la trama y la
web (vista "Sensores") muestra CH0-CH3 con su voltaje (0-5V).

También recibe los comandos tecleados en la web (vista "Arduino", teclas
a/s/d...) y los reenvía por el puerto serie hacia el dispositivo.

Dependencias:
    pip install pyserial websocket-client
"""

import json
import queue
import socket
import threading
import time

import serial
import websocket

PUERTO = "COM10"                # Puerto COM asignado al CH340
BAUDIOS = 115200
WS_URL = "wss://arduino.libardo-apps.es"  # Producción: "wss://arduino.libardo-apps.es"

# "binario" → reenvía la trama original de 2 bytes (recomendado)
# "json"    → envía {"canales":[v0,v1,v2,v3]} cada ciclo completo (canal 3)
MODO_ENVIO = "binario"

REINTENTO_WS = 3  # segundos entre reintentos de conexión al WS
PING_INTERVALO = 15  # segundos entre pings de keepalive (evita timeouts de proxy)

canales = [0, 0, 0, 0]

# Cola de mensajes hacia el WebSocket (bytes para binario, str para JSON)
cola_ws = queue.Queue(maxsize=200)

ser = None  # puerto serie (compartido con el hilo del WS)


def encolar_mensaje(msg):
    """Encuela un mensaje (bytes para binario, str para JSON) hacia el WS."""
    try:
        cola_ws.put_nowait(msg)
    except queue.Full:
        pass  # si el servidor va lento, se descarta esta actualización


def hilo_websocket():
    """Mantiene la conexión WS: envía las tramas encoladas y recibe comandos.

    La recepción (recv) va en un hilo aparte, así el envío de tramas nunca se
    bloquea ni caduca por timeout, y el cierre por parte del servidor se
    detecta al instante para reconectar.
    """
    global ser
    while True:
        ws = None
        try:
            ws = websocket.WebSocket()
            ws.connect(WS_URL, timeout=10)
            ws.send("arduino")   # registro obligatorio del protocolo
            # Rehidrata el servidor con el estado actual tras cada reconexión
            # (la web muestra los valores al instante, sin esperar la trama del canal 3)
            try:
                ws.send(json.dumps({"canales": canales}, separators=(",", ":")))
            except Exception:
                pass
            # Bloqueante: los send no caducan por timeout (recv va en otro hilo)
            ws.settimeout(None)
            # Nagle off (latencia) + keepalive TCP (detectar caídas)
            try:
                ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                ws.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except Exception:
                pass
            print(f"[WS] Conectado a {WS_URL} y registrado como 'arduino'")

            cerrado = threading.Event()
            ultimo_ping = time.monotonic()

            def lector():
                """Recibe comandos del frontend; avisa si el servidor cierra."""
                try:
                    while not cerrado.is_set():
                        cmd = ws.recv()  # bloqueante; auto-responde los pings
                        if not cmd:
                            break       # el servidor cerró la conexión
                        print(f"[WS] Comando del frontend: {cmd}")
                        if ser is not None:
                            ser.write(cmd.encode("ascii"))
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
                    msg = cola_ws.get(timeout=0.05)
                    if isinstance(msg, bytes):
                        ws.send(msg, websocket.ABNF.OPCODE_BINARY)
                    else:
                        ws.send(msg)
                except queue.Empty:
                    # Sin datos pendientes: ping de keepalive periódico
                    if time.monotonic() - ultimo_ping > PING_INTERVALO:
                        ultimo_ping = time.monotonic()
                        ws.ping()
                except Exception:
                    cerrado.set()
                    raise
        except Exception as e:
            print(f"[WS] Desconectado ({e}). Reintentando en {REINTENTO_WS}s...")
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
        time.sleep(REINTENTO_WS)


def main():
    global ser
    try:
        ser = serial.Serial(PUERTO, BAUDIOS, timeout=1)
    except serial.SerialException as e:
        print(f"Error de conexión: {e}")
        return

    # Hilo que mantiene la conexión WebSocket
    threading.Thread(target=hilo_websocket, daemon=True).start()

    print(f"--- Recibiendo 4 Canales ADC desde la FPGA ({PUERTO}) → {WS_URL} ---\n")

    try:
        while True:
            b1_raw = ser.read(1)
            if not b1_raw:
                continue

            b1 = b1_raw[0]  # en Python 3, read() devuelve bytes → el índice 0 es el entero

            # Detecta Byte 1 de la trama (Bit 7 == 1)
            if (b1 & 0x80) != 0:
                b2_raw = ser.read(1)
                if not b2_raw:
                    continue

                b2 = b2_raw[0]

                # Valida Byte 2 de la trama (Bit 7 == 0)
                if (b2 & 0x80) == 0:
                    ch_id = (b1 >> 5) & 0x03
                    adc_val = ((b1 & 0x1F) << 5) | (b2 & 0x1F)
                    canales[ch_id] = adc_val

                    # --- Envío al servidor web (formatos aceptados por la página) ---
                    if MODO_ENVIO == "binario":
                        # La trama original de 2 bytes, tal y como la decodifica
                        # el servidor (mismo protocolo que muestra la web).
                        encolar_mensaje(bytes((b1, b2)))
                    elif ch_id == 3:
                        # Alternativa en texto, un JSON con los 4 canales.
                        encolar_mensaje(
                            json.dumps({"canales": canales}, separators=(",", ":"))
                        )

                    # Muestra el estado global cada vez que se actualiza el canal 3
                    if ch_id == 3:
                        v0 = (canales[0] / 1023.0) * 5.0
                        v1 = (canales[1] / 1023.0) * 5.0
                        v2 = (canales[2] / 1023.0) * 5.0
                        v3 = (canales[3] / 1023.0) * 5.0

                        print(f"CH0: {canales[0]:4d} ({v0:.2f}V) | "
                              f"CH1: {canales[1]:4d} ({v1:.2f}V) | "
                              f"CH2: {canales[2]:4d} ({v2:.2f}V) | "
                              f"CH3: {canales[3]:4d} ({v3:.2f}V)")
    except KeyboardInterrupt:
        print("\nConexión finalizada por el usuario.")
    finally:
        if ser.is_open:
            ser.close()


if __name__ == "__main__":
    main()