#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Keypad.h>
#include <DHT.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// ======================================================
// DAIRYSYNC WIFI / DJANGO SETTINGS
// ======================================================
// Replace these values locally before uploading.
// Do not commit real passwords or API keys to GitHub.
const char* WIFI_SSID = "Foxx";
const char* WIFI_PASSWORD = "@jamie.?1F.048#";

// Use your computer/server LAN IP, not 127.0.0.1.
const char* SENSOR_API_URL =
  "http://192.168.210.21:8000/api/sensor-data/";

const char* DISPENSE_API_URL =
  "http://192.168.210.21:8000/api/dispense/";

const char* ESP32_API_KEY = "YOUR_NEW_ESP32_API_KEY";
const char* FRIDGE_CODE = "F001";

const float SUPPLY_VOLTAGE = 5.0;

const unsigned long SENSOR_UPLOAD_INTERVAL = 30000UL;
const unsigned long WIFI_RETRY_INTERVAL = 10000UL;
const unsigned long API_RETRY_INTERVAL = 15000UL;

// Set true while debugging WiFi. Set false after WiFi is stable.
const bool SCAN_WIFI_ON_BOOT = true;

unsigned long lastWiFiAttempt = 0;
unsigned long lastApiAttempt = 0;

bool djangoOnline = false;

bool wifiAttemptInProgress = false;
unsigned long wifiAttemptStartedAt = 0;
const unsigned long WIFI_CONNECT_TIMEOUT = 30000UL;

// Store one failed dispense update for automatic retry.
int pendingDispenseSlot = 0;
unsigned long lastPendingDispenseAttempt = 0;
const unsigned long DISPENSE_RETRY_INTERVAL = 10000UL;

// ======================================================
// LCD
// ======================================================

#define LCD_SDA_PIN 8
#define LCD_SCL_PIN 9

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ======================================================
// RFID RC522
// ======================================================

#define RFID_SS_PIN   10
#define RFID_RST_PIN  14
#define RFID_SCK_PIN  12
#define RFID_MISO_PIN 13
#define RFID_MOSI_PIN 11

MFRC522 mfrc522(RFID_SS_PIN, RFID_RST_PIN);

bool rfidAvailable = false;

// ======================================================
// DHT11 TEMPERATURE SENSOR
// ======================================================

#define DHT_PIN  2
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);

float currentTemperature = NAN;
float currentHumidity = NAN;

unsigned long lastTemperatureRead = 0;
const unsigned long TEMPERATURE_READ_INTERVAL = 2500UL;

const bool ENABLE_HIGH_TEMPERATURE_PROTECTION = true;
const float MAX_ALLOWED_TEMPERATURE = 45.0f;

// ======================================================
// FAST HC-SR04 ULTRASONIC SENSOR
// ======================================================

#define TRIG_PIN 38
#define ECHO_PIN 39

const float MIN_PRODUCT_DISTANCE_CM = 1.5f;
const float MAX_PRODUCT_DISTANCE_CM = 18.0f;

// A large change stops the servo after one reading.
const float STRONG_DISTANCE_CHANGE_CM = 3.5f;

// A smaller change requires two readings.
const float NORMAL_DISTANCE_CHANGE_CM = 1.5f;
const int NORMAL_REQUIRED_DETECTIONS = 2;

// Fast polling.
const unsigned long ULTRASONIC_READ_INTERVAL = 18UL;
const unsigned long ULTRASONIC_TIMEOUT_US = 2500UL;

// Safety timeout.
const unsigned long MAX_DISPENSE_TIME = 7000UL;

// Start checking immediately after servo movement begins.
const unsigned long MIN_SERVO_RUN_TIME = 0UL;

float baselineDistanceCm = -1.0f;

// ======================================================
// OUTPUTS
// ======================================================

#define BUZZER_PIN 40
#define GREEN_LED  41
#define RED_LED    42

// ======================================================
// CONTINUOUS-ROTATION SERVOS
// ======================================================

const uint8_t servoPins[6] = {
  4, 5, 6, 7, 15, 16
};

const int TOTAL_SERVOS = 6;

const uint32_t SERVO_FREQUENCY = 50;
const uint8_t SERVO_RESOLUTION = 10;
const uint32_t SERVO_MAX_DUTY = 1023;

// Calibrate each neutral value in steps of 5 if necessary.
int servoStopPulse[6] = {
  1500, 1500, 1500, 1500, 1500, 1500
};

// Very slow speed. Raise an individual value to 18–22
// if that servo cannot move its spiral under load.
int servoSpeedPercent[6] = {
  15, 15, 15, 15, 15, 15
};

// 1 = forward; -1 = reverse.
int servoDirection[6] = {
  1, 1, 1, 1, 1, 1
};

const int MIN_SPEED_OFFSET_US = 15;
const int MAX_SPEED_OFFSET_US = 220;

// ======================================================
// KEYPAD
// ======================================================

const byte ROWS = 4;
const byte COLS = 4;

char keys[ROWS][COLS] = {
  {'1', '2', '3', 'A'},
  {'4', '5', '6', 'B'},
  {'7', '8', '9', 'C'},
  {'*', '0', '#', 'D'}
};

byte rowPins[ROWS] = {21, 35, 36, 37};
byte colPins[COLS] = {17, 18, 19, 20};

Keypad keypad = Keypad(
  makeKeymap(keys),
  rowPins,
  colPins,
  ROWS,
  COLS
);

// ======================================================
// AUTHORIZED RFID CARDS
// ======================================================

String authorizedCards[] = {
  "73723CE4",
  "12345678",
  "9ABCDEF0"
};

const int totalCards =
  sizeof(authorizedCards) / sizeof(authorizedCards[0]);

// ======================================================
// SYSTEM STATE
// ======================================================

enum State {
  WAIT_PRODUCT,
  WAIT_CONFIRM,
  WAIT_RFID,
  DISPENSING
};

State state = WAIT_PRODUCT;

char selectedProduct = 0;

String lastUID = "";
unsigned long lastUIDTime = 0;

const unsigned long DUPLICATE_CARD_DELAY = 2000UL;

// ======================================================
// WIFI / DJANGO COMMUNICATION
// ======================================================

String jsonEscape(const String &value) {
  String escaped = value;
  escaped.replace("\\", "\\\\");
  escaped.replace("\"", "\\\"");
  escaped.replace("\n", "\\n");
  escaped.replace("\r", "\\r");
  return escaped;
}


void scanWiFiNetworks() {
  Serial.println();
  Serial.println("Scanning WiFi networks...");

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(false, false);
  delay(500);

  int networkCount = WiFi.scanNetworks();

  if (networkCount <= 0) {
    Serial.println("No WiFi networks found.");
    return;
  }

  for (int i = 0; i < networkCount; i++) {
    Serial.print(i + 1);
    Serial.print(". ");
    Serial.print(WiFi.SSID(i));
    Serial.print(" | Signal: ");
    Serial.print(WiFi.RSSI(i));
    Serial.print(" dBm | Channel: ");
    Serial.print(WiFi.channel(i));
    Serial.print(" | Encryption: ");
    Serial.println(WiFi.encryptionType(i));
  }

  WiFi.scanDelete();
}

const char* wifiStatusText(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:
      return "Idle";
    case WL_NO_SSID_AVAIL:
      return "SSID not found";
    case WL_SCAN_COMPLETED:
      return "Scan completed";
    case WL_CONNECTED:
      return "Connected";
    case WL_CONNECT_FAILED:
      return "Connection failed";
    case WL_CONNECTION_LOST:
      return "Connection lost";
    case WL_DISCONNECTED:
      return "Disconnected";
    default:
      return "Unknown";
  }
}

void startWiFiAttempt(bool forceAttempt = false) {
  wl_status_t currentStatus = WiFi.status();

  if (currentStatus == WL_CONNECTED) {
    wifiAttemptInProgress = false;
    return;
  }

  if (wifiAttemptInProgress) {
    return;
  }

  if (
    !forceAttempt &&
    lastWiFiAttempt != 0 &&
    millis() - lastWiFiAttempt < WIFI_RETRY_INTERVAL
  ) {
    return;
  }

  lastWiFiAttempt = millis();
  wifiAttemptStartedAt = millis();
  wifiAttemptInProgress = true;
  djangoOnline = false;

  Serial.println();
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  WiFi.setSleep(false);

  // Stop any previous unfinished connection attempt before setting new config.
  WiFi.disconnect(true, true);
  delay(1200);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void serviceWiFiConnection() {
  wl_status_t status = WiFi.status();

  if (status == WL_CONNECTED) {
    if (wifiAttemptInProgress) {
      wifiAttemptInProgress = false;

      Serial.println();
      Serial.println("WiFi connected successfully.");

      Serial.print("ESP32 IP: ");
      Serial.println(WiFi.localIP());

      Serial.print("Gateway: ");
      Serial.println(WiFi.gatewayIP());

      Serial.print("Signal strength: ");
      Serial.print(WiFi.RSSI());
      Serial.println(" dBm");

      // Force the first API upload immediately.
      lastApiAttempt = 0;
    }

    return;
  }

  if (!wifiAttemptInProgress) {
    startWiFiAttempt(false);
    return;
  }

  if (millis() - wifiAttemptStartedAt < WIFI_CONNECT_TIMEOUT) {
    static unsigned long lastDotAt = 0;

    if (millis() - lastDotAt >= 500UL) {
      lastDotAt = millis();
      Serial.print(".");
    }

    return;
  }

  wifiAttemptInProgress = false;
  lastWiFiAttempt = millis();  // Start retry interval from the timeout moment.

  Serial.println();
  Serial.println("WiFi connection attempt timed out.");

  Serial.print("WiFi status: ");
  Serial.print(static_cast<int>(status));
  Serial.print(" (");
  Serial.print(wifiStatusText(status));
  Serial.println(")");

  // Fully stop the failed STA attempt before the next retry.
  // This prevents: wifi:sta is connecting, cannot set config
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(true, true);
  delay(1200);
  WiFi.setAutoReconnect(true);

  Serial.println(
    "WiFi driver reset. Will retry after retry interval. Check password, WPA2 2.4 GHz, signal, and hotspot device limit."
  );
}

bool waitForInitialWiFiConnection() {
  startWiFiAttempt(true);

  while (
    wifiAttemptInProgress &&
    WiFi.status() != WL_CONNECTED
  ) {
    serviceWiFiConnection();
    delay(20);
  }

  return WiFi.status() == WL_CONNECTED;
}

bool beginHttpClient(
  HTTPClient &http,
  WiFiClient &plainClient,
  WiFiClientSecure &secureClient,
  const String &url
) {
  if (url.startsWith("https://")) {
    // For production, replace setInsecure() with a trusted CA.
    secureClient.setInsecure();
    return http.begin(secureClient, url);
  }

  return http.begin(plainClient, url);
}

bool postJsonToDjango(
  const String &url,
  const String &payload,
  const char* label
) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.print(label);
    Serial.println(": WiFi unavailable.");
    return false;
  }

  HTTPClient http;
  WiFiClient plainClient;
  WiFiClientSecure secureClient;

  if (!beginHttpClient(http, plainClient, secureClient, url)) {
    Serial.print(label);
    Serial.println(": HTTP client failed to start.");
    return false;
  }

  http.setConnectTimeout(5000);
  http.setTimeout(7000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Api-Key", ESP32_API_KEY);

  int statusCode = http.POST(payload);

  String response;
  if (statusCode > 0) {
    response = http.getString();
  } else {
    response = http.errorToString(statusCode);
  }

  http.end();

  Serial.print(label);
  Serial.print(" HTTP status: ");
  Serial.println(statusCode);

  if (response.length() > 0) {
    Serial.println(response);
  }

  return statusCode >= 200 && statusCode < 300;
}

bool sendSensorDataToDjango() {
  if (isnan(currentTemperature) || isnan(currentHumidity)) {
    Serial.println("Sensor upload skipped: DHT11 data unavailable.");
    return false;
  }

  String payload = "{";
  payload += "\"fridge_code\":\"";
  payload += jsonEscape(String(FRIDGE_CODE));
  payload += "\",";
  payload += "\"temperature\":";
  payload += String(currentTemperature, 1);
  payload += ",";
  payload += "\"humidity\":";
  payload += String(currentHumidity, 1);
  payload += ",";
  payload += "\"voltage\":";
  payload += String(SUPPLY_VOLTAGE, 1);
  payload += ",";
  payload += "\"door_open\":false,";
  payload += "\"stock\":[]";
  payload += "}";

  return postJsonToDjango(
    String(SENSOR_API_URL),
    payload,
    "Sensor API"
  );
}

bool sendDispenseToDjango(int slotNumber) {
  String payload = "{";
  payload += "\"fridge_code\":\"";
  payload += jsonEscape(String(FRIDGE_CODE));
  payload += "\",";
  payload += "\"slot_number\":";
  payload += String(slotNumber);
  payload += ",";
  payload += "\"quantity\":1,";
  payload += "\"product_detected\":true";
  payload += "}";

  return postJsonToDjango(
    String(DISPENSE_API_URL),
    payload,
    "Dispense API"
  );
}

void retryPendingDispenseUpdate() {
  if (pendingDispenseSlot <= 0) {
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  if (
    millis() - lastPendingDispenseAttempt <
    DISPENSE_RETRY_INTERVAL
  ) {
    return;
  }

  lastPendingDispenseAttempt = millis();

  Serial.print("Retrying Django stock update for slot ");
  Serial.println(pendingDispenseSlot);

  if (sendDispenseToDjango(pendingDispenseSlot)) {
    Serial.println("Pending stock update completed.");
    pendingDispenseSlot = 0;
  }
}

void maintainCloudConnection() {
  serviceWiFiConnection();

  if (WiFi.status() != WL_CONNECTED) {
    djangoOnline = false;
    return;
  }

  retryPendingDispenseUpdate();

  unsigned long interval =
    djangoOnline ? SENSOR_UPLOAD_INTERVAL : API_RETRY_INTERVAL;

  if (
    lastApiAttempt != 0 &&
    millis() - lastApiAttempt < interval
  ) {
    return;
  }

  lastApiAttempt = millis();

  djangoOnline = sendSensorDataToDjango();

  if (djangoOnline) {
    Serial.print("DAIRYSYNC online. ESP32 IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(
      "Django API unavailable; local vending remains operational."
    );
  }
}

// ======================================================
// SERVO PWM
// ======================================================

uint32_t microsecondsToDuty(uint32_t pulseWidthUs) {
  const uint32_t periodUs =
    1000000UL / SERVO_FREQUENCY;

  return (
    pulseWidthUs * SERVO_MAX_DUTY
  ) / periodUs;
}

int calculateServoPulse(
  int index,
  int speedPercent
) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return 1500;
  }

  speedPercent = constrain(speedPercent, 0, 100);

  if (speedPercent == 0) {
    return servoStopPulse[index];
  }

  int speedOffset = map(
    speedPercent,
    1,
    100,
    MIN_SPEED_OFFSET_US,
    MAX_SPEED_OFFSET_US
  );

  int pulse =
    servoStopPulse[index] +
    servoDirection[index] * speedOffset;

  return constrain(pulse, 1200, 1800);
}

void disableServoSignal(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return;
  }

  uint8_t pin = servoPins[index];

  ledcDetach(pin);
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
}

void disableAllServos() {
  for (int i = 0; i < TOTAL_SERVOS; i++) {
    pinMode(servoPins[i], OUTPUT);
    digitalWrite(servoPins[i], LOW);
  }
}

void stopServo(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return;
  }

  ledcWrite(
    servoPins[index],
    microsecondsToDuty(servoStopPulse[index])
  );
}

bool attachSelectedServo(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return false;
  }

  bool attached = ledcAttach(
    servoPins[index],
    SERVO_FREQUENCY,
    SERVO_RESOLUTION
  );

  if (!attached) {
    Serial.print("Could not attach servo ");
    Serial.println(index + 1);
    return false;
  }

  stopServo(index);
  delay(40);

  return true;
}

void runServoAtConfiguredSpeed(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return;
  }

  int pulse = calculateServoPulse(
    index,
    servoSpeedPercent[index]
  );

  ledcWrite(
    servoPins[index],
    microsecondsToDuty(pulse)
  );

  Serial.print("Servo ");
  Serial.print(index + 1);
  Serial.print(" running at ");
  Serial.print(servoSpeedPercent[index]);
  Serial.print("%, pulse ");
  Serial.print(pulse);
  Serial.println(" us");
}

// ======================================================
// FAST ULTRASONIC SENSOR
// ======================================================

float readDistanceFastCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);

  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration = pulseIn(
    ECHO_PIN,
    HIGH,
    ULTRASONIC_TIMEOUT_US
  );

  if (duration == 0) {
    return -1.0f;
  }

  float distance =
    duration * 0.0343f / 2.0f;

  if (distance < 1.0f || distance > 45.0f) {
    return -1.0f;
  }

  return distance;
}

void sortThreeValues(float values[3]) {
  if (values[0] > values[1]) {
    float temp = values[0];
    values[0] = values[1];
    values[1] = temp;
  }

  if (values[1] > values[2]) {
    float temp = values[1];
    values[1] = values[2];
    values[2] = temp;
  }

  if (values[0] > values[1]) {
    float temp = values[0];
    values[0] = values[1];
    values[1] = temp;
  }
}

float captureFastBaseline() {
  float values[3];
  int validCount = 0;

  for (int i = 0; i < 3; i++) {
    float distance = readDistanceFastCm();

    if (distance > 0) {
      values[validCount] = distance;
      validCount++;
    }

    delay(18);
  }

  if (validCount == 0) {
    return -1.0f;
  }

  if (validCount == 1) {
    return values[0];
  }

  if (validCount == 2) {
    return (values[0] + values[1]) / 2.0f;
  }

  sortThreeValues(values);
  return values[1];
}

bool distanceInsideDetectionArea(float distance) {
  return (
    distance >= MIN_PRODUCT_DISTANCE_CM &&
    distance <= MAX_PRODUCT_DISTANCE_CM
  );
}

bool strongProductDetection(float distance) {
  if (!distanceInsideDetectionArea(distance)) {
    return false;
  }

  if (baselineDistanceCm < 0) {
    return false;
  }

  return (
    baselineDistanceCm - distance >=
    STRONG_DISTANCE_CHANGE_CM
  );
}

bool normalProductDetection(float distance) {
  if (!distanceInsideDetectionArea(distance)) {
    return false;
  }

  if (baselineDistanceCm < 0) {
    return true;
  }

  return (
    baselineDistanceCm - distance >=
    NORMAL_DISTANCE_CHANGE_CM
  );
}

// ======================================================
// DHT11
// ======================================================

bool readTemperatureNow() {
  const int maxAttempts = 3;

  for (int attempt = 1; attempt <= maxAttempts; attempt++) {
    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();

    if (!isnan(humidity) && !isnan(temperature)) {
      currentHumidity = humidity;
      currentTemperature = temperature;
      lastTemperatureRead = millis();

      Serial.print("Temperature: ");
      Serial.print(currentTemperature, 1);
      Serial.print(" C, Humidity: ");
      Serial.print(currentHumidity, 1);
      Serial.println(" %");

      return true;
    }

    if (attempt < maxAttempts) {
      delay(250);
    }
  }

  // Preserve the last valid reading instead of replacing it with NAN.
  lastTemperatureRead = millis();
  Serial.println("DHT11 reading failed after 3 attempts; keeping last valid reading.");
  return false;
}

void updateTemperature() {
  if (
    millis() - lastTemperatureRead <
    TEMPERATURE_READ_INTERVAL
  ) {
    return;
  }

  readTemperatureNow();
}

bool temperatureIsSafe() {
  if (isnan(currentTemperature)) {
    return false;
  }

  if (
    ENABLE_HIGH_TEMPERATURE_PROTECTION &&
    currentTemperature > MAX_ALLOWED_TEMPERATURE
  ) {
    return false;
  }

  return true;
}

void showTemperatureOnLCD() {
  if (state != WAIT_PRODUCT) {
    return;
  }

  lcd.setCursor(0, 1);

  if (isnan(currentTemperature)) {
    lcd.print("1-6 T:--.-C    ");
  } else {
    lcd.print("1-6 T:");
    lcd.print(currentTemperature, 1);
    lcd.print((char)223);
    lcd.print("C   ");
  }
}

// ======================================================
// RFID
// ======================================================

bool isAuthorized(String uid) {
  uid.trim();
  uid.toUpperCase();

  for (int i = 0; i < totalCards; i++) {
    String savedUID = authorizedCards[i];
    savedUID.trim();
    savedUID.toUpperCase();

    if (uid == savedUID) {
      return true;
    }
  }

  return false;
}

String readRFIDUID() {
  String uid = "";

  for (byte i = 0; i < mfrc522.uid.size; i++) {
    if (mfrc522.uid.uidByte[i] < 0x10) {
      uid += "0";
    }

    uid += String(
      mfrc522.uid.uidByte[i],
      HEX
    );
  }

  uid.toUpperCase();
  return uid;
}

// ======================================================
// SIGNALS
// ======================================================

void keyBeep() {
  tone(BUZZER_PIN, 1500);
  delay(40);
  noTone(BUZZER_PIN);
}

void successSignal() {
  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  tone(BUZZER_PIN, 1900);
  delay(80);
  noTone(BUZZER_PIN);

  delay(40);

  tone(BUZZER_PIN, 2400);
  delay(100);
  noTone(BUZZER_PIN);
}

void deniedSignal() {
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);

  tone(BUZZER_PIN, 600);
  delay(180);
  noTone(BUZZER_PIN);

  delay(70);

  tone(BUZZER_PIN, 600);
  delay(180);
  noTone(BUZZER_PIN);
}

void cancelSignal() {
  digitalWrite(RED_LED, HIGH);

  tone(BUZZER_PIN, 1000);
  delay(100);
  noTone(BUZZER_PIN);

  digitalWrite(RED_LED, LOW);
}

void productDetectedSignal() {
  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  tone(BUZZER_PIN, 2300);
  delay(80);
  noTone(BUZZER_PIN);
}

void dispensingErrorSignal() {
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);

  tone(BUZZER_PIN, 500);
  delay(250);
  noTone(BUZZER_PIN);

  delay(80);

  tone(BUZZER_PIN, 500);
  delay(250);
  noTone(BUZZER_PIN);
}

void temperatureWarningSignal() {
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);

  for (int i = 0; i < 3; i++) {
    tone(BUZZER_PIN, 700);
    delay(150);
    noTone(BUZZER_PIN);
    delay(80);
  }
}

// ======================================================
// RESET
// ======================================================

void resetSystem() {
  disableAllServos();

  state = WAIT_PRODUCT;
  selectedProduct = 0;
  baselineDistanceCm = -1.0f;

  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Select Product");

  showTemperatureOnLCD();

  Serial.println();
  Serial.println("System ready.");
}

// ======================================================
// DISPENSING
// ======================================================

void dispenseProduct(char product) {
  int index = product - '1';

  if (index < 0 || index >= TOTAL_SERVOS) {
    resetSystem();
    return;
  }

  state = DISPENSING;

  bool temperatureReadSuccessful =
    readTemperatureNow();

  if (
    !temperatureReadSuccessful ||
    !temperatureIsSafe()
  ) {
    lcd.clear();

    if (isnan(currentTemperature)) {
      lcd.setCursor(0, 0);
      lcd.print("TEMP ERROR");

      lcd.setCursor(0, 1);
      lcd.print("Check DHT11");
    } else {
      lcd.setCursor(0, 0);
      lcd.print("HIGH TEMP");

      lcd.setCursor(0, 1);
      lcd.print(currentTemperature, 1);
      lcd.print((char)223);
      lcd.print("C");
    }

    temperatureWarningSignal();

    delay(1500);
    digitalWrite(RED_LED, LOW);

    resetSystem();
    return;
  }

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Checking Area");

  lcd.setCursor(0, 1);
  lcd.print("Please Wait");

  baselineDistanceCm = captureFastBaseline();

  Serial.print("Baseline: ");

  if (baselineDistanceCm < 0) {
    Serial.println("Unavailable");
  } else {
    Serial.print(baselineDistanceCm, 1);
    Serial.println(" cm");
  }

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Dispensing...");

  lcd.setCursor(0, 1);
  lcd.print("Product ");
  lcd.print(product);

  if (!attachSelectedServo(index)) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("SERVO ERROR");

    lcd.setCursor(0, 1);
    lcd.print("Product ");
    lcd.print(product);

    dispensingErrorSignal();

    delay(1200);
    resetSystem();
    return;
  }

  runServoAtConfiguredSpeed(index);

  unsigned long servoStartTime = millis();
  unsigned long lastUltrasonicRead = 0;

  int normalDetectionCount = 0;
  int invalidReadingCount = 0;

  bool productConfirmed = false;
  bool dispensingTimedOut = false;

  while (true) {
    unsigned long now = millis();
    unsigned long elapsed =
      now - servoStartTime;

    if (elapsed >= MAX_DISPENSE_TIME) {
      dispensingTimedOut = true;
      break;
    }

    if (elapsed < MIN_SERVO_RUN_TIME) {
      continue;
    }

    if (
      now - lastUltrasonicRead >=
      ULTRASONIC_READ_INTERVAL
    ) {
      lastUltrasonicRead = now;

      float distance = readDistanceFastCm();

      if (distance < 0) {
        invalidReadingCount++;

        if (invalidReadingCount >= 2) {
          normalDetectionCount = 0;
          invalidReadingCount = 0;
        }

        continue;
      }

      invalidReadingCount = 0;

      Serial.print("Distance: ");
      Serial.print(distance, 1);
      Serial.print(" cm");

      if (baselineDistanceCm > 0) {
        Serial.print(", change: ");
        Serial.print(
          baselineDistanceCm - distance,
          1
        );
        Serial.print(" cm");
      }

      Serial.println();

      if (strongProductDetection(distance)) {
        Serial.println(
          "Strong product detection."
        );

        productConfirmed = true;
        break;
      }

      if (normalProductDetection(distance)) {
        normalDetectionCount++;

        Serial.print("Confirmation: ");
        Serial.print(normalDetectionCount);
        Serial.print("/");
        Serial.println(
          NORMAL_REQUIRED_DETECTIONS
        );

        if (
          normalDetectionCount >=
          NORMAL_REQUIRED_DETECTIONS
        ) {
          productConfirmed = true;
          break;
        }
      } else {
        normalDetectionCount = 0;
      }
    }
  }

  // Stop immediately before any network request.
  stopServo(index);
  delay(60);
  disableServoSignal(index);

  Serial.print("Servo ");
  Serial.print(index + 1);
  Serial.println(" stopped and detached.");

  if (productConfirmed) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Product Sensed");

    lcd.setCursor(0, 1);
    lcd.print("Take Product ");
    lcd.print(product);

    productDetectedSignal();

    // Updating Django happens only after the servo is stopped.
    if (WiFi.status() == WL_CONNECTED) {
      bool updated =
        sendDispenseToDjango(index + 1);

      djangoOnline = updated;

      if (!updated) {
        pendingDispenseSlot = index + 1;

        Serial.println(
          "Stock update queued for automatic retry."
        );
      }
    } else {
      pendingDispenseSlot = index + 1;

      Serial.println(
        "WiFi offline; stock update queued."
      );
    }

    delay(1300);
  } else if (dispensingTimedOut) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("DISPENSE ERROR");

    lcd.setCursor(0, 1);
    lcd.print("No Product");

    dispensingErrorSignal();

    delay(1500);
  }

  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);

  resetSystem();
}

// ======================================================
// SETUP
// ======================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("==============================");
  Serial.println("DAIRYSYNC ESP32-S3 VENDING");
  Serial.println("==============================");
  Serial.println("WiFi requires a 2.4 GHz WPA2 network.");
  Serial.println("Use a simple hotspot password while testing.");

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);

  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  disableAllServos();

  dht.begin();

  Wire.begin(
    LCD_SDA_PIN,
    LCD_SCL_PIN
  );

  lcd.init();
  lcd.backlight();
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("DAIRYSYNC");

  lcd.setCursor(0, 1);
  lcd.print("Starting...");

  SPI.begin(
    RFID_SCK_PIN,
    RFID_MISO_PIN,
    RFID_MOSI_PIN,
    RFID_SS_PIN
  );

  mfrc522.PCD_Init();
  delay(120);

  byte version =
    mfrc522.PCD_ReadRegister(
      MFRC522::VersionReg
    );

  Serial.print("RC522 version: 0x");
  Serial.println(version, HEX);

  if (version == 0x91 || version == 0x92) {
    rfidAvailable = true;

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("RFID READY");

    lcd.setCursor(0, 1);
    lcd.print("Connecting WiFi");

    digitalWrite(GREEN_LED, HIGH);

    tone(BUZZER_PIN, 1800);
    delay(120);
    noTone(BUZZER_PIN);

    delay(500);
    digitalWrite(GREEN_LED, LOW);
  } else {
    rfidAvailable = false;

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("RFID ERROR");

    lcd.setCursor(0, 1);
    lcd.print("Check Wiring");

    digitalWrite(RED_LED, HIGH);

    tone(BUZZER_PIN, 500);
    delay(400);
    noTone(BUZZER_PIN);

    delay(1000);
    digitalWrite(RED_LED, LOW);
  }

  // Allow DHT11 to stabilize before the first cloud upload.
  delay(2000);
  readTemperatureNow();

  if (SCAN_WIFI_ON_BOOT) {
    scanWiFiNetworks();
  }

  // Make one blocking WiFi attempt during startup so the result is visible.
  bool wifiConnected = waitForInitialWiFiConnection();

  if (wifiConnected) {
    Serial.println("Testing Django sensor API...");
    djangoOnline = sendSensorDataToDjango();

    if (djangoOnline) {
      Serial.println("Initial Django upload succeeded.");
    } else {
      Serial.println(
        "Initial Django upload failed; automatic retry remains enabled."
      );
    }
  } else {
    Serial.println(
      "Starting local vending mode; WiFi will retry automatically."
    );
  }

  float testDistance = readDistanceFastCm();

  Serial.print("Ultrasonic test: ");

  if (testDistance < 0) {
    Serial.println("No echo");
  } else {
    Serial.print(testDistance, 1);
    Serial.println(" cm");
  }

  resetSystem();
}

// ======================================================
// LOOP
// ======================================================

void loop() {
  maintainCloudConnection();
  updateTemperature();

  if (state == WAIT_PRODUCT) {
    showTemperatureOnLCD();
  }

  char key = keypad.getKey();

  if (key == 'C' || key == 'D') {
    cancelSignal();
    resetSystem();
    return;
  }

  if (state == WAIT_PRODUCT) {
    if (key >= '1' && key <= '6') {
      selectedProduct = key;

      keyBeep();

      Serial.print("Selected product: ");
      Serial.println(selectedProduct);

      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Product ");
      lcd.print(selectedProduct);

      lcd.setCursor(0, 1);
      lcd.print("Press A Confirm");

      state = WAIT_CONFIRM;
    }
  }

  else if (state == WAIT_CONFIRM) {
    if (key == 'A') {
      keyBeep();

      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Scan RFID Card");

      lcd.setCursor(0, 1);
      lcd.print("Product ");
      lcd.print(selectedProduct);

      state = WAIT_RFID;
    }

    else if (key >= '1' && key <= '6') {
      selectedProduct = key;

      keyBeep();

      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Product ");
      lcd.print(selectedProduct);

      lcd.setCursor(0, 1);
      lcd.print("Press A Confirm");
    }
  }

  else if (state == WAIT_RFID) {
    if (!rfidAvailable) {
      return;
    }

    if (
      mfrc522.PICC_IsNewCardPresent() &&
      mfrc522.PICC_ReadCardSerial()
    ) {
      String uid = readRFIDUID();

      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();

      if (
        uid == lastUID &&
        millis() - lastUIDTime <
        DUPLICATE_CARD_DELAY
      ) {
        return;
      }

      lastUID = uid;
      lastUIDTime = millis();

      Serial.print("Scanned UID: ");
      Serial.println(uid);

      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Card Detected");

      lcd.setCursor(0, 1);
      lcd.print(uid.substring(0, 16));

      delay(250);

      if (isAuthorized(uid)) {
        Serial.println("Card authorized.");

        successSignal();
        dispenseProduct(selectedProduct);
      } else {
        Serial.println("Card denied.");

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("ACCESS DENIED");

        lcd.setCursor(0, 1);
        lcd.print("Unknown Card");

        deniedSignal();

        delay(800);
        digitalWrite(RED_LED, LOW);

        resetSystem();
      }
    }
  }
}