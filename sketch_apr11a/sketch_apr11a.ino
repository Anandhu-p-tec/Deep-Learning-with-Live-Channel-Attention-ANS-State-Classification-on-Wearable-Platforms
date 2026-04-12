#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <MPU6050.h>
#include "DHT.h"

#define GSR_PIN     34
#define BUZZER_PIN  25
#define DHT_PIN     4
#define DHT_TYPE    DHT11

MAX30105 particleSensor;
MPU6050 mpu(0x69);
DHT dht(DHT_PIN, DHT_TYPE);

float spo2      = 0;
float bpm       = 0;
float temp      = 36.5;
int   gsr       = 0;
float ax_g, ay_g, az_g;
float accel_mag = 0;
int   riskScore = 0;

uint32_t lastReportTime = 0;
uint32_t lastTempTime   = 0;

const byte RATE_SIZE = 4;
byte  rates[RATE_SIZE];
byte  rateSpot       = 0;
long  lastBeat       = 0;
float beatsPerMinute = 0;
int   beatAvg        = 0;

long irValue  = 0;
long redValue = 0;
bool fingerOn = false;

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Wire.begin(21, 22);
  Wire.setClock(400000);
  delay(300);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 FAIL");
  } else {
    Serial.println("MAX30105 OK");
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0xFF);
    particleSensor.setPulseAmplitudeIR(0xFF);
    particleSensor.setPulseAmplitudeGreen(0);
  }

  mpu.initialize();
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 FAIL");
  } else {
    Serial.println("MPU6050 OK");
  }

  dht.begin();
  Serial.println("DHT11 OK");
  Serial.println("BOOT_OK");
}

float estimateSpO2(long ir, long red) {
  if (ir < 100000) return 0;  // matches your sensor baseline
  float r   = ((float)red / (float)ir);
  float est = 104.0 - 17.0 * r;
  if (est > 100) est = 100;
  if (est < 90)  est = 90;
  return est;
}

int computeRisk() {
  int score = 0;
  if (spo2 > 0 && spo2 < 94)              score++;
  if (bpm > 110 || (bpm > 0 && bpm < 50)) score++;
  if (temp > 37.5)                         score++;
  if (gsr > 2000)                          score++;
  if (accel_mag > 2.0)                     score++;
  return score;
}

String getANSState(int risk) {
  if (risk == 0) return "NORMAL";
  if (risk == 1) return "MILD";
  if (risk == 2) return "SYMP_AROUSAL";
  if (risk == 3) return "PARA_SUPP";
  return "MIXED";
}

void loop() {

  irValue  = particleSensor.getIR();
  redValue = particleSensor.getRed();

  // YOUR sensor baseline is ~80k so threshold = 100k
  fingerOn = (irValue > 100000);

  if (fingerOn) {
    if (checkForBeat(irValue)) {
      long delta     = millis() - lastBeat;
      lastBeat       = millis();
      beatsPerMinute = 60 / (delta / 1000.0);

      if (beatsPerMinute > 20 && beatsPerMinute < 255) {
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;
        beatAvg = 0;
        for (byte x = 0; x < RATE_SIZE; x++)
          beatAvg += rates[x];
        beatAvg /= RATE_SIZE;
      }
    }
    bpm  = beatAvg;
    spo2 = estimateSpO2(irValue, redValue);
  } else {
    bpm      = 0;
    spo2     = 0;
    beatAvg  = 0;
    rateSpot = 0;
    for (byte x = 0; x < RATE_SIZE; x++) rates[x] = 0;
  }

  if (millis() - lastTempTime > 2000) {
    lastTempTime = millis();
    float t = dht.readTemperature();
    if (!isnan(t) && t > 20 && t < 45) temp = t;
  }

  if (millis() - lastReportTime > 100) {
    lastReportTime = millis();

    gsr = analogRead(GSR_PIN);

    int16_t ax, ay, az;
    mpu.getAcceleration(&ax, &ay, &az);
    ax_g      = ax / 16384.0;
    ay_g      = ay / 16384.0;
    az_g      = az / 16384.0;
    accel_mag = sqrt(ax_g*ax_g + ay_g*ay_g + az_g*az_g);

    riskScore    = computeRisk();
    String state = getANSState(riskScore);

    if (riskScore >= 3) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(100);
      digitalWrite(BUZZER_PIN, LOW);
    }

    Serial.print("GSR:");    Serial.print(gsr);
    Serial.print(",SPO2:");  Serial.print(spo2, 2);
    Serial.print(",TEMP:");  Serial.print(temp, 2);
    Serial.print(",AX:");    Serial.print(ax_g, 2);
    Serial.print(",AY:");    Serial.print(ay_g, 2);
    Serial.print(",AZ:");    Serial.print(az_g, 2);
    Serial.print(",BPM:");   Serial.print(bpm, 2);
    Serial.print(",RISK:");  Serial.print(riskScore);
    Serial.print(",STATE:"); Serial.println(state);
  }
}
