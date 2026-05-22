/* ============================================================
   DAIRYSYNC — ESP32 PRODUCTION FIRMWARE
   Integrates with Django backend built in this project.

   Hardware:
     - ESP32 DevKit
     - DHT22 (temperature + humidity)
     - LiquidCrystal I2C 16x2 LCD
     - 3x Push buttons (Milk, Yoghurt, Cheese)
     - 3x Servo motors (dispensing)
     - Magnetic door switch
     - Voltage divider on ADC pin (battery monitoring)
     - Buzzer (alerts)
     - IR sensors (stock detection per slot)

   Backend endpoints used:
     POST /api/sensor-data/   → send readings every 30s + after dispense

   Libraries needed (Arduino IDE Library Manager):
     - ESP32Servo
     - DHT sensor library (Adafruit)
     - LiquidCrystal I2C
     - ArduinoJson  (version 6.x)
     - WiFi (built-in ESP32)
     - HTTPClient (built-in ESP32)
============================================================ */

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <ESP32Servo.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>


// ============================================================
//  CONFIGURATION
//  Change these to match your setup
// ============================================================

const char* WIFI_SSID      = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD  = "YOUR_WIFI_PASSWORD";

// Django server URL — no trailing slash
// Development: "http://192.168.1.100:8000"
// Production:  "https://yourdomain.com"
const char* SERVER_URL     = "http://192.168.1.100:8000";

// Must match DEVICE_API_KEY in your Django .env file
const char* DEVICE_API_KEY = "your-esp32-secret-key-here";

// Must match fridge_code in your Django Fridge table
const char* FRIDGE_CODE    = "FRG-01";

// How often to send sensor data (milliseconds)
const unsigned long REPORT_INTERVAL = 30000;

// Thresholds
const float TEMP_THRESHOLD    = 6.0;   // above this = high temp alert
const float VOLTAGE_LOW       = 10.5;  // below this = power fault alert


// ============================================================
//  PIN DEFINITIONS
// ============================================================

#define DHTPIN           4
#define DHTTYPE          DHT22

#define BTN_MILK         13
#define BTN_YOGHURT      12
#define BTN_CHEESE       14

#define SERVO_MILK_PIN   25
#define SERVO_YOGHURT    26
#define SERVO_CHEESE_PIN 33

#define IR_MILK          34   // LOW = item present
#define IR_YOGHURT       35
#define IR_CHEESE        32

#define DOOR_SWITCH      27   // LOW = closed, HIGH = open
#define BUZZER_PIN       15
#define VOLTAGE_PIN      36   // ADC — voltage divider (R1=30k, R2=10k)


// ============================================================
//  OBJECTS
// ============================================================

LiquidCrystal_I2C lcd(0x27, 16, 2);
DHT dht(DHTPIN, DHTTYPE);
Servo servoMilk;
Servo servoYoghurt;
Servo servoCheese;


// ============================================================
//  SLOT CONFIG
//  slotNumber must match Django FridgeSlot.slot_number values
// ============================================================

struct SlotConfig {
    const char* name;
    int         buttonPin;
    int         irPin;
    int         slotNumber;
    Servo*      servo;
};

SlotConfig slots[] = {
    { "MILK",    BTN_MILK,    IR_MILK,    1, &servoMilk    },
    { "YOGHURT", BTN_YOGHURT, IR_YOGHURT, 2, &servoYoghurt },
    { "CHEESE",  BTN_CHEESE,  IR_CHEESE,  3, &servoCheese  },
};

const int SLOT_COUNT = sizeof(slots) / sizeof(slots[0]);


// ============================================================
//  STATE
// ============================================================

unsigned long lastReportTime = 0;
bool          doorWasOpen    = false;
bool          wifiConnected  = false;


// ============================================================
//  FUNCTION DECLARATIONS
// ============================================================

void connectWiFi();
void sendSensorData(bool afterDispense = false, int changedSlot = -1);
void processOrder(SlotConfig& slot);
float readVoltage();
void lcdPrint(String line1, String line2);
void beep(int count, int duration);


// ============================================================
//  SETUP
// ============================================================

void setup() {
    Serial.begin(115200);
    Serial.println("\n[DAIRYSYNC] Booting...");

    // Button and sensor pins
    for (int i = 0; i < SLOT_COUNT; i++) {
        pinMode(slots[i].buttonPin, INPUT_PULLUP);
        pinMode(slots[i].irPin,     INPUT_PULLUP);
    }
    pinMode(DOOR_SWITCH, INPUT_PULLUP);
    pinMode(BUZZER_PIN,  OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);

    // Servos — all closed on boot
    servoMilk.attach(SERVO_MILK_PIN);
    servoYoghurt.attach(SERVO_YOGHURT);
    servoCheese.attach(SERVO_CHEESE_PIN);
    servoMilk.write(0);
    servoYoghurt.write(0);
    servoCheese.write(0);

    // LCD + DHT22
    lcd.init();
    lcd.backlight();
    dht.begin();

    lcdPrint("DAIRYSYNC", "Booting...");

    // Connect to WiFi
    connectWiFi();

    // Send initial reading to server
    sendSensorData();

    lcdPrint("DAIRYSYNC", "Select Product");
    beep(1, 200);
}


// ============================================================
//  MAIN LOOP
// ============================================================

void loop() {

    // Button press → dispense product
    for (int i = 0; i < SLOT_COUNT; i++) {
        if (digitalRead(slots[i].buttonPin) == LOW) {
            delay(50);  // debounce
            if (digitalRead(slots[i].buttonPin) == LOW) {
                processOrder(slots[i]);
                delay(500);
            }
        }
    }

    // Periodic sensor report
    if (millis() - lastReportTime >= REPORT_INTERVAL) {
        lastReportTime = millis();
        sendSensorData();
    }

    // Door monitoring
    bool doorOpen = (digitalRead(DOOR_SWITCH) == HIGH);
    if (doorOpen && !doorWasOpen) {
        doorWasOpen = true;
        Serial.println("[DAIRYSYNC] Door opened");
        lcdPrint("Door Open!", "Please close");
        beep(2, 200);
    } else if (!doorOpen && doorWasOpen) {
        doorWasOpen = false;
        Serial.println("[DAIRYSYNC] Door closed");
        lcdPrint("DAIRYSYNC", "Select Product");
    }

    // WiFi reconnect if dropped
    if (WiFi.status() != WL_CONNECTED) {
        wifiConnected = false;
        connectWiFi();
    }

    delay(100);
}


// ============================================================
//  PROCESS ORDER
// ============================================================

void processOrder(SlotConfig& slot) {
    Serial.printf("[DAIRYSYNC] Order: %s\n", slot.name);
    lcdPrint(slot.name, "Checking...");

    // Stock check via IR sensor
    bool inStock = (digitalRead(slot.irPin) == LOW);
    if (!inStock) {
        lcdPrint("OUT OF STOCK", slot.name);
        beep(3, 150);
        delay(2500);
        lcdPrint("DAIRYSYNC", "Select Product");
        return;
    }

    // Temperature check
    float temp = dht.readTemperature();
    if (isnan(temp)) {
        lcdPrint("Sensor Error", "Try again");
        delay(2000);
        lcdPrint("DAIRYSYNC", "Select Product");
        return;
    }

    if (temp > TEMP_THRESHOLD) {
        lcdPrint("TEMP TOO HIGH", String(temp, 1) + "C - Sorry");
        beep(3, 200);
        delay(3000);
        lcdPrint("DAIRYSYNC", "Select Product");
        return;
    }

    // Simulate payment
    lcdPrint("Processing Pay", "Please wait...");
    delay(2000);

    // Dispense
    lcdPrint("Dispensing...", slot.name);
    slot.servo->write(90);
    delay(1500);
    slot.servo->write(0);
    beep(1, 300);

    lcdPrint("Please take:", slot.name);
    delay(3000);

    // Immediately report updated stock to server
    sendSensorData(true, slot.slotNumber);

    lcdPrint("DAIRYSYNC", "Select Product");
}


// ============================================================
//  SEND SENSOR DATA TO DJANGO
//  Sends all readings + stock levels
//  afterDispense: true = called right after a sale
//  changedSlot:   slot number that was just dispensed
// ============================================================

void sendSensorData(bool afterDispense, int changedSlot) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[DAIRYSYNC] WiFi offline — skipping report");
        return;
    }

    float temperature = dht.readTemperature();
    float humidity    = dht.readHumidity();
    float voltage     = readVoltage();
    bool  doorOpen    = (digitalRead(DOOR_SWITCH) == HIGH);

    if (isnan(temperature) || isnan(humidity)) {
        Serial.println("[DAIRYSYNC] DHT22 error — skipping");
        return;
    }

    // Build JSON payload
    DynamicJsonDocument doc(512);
    doc["api_key"]     = DEVICE_API_KEY;
    doc["fridge_code"] = FRIDGE_CODE;
    doc["temperature"] = round(temperature * 10.0) / 10.0;
    doc["humidity"]    = round(humidity    * 10.0) / 10.0;
    doc["voltage"]     = round(voltage     * 10.0) / 10.0;
    doc["door_open"]   = doorOpen;

    JsonArray stockArray = doc.createNestedArray("stock");
    for (int i = 0; i < SLOT_COUNT; i++) {
        bool hasStock = (digitalRead(slots[i].irPin) == LOW);
        int  level    = hasStock ? 5 : 0;

        // After a dispense, reduce the dispensed slot by 1
        if (afterDispense && slots[i].slotNumber == changedSlot && hasStock) {
            level = 4;
        }

        JsonObject item     = stockArray.createNestedObject();
        item["slot_number"] = slots[i].slotNumber;
        item["stock_level"] = level;
    }

    String payload;
    serializeJson(doc, payload);

    Serial.println("[DAIRYSYNC] POST /api/sensor-data/");
    Serial.println(payload);

    HTTPClient http;
    String url = String(SERVER_URL) + "/api/sensor-data/";
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Api-Key", DEVICE_API_KEY);
    http.setTimeout(8000);

    int code = http.POST(payload);
    Serial.printf("[DAIRYSYNC] Response: %d\n", code);

    if (code == 200) {
        // Show briefly only if not mid-transaction
        if (!afterDispense) {
            lcdPrint("Server: OK", "Data synced");
            delay(800);
            lcdPrint("DAIRYSYNC", "Select Product");
        }
    } else {
        lcdPrint("Server Error", "Code: " + String(code));
        beep(2, 100);
        delay(1500);
        lcdPrint("DAIRYSYNC", "Select Product");
    }

    http.end();

    // Local buzzer alerts regardless of server response
    if (temperature > TEMP_THRESHOLD) {
        Serial.println("[DAIRYSYNC] HIGH TEMP ALERT");
        lcdPrint("HIGH TEMP!", String(temperature, 1) + " C");
        beep(5, 200);
        delay(2000);
        lcdPrint("DAIRYSYNC", "Select Product");
    }

    if (voltage > 0 && voltage < VOLTAGE_LOW) {
        Serial.println("[DAIRYSYNC] LOW VOLTAGE ALERT");
        lcdPrint("LOW VOLTAGE!", String(voltage, 1) + " V");
        beep(4, 300);
        delay(2000);
        lcdPrint("DAIRYSYNC", "Select Product");
    }
}


// ============================================================
//  WIFI CONNECTION
// ============================================================

void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;

    Serial.printf("[DAIRYSYNC] Connecting to: %s\n", WIFI_SSID);
    lcdPrint("Connecting...", WIFI_SSID);

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        wifiConnected = true;
        String ip = WiFi.localIP().toString();
        Serial.printf("\n[DAIRYSYNC] WiFi OK. IP: %s\n", ip.c_str());
        lcdPrint("WiFi Connected", ip);
        beep(2, 100);
        delay(1500);
    } else {
        wifiConnected = false;
        Serial.println("\n[DAIRYSYNC] WiFi FAILED — offline mode");
        lcdPrint("WiFi FAILED", "Offline mode");
        beep(3, 500);
        delay(2000);
    }
}


// ============================================================
//  READ BATTERY VOLTAGE
//  Voltage divider: R1=30kΩ, R2=10kΩ → factor = 4.0
//  Adjust VOLTAGE_FACTOR if using different resistors
// ============================================================

float readVoltage() {
    const float VOLTAGE_FACTOR = 4.0;
    int   raw        = analogRead(VOLTAGE_PIN);
    float adcVoltage = (raw / 4095.0) * 3.3;
    return adcVoltage * VOLTAGE_FACTOR;
}


// ============================================================
//  LCD HELPER — max 16 chars per line
// ============================================================

void lcdPrint(String line1, String line2) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(line1.substring(0, 16));
    lcd.setCursor(0, 1);
    lcd.print(line2.substring(0, 16));
}


// ============================================================
//  BUZZER HELPER
// ============================================================

void beep(int count, int duration) {
    for (int i = 0; i < count; i++) {
        digitalWrite(BUZZER_PIN, HIGH);
        delay(duration);
        digitalWrite(BUZZER_PIN, LOW);
        if (i < count - 1) delay(100);
    }
}
