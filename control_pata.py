#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
control_pata.py — Control por USB-Serial de UNA pata de hexápodo (3 DOF)
========================================================================

Controla una sola pata (servos de coxa, fémur y tibia) conectada a un
Arduino (Uno/Nano) con conversor CH340 a 115200 bps.

La CINEMÁTICA INVERSA (IK) se calcula AQUÍ, en Python, usando las
fórmulas del diagrama 3-DOF y las longitudes reales de los segmentos
(L1 coxa, L2 fémur, L3 tibia), configurables abajo. El resultado son
ángulos de servo que se envían al firmware como "coxa,femur,tibia".

Fórmulas del diagrama (coordenadas: x adelante, y arriba, z lateral):

    FeetDistance = √(x² + z²)
    HF           = √(y² + (FeetDistance − L1)²)
    alpha1       = acos(y / HF)
    alpha2       = acos((L2² + HF² − L3²) / (2·L2·HF))
    theta        = acos((L2² + L3² − HF²) / (2·L2·L3))
    gama         = atan2(z, x)
    coxa  = gama
    femur = alpha1 + alpha2
    tibia = 180 − theta            (equivalente a Beta + 90, Beta = 90 − theta)

Modos de uso:
    python control_pata.py                 → menú + puente WS (auto-det. CH340)
    python control_pata.py --puerto COM10  → puerto explícito
    python control_pata.py --sin-ws        → sin conexión al dashboard
    python control_pata.py --test          → verifica IK/FK sin conectar
    python control_pata.py --listar        → lista puertos serie

Integración con el dashboard (servidor WebSocket):
  - Se registra como cliente "arduino" y reporta el estado de la pata
    ({"pata":{coxa,femur,tibia,gesto}}) para animar la vista 3D de la web.
  - Recibe comandos {"cmd":"pata", modo:estatico|gesto|neutro|velocidad}
    desde el frontend y los traduce a comandos seriales del firmware.

Dependencias:
    pip install pyserial websocket-client
"""

import argparse
import json
import math
import queue
import socket
import sys
import threading
import time

import serial
from serial.tools import list_ports
import websocket

# ---------------------------------------------------------------------------
# CONFIGURACIÓN DE LA PATA (¡AJUSTA A TU ROBOT!)
# ---------------------------------------------------------------------------
L_COXA  = 40.0   # mm — segmento horizontal de la coxa (L1)
L_FEMUR = 80.0   # mm — longitud del fémur (L2)
L_TIBIA = 100.0  # mm — longitud de la tibia (L3)

# Mapeo ángulo del diagrama → ángulo de servo: servo = offset + dir * ang
# CALIBRADO AL MONTAJE REAL del robot (2026-08): coxa y fémur están montados
# al revés (espejo: coxa → 90−gama, fémur → 180−ang); la tibia va normal.
# Si cambias el montaje, ajusta aquí Y en los checkboxes "Espejo" de la
# vista Pata de la web (para que el modelo 3D siga coincidiendo).
OFFSET    = (90.0, 180.0, 0.0)  # coxa neutra a 90°; fémur espejado; tibia normal
DIRECCION = (-1, -1, 1)         # coxa y fémur invertidos; tibia normal

# Límites de seguridad por servo (grados), en orden coxa, fémur, tibia
LIMITES_SERVO = ((0.0, 180.0), (0.0, 180.0), (0.0, 180.0))

# Posición neutra/reposo de los servos
NEUTRO_SERVO = (90.0, 90.0, 90.0)

# ── Comunicación serie ──────────────────────────────────────────────────────
BAUDIOS          = 115200        # velocidad del CH340
TIMEOUT_SERIAL   = 0.3           # s, espera de respuestas OK/ERR/POS
ESPERA_RESET     = 2.0           # s, auto-reset del Arduino al abrir el puerto
INTERVALO_WAYPOINT = 0.04        # s entre comandos de una trayectoria IK

# ── Servidor WebSocket (dashboard) ──────────────────────────────────────────
WS_URL = "wss://arduino.libardo-apps.es"  # Local: "ws://localhost:3000"
REINTENTO_WS = 3     # segundos entre reintentos de conexión al WS
PING_INTERVALO = 15  # segundos entre pings de keepalive (evita timeouts)

# Estado actual de la pata (se reporta al servidor para animar la web)
estado_pata = {"coxa": NEUTRO_SERVO[0], "femur": NEUTRO_SERVO[1],
               "tibia": NEUTRO_SERVO[2], "gesto": None}

# Cola de mensajes hacia el WebSocket
cola_ws = queue.Queue(maxsize=200)

# El puerto serie se comparte entre el menú (hilo principal) y el hilo WS
lock_serial = threading.Lock()


# ---------------------------------------------------------------------------
# Clase Leg: cinemática de la pata (IK + FK)
# ---------------------------------------------------------------------------
class Leg:
    """Modelo cinemático de una pata 3-DOF (coxa, fémur, tibia).

    ik(x, y, z) → ángulos de SERVO en grados (con offset, dirección y límites).
    fk(c, f, t) → posición del pie (x, y, z) en mm (para verificar).
    """

    def __init__(self, coxa=L_COXA, femur=L_FEMUR, tibia=L_TIBIA,
                 offset=OFFSET, direccion=DIRECCION,
                 limites=LIMITES_SERVO, neutro=NEUTRO_SERVO):
        self.coxa  = float(coxa)
        self.femur = float(femur)
        self.tibia = float(tibia)
        self.offset = tuple(float(o) for o in offset)
        self.dir    = tuple(int(d) for d in direccion)
        self.limites = tuple((float(a), float(b)) for a, b in limites)
        self.neutro  = tuple(float(n) for n in neutro)

    # ── Cinemática inversa ────────────────────────────────────────────────

    def _ik_geometria(self, x, y, z):
        """(x, y, z) en mm → ángulos del diagrama (coxa, femur, tibia)."""
        pies = math.hypot(x, z)                       # Feet Distance
        if pies < self.coxa - 1e-6:
            raise ValueError(
                f"objetivo inalcanzable: el pie ({x:.0f},{y:.0f},{z:.0f}) está "
                f"más cerca del eje del coxa que la longitud del coxa ({self.coxa} mm)")
        hf = math.hypot(y, pies - self.coxa)          # HF
        if hf < 1e-6:
            raise ValueError("objetivo degenerado (HF ≈ 0)")
        if hf > self.femur + self.tibia + 1e-3 or hf < abs(self.femur - self.tibia) - 1e-3:
            raise ValueError(
                f"objetivo fuera del alcance de fémur+tibia: HF={hf:.1f} mm "
                f"(debe estar entre {abs(self.femur - self.tibia):.1f} y "
                f"{self.femur + self.tibia:.1f})")

        alpha1 = math.degrees(math.acos(self._clamp(y / hf, -1.0, 1.0)))
        alpha2 = math.degrees(math.acos(self._clamp(
            (self.femur**2 + hf**2 - self.tibia**2) / (2.0 * self.femur * hf),
            -1.0, 1.0)))
        theta = math.degrees(math.acos(self._clamp(
            (self.femur**2 + self.tibia**2 - hf**2) / (2.0 * self.femur * self.tibia),
            -1.0, 1.0)))

        gama  = math.degrees(math.atan2(z, x))        # Gama
        femur = alpha1 + alpha2                       # FemurAngle = Alpha + 90
        tibia = 180.0 - theta                         # TibiaAngle = Beta + 90

        return gama, femur, tibia

    def ik(self, x, y, z):
        """(x, y, z) mm → ángulos de SERVO (grados), recortados a los límites."""
        g, f, t = self._ik_geometria(x, y, z)
        return self._a_servo(g, f, t)

    def es_alcanzable(self, x, y, z):
        """True si el punto está dentro del espacio de trabajo de la pata."""
        try:
            self._ik_geometria(x, y, z)
            return True
        except ValueError:
            return False

    # ── Cinemática directa (verificación / depuración) ────────────────────

    def fk(self, c, f, t):
        """Ángulos de servo (grados) → posición del pie (x, y, z) en mm."""
        g, fg, tg = self._de_servo(c, f, t)           # ángulos del diagrama
        theta = 180.0 - tg
        hf = math.sqrt(self.femur**2 + self.tibia**2
                       - 2.0 * self.femur * self.tibia * math.cos(math.radians(theta)))
        alpha2 = math.degrees(math.acos(self._clamp(
            (self.femur**2 + hf**2 - self.tibia**2) / (2.0 * self.femur * hf),
            -1.0, 1.0)))
        alpha  = fg - 90.0
        alpha1 = alpha - alpha2 + 90.0
        y = hf * math.cos(math.radians(alpha1))
        r_plano = hf * math.sin(math.radians(alpha1))
        pies = r_plano + self.coxa
        x = pies * math.cos(math.radians(g))
        z = pies * math.sin(math.radians(g))
        return x, y, z

    # ── Conversión diagrama ↔ servo ───────────────────────────────────────

    def _a_servo(self, g, f, t):
        angs = []
        for i, a in enumerate((g, f, t)):
            v = self.offset[i] + self.dir[i] * a
            lo, hi = self.limites[i]
            if v < lo or v > hi:
                print(f"[!] Servo {i}: {v:.1f}° fuera de límites → recortado")
            angs.append(max(lo, min(hi, v)))
        return tuple(angs)

    def _de_servo(self, c, f, t):
        vals = []
        for i, v in enumerate((c, f, t)):
            vals.append((v - self.offset[i]) * self.dir[i])
        return tuple(vals)

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Gestos (modo dinámico) — waypoints en el espacio (x, y, z) → IK → ángulos
# ---------------------------------------------------------------------------
def waypoints_gesto(leg, nombre):
    """Devuelve una lista de (coxa, femur, tibia) para el gesto indicado."""
    nombre = nombre.strip().lower()
    wps = []

    if nombre == "saludar":
        # Oscilación de la pata: levantar, barrer la coxa izq→der, bajar.
        x = leg.coxa + 0.55 * (leg.femur + leg.tibia)
        for y in _linspace(-40.0, 20.0, 6):            # 1) levantar
            wps.append(leg.ik(x, y, 0.0))
        for ph in _linspace(-90.0, 90.0, 20):          # 2) oscilar
            z = 80.0 * math.sin(math.radians(ph))
            wps.append(leg.ik(x, 10.0, z))
        for y in _linspace(20.0, -40.0, 6):            # 3) bajar
            wps.append(leg.ik(x, y, 0.0))

    elif nombre == "estirar":
        # Extensión máxima controlada hacia delante (margen de 15 mm).
        x = leg.coxa + leg.femur + leg.tibia - 15.0
        wps.append(leg.ik(x, 0.0, 0.0))

    elif nombre == "punito":
        # Pata recogida/cerrada: pie pegado al cuerpo, lo más arriba posible.
        x = leg.coxa + 2.0
        y = leg.femur + leg.tibia - 15.0
        wps.append(leg.ik(x, y, 0.0))

    else:
        raise ValueError(f"gesto desconocido: {nombre} (saludar | estirar | punito)")

    return wps


def _linspace(a, b, n):
    return [a + (b - a) * i / (n - 1) for i in range(n)]


# ---------------------------------------------------------------------------
# Comunicación serie con el firmware
# ---------------------------------------------------------------------------
class PataSerial:
    """Enlace USB-Serial con el firmware de la pata (protocolo de líneas)."""

    def __init__(self, puerto, baudios=BAUDIOS, timeout=TIMEOUT_SERIAL):
        self.puerto = puerto
        self.baudios = baudios
        self.timeout = timeout
        self.ser = None

    def conectar(self, reintentos=5):
        """Abre el puerto con reintentos y espera el auto-reset del Arduino."""
        ultimo_error = None
        for intento in range(1, reintentos + 1):
            try:
                self.ser = serial.Serial(self.puerto, self.baudios,
                                         timeout=self.timeout)
                self.ser.reset_input_buffer()
                print(f"[✓] Puerto {self.puerto} abierto a {self.baudios} bps")
                print(f"[…] Esperando auto-reset del Arduino ({ESPERA_RESET:.0f} s)…")
                time.sleep(ESPERA_RESET)
                self.ser.reset_input_buffer()
                return self
            except (serial.SerialException, OSError) as e:
                ultimo_error = e
                print(f"[!] Intento {intento}/{reintentos}: no se pudo abrir "
                      f"{self.puerto} ({e})")
                if intento < reintentos:
                    time.sleep(1.0)
        raise ConnectionError(
            f"No se pudo conectar a {self.puerto} tras {reintentos} intentos: "
            f"{ultimo_error}\n  ¿Está el CH340 enchufado y libre? ¿Otro "
            f"programa ocupa el puerto?")

    def cerrar(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"[✓] Puerto {self.puerto} cerrado")

    def enviar(self, linea):
        """Envía una línea y devuelve las respuestas recibidas (lista)."""
        if not self.ser or not self.ser.is_open:
            raise serial.SerialException("el puerto serie no está abierto")
        self.ser.write((linea.strip() + "\n").encode("ascii", "replace"))
        return self.leer_respuestas()

    def leer_respuestas(self, espera=TIMEOUT_SERIAL):
        """Lee las líneas que el Arduino responda durante `espera` segundos."""
        respuestas = []
        t0 = time.monotonic()
        self.ser.timeout = 0.05
        while time.monotonic() - t0 < espera:
            try:
                raw = self.ser.readline()
            except serial.SerialException:
                break
            if not raw:
                continue
            linea = raw.decode("ascii", "replace").strip()
            if linea:
                respuestas.append(linea)
        return respuestas

    # ── Comandos de alto nivel ─────────────────────────────────────────────
    def estatico(self, coxa, femur, tibia):
        # Formato plano "c,f,t" (sin prefijo): es el protocolo del firmware
        # simple motorhexapod.ino (el que SÍ funciona con el robot físico) y
        # también lo acepta pata_hexapodo.ino.
        return self.enviar(f"{coxa:.1f},{femur:.1f},{tibia:.1f}")

    def gesto_firmware(self, nombre):
        # Solo lo entiende pata_hexapodo.ino (motorhexapod.ino ignora "G,..").
        # El flujo normal usa siempre IK en Python (aplicar_gesto).
        return self.enviar(f"G,{nombre}")

    def neutro(self):
        # Neutro en formato plano: compatible con ambos firmwares.
        c, f, t = NEUTRO_SERVO
        return self.enviar(f"{c:.1f},{f:.1f},{t:.1f}")

    def velocidad(self, grados_seg):
        # Solo lo usa pata_hexapodo.ino; motorhexapod.ino lo ignora sin romperse.
        return self.enviar(f"V,{grados_seg:.0f}")

    def estado(self):
        return self.enviar("?")

    def gesto_ik(self, leg, nombre, intervalo=INTERVALO_WAYPOINT,
                 on_waypoint=None):
        """Calcula la trayectoria IK en Python y la transmite waypoint a
        waypoint. La interpolación suave la hace el firmware."""
        wps = waypoints_gesto(leg, nombre)
        print(f"[→] Gesto '{nombre}': {len(wps)} waypoints IK → streaming…")
        for i, (c, f, t) in enumerate(wps, 1):
            self.enviar(f"A,{c:.1f},{f:.1f},{t:.1f}")
            if on_waypoint:
                on_waypoint(i, len(wps), (c, f, t))
            time.sleep(intervalo)
        print(f"[✓] Trayectoria '{nombre}' completada")


# ---------------------------------------------------------------------------
# Puente WebSocket ↔ Serial (mismo patrón que generadorondas.py / picfpgaADC.py)
# ---------------------------------------------------------------------------

def reportar_pata(gesto=None):
    """Encuela el estado de la pata hacia el servidor (anima los frontends)."""
    if gesto is not None:
        estado_pata["gesto"] = gesto
    try:
        cola_ws.put_nowait(json.dumps(
            {"pata": {"coxa": round(estado_pata["coxa"], 1),
                      "femur": round(estado_pata["femur"], 1),
                      "tibia": round(estado_pata["tibia"], 1),
                      "gesto": estado_pata["gesto"]}},
            separators=(",", ":")))
    except queue.Full:
        pass  # el servidor va lento: se descarta esta actualización


def aplicar_estatico(ctrl, coxa, femur, tibia, verbose=True):
    """Modo estático: mueve los 3 servos y reporta el estado al servidor."""
    with lock_serial:
        resp = ctrl.estatico(coxa, femur, tibia)
    estado_pata.update(coxa=coxa, femur=femur, tibia=tibia, gesto=None)
    reportar_pata()
    if verbose:
        print(f"  ← coxa={coxa:.1f} femur={femur:.1f} tibia={tibia:.1f} "
              f"({' | '.join(resp) if resp else 'sin respuesta'})")
    return resp


def aplicar_gesto(ctrl, leg, nombre, intervalo=INTERVALO_WAYPOINT, verbose=True):
    """Modo dinámico: trayectoria IK calculada AQUÍ y reportada waypoint a
    waypoint para que la web anime la pata en tiempo real."""
    wps = waypoints_gesto(leg, nombre)
    estado_pata["gesto"] = nombre
    reportar_pata()
    print(f"[→] Gesto '{nombre}': {len(wps)} waypoints IK → streaming…")
    try:
        for c, f, t in wps:
            with lock_serial:
                ctrl.estatico(c, f, t)
            estado_pata.update(coxa=c, femur=f, tibia=t)
            reportar_pata()
            time.sleep(intervalo)
    finally:
        estado_pata["gesto"] = None
        reportar_pata()
    if verbose:
        print(f"[✓] Trayectoria '{nombre}' completada")


def aplicar_neutro(ctrl, verbose=True):
    """Vuelve a la posición de reposo y reporta el estado."""
    with lock_serial:
        resp = ctrl.neutro()
    estado_pata.update(coxa=NEUTRO_SERVO[0], femur=NEUTRO_SERVO[1],
                       tibia=NEUTRO_SERVO[2], gesto=None)
    reportar_pata()
    if verbose:
        print(f"  ← {' | '.join(resp) if resp else 'sin respuesta'}")
    return resp


def aplicar_velocidad(ctrl, grados_seg):
    """Cambia la velocidad de interpolación del firmware."""
    with lock_serial:
        return ctrl.velocidad(grados_seg)


def procesar_mensaje_ws(raw, ctrl, leg):
    """Procesa un comando llegado del servidor (hilo WS).

    Solo interesan los JSON {"cmd":"pata", ...}; los caracteres ASCII de la
    vista "Arduino" del dashboard se ignoran (esta pata tiene su protocolo).
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return
    if not isinstance(msg, dict) or msg.get("cmd") != "pata":
        return
    try:
        modo = msg.get("modo")
        if modo == "estatico":
            c = float(msg.get("coxa", estado_pata["coxa"]))
            f = float(msg.get("femur", estado_pata["femur"]))
            t = float(msg.get("tibia", estado_pata["tibia"]))
            aplicar_estatico(ctrl, c, f, t)
        elif modo == "gesto" and isinstance(msg.get("gesto"), str):
            aplicar_gesto(ctrl, leg, msg["gesto"].strip().lower())
        elif modo == "neutro":
            aplicar_neutro(ctrl)
        elif modo == "velocidad":
            aplicar_velocidad(ctrl, float(msg.get("velocidad", 120.0)))
        else:
            print(f"[WS] Comando de pata desconocido: {msg}")
    except Exception as e:
        print(f"[WS] Error al aplicar comando de pata: {e}")


def hilo_websocket(ctrl, leg):
    """Mantiene la conexión WS: reporta el estado y recibe comandos.

    La recepción (recv) va en un hilo aparte, así el envío de estados nunca se
    bloquea ni caduca por timeout, y el cierre por parte del servidor se
    detecta al instante para reconectar.
    """
    while True:
        ws = None
        try:
            ws = websocket.WebSocket()
            ws.connect(WS_URL, timeout=10)
            ws.send("arduino")  # registro obligatorio del protocolo del servidor
            # Rehidrata el servidor con el estado actual tras cada reconexión
            reportar_pata()
            # Bloqueante: los send no caducan por timeout (recv va en otro hilo)
            ws.settimeout(None)
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
                        msg = ws.recv()  # bloqueante; auto-responde los pings
                        if not msg:
                            break       # el servidor cerró la conexión
                        procesar_mensaje_ws(msg, ctrl, leg)
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


# ---------------------------------------------------------------------------
# Detección del puerto CH340
# ---------------------------------------------------------------------------
def listar_puertos():
    puertos = list(list_ports.comports())
    if not puertos:
        print("No hay puertos serie disponibles.")
        return []
    print("Puertos serie detectados:")
    for i, p in enumerate(puertos, 1):
        print(f"  [{i}] {p.device} — {p.description} (hwid: {p.hwid})")
    return puertos


def detectar_puerto(preferido=None):
    """Busca el CH340 automáticamente; si no, deja elegir al usuario."""
    if preferido:
        return preferido
    for p in list_ports.comports():
        info = f"{p.description} {p.hwid}".lower()
        if "ch340" in info or "1a86" in info:      # VID 1A86 = WCH (CH340)
            print(f"[✓] CH340 detectado en {p.device} ({p.description})")
            return p.device
    puertos = listar_puertos()
    if puertos:
        sel = input("Elige el número del puerto (o escribe el nombre): ").strip()
        try:
            return puertos[int(sel) - 1].device
        except (ValueError, IndexError):
            return sel or puertos[0].device
    raise ConnectionError("No se detectó ningún puerto serie")


# ---------------------------------------------------------------------------
# Verificación de la cinemática (--test)
# ---------------------------------------------------------------------------
def test_cinematica(leg):
    print("=== Verificación IK → FK (sin hardware) ===")
    print(f"Longitudes: L1={leg.coxa} mm, L2={leg.femur} mm, L3={leg.tibia} mm\n")
    objetivos = [
        ("estirar ", leg.coxa + leg.femur + leg.tibia - 15.0, 0.0, 0.0),
        ("neutro  ", leg.coxa + 0.55 * (leg.femur + leg.tibia), -40.0, 0.0),
        ("punito  ", leg.coxa + 2.0, leg.femur + leg.tibia - 15.0, 0.0),
        ("lateral ", 100.0, 10.0, 70.0),
    ]
    print(f"{'objetivo':<12} {'x,y,z (mm)':<22} {'servos c,f,t':<22} "
          f"{'fk x,y,z':<22} {'error(mm)':<10}")
    ok = True
    for nombre, x, y, z in objetivos:
        try:
            c, f, t = leg.ik(x, y, z)
            x2, y2, z2 = leg.fk(c, f, t)
            err = math.dist((x, y, z), (x2, y2, z2))
            estado = "OK" if err < 1.0 else "REVISAR"
            if err >= 1.0:
                ok = False
            print(f"{nombre:<12} ({x:.0f},{y:.0f},{z:.0f})         "
                  f"({c:5.1f},{f:5.1f},{t:5.1f})       "
                  f"({x2:5.1f},{y2:5.1f},{z2:5.1f})       {err:5.2f}  {estado}")
        except ValueError as e:
            ok = False
            print(f"{nombre:<12} ({x:.0f},{y:.0f},{z:.0f})  →  ERROR: {e}")
    print("\nResultado:", "TODO CORRECTO ✓" if ok else "HAY ERRORES ✗")


# ---------------------------------------------------------------------------
# Menú interactivo
# ---------------------------------------------------------------------------
def _leer_3_angulos(prompt="Ángulos coxa,femur,tibia (ej: 90 45 120): "):
    """Pide 3 ángulos y los valida contra los límites de seguridad."""
    texto = input(prompt).strip().replace(",", " ")
    partes = texto.split()
    if len(partes) != 3:
        raise ValueError("se necesitan 3 valores separados por espacio o coma")
    valores = [float(p) for p in partes]
    for i, v in enumerate(valores):
        lo, hi = LIMITES_SERVO[i]
        if not (lo <= v <= hi):
            raise ValueError(f"servo {i}: {v}° fuera de límites [{lo}, {hi}]")
    return valores


def menu(ctrl, leg):
    print("\n=== CONTROL DE PATA HEXÁPODO 3-DOF ===")
    while True:
        print("\n  1. Modo ESTÁTICO  — enviar 3 ángulos directos")
        print("  2. Modo DINÁMICO  — gesto (IK calculada en Python)")
        print("  3. Posición neutra (reposo)")
        print("  4. Consultar estado del firmware")
        print("  5. Cambiar velocidad de interpolación")
        print("  6. Salir")
        op = input("\nOpción: ").strip()

        try:
            if op == "1":
                c, f, t = _leer_3_angulos()
                aplicar_estatico(ctrl, c, f, t)

            elif op == "2":
                print("  Gestos: saludar | estirar | punito")
                nombre = input("  Gesto: ").strip().lower()
                if nombre not in ("saludar", "estirar", "punito"):
                    print("[!] Gesto desconocido")
                    continue
                # Siempre IK en Python con waypoints en formato plano "c,f,t":
                # funciona tanto con motorhexapod.ino como con pata_hexapodo.ino
                aplicar_gesto(ctrl, leg, nombre)

            elif op == "3":
                aplicar_neutro(ctrl)

            elif op == "4":
                with lock_serial:
                    resp = ctrl.estado()
                print("  ←", " | ".join(resp) if resp else "(sin respuesta)")

            elif op == "5":
                v = float(input("  Velocidad (grados/segundo, 5..600): "))
                resp = aplicar_velocidad(ctrl, v)
                print("  ←", " | ".join(resp) if resp else "(sin respuesta)")

            elif op == "6":
                break

            else:
                print("[!] Opción no válida")

        except ValueError as e:
            print(f"[!] Entrada inválida: {e}")
        except serial.SerialException as e:
            print(f"[!] Error serie: {e}. Intenta reconectar.")
            try:
                ctrl.conectar()
            except ConnectionError:
                print("[!] Reintenta de nuevo cuando el cable esté conectado")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Control de una pata hexápodo 3-DOF (coxa/fémur/tibia) vía CH340")
    parser.add_argument("--puerto", help="puerto COM explícito (ej: COM10)")
    parser.add_argument("--baudios", type=int, default=BAUDIOS,
                        help=f"velocidad serie (def: {BAUDIOS})")
    parser.add_argument("--intervalo", type=float, default=INTERVALO_WAYPOINT,
                        help="segundos entre waypoints IK (def: 0.04)")
    parser.add_argument("--listar", action="store_true",
                        help="lista puertos serie y sale")
    parser.add_argument("--test", action="store_true",
                        help="verifica IK/FK sin conectar hardware")
    parser.add_argument("--sin-ws", action="store_true",
                        help="no conectar al servidor WebSocket (solo serial)")
    args = parser.parse_args()

    leg = Leg()

    if args.listar:
        listar_puertos()
        return

    if args.test:
        test_cinematica(leg)
        return

    try:
        puerto = detectar_puerto(args.puerto)
    except ConnectionError as e:
        print(f"[!] {e}")
        sys.exit(1)

    ctrl = PataSerial(puerto, args.baudios)
    try:
        ctrl.conectar()
    except ConnectionError as e:
        print(f"[!] {e}")
        sys.exit(1)

    # Puente WebSocket: reporta el estado y recibe comandos de la web
    if not args.sin_ws:
        threading.Thread(target=hilo_websocket, args=(ctrl, leg), daemon=True).start()
        print(f"[WS] Puente activo hacia {WS_URL} (--sin-ws para desactivarlo)")
    else:
        print("[WS] Puente desactivado (--sin-ws)")

    try:
        menu(ctrl, leg)
    except KeyboardInterrupt:
        print("\n[!] Interrumpido por el usuario")
    finally:
        ctrl.cerrar()


if __name__ == "__main__":
    main()
