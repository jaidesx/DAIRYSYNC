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
// DAIRYSYNC NETWORK / DJANGO API
// ======================================================
// Fill these locally before uploading. Do not commit real credentials.
// For a phone hotspot, use the computer's LAN IP in API URLs, not 127.0.0.1.
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* API_URL = "http://192.168.5.36:8000/api/sensor-data/";
const char* DISPENSE_API_URL = "http://192.168.5.36:8000/api/dispense/";
const char* API_KEY = "YOUR_ESP32_API_KEY";
const char* FRIDGE_CODE = "F001";

const unsigned long SENSOR_UPLOAD_INTERVAL = 30000;
const unsigned long WIFI_RETRY_INTERVAL = 10000;
const unsigned long API_RETRY_INTERVAL = 15000;
const float SUPPLY_VOLTAGE = 5.0;

unsigned long lastSensorUpload = 0;
unsigned long lastWiFiAttempt = 0;
unsigned long lastApiAttempt = 0;
bool djangoOnline = false;

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

// ======================================================
// DHT11 TEMPERATURE SENSOR
// ======================================================

#define DHT_PIN  2
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);

float currentTemperature = NAN;
float currentHumidity = NAN;

unsigned long lastTemperatureRead = 0;

// DHT11 should not be read too frequently.
const unsigned long TEMPERATURE_READ_INTERVAL = 2000;

// Set to true if dispensing should be blocked when the
// temperature exceeds MAX_ALLOWED_TEMPERATURE.
const bool ENABLE_HIGH_TEMPERATURE_PROTECTION = true;

const float MAX_ALLOWED_TEMPERATURE = 45.0;

// ======================================================
// ULTRASONIC HC-SR04
// ======================================================

#define TRIG_PIN 38
#define ECHO_PIN 39

const float MIN_PRODUCT_DISTANCE_CM = 1.0;
const float MAX_PRODUCT_DISTANCE_CM = 15.0;

// Product must be detected several times to avoid noise.
const int REQUIRED_DETECTIONS = 3;

// Delay between ultrasonic measurements.
const unsigned long SENSOR_READ_INTERVAL = 60;

// Safety timeout. Servo stops even when no product is sensed.
const unsigned long MAX_DISPENSE_TIME = 8000;

// Ignore ultrasonic detection briefly after the servo starts.
const unsigned long MIN_SERVO_RUN_TIME = 250;

// ======================================================
// OUTPUTS
// ======================================================

#define BUZZER_PIN 40
#define GREEN_LED  41
#define RED_LED    42

// ======================================================
// SERVO PINS
// ======================================================

const uint8_t servoPins[6] = {
  4, 5, 6, 7, 15, 16
};

const int TOTAL_SERVOS = 6;

// ======================================================
// CONTINUOUS-ROTATION SERVO SETTINGS
// ======================================================

const uint32_t SERVO_FREQUENCY = 50;
const uint8_t SERVO_RESOLUTION = 10;
const uint32_t SERVO_MAX_DUTY = 1023;

// Around 1500 microseconds normally stops a continuous
// rotation servo. Adjust each value if necessary.
int servoStopPulse[6] = {
  1500,
  1500,
  1500,
  1500,
  1500,
  1500
};

// Above 1500 normally rotates in one direction.
// Use values below 1500 for the opposite direction.
int servoRunPulse[6] = {
  1700,
  1700,
  1700,
  1700,
  1700,
  1700
};

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

byte rowPins[ROWS] = {
  21, 35, 36, 37
};

byte colPins[COLS] = {
  17, 18, 19, 20
};

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
// SYSTEM STATES
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

const unsigned long duplicateCardDelay = 2000;

// ======================================================
// FUNCTION DECLARATIONS
// ======================================================

void connectWiFi();
void maintainCloudConnection();
bool sendSensorDataToDjango();
bool sendDispenseToDjango(int slotNumber);
String jsonEscape(const String &value);

uint32_t microsecondsToDuty(uint32_t pulseWidthUs);

void disableServoSignal(int index);
void disableAllServos();
bool attachSelectedServo(int index);
void runServo(int index);
void stopServo(int index);

float readDistanceCm();
bool productDetected();

void updateTemperature();
bool temperatureIsSafe();
void showTemperatureOnLCD();

bool isAuthorized(String uid);
String readRFIDUID();

void resetSystem();
void dispenseProduct(char product);

void keyBeep();
void successSignal();
void deniedSignal();
void cancelSignal();
void productDetectedSignal();
void temperatureWarningSignal();


// ======================================================
// WIFI AND DJANGO COMMUNICATION
// ======================================================

String jsonEscape(const String &value) {
  String escaped = value;
  escaped.replace("\\", "\\\\");
  escaped.replace("\"", "\\\"");
  return escaped;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (lastWiFiAttempt != 0 && millis() - lastWiFiAttempt < WIFI_RETRY_INTERVAL) return;

  lastWiFiAttempt = millis();
  djangoOnline = false;
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

bool sendSensorDataToDjango() {
  if (WiFi.status() != WL_CONNECTED) return false;
  if (isnan(currentTemperature) || isnan(currentHumidity)) {
    Serial.println("Upload skipped: DHT reading unavailable.");
    return false;
  }

  HTTPClient http;
  WiFiClientSecure secureClient;
  WiFiClient plainClient;
  bool started = false;

  String url(API_URL);
  if (url.startsWith("https://")) {
    // For production, replace setInsecure() with a trusted root CA certificate.
    secureClient.setInsecure();
    started = http.begin(secureClient, url);
  } else {
    started = http.begin(plainClient, url);
  }

  if (!started) {
    Serial.println("HTTP client failed to start.");
    return false;
  }

  http.setConnectTimeout(7000);
  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Api-Key", API_KEY);

  String payload = "{";
  payload += "\"fridge_code\":\"" + jsonEscape(FRIDGE_CODE) + "\",";
  payload += "\"temperature\":" + String(currentTemperature, 1) + ",";
  payload += "\"humidity\":" + String(currentHumidity, 1) + ",";
  payload += "\"voltage\":" + String(SUPPLY_VOLTAGE, 1) + ",";
  payload += "\"door_open\":false,";
  payload += "\"stock\":[]";
  payload += "}";

  int code = http.POST(payload);
  String response = code > 0 ? http.getString() : http.errorToString(code);
  http.end();

  Serial.print("Django HTTP status: ");
  Serial.println(code);
  Serial.println(response);

  return code >= 200 && code < 300;
}

bool sendDispenseToDjango(int slotNumber) {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  WiFiClientSecure secureClient;
  WiFiClient plainClient;
  bool started = false;

  String url(DISPENSE_API_URL);
  if (url.startsWith("https://")) {
    secureClient.setInsecure();
    started = http.begin(secureClient, url);
  } else {
    started = http.begin(plainClient, url);
  }

  if (!started) {
    Serial.println("Dispense HTTP client failed to start.");
    return false;
  }

  http.setConnectTimeout(7000);
  http.setTimeout(8000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Api-Key", API_KEY);

  String payload = "{";
  payload += "\"fridge_code\":\"" + jsonEscape(FRIDGE_CODE) + "\",";
  payload += "\"slot_number\":" + String(slotNumber) + ",";
  payload += "\"quantity\":1,";
  payload += "\"product_detected\":true";
  payload += "}";

  int code = http.POST(payload);
  String response = code > 0 ? http.getString() : http.errorToString(code);
  http.end();

  Serial.print("Dispense API HTTP status: ");
  Serial.println(code);
  Serial.println(response);

  return code >= 200 && code < 300;
}

void maintainCloudConnection() {
  connectWiFi();

  if (WiFi.status() != WL_CONNECTED) {
    djangoOnline = false;
    return;
  }

  unsigned long interval = djangoOnline ? SENSOR_UPLOAD_INTERVAL : API_RETRY_INTERVAL;
  if (millis() - lastApiAttempt < interval) return;

  lastApiAttempt = millis();
  updateTemperature();
  djangoOnline = sendSensorDataToDjango();

  if (djangoOnline) {
    lastSensorUpload = millis();
    Serial.print("DAIRYSYNC online. IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("DAIRYSYNC API offline; local dispensing remains available.");
  }
}

// ======================================================
// PWM CONVERSION
// ======================================================

uint32_t microsecondsToDuty(uint32_t pulseWidthUs) {
  const uint32_t periodUs =
    1000000UL / SERVO_FREQUENCY;

  return (
    pulseWidthUs * SERVO_MAX_DUTY
  ) / periodUs;
}

// ======================================================
// SERVO CONTROL
// ======================================================

void disableServoSignal(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return;
  }

  uint8_t pin = servoPins[index];

  // Remove PWM from the selected servo.
  ledcDetach(pin);

  // Keep the signal pin LOW.
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
}

void disableAllServos() {
  for (int i = 0; i < TOTAL_SERVOS; i++) {
    pinMode(servoPins[i], OUTPUT);
    digitalWrite(servoPins[i], LOW);
  }
}

bool attachSelectedServo(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return false;
  }

  uint8_t pin = servoPins[index];

  bool attached = ledcAttach(
    pin,
    SERVO_FREQUENCY,
    SERVO_RESOLUTION
  );

  if (!attached) {
    Serial.print("Failed to attach servo ");
    Serial.println(index + 1);
    return false;
  }

  return true;
}

void runServo(int index) {
  if (index < 0 || index >= TOTAL_SERVOS) {
    return;
  }

  ledcWrite(
    servoPins[index],
    microsecondsToDuty(servoRunPulse[index])
  );
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

// ======================================================
// DHT11 TEMPERATURE FUNCTIONS
// ======================================================

void updateTemperature() {
  if (
    millis() - lastTemperatureRead <
    TEMPERATURE_READ_INTERVAL
  ) {
    return;
  }

  lastTemperatureRead = millis();

  float newHumidity = dht.readHumidity();
  float newTemperature = dht.readTemperature();

  if (
    isnan(newHumidity) ||
    isnan(newTemperature)
  ) {
    Serial.println("DHT11 reading failed.");
    return;
  }

  currentHumidity = newHumidity;
  currentTemperature = newTemperature;

  Serial.print("Temperature: ");
  Serial.print(currentTemperature, 1);
  Serial.print(" C, Humidity: ");
  Serial.print(currentHumidity, 1);
  Serial.println(" %");
}

bool temperatureIsSafe() {
  // An unreadable sensor should not cause the servo to run
  // without the system knowing the temperature.
  if (isnan(currentTemperature)) {
    Serial.println("Temperature unavailable.");
    return false;
  }

  if (
    ENABLE_HIGH_TEMPERATURE_PROTECTION &&
    currentTemperature > MAX_ALLOWED_TEMPERATURE
  ) {
    Serial.print("High temperature detected: ");
    Serial.print(currentTemperature, 1);
    Serial.println(" C");

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
    lcd.print("1-6 Temp: --.- ");
  } else {
    lcd.print("1-6 T:");

    if (currentTemperature < 10) {
      lcd.print(" ");
    }

    lcd.print(currentTemperature, 1);
    lcd.print((char)223);
    lcd.print("C ");

    // Clear any remaining LCD characters.
    lcd.print(" ");
  }
}

// ======================================================
// ULTRASONIC FUNCTIONS
// ======================================================

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);

  digitalWrite(TRIG_PIN, LOW);

  // Stop waiting after 30 milliseconds.
  unsigned long duration =
    pulseIn(ECHO_PIN, HIGH, 30000UL);

  if (duration == 0) {
    return -1.0;
  }

  return duration * 0.0343 / 2.0;
}

bool productDetected() {
  float distance = readDistanceCm();

  if (distance < 0) {
    Serial.println("Ultrasonic: no echo");
    return false;
  }

  Serial.print("Product distance: ");
  Serial.print(distance, 1);
  Serial.println(" cm");

  return (
    distance >= MIN_PRODUCT_DISTANCE_CM &&
    distance <= MAX_PRODUCT_DISTANCE_CM
  );
}

// ======================================================
// RFID FUNCTIONS
// ======================================================

bool isAuthorized(String uid) {
  uid.toUpperCase();

  for (int i = 0; i < totalCards; i++) {
    String savedUID = authorizedCards[i];
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
// RESET SYSTEM
// ======================================================

void resetSystem() {
  disableAllServos();

  state = WAIT_PRODUCT;
  selectedProduct = 0;

  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Select Product");

  showTemperatureOnLCD();

  Serial.println();
  Serial.println("Waiting for product selection.");
}

// ======================================================
// BUZZER AND LED SIGNALS
// ======================================================

void keyBeep() {
  tone(BUZZER_PIN, 1500);
  delay(50);
  noTone(BUZZER_PIN);
}

void successSignal() {
  digitalWrite(RED_LED, LOW);
  digitalWrite(GREEN_LED, HIGH);

  tone(BUZZER_PIN, 1800);
  delay(100);
  noTone(BUZZER_PIN);

  delay(70);

  tone(BUZZER_PIN, 2300);
  delay(150);
  noTone(BUZZER_PIN);
}

void deniedSignal() {
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);

  tone(BUZZER_PIN, 600);
  delay(250);
  noTone(BUZZER_PIN);

  delay(100);

  tone(BUZZER_PIN, 600);
  delay(250);
  noTone(BUZZER_PIN);
}

void cancelSignal() {
  digitalWrite(RED_LED, HIGH);

  tone(BUZZER_PIN, 1000);
  delay(150);
  noTone(BUZZER_PIN);

  digitalWrite(RED_LED, LOW);
}

void productDetectedSignal() {
  digitalWrite(GREEN_LED, HIGH);

  tone(BUZZER_PIN, 2200);
  delay(100);
  noTone(BUZZER_PIN);

  delay(60);

  tone(BUZZER_PIN, 2600);
  delay(120);
  noTone(BUZZER_PIN);
}

void temperatureWarningSignal() {
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, HIGH);

  for (int i = 0; i < 3; i++) {
    tone(BUZZER_PIN, 700);
    delay(180);
    noTone(BUZZER_PIN);
    delay(100);
  }
}

// ======================================================
// DISPENSE PRODUCT
// ======================================================

void dispenseProduct(char product) {
  int index = product - '1';

  if (index < 0 || index >= TOTAL_SERVOS) {
    Serial.println("Invalid product.");
    resetSystem();
    return;
  }

  // Get a fresh temperature reading before dispensing.
  lastTemperatureRead = 0;
  updateTemperature();

  if (!temperatureIsSafe()) {
    lcd.clear();
    lcd.setCursor(0, 0);

    if (isnan(currentTemperature)) {
      lcd.print("TEMP ERROR");
      lcd.setCursor(0, 1);
      lcd.print("Check DHT11");
    } else {
      lcd.print("HIGH TEMP");
      lcd.setCursor(0, 1);
      lcd.print(currentTemperature, 1);
      lcd.print((char)223);
      lcd.print("C");
    }

    temperatureWarningSignal();

    delay(2000);

    digitalWrite(RED_LED, LOW);
    resetSystem();
    return;
  }

  state = DISPENSING;

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Dispensing...");

  lcd.setCursor(0, 1);
  lcd.print("Product ");
  lcd.print(product);

  Serial.print("Authorized. Attaching servo ");
  Serial.println(index + 1);

  // Servo receives PWM only after authorization.
  if (!attachSelectedServo(index)) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("SERVO ERROR");

    lcd.setCursor(0, 1);
    lcd.print("Product ");
    lcd.print(product);

    digitalWrite(RED_LED, HIGH);
    delay(1500);
    digitalWrite(RED_LED, LOW);

    resetSystem();
    return;
  }

  runServo(index);

  Serial.print("Servo ");
  Serial.print(index + 1);
  Serial.println(" running.");

  unsigned long servoStartTime = millis();
  unsigned long lastSensorRead = 0;

  int consecutiveDetections = 0;
  bool detected = false;
  bool timedOut = false;

  while (true) {
    unsigned long elapsed =
      millis() - servoStartTime;

    // Stop when maximum dispensing time is reached.
    if (elapsed >= MAX_DISPENSE_TIME) {
      timedOut = true;
      Serial.println("Dispensing timeout.");
      break;
    }

    // Allow the product to begin moving.
    if (elapsed < MIN_SERVO_RUN_TIME) {
      delay(5);
      continue;
    }

    if (
      millis() - lastSensorRead >=
      SENSOR_READ_INTERVAL
    ) {
      lastSensorRead = millis();

      if (productDetected()) {
        consecutiveDetections++;

        Serial.print("Valid product detections: ");
        Serial.println(consecutiveDetections);

        if (
          consecutiveDetections >=
          REQUIRED_DETECTIONS
        ) {
          detected = true;

          Serial.println(
            "Product confirmed by ultrasonic sensor."
          );

          break;
        }
      } else {
        consecutiveDetections = 0;
      }
    }

    delay(2);
  }

  // Stop immediately after detection or timeout.
  stopServo(index);

  // Let the neutral stop pulse reach the servo.
  delay(250);

  disableServoSignal(index);

  Serial.print("Servo ");
  Serial.print(index + 1);
  Serial.println(" stopped and detached.");

  if (detected) {
    if (WiFi.status() == WL_CONNECTED) {
      bool stockUpdated = sendDispenseToDjango(index + 1);
      djangoOnline = stockUpdated;

      if (!stockUpdated) {
        Serial.println("Dispense recorded locally; Django stock update will need reconciliation.");
      }
    } else {
      Serial.println("WiFi offline; local dispensing completed without Django stock update.");
    }

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Product Sensed");

    lcd.setCursor(0, 1);
    lcd.print("Take Product ");
    lcd.print(product);

    productDetectedSignal();

    delay(2000);
  } else if (timedOut) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("DISPENSE ERROR");

    lcd.setCursor(0, 1);
    lcd.print("No Product");

    digitalWrite(GREEN_LED, LOW);
    digitalWrite(RED_LED, HIGH);

    deniedSignal();

    delay(1800);

    digitalWrite(RED_LED, LOW);
  }

  digitalWrite(GREEN_LED, LOW);

  resetSystem();
}

// ======================================================
// SETUP
// ======================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("============================");
  Serial.println("ESP32-S3 VENDING MACHINE");
  Serial.println("============================");

  WiFi.setSleep(false);
  connectWiFi();

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);

  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED, LOW);
  digitalWrite(RED_LED, LOW);

  // Ultrasonic sensor.
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(TRIG_PIN, LOW);

  // Disable every servo during startup.
  disableAllServos();

  // Start DHT11.
  dht.begin();

  // Start LCD.
  Wire.begin(
    LCD_SDA_PIN,
    LCD_SCL_PIN
  );

  lcd.init();
  lcd.backlight();
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("VENDING SYSTEM");

  lcd.setCursor(0, 1);
  lcd.print("Starting...");

  // Start RFID SPI.
  SPI.begin(
    RFID_SCK_PIN,
    RFID_MISO_PIN,
    RFID_MOSI_PIN,
    RFID_SS_PIN
  );

  mfrc522.PCD_Init();
  delay(100);

  byte version =
    mfrc522.PCD_ReadRegister(
      MFRC522::VersionReg
    );

  Serial.print("RC522 version: 0x");
  Serial.println(version, HEX);

  if (
    version == 0x91 ||
    version == 0x92
  ) {
    Serial.println("RFID reader detected.");

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("RFID READY");

    lcd.setCursor(0, 1);
    lcd.print("System Ready");

    digitalWrite(GREEN_LED, HIGH);

    tone(BUZZER_PIN, 1800);
    delay(150);
    noTone(BUZZER_PIN);

    delay(700);
    digitalWrite(GREEN_LED, LOW);
  } else {
    Serial.println("RFID reader not detected.");

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("RFID ERROR");

    lcd.setCursor(0, 1);
    lcd.print("Check Wiring");

    digitalWrite(RED_LED, HIGH);

    tone(BUZZER_PIN, 500);
    delay(500);
    noTone(BUZZER_PIN);

    delay(1500);
    digitalWrite(RED_LED, LOW);
  }

  // Allow the DHT11 sensor to stabilize.
  delay(2000);

  lastTemperatureRead = 0;
  updateTemperature();

  // Test ultrasonic sensor.
  float startupDistance = readDistanceCm();

  Serial.print("Initial ultrasonic distance: ");

  if (startupDistance < 0) {
    Serial.println("No echo");
  } else {
    Serial.print(startupDistance, 1);
    Serial.println(" cm");
  }

  resetSystem();
}

// ======================================================
// MAIN LOOP
// ======================================================

void loop() {
  // Keep the Django heartbeat alive without blocking local operation.
  maintainCloudConnection();

  // Continuously monitor temperature.
  updateTemperature();

  // Update temperature on the home screen.
  if (state == WAIT_PRODUCT) {
    showTemperatureOnLCD();
  }

  char key = keypad.getKey();

  // Cancel the current operation.
  if (key == 'C' || key == 'D') {
    cancelSignal();
    resetSystem();
    return;
  }

  // ----------------------------------------------------
  // SELECT PRODUCT
  // ----------------------------------------------------

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

  // ----------------------------------------------------
  // CONFIRM PRODUCT
  // ----------------------------------------------------

  else if (state == WAIT_CONFIRM) {
    if (key == 'A') {
      keyBeep();

      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Scan RFID Card");

      lcd.setCursor(0, 1);
      lcd.print("Product ");
      lcd.print(selectedProduct);

      Serial.println("Waiting for RFID card.");

      state = WAIT_RFID;
    } else if (key >= '1' && key <= '6') {
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

  // ----------------------------------------------------
  // WAIT FOR AUTHORIZED RFID CARD
  // ----------------------------------------------------

  else if (state == WAIT_RFID) {
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
        duplicateCardDelay
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

      delay(400);

      if (isAuthorized(uid)) {
        Serial.println("Card authorized.");

        successSignal();

        // Servo starts only here, after RFID authorization.
        dispenseProduct(selectedProduct);
      } else {
        Serial.println("Card denied.");

        lcd.clear();
        lcd.setCursor(0, 0);
        lcd.print("ACCESS DENIED");

        lcd.setCursor(0, 1);
        lcd.print("Unknown Card");

        deniedSignal();

        delay(1000);

        digitalWrite(RED_LED, LOW);

        resetSystem();
      }
    }
  }
}
