// Minimal ESP32 firmware to stream ANS sensor lines in the format
// expected by serial_reader/esp32_reader.py.

#include <Arduino.h>

static const int GSR_PIN = 34;
static unsigned long lastSendMs = 0;

float readSpo2Mock() {
  // Replace with actual SpO2 sensor reading.
  return 97.0 + (random(-20, 20) / 10.0);
}

float readTempMock() {
  // Replace with actual temperature sensor reading.
  return 36.3 + (random(-15, 15) / 10.0);
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  randomSeed(esp_random());
}

void loop() {
  // 20 Hz output to match app expectations.
  if (millis() - lastSendMs < 50) {
    return;
  }
  lastSendMs = millis();

  int gsr = analogRead(GSR_PIN);
  float spo2 = readSpo2Mock();
  float temp = readTempMock();

  // Mock accelerometer values (replace with real IMU readings).
  float ax = random(-200, 200) / 100.0;
  float ay = random(-200, 200) / 100.0;
  float az = 9.8 + (random(-100, 100) / 100.0);

  Serial.print("GSR:"); Serial.print(gsr);
  Serial.print(",SPO2:"); Serial.print(spo2, 1);
  Serial.print(",TEMP:"); Serial.print(temp, 1);
  Serial.print(",AX:"); Serial.print(ax, 2);
  Serial.print(",AY:"); Serial.print(ay, 2);
  Serial.print(",AZ:"); Serial.println(az, 2);
}
