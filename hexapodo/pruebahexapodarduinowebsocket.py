import serial
import time
import math
import json
import queue
import threading
import socket
import websocket

# =======================================================================
# CONFIGURACIÓN
# =======================================================================
PUERTO_SERIE = 'COM8'  # Cambia por tu puerto (ej. /dev/ttyUSB0)
BAUD_RATE = 115200
WS_URL = "wss://arduino.libardo-apps.es"

# Medidas de tu robot en mm (LAS DEL CÓDIGO BUENO)
L_COXA = 30.0
L_FEMUR = 80.0
L_TIBIA = 120.0

# =======================================================================
# VARIABLES GLOBALES Y CONEXIÓN
# =======================================================================
estado_pata = {"coxa": 90, "femur": 90, "tibia": 90, "gesto": None}
cola_ws = queue.Queue(maxsize=200)
lock_serial = threading.Lock()

print(f"Conectando al Arduino en {PUERTO_SERIE}...")
try:
    arduino = serial.Serial(PUERTO_SERIE, BAUD_RATE)
    time.sleep(2)  # Espera a que el Arduino se reinicie al conectar
    print("¡Arduino conectado!")
except:
    print("Error: No se pudo conectar al Arduino. Ejecutando en modo simulación.")
    arduino = None

# =======================================================================
# CINEMÁTICA Y CONTROL (TU CÓDIGO BUENO)
# =======================================================================
def enviar_angulos(coxa, femur, tibia, verbose=True):
    """Envía los ángulos directamente al Arduino y avisa al WebSocket"""
    comando = f"{int(coxa)},{int(femur)},{int(tibia)}\n"
    
    with lock_serial:
        if arduino:
            arduino.write(comando.encode('utf-8'))
            
    # Actualizar estado para la web
    estado_pata.update(coxa=int(coxa), femur=int(femur), tibia=int(tibia))
    reportar_pata()
    
    if verbose:
        print(f"Enviando ángulos -> Coxa: {int(coxa)}°, Femur: {int(femur)}°, Tibia: {int(tibia)}°")
    time.sleep(0.05) # Pequeña pausa para dar tiempo al servo

def cinematica_inversa(x, y, z):
    """Calcula los ángulos (matemática original que te funciona bien)"""
    try:
        feet_dist = math.sqrt(x**2 + z**2)
        hf = math.sqrt(y**2 + (feet_dist - L_COXA)**2)

        alpha1 = math.degrees(math.acos(y / hf))
        
        val_alpha2 = (L_FEMUR**2 + hf**2 - L_TIBIA**2) / (2 * L_FEMUR * hf)
        alpha2 = math.degrees(math.acos(val_alpha2))
        
        val_theta = (L_FEMUR**2 + L_TIBIA**2 - hf**2) / (2 * L_FEMUR * L_TIBIA)
        theta = math.degrees(math.acos(val_theta))
        
        gama = math.degrees(math.atan2(z, x))
        alpha = alpha1 + alpha2 - 90
        beta = 90 - theta

        coxa_angle = 90 + gama
        femur_angle = alpha + 90
        tibia_angle = beta + 90

        c = max(0, min(180, coxa_angle))
        f = max(0, min(180, femur_angle))
        t = max(0, min(180, tibia_angle))
        
        return c, f, t

    except ValueError:
        print(f"Error: La coordenada ({x}, {y}, {z}) está fuera de alcance.")
        return None

def mover_a_coordenada(x, y, z):
    angulos = cinematica_inversa(x, y, z)
    if angulos:
        enviar_angulos(*angulos, verbose=False)

# =======================================================================
# RUTINAS DINÁMICAS (TU CÓDIGO BUENO)
# =======================================================================
def ejecutar_rutina(nombre):
    """Ejecuta la rutina en un hilo para no bloquear el WebSocket"""
    estado_pata["gesto"] = nombre
    reportar_pata()
    
    if nombre == "saludar":
        print("Ejecutando: Saludar...")
        for _ in range(3):
            mover_a_coordenada(50, 80, 50)
            time.sleep(0.3)
            mover_a_coordenada(50, 80, -50)
            time.sleep(0.3)
        mover_a_coordenada(80, 100, 0)
        
    elif nombre == "estirar":
        print("Ejecutando: Estirar...")
        for x in range(50, 150, 10):
            mover_a_coordenada(x, 50, 0)
        time.sleep(1)
        mover_a_coordenada(80, 100, 0)
        
    elif nombre == "punito":
        print("Ejecutando: Puñito...")
        mover_a_coordenada(50, 100, 0)
        time.sleep(0.5)
        mover_a_coordenada(140, 100, 0)
        time.sleep(1)
        mover_a_coordenada(80, 100, 0)

    # Volver a estado sin gesto
    estado_pata["gesto"] = None
    reportar_pata()

# =======================================================================
# INTEGRACIÓN WEBSOCKET
# =======================================================================
def reportar_pata():
    """Envía el estado actual al servidor para animar la vista 3D"""
    try:
        msg = json.dumps({"pata": estado_pata}, separators=(",", ":"))
        cola_ws.put_nowait(msg)
    except queue.Full:
        pass

def procesar_mensaje_ws(raw):
    """Lee comandos que llegan desde la web"""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return
        
    if not isinstance(msg, dict) or msg.get("cmd") != "pata":
        return
        
    modo = msg.get("modo")
    if modo == "estatico":
        c = float(msg.get("coxa", estado_pata["coxa"]))
        f = float(msg.get("femur", estado_pata["femur"]))
        t = float(msg.get("tibia", estado_pata["tibia"]))
        enviar_angulos(c, f, t)
    elif modo == "neutro":
        enviar_angulos(90, 90, 90)
    elif modo == "gesto" and isinstance(msg.get("gesto"), str):
        # Lanzar la rutina en un hilo aparte
        nombre = msg["gesto"].strip().lower()
        threading.Thread(target=ejecutar_rutina, args=(nombre,), daemon=True).start()

def hilo_websocket():
    """Mantiene la conexión viva con el servidor en segundo plano"""
    while True:
        ws = None
        try:
            ws = websocket.WebSocket()
            ws.connect(WS_URL, timeout=10)
            ws.send("arduino") 
            reportar_pata()
            ws.settimeout(None)
            print(f"\n[WS] Conectado al Dashboard en {WS_URL}")

            cerrado = threading.Event()
            ultimo_ping = time.monotonic()

            def lector():
                try:
                    while not cerrado.is_set():
                        msg = ws.recv() 
                        if not msg:
                            break 
                        procesar_mensaje_ws(msg)
                except Exception:
                    pass
                finally:
                    cerrado.set()

            threading.Thread(target=lector, daemon=True).start()

            while not cerrado.is_set():
                try:
                    msg = cola_ws.get(timeout=0.05)
                    ws.send(msg)
                except queue.Empty:
                    if time.monotonic() - ultimo_ping > 15:
                        ultimo_ping = time.monotonic()
                        ws.ping()
                except Exception:
                    cerrado.set()
                    raise
        except Exception as e:
            pass
        finally:
            if ws:
                try:
                    ws.close()
                except:
                    pass
        time.sleep(3) # Espera antes de reconectar

# =======================================================================
# MENÚ PRINCIPAL
# =======================================================================
def menu():
    # Arrancar el hilo del WebSocket antes de mostrar el menú
    threading.Thread(target=hilo_websocket, daemon=True).start()
    
    while True:
        print("\n--- CONTROL DE BRAZO ROBÓTICO + WEBSOCKET ---")
        print("1. Enviar ángulos estáticos (Manual)")
        print("2. Dinámico: Saludar")
        print("3. Dinámico: Estirar")
        print("4. Dinámico: Puñito")
        print("5. Centrar a 90,90,90")
        print("6. Salir")
        
        opcion = input("Elige una opción: ")
        
        if opcion == '1':
            try:
                c = float(input("Ángulo Coxa (0-180): "))
                f = float(input("Ángulo Femur (0-180): "))
                t = float(input("Ángulo Tibia (0-180): "))
                enviar_angulos(c, f, t)
            except ValueError:
                print("Por favor, ingresa números válidos.")
        elif opcion == '2':
            threading.Thread(target=ejecutar_rutina, args=("saludar",), daemon=True).start()
        elif opcion == '3':
            threading.Thread(target=ejecutar_rutina, args=("estirar",), daemon=True).start()
        elif opcion == '4':
            threading.Thread(target=ejecutar_rutina, args=("punito",), daemon=True).start()
        elif opcion == '5':
            enviar_angulos(90, 90, 90)
        elif opcion == '6':
            break
        else:
            print("Opción no válida.")

if __name__ == "__main__":
    menu()