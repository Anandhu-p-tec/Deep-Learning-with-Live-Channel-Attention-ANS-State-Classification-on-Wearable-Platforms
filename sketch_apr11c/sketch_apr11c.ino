#include <Wire.h>
#include "MAX30105.h"

MAX30105 particleSensor;

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  delay(300);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 NOT FOUND");
    while(1);
  }
  Serial.println("MAX30105 FOUND - place finger");
  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0xFF);
  particleSensor.setPulseAmplitudeIR(0xFF);
  particleSensor.setPulseAmplitudeGreen(0);
}

void loop() {
  long ir = particleSensor.getIR();
  Serial.println(ir);
  delay(100);
}
