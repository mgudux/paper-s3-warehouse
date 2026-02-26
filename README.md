# Warehouse Digital

A warehouse inventory system built around the PaperS3. Each display sits on a shelf and shows what's stored there, tap to add or remove stock and the backend updates automatically over Bluetooth Low Energy with a range of 50+ meters.

Warehouse workers can update stock counts directly at the shelf without needing a scanner, a phone or a PC. The e-paper screens hold their image with no power draw and the whole thing runs for years on a battery.

The firmware is fully functional and complete. Other files resemble a prototype, that is fully functional but it doesn't include some features meant for production (Quick flashing, USB detection, Export etc.)

Here's a quick 1 minute preview:
---


https://github.com/user-attachments/assets/7dcdffc9-c973-4dbe-a684-dd5da1b88f28

## Project Structure

```
├── src/
│   ├── app/               Django backend (web interface + API)
│   └── firmware/          MicroPython code for the M5Stack Paper S3
├── docker-compose.yml     Spins up PostgreSQL for local dev
├── Dockerfile             Production container for the web app
└── start-server.sh        Convenience script for local development
```

**Backend** (`src/app/`), a Django app with a PostgreSQL database. Handles the web UI, the REST API that the BLE bridge talks to, stock history tracking via `django-simple-history`, and database backups.

**Firmware** (`src/firmware/`), MicroPython running on the M5Stack Paper S3. Displays a 3×2 grid of items with current and minimum stock counts as well as two buttons to change current stock. Communicates over BLE (Nordic UART Service). Powers itself off after 90 seconds of inactivity to save battery.

**BLE Bridge** (`src/app/website/ble_bridge.py`), a Python script that runs on a host machine (Raspberry Pi works well). Scans for the e-paper devices, handles the BLE connections, and relays inventory updates to the Django API. Supports multiple devices simultaneously.

---

## How it works

1. A device wakes up when someone taps it
2. The worker taps `+` or `-` to adjust the count for an item
3. After 10 seconds of no further input, the device sends the updated count over BLE to the bridge
4. The bridge forwards it to the Django API
5. The API saves the change and sends back the current config (item names, min stock levels, chest IDs)
6. The device updates its local inventory file and goes back to sleep

The web interface lets you see all devices and items at a glance, grouped by warehouse row. You can filter by stock status (critical/low/good), search by item name or location code (e.g. `R1-E2-K3`) and view the full change history.

---

## Setup

### Requirements

- Python 3.11 or newer
- Docker (required for PostgreSQL)
- A `.env` file with your database credentials (see below)

### Environment variables

Create a `.env` file in the project root and add it to gitignore:

```
POSTGRES_DB=lager
POSTGRES_USER=lager
POSTGRES_PASSWORD=yourpassword
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### Running locally

```bash
./start-server.sh
```

This starts the database container and runs the Django dev server. Use `--build` the first time or after changing dependencies.

```bash
./start-server.sh --build
```

### Running in production

```bash
docker compose up --build
```

The web app runs on port 8000. You'll want to put nginx in front of it.

---

## Hardware

The firmware targets the **M5Stack Paper S3**, an ESP32-S3 with a 9.7" e-paper display and a 2000mAh battery. The touch panel is a 3×2 grid (each cell is one shelf location).

Each device covers a 2×2 or 2×3 block of shelf positions (height × width). The position is configured in the web UI, you set the row, the bottom level, and the leftmost box column. The device figures out which items belong to it based on that footprint.

---

## The location system

Shelf positions are described in german language (you can change this as you like) as `R{row}-E{level}-K{box}`:
- **R**, Reihe (row), 1–6
- **E**, Ebene (level), 1–4
- **K**, Kiste (box/column), 1–6

The search understands these codes. You can search for `R1`, `R1-E2`, `R1-E2-K3`, or just type an item name and it will use trigram similarity to find close matches. You can modify the sensivity in the code.

---

## Features

- **Web dashboard**, live stock overview grouped by row and device, with collapsible rows
- **Stock history**, full audit trail of every stock change and device reconfiguration
- **Analytics**, top 10 most consumed items and most frequently critical items (90-day window)
- **Device management**, configure device positions via the UI; swapping two devices' positions is handled automatically
- **Database backups**, manual and automatic (daily at 00:01), keeps the last 50, restore from the UI
- **OTA firmware updates**, serve `main.py` from the web server; devices pick it up on next boot via `boot.py`
- Warning: Some Endpoints in URL are not accessible as some files are confidental. You can either remove those endpoints or add/change them.

---

## Notes

- The BLE bridge (`ble_bridge.py`) is meant to run as a persistent process on a machine in the warehouse. It reconnects automatically if a device drops.
- `django-simple-history` tracks changes to both `Item` and `Device` models. The history tables are `item_history` and `device_history`.
- The `SECRET_KEY` in `settings.py` is the default Django insecure key for local dev, replace it before deploying anywhere.
- Stock validation happens in `stock_status()`: critical is ≤1 or ≤25% of min stock, low is anything below min stock.
