import serial
import time
import math

# --- CONFIGURACIÓN ---
PUERTO_SERIE = 'COM8'  # Cambia esto por tu puerto (ej. /dev/ttyUSB0 en Linux/Mac)
BAUD_RATE = 115200

# Medidas de tu robot en mm (MODIFICA ESTOS VALORES)
L_COXA = 30.0
L_FEMUR = 80.0
L_TIBIA = 120.0

try:
    arduino = serial.Serial(PUERTO_SERIE, BAUD_RATE)
    time.sleep(2) # Espera a que el Arduino se reinicie al conectar
except:
    print("Error: No se pudo conectar al Arduino. Ejecutando en modo simulación.")
    arduino = None

def enviar_angulos(coxa, femur, tibia):
    """Envía los ángulos directamente al Arduino"""
    comando = f"{int(coxa)},{int(femur)},{int(tibia)}\n"
    if arduino:
        arduino.write(comando.encode('utf-8'))
    print(f"Enviando ángulos -> Coxa: {int(coxa)}°, Femur: {int(femur)}°, Tibia: {int(tibia)}°")
    time.sleep(0.05) # Pequeña pausa para dar tiempo al servo
def cinematica_inversa(x, y, z):
    """Calcula los ángulos basados en image_c143ec.jpg con offset en coxa"""
    try:
        # 1. Calcular distancias base (¡Estas son las líneas que faltaban!)
        feet_dist = math.sqrt(x**2 + z**2)
        hf = math.sqrt(y**2 + (feet_dist - L_COXA)**2)

        # 2. Ángulos internos en radianes y conversión a grados
        alpha1 = math.degrees(math.acos(y / hf))
        
        val_alpha2 = (L_FEMUR**2 + hf**2 - L_TIBIA**2) / (2 * L_FEMUR * hf)
        alpha2 = math.degrees(math.acos(val_alpha2))
        
        val_theta = (L_FEMUR**2 + L_TIBIA**2 - hf**2) / (2 * L_FEMUR * L_TIBIA)
        theta = math.degrees(math.acos(val_theta))
        
        # 3. Correcciones según la imagen
        gama = math.degrees(math.atan2(z, x))
        alpha = alpha1 + alpha2 - 90
        beta = 90 - theta

        # 4. Asignación a los motores (Aquí está el +90 del Coxa)
        coxa_angle = 90 + gama
        femur_angle = alpha + 90
        tibia_angle = beta + 90

        # 5. Restringir los valores entre 0 y 180 grados por seguridad
        c = max(0, min(180, coxa_angle))
        f = max(0, min(180, femur_angle))
        t = max(0, min(180, tibia_angle))
        
        return c, f, t

    except ValueError:
        # Ocurre si le pides al brazo ir más lejos de lo que físicamente puede
        print(f"Error: La coordenada ({x}, {y}, {z}) está fuera de alcance.")
        return None
def mover_a_coordenada(x, y, z):
    angulos = cinematica_inversa(x, y, z)
    if angulos:
        enviar_angulos(*angulos)

# --- RUTINAS DINÁMICAS ---
def rutina_saludar():
    print("Ejecutando: Saludar...")
    # Sube el brazo y lo mueve de izquierda a derecha (Z varía)
    for _ in range(3):
        mover_a_coordenada(50, 80, 50)
        time.sleep(0.3)
        mover_a_coordenada(50, 80, -50)
        time.sleep(0.3)
    mover_a_coordenada(80, 100, 0) # Volver al centro

def rutina_estirar():
    print("Ejecutando: Estirar...")
    # Mueve X hacia adelante gradualmente
    for x in range(50, 150, 10):
        mover_a_coordenada(x, 50, 0)
    time.sleep(1)
    mover_a_coordenada(80, 100, 0) # Retraer

def rutina_punito():
    print("Ejecutando: Puñito...")
    # Prepara el golpe atrás
    mover_a_coordenada(50, 100, 0)
    time.sleep(0.5)
    # Movimiento rápido hacia adelante
    mover_a_coordenada(140, 100, 0)
    time.sleep(1)
    mover_a_coordenada(80, 100, 0) # Retraer

# --- MENÚ PRINCIPAL ---
def menu():
    while True:
        print("\n--- CONTROL DE BRAZO ROBÓTICO ---")
        print("1. Enviar ángulos estáticos (Manual)")
        print("2. Dinámico: Saludar")
        print("3. Dinámico: Estirar")
        print("4. Dinámico: Puñito")
        print("5. Salir")
        
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
            rutina_saludar()
        elif opcion == '3':
            rutina_estirar()
        elif opcion == '4':
            rutina_punito()
        elif opcion == '5':
            break
        else:
            print("Opción no válida.")

if __name__ == "__main__":
    menu()