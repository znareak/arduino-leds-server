#include <Servo.h>

Servo coxa, femur, tibia;

void setup() {
  Serial.begin(115200);
  
  // Asigna los pines de tus servos
  coxa.attach(9);
  femur.attach(10);
  tibia.attach(11);

  // Posición inicial (Home)
  coxa.write(90);
  femur.write(90);
  tibia.write(90);
}

void loop() {
  if (Serial.available() > 0) {
    // Lee la cadena hasta el salto de línea enviada por el Python
    String data = Serial.readStringUntil('\n');
    
    // Separa los ángulos por las comas
    int firstComma = data.indexOf(',');
    int secondComma = data.indexOf(',', firstComma + 1);
    
    // Si encuentra ambas comas, extrae los números
    if (firstComma > 0 && secondComma > 0) {
      int angleCoxa = data.substring(0, firstComma).toInt();
      int angleFemur = data.substring(firstComma + 1, secondComma).toInt();
      int angleTibia = data.substring(secondComma + 1).toInt();
      
      // Mueve los servos directamente, sin matemáticas raras en el Arduino
      coxa.write(angleCoxa);
      femur.write(angleFemur);
      tibia.write(angleTibia);
    }
  }
}