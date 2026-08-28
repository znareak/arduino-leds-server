// ============================================================================
//  PATA HEXÁPODO 3-DOF — Firmware Arduino
//  Control de UNA sola pata: coxa + fémur + tibia (3 servos RC)
// ============================================================================
//
//  PLACA:      Arduino Uno / Nano (ATmega328P). Compatible con Mega/Leonardo.
//  SERVOS:     Conectados DIRECTOS a pines PWM del Arduino (solo son 3).
//              (Para PCA9685 I2C, ver las notas al final del archivo)
//  CONVERSOR:  CH340 (USB-Serial) a 115200 bps, 8N1, sin paridad.
//
//  ┌──────────────────────────────────────────────────────────────────────┐
//  │ PROTOCOLO SERIAL (una línea por comando, terminada en \n)            │
//  ├──────────────────────────────────────────────────────────────────────┤
//  │ A,<coxa>,<femur>,<tibia>   → modo ESTÁTICO: 3 ángulos directos       │
//  │ <coxa>,<femur>,<tibia>      → ídem, sin prefijo (motorhexapod)       │
//  │ {"coxa":90,"femur":45,"tibia":120} → modo ESTÁTICO: JSON             │
//  │ G,<gesto>                  → modo DINÁMICO: secuencia de movimiento  │
//  │     gesto ∈ saludar | estirar | punito                               │
//  │ N                          → volver a posición neutra (reposo)       │
//  │ V,<grados_por_segundo>     → velocidad de interpolación (5..600)     │
//  │ ?                          → estado actual (responde POS,c,f,t)      │
//  │ T                          → TEST: mueve cada servo por turno       │
//  │ H                          → ayuda                                   │
//  ├──────────────────────────────────────────────────────────────────────┤
//  │ Respuestas: OK <comando> · POS,c,f,t · DONE gesto · WARN/ERR ...     │
//  └──────────────────────────────────────────────────────────────────────┘
//
//  IK: la cinemática inversa con longitudes reales (L1,L2,L3) la calcula el
//  script del PC (control_pata.py) y envía comandos "A,..". Los gestos del
//  firmware son secuencias de ángulos aproximadas que funcionan SIN PC.
//
//  MOVIMIENTO SUAVE: cada servo avanza hacia su objetivo a velocidad angular
//  constante (grados/segundo), sin saltos bruscos.
// ============================================================================

#include <Servo.h>

// ── Hardware ────────────────────────────────────────────────────────────────
const uint8_t PIN_COXA  = 9;   // servo de rotación horizontal
const uint8_t PIN_FEMUR = 10;  // servo "hombro" vertical
const uint8_t PIN_TIBIA = 11;  // servo "rodilla"
//  ⚠️ DIAGNÓSTICO: si el coxa no se mueve y su pin NO emite pulsos de ~50 Hz
//  (con un analizador lógico verás 1-2 ms de pulso cada 20 ms), el pin 9
//  puede estar dañado. Prueba a cambiarlo a otro pin PWM libre (ej. 6, 5, 3)
//  y conecta el servo ahí. Servo.h funciona en cualquier pin digital 2-13.

// ── Límites de seguridad por servo (grados) ────────────────────────────────
// Ajústalos a los límites MECÁNICOS reales de tu pata para no forzarla.
// Orden de los índices: [0]=coxa, [1]=fémur, [2]=tibia.
const float LIM_MIN[3] = {   0.0f,   0.0f,   0.0f };
const float LIM_MAX[3] = { 180.0f, 180.0f, 180.0f };

// ── Posición neutra / reposo ────────────────────────────────────────────────
// 90° en los 3 servos = servo centrado. Ajusta según tu montaje.
const float NEUTRO[3] = { 90.0f, 90.0f, 90.0f };

// Velocidad de interpolación por defecto (grados/segundo)
float velocidadDegS = 120.0f;

// Período del bucle de movimiento (ms) → 50 Hz de interpolación
const unsigned long TICK_MS = 20;

// ── Estado interno ──────────────────────────────────────────────────────────
Servo servo[3];
float angActual[3];    // posición que "ve" el firmware en cada momento
float angObjetivo[3];  // destino actual (modo estático o waypoint de gesto)
unsigned long ultimoTick = 0;

// LED de actividad (corazón): parpadea para indicar que el firmware vive
unsigned long ultimoLatido = 0;

// ── Secuenciador de gestos ──────────────────────────────────────────────────
struct PuntoGesto {
  float ang[3];       // ángulos objetivo del waypoint
  unsigned long ms;   // tiempo de permanencia en el waypoint
};

// "saludar": levantar la pata, oscilar la coxa a izquierda/derecha y bajar.
const PuntoGesto GESTO_SALUDAR[] = {
  { { 90, 120,  90 }, 400 },  // levantar (fémur arriba)
  { { 65, 120,  90 }, 350 },  // oscilar ←
  { {115, 120,  90 }, 350 },  // oscilar →
  { { 65, 120,  90 }, 350 },  // oscilar ←
  { {115, 120,  90 }, 350 },  // oscilar →
  { { 90, 120,  90 }, 350 },  // centrar
  { { 90,  90,  90 }, 500 },  // bajar a neutro
};

// "estirar": extensión máxima controlada hacia delante.
// (Ángulos aproximados; la extensión IK exacta la calcula control_pata.py)
const PuntoGesto GESTO_ESTIRAR[] = {
  { { 90, 115,  48 }, 800 },
  { { 90,  90,  90 }, 400 },
};

// "punito": pata recogida/plegada cerca del cuerpo.
const PuntoGesto GESTO_PUNITO[] = {
  { { 90,  30,  50 }, 800 },
  { { 90,  90,  90 }, 400 },
};

// "test": mueve CADA servo por turno para verificar cableado y pines.
const PuntoGesto GESTO_TEST[] = {
  { { 60,  90,  90 }, 700 },  // coxa a 60°
  { {120,  90,  90 }, 700 },  // coxa a 120°
  { { 90,  45,  90 }, 700 },  // fémur a 45°
  { { 90, 135,  90 }, 700 },  // fémur a 135°
  { { 90,  90,  45 }, 700 },  // tibia a 45°
  { { 90,  90, 135 }, 700 },  // tibia a 135°
  { { 90,  90,  90 }, 700 },  // neutro
};

const PuntoGesto* gestoPuntos = nullptr;
int   gestoNum    = 0;
int   gestoIdx    = 0;
unsigned long gestoInicioMs = 0;
bool  gestoActivo = false;

// ============================================================================
//  Helpers
// ============================================================================

// Fija el objetivo recortando a los límites de seguridad de cada servo.
void fijarObjetivo(float c, float f, float t) {
  const float vals[3] = { c, f, t };
  for (int i = 0; i < 3; i++) {
    if (isnan(vals[i])) continue;          // no tocar servos no especificados
    if (vals[i] < LIM_MIN[i] || vals[i] > LIM_MAX[i]) {
      Serial.print(F("WARN servo "));
      Serial.print(i);
      Serial.println(F(" fuera de límites → recortado"));
    }
    angObjetivo[i] = constrain(vals[i], LIM_MIN[i], LIM_MAX[i]);
  }
}

// Extrae el número que sigue a una clave dentro de un JSON simple
// (ej: {"coxa":90,...}). Devuelve NAN si la clave no existe.
float extraerJSON(const String& s, const char* clave) {
  int i = s.indexOf(clave);
  if (i < 0) return NAN;
  i += strlen(clave);
  // saltar '"' ':' y espacios
  while (i < (int)s.length() && (s[i] == '"' || s[i] == ':' || s[i] == ' ')) i++;
  return s.substring(i).toFloat();
}

void enviarEstado() {
  Serial.print(F("POS,"));
  Serial.print(angActual[0], 1); Serial.print(',');
  Serial.print(angActual[1], 1); Serial.print(',');
  Serial.print(angActual[2], 1); Serial.println();
}

void enviarAyuda() {
  Serial.println(F("AYUDA: A,c,f,t | {\"coxa\":..,\"femur\":..,\"tibia\":..} | G,saludar|estirar|punito | N | V,grados_seg | ?"));
}

// ============================================================================
//  Gestos (modo dinámico)
// ============================================================================

void iniciarGesto(const String& nombre) {
  const PuntoGesto* pts = nullptr;
  int n = 0;

  if (nombre == "saludar") {
    pts = GESTO_SALUDAR; n = sizeof(GESTO_SALUDAR) / sizeof(GESTO_SALUDAR[0]);
  } else if (nombre == "estirar") {
    pts = GESTO_ESTIRAR; n = sizeof(GESTO_ESTIRAR) / sizeof(GESTO_ESTIRAR[0]);
  } else if (nombre == "punito") {
    pts = GESTO_PUNITO;  n = sizeof(GESTO_PUNITO) / sizeof(GESTO_PUNITO[0]);
  } else if (nombre == "test") {
    pts = GESTO_TEST;    n = sizeof(GESTO_TEST) / sizeof(GESTO_TEST[0]);
  } else {
    Serial.println(F("ERR gesto desconocido (usa: saludar | estirar | punito | test)"));
    return;
  }

  gestoPuntos    = pts;
  gestoNum       = n;
  gestoIdx       = 0;
  gestoActivo    = true;
  gestoInicioMs  = millis();
  fijarObjetivo(pts[0].ang[0], pts[0].ang[1], pts[0].ang[2]);
  Serial.print(F("OK G "));
  Serial.println(nombre);
}

// Avanza la secuencia del gesto cuando el waypoint se alcanza y cumple su tiempo.
void actualizarGesto() {
  if (!gestoActivo || !gestoPuntos) return;

  const PuntoGesto& p = gestoPuntos[gestoIdx];

  bool llegado = true;
  for (int i = 0; i < 3; i++) {
    if (fabs(angActual[i] - angObjetivo[i]) > 0.5f) llegado = false;
  }
  if (!llegado) return;

  if (millis() - gestoInicioMs < p.ms) return;  // permanencia en el waypoint

  gestoIdx++;
  if (gestoIdx >= gestoNum) {
    gestoActivo = false;
    gestoPuntos = nullptr;
    Serial.println(F("DONE gesto"));
    return;
  }
  gestoInicioMs = millis();
  const PuntoGesto& s = gestoPuntos[gestoIdx];
  fijarObjetivo(s.ang[0], s.ang[1], s.ang[2]);
}

// ============================================================================
//  Interpolación suave (velocidad angular constante)
// ============================================================================

void actualizarMovimiento() {
  unsigned long ahora = millis();
  if (ultimoTick == 0) { ultimoTick = ahora; return; }  // 1ª pasada: calibrar reloj
  if (ahora - ultimoTick < TICK_MS) return;
  float dt = (ahora - ultimoTick) / 1000.0f;
  ultimoTick = ahora;

  float pasoMax = velocidadDegS * dt;  // grados que puede avanzar cada servo

  for (int i = 0; i < 3; i++) {
    float dif = angObjetivo[i] - angActual[i];
    if (fabs(dif) < 0.05f) continue;                    // ya llegó
    angActual[i] += constrain(dif, -pasoMax, pasoMax);  // paso limitado
    servo[i].write((int)lround(angActual[i]));
  }
}

// ============================================================================
//  Comandos seriales
// ============================================================================

String lineaSerial = "";

void ejecutarComando(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  // ¿Consulta de estado?
  if (cmd == "?") { enviarEstado(); return; }
  if (cmd == "H") { enviarAyuda(); return; }

  // ¿Test de servos individual (diagnóstico de pines)?
  if (cmd == "T") { iniciarGesto("test"); return; }

  // ¿Posición neutra?
  if (cmd == "N") {
    gestoActivo = false;
    gestoPuntos = nullptr;
    fijarObjetivo(NEUTRO[0], NEUTRO[1], NEUTRO[2]);
    Serial.println(F("OK N"));
    return;
  }

  // ¿Cambio de velocidad de interpolación?
  if (cmd.startsWith("V,")) {
    float v = cmd.substring(2).toFloat();
    if (v > 0) {
      velocidadDegS = constrain(v, 5.0f, 600.0f);
      Serial.print(F("OK V "));
      Serial.println(velocidadDegS, 0);
    } else {
      Serial.println(F("ERR velocidad inválida (V,grados_por_segundo)"));
    }
    return;
  }

  // ¿Gesto (modo dinámico)?
  if (cmd.startsWith("G,")) {
    String nombre = cmd.substring(2);
    nombre.trim();
    nombre.toLowerCase();
    iniciarGesto(nombre);
    return;
  }

  // ¿Ángulos estáticos JSON: {"coxa":90,"femur":45,"tibia":120}"?
  // (Debe ir ANTES del CSV: un JSON con comas lo capturaría el CSV)
  if (cmd.startsWith("{")) {
    float c = extraerJSON(cmd, "coxa");
    float f = extraerJSON(cmd, "femur");
    float t = extraerJSON(cmd, "tibia");
    if (!isnan(c) && !isnan(f) && !isnan(t)) {
      gestoActivo = false;
      gestoPuntos = nullptr;
      fijarObjetivo(c, f, t);
      Serial.println(F("OK JSON"));
    } else {
      Serial.println(F("ERR JSON: usa {\"coxa\":90,\"femur\":45,\"tibia\":120}"));
    }
    return;
  }

  // ¿Ángulos estáticos CSV: "A,90,45,120" o directo "90,45,120"?
  // Parseo manual con indexOf/substring: sscanf con %f NO es fiable en AVR
  // (avr-libc no enlaza el soporte de floats en scanf por defecto), por eso
  // el firmware motorhexapod.ino (sin sscanf) sí funciona y este no.
  {
    String angLine = cmd;
    if (angLine.startsWith("A,")) angLine = angLine.substring(2);  // quitar prefijo
    int c1 = angLine.indexOf(',');
    int c2 = angLine.indexOf(',', c1 + 1);
    if (c1 > 0 && c2 > c1 + 1) {
      float c = angLine.substring(0, c1).toFloat();
      float f = angLine.substring(c1 + 1, c2).toFloat();
      float t = angLine.substring(c2 + 1).toFloat();
      gestoActivo = false;
      gestoPuntos = nullptr;
      fijarObjetivo(c, f, t);
      Serial.print(F("OK A "));
      Serial.print(angObjetivo[0], 1); Serial.print(',');
      Serial.print(angObjetivo[1], 1); Serial.print(',');
      Serial.println(angObjetivo[2], 1);
    } else {
      Serial.println(F("ERR formato: <coxa>,<femur>,<tibia> (o A,<coxa>,<femur>,<tibia>)"));
    }
    return;
  }

  Serial.println(F("ERR comando desconocido (H = ayuda)"));
}

// ============================================================================
//  Setup / Loop
// ============================================================================

void setup() {
  Serial.begin(115200);
  while (!Serial) { /* Leonardo/Micro: esperar a que abra el puerto USB */ }

  servo[0].attach(PIN_COXA);
  servo[1].attach(PIN_FEMUR);
  servo[2].attach(PIN_TIBIA);

  // Empezar en neutro sin moverse (el servo debe estar ya montado en neutro)
  for (int i = 0; i < 3; i++) {
    angActual[i]   = NEUTRO[i];
    angObjetivo[i] = NEUTRO[i];
    servo[i].write((int)NEUTRO[i]);
  }

  pinMode(LED_BUILTIN, OUTPUT);

  Serial.println(F("READY pata_hexapodo 115200 (H = ayuda)"));
}

void loop() {
  // 1) Leer línea(s) del puerto serie
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineaSerial.length() > 0) ejecutarComando(lineaSerial);
      lineaSerial = "";
    } else if (lineaSerial.length() < 63) {
      lineaSerial += c;
    }
  }

  // 2) Interpolar servos hacia sus objetivos (suave)
  actualizarMovimiento();

  // 3) Avanzar la secuencia del gesto activo
  actualizarGesto();

  // 4) Latido del LED integrado (indica firmware vivo)
  if (millis() - ultimoLatido > 500) {
    ultimoLatido = millis();
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}

// ============================================================================
//  NOTAS
// ============================================================================
//  • PCA9685 (I2C): si prefieres un driver de 16 canales, sustituye Servo.h
//    por Adafruit_PWMServoDriver.h, inicialízalo con Wire en setup() y en
//    actualizarMovimiento() usa pwm.setPWM(i, 0, anguloAPulso(angActual[i])).
//    El resto del protocolo serial NO cambia.
//
//  • Montaje físico: los gestos embebidos suponen la convención del diagrama
//    IK 3DOF (neutro = 90/90/90). Si tu pata monta los servos al revés,
//    ajusta NEUTRO, LIM_MIN/LIM_MAX o añade un offset por servo.
//
//  • El auto-reset del Arduino (DTR) reinicia el firmware cada vez que se
//    abre el puerto; el script Python espera ~2 s tras conectar.
// ============================================================================
