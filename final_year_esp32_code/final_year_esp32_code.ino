#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <MPU6050.h>
#include "DHT.h"

// ═══════════════════════════════════════════════
//  PIN DEFINITIONS
// ═══════════════════════════════════════════════
#define GSR_PIN     34   // GSR sensor
#define BUZZER_PIN  25   // Buzzer
#define DHT_PIN      4   // DHT11
#define DHT_TYPE    DHT11
#define ECG_PIN     33   // AD8232 OUTPUT
#define LO_PLUS     32   // AD8232 LO+
// AD8232 LO-  → GND
// AD8232 VCC  → 3.3V
// AD8232 GND  → GND
// AD8232 SDN  → 3.3V

// ═══════════════════════════════════════════════
//  SENSOR OBJECTS
// ═══════════════════════════════════════════════
MAX30105 particleSensor;
MPU6050  mpu(0x69);
DHT      dht(DHT_PIN, DHT_TYPE);

// ═══════════════════════════════════════════════
//  MAX30105 — SPO2 + BPM
// ═══════════════════════════════════════════════
const byte RATE_SIZE   = 4;
byte  rates[RATE_SIZE] = {0};
byte  rateSpot         = 0;
long  lastBeat         = 0;
float beatsPerMinute   = 0;
int   beatAvg          = 0;
long  irValue          = 0;
long  redValue         = 0;
bool  fingerOn         = false;
float spo2             = 0;
float bpm              = 0;

// ═══════════════════════════════════════════════
//  AD8232 ECG — Smart filtered
// ═══════════════════════════════════════════════
int   ecgBuffer[20]    = {0};
int   bufIndex         = 0;
int   lastValidECG     = 1500;
int   ecgRaw           = 0;
int   ecgSmoothed      = 0;
int   ecgHR            = 0;
long  lastPeakTime     = 0;
bool  abovePeak        = false;
int   dynamicPeak      = 1500;
int   dynamicMin       = 1500;
long  lastThreshUpdate = 0;
int   hrECGBuffer[5]   = {0};
int   hrECGIndex       = 0;

const byte GSR_SMOOTH = 8;
int gsrBuffer[8] = {1000,1000,1000,1000,1000,1000,1000,1000};
byte gsrIdx = 0;
int gsrSmoothed = 1000;

// ═══════════════════════════════════════════════
//  OTHER SENSORS
// ═══════════════════════════════════════════════
float temp      = 36.5;
int   gsr       = 0;
float ax_g      = 0, ay_g = 0, az_g = 0;
float accel_mag = 0;
int   riskScore = 0;

// ═══════════════════════════════════════════════
//  TIMING
// ═══════════════════════════════════════════════
uint32_t lastReportTime = 0;
uint32_t lastTempTime   = 0;

// ═══════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  pinMode(LO_PLUS, INPUT);

  Wire.begin(21, 22);
  Wire.setClock(400000);
  delay(300);

  // MAX30105
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30105 FAIL");
  } else {
    Serial.println("MAX30105 OK");
    particleSensor.setup();
    particleSensor.setPulseAmplitudeRed(0xFF);
    particleSensor.setPulseAmplitudeIR(0xFF);
    particleSensor.setPulseAmplitudeGreen(0);
  }

  // MPU6050
  mpu.initialize();
  if (!mpu.testConnection()) {
    Serial.println("MPU6050 FAIL");
  } else {
    Serial.println("MPU6050 OK");
  }

  // DHT11
  dht.begin();
  Serial.println("DHT11 OK");
  Serial.println("AD8232 OK");
  Serial.println("BOOT_OK");
}

// ═══════════════════════════════════════════════
//  SPO2 ESTIMATE
// ═══════════════════════════════════════════════
float estimateSpO2(long ir, long red) {
  if (ir < 100000) return 0;
  float r   = (float)red / (float)ir;
  float est = 104.0 - 17.0 * r;
  if (est > 100) est = 100;
  if (est < 90)  est = 90;
  return est;
}

// ═══════════════════════════════════════════════
//  ECG — FILTER LOOSE WIRE + NOISE
// ═══════════════════════════════════════════════
int getFilteredECG() {
  int raw = analogRead(ECG_PIN);
  if (raw < 100)                      return lastValidECG;
  if (abs(raw - lastValidECG) > 1500) return lastValidECG;
  lastValidECG = raw;
  return raw;
}

// ═══════════════════════════════════════════════
//  ECG — ROLLING AVERAGE SMOOTHING
// ═══════════════════════════════════════════════
int getSmoothedECG() {
  ecgBuffer[bufIndex] = getFilteredECG();
  bufIndex = (bufIndex + 1) % 20;
  long sum = 0;
  for (int i = 0; i < 20; i++) sum += ecgBuffer[i];
  return sum / 20;
}

// ═══════════════════════════════════════════════
//  ECG — AUTO THRESHOLD UPDATE
// ═══════════════════════════════════════════════
void updateDynamicThreshold(int val) {
  if (val > dynamicPeak) dynamicPeak = val;
  if (val < dynamicMin)  dynamicMin  = val;
  if (millis() - lastThreshUpdate > 2000) {
    lastThreshUpdate = millis();
    dynamicPeak = dynamicPeak * 0.85 + lastValidECG * 0.15;
    dynamicMin  = dynamicMin  * 0.85 + lastValidECG * 0.15;
  }
}

// ═══════════════════════════════════════════════
//  ECG — SMART BEAT DETECTION
// ═══════════════════════════════════════════════
int detectECGHeartRate(int smoothed) {
  updateDynamicThreshold(smoothed);

  int range     = dynamicPeak - dynamicMin;
  int threshold = dynamicMin + (int)(range * 0.7);

  if (range < 50) return ecgHR;

  if (smoothed > threshold && !abovePeak) {
    abovePeak     = true;
    long now      = millis();
    long interval = now - lastPeakTime;
    lastPeakTime  = now;

    if (interval > 300 && interval < 1500) {
      int newHR = (int)(60000.0 / interval);
      hrECGBuffer[hrECGIndex] = newHR;
      hrECGIndex = (hrECGIndex + 1) % 5;
      int sum = 0, count = 0;
      for (int i = 0; i < 5; i++) {
        if (hrECGBuffer[i] > 0) {
          sum += hrECGBuffer[i];
          count++;
        }
      }
      if (count > 0) ecgHR = sum / count;
    }
  } else if (smoothed <= threshold) {
    abovePeak = false;
  }
  return ecgHR;
}

// ═══════════════════════════════════════════════
//  RISK SCORE
// ═══════════════════════════════════════════════
int computeRisk() {
  int score = 0;
  // Use MAX30105 BPM if finger on, else ECG HR
  float activeHR = (bpm > 0) ? bpm : (float)ecgHR;

  if (spo2 > 0 && spo2 < 90)                            score++;
  if (activeHR > 110 || (activeHR > 0 && activeHR < 50)) score++;
  if (temp > 37.5)                                       score++;
  if (gsr > 2000)                                        score++;
  if (accel_mag > 2.0)                                   score++;
  return score;
}

// ═══════════════════════════════════════════════
//  ANS STATE
// ═══════════════════════════════════════════════
String getANSState(int risk) {
  if (risk == 0) return "NORMAL";
  if (risk == 1) return "MILD";
  if (risk == 2) return "SYMP_AROUSAL";
  if (risk == 3) return "PARA_SUPP";
  return "MIXED";
}

// ═══════════════════════════════════════════════
//  MAIN LOOP
// ═══════════════════════════════════════════════
void loop() {

  // ── MAX30105 reads every loop cycle ──────────
  irValue  = particleSensor.getIR();
  redValue = particleSensor.getRed();
  fingerOn = (irValue > 100000);

  if (fingerOn) {
    if (checkForBeat(irValue)) {
      long delta = millis() - lastBeat;
      lastBeat   = millis();
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

  // ── DHT11 every 2 seconds ────────────────────
  if (millis() - lastTempTime > 2000) {
    lastTempTime = millis();
    float t = dht.readTemperature();
    if (!isnan(t) && t > 20 && t < 45) temp = t;
  }

  // ── 100ms report cycle ───────────────────────
  if (millis() - lastReportTime > 100) {
    lastReportTime = millis();

    // GSR with smoothing / dropout rejection
    int gsrRaw = analogRead(GSR_PIN);
    if (gsrRaw > 50) {
      gsrBuffer[gsrIdx] = gsrRaw;
      gsrIdx = (gsrIdx + 1) % GSR_SMOOTH;
      long sum = 0;
      for (byte i = 0; i < GSR_SMOOTH; i++) {
        sum += gsrBuffer[i];
      }
      gsrSmoothed = sum / GSR_SMOOTH;
    }
    gsr = gsrSmoothed;

    // MPU6050
    int16_t ax, ay, az;
    mpu.getAcceleration(&ax, &ay, &az);
    ax_g      = ax / 16384.0;
    ay_g      = ay / 16384.0;
    az_g      = az / 16384.0;
    accel_mag = sqrt(ax_g*ax_g + ay_g*ay_g + az_g*az_g);

    // ECG smart read
    ecgSmoothed = getSmoothedECG();
    ecgRaw      = lastValidECG;
    ecgHR       = detectECGHeartRate(ecgSmoothed);

    // Risk and ANS state
    riskScore    = computeRisk();
    String state = getANSState(riskScore);

    // Buzzer alert
    if (riskScore >= 3) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(100);
      digitalWrite(BUZZER_PIN, LOW);
    }

    // ── Serial output for Streamlit ──────────
    Serial.print("GSR:");     Serial.print(gsr);
    Serial.print(",SPO2:");   Serial.print(spo2,       2);
    Serial.print(",TEMP:");   Serial.print(temp,       2);
    Serial.print(",AX:");     Serial.print(ax_g,       2);
    Serial.print(",AY:");     Serial.print(ay_g,       2);
    Serial.print(",AZ:");     Serial.print(az_g,       2);
    Serial.print(",BPM:");    Serial.print(bpm,        2);
    Serial.print(",RISK:");   Serial.print(riskScore);
    Serial.print(",STATE:");  Serial.print(state);
    Serial.print(",ECG:");    Serial.print(ecgSmoothed);
    Serial.print(",ECG_HR:"); Serial.print(ecgHR);
    Serial.print(",LO:");     Serial.println(digitalRead(LO_PLUS));
  }
}
