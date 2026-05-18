# DAIRYSYNC: IoT-Enabled Smart Dairy Vending Fridge System

DAIRYSYNC is an IoT-enabled smart dairy vending and monitoring system designed to automate dairy product dispensing, stock monitoring, temperature monitoring, alert generation, and restocking management.

The system combines an ESP32 microcontroller, sensors, gear motors, a spiral dispensing mechanism, and a Django-based web dashboard to provide real-time control and monitoring of dairy fridges.

---

## Project Overview

DAIRYSYNC is designed for dairy businesses such as Pearl Dairy Farm, supermarkets, schools, institutions, restaurants, and smart retail environments where dairy products need to be stored, monitored, and restocked efficiently.

The system helps solve problems such as:

- Manual fridge inspection
- Delayed restocking
- Product spoilage due to temperature rise
- Lack of real-time stock visibility
- Poor tracking of distributed dairy fridges
- No automatic alert system for faults and low stock

---

## Main Features

### IoT and Hardware Features

- ESP32-based smart fridge monitoring
- DHT22 temperature and humidity sensing
- IR sensor stock detection
- Magnetic door switch monitoring
- Voltage monitoring
- Gear motor product dispensing
- Spiral coil dispensing mechanism
- Buzzer and LED status alerts
- WiFi communication with Django server

### Django Web System Features

- Secure login and logout
- Admin dashboard
- Institution management
- Fridge management
- Product management
- Fridge slot management
- Stock level monitoring
- Sensor readings
- Alerts and notifications
- Restock order generation
- Restock approval
- PDF report generation
- QR code fridge identification
- AI-based stock prediction
- REST API integration
- Serializers and API endpoints
- Unit and API tests

---

## System Modules

The Django system contains the following main modules:

- Institutions
- Fridges
- Products
- Fridge Slots
- Sensor Readings
- Stock Readings
- Alerts
- Restock Orders
- Transactions
- AI Stock Prediction
- PDF Reports
- QR Code Identification

---

## Technologies Used

### Backend

- Python
- Django
- Django REST Framework
- SQLite / MySQL / PostgreSQL

### Frontend

- HTML
- CSS
- JavaScript
- Chart.js
- Django Templates

### IoT / Embedded System

- ESP32
- Arduino IDE
- DHT22 Sensor
- IR Sensors
- Magnetic Door Switch
- Voltage Sensor
- L298N Motor Driver
- Gear Motors
- Buzzer
- LEDs
- 12V DC Power Supply

### Integrations

- Africa's Talking SMS API
- Gmail SMTP Email Alerts
- QR Code Generation
- PDF Report Generation

---

## Project Structure

```text
DAIRYSYNC/
│
├── manage.py
├── README.md
├── .gitignore
├── requirements.txt
│
├── project/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
└── dairysync/
    ├── admin.py
    ├── apps.py
    ├── forms.py
    ├── models.py
    ├── serializers.py
    ├── tests.py
    ├── urls.py
    ├── utils.py
    ├── views.py
    │
    └── templates/
        ├── registration/
        │   └── login.html
        │
        └── dairysync/
            ├── base.html
            ├── dashboard.html
            ├── form.html
            ├── institutions.html
            ├── fridges.html
            ├── products.html
            ├── stock.html
            ├── restock_orders.html
            ├── readings.html
            ├── alerts.html
            ├── ai_prediction.html
            └── pdf_report.html