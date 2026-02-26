import os
import sys
import gc
import json
import time
import machine
import network
import M5
from M5 import *
from m5ble import *

# ============================================================================
# CONFIGURATION
# ============================================================================
# Disable serial output to save power
PRODUCTION_MODE = True

SCREEN_WIDTH = 960
SCREEN_HEIGHT = 540
RAW_TOUCH_W = 540
RAW_TOUCH_H = 960
INVENTORY_FILE = "/flash/inventory.json"
DEVICE_NAME = "PaperS3-Inventory"
CONFIG_CHECK_INTERVAL_MS = 10000
AUTO_CONFIRM_DELAY_MS = 10000  # Auto-send after 10s idle
INACTIVITY_TIMEOUT_MS = 90000  # Power off after 90s idle

# UUIDs
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

DEFAULT_INVENTORY = [
    {"chest_id": "temp_1", "item": "Placeholder 1", "current": 1, "min_stock": 1},
    {"chest_id": "temp_2", "item": "Placeholder 2", "current": 1, "min_stock": 1},
    {"chest_id": "temp_3", "item": "Placeholder 3", "current": 1, "min_stock": 1},
    {"chest_id": "temp_4", "item": "Placeholder 4", "current": 1, "min_stock": 1},
    {"chest_id": "temp_5", "item": "Placeholder 5", "current": 1, "min_stock": 1},
    {"chest_id": "temp_6", "item": "Placeholder 6", "current": 1, "min_stock": 1},
]

COLOR_BLACK = 0x000000
COLOR_WHITE = 0xFFFFFF
COLOR_GRAY = 0x808080
COLOR_DARK_GRAY = 0x404040

DEBOUNCE_MS = 50
TAP_DEBOUNCE_MS = 350

# ============================================================================
# UTILITIES & DEBUGGING
# ============================================================================


def log(message):
    # Skip logging in production mode
    if PRODUCTION_MODE:
        return
    try:
        print("[{}] {}".format(time.ticks_ms(), message))
    except:
        pass


def debug_log(tag, message):
    if PRODUCTION_MODE:
        return
    log("DEBUG [{}]: {}".format(tag, message))


def get_timestamp():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
        t[0], t[1], t[2], t[3], t[4], t[5]
    )


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def get_battery_percentage():
    try:
        return M5.Power.getBatteryLevel()
    except:
        return 0


def _uuid_undashed(uuid_str):
    return uuid_str.replace("-", "").lower()

# ============================================================================
# TOUCH MAPPER
# ============================================================================


class TouchMapper:
    def __init__(self, rotation=1):
        self.rotation = rotation
        try:
            M5.Touch.setRotation(rotation)
        except:
            pass

    def to_screen(self, raw_point):
        if raw_point is None:
            return None
        try:
            rx = int(getattr(raw_point, "x", raw_point[0]))
            ry = int(getattr(raw_point, "y", raw_point[1]))
        except:
            return None
        x = int((ry * SCREEN_WIDTH) / RAW_TOUCH_H)
        y = int(((RAW_TOUCH_W - rx) * SCREEN_HEIGHT) / RAW_TOUCH_W)
        return clamp(x, 0, SCREEN_WIDTH - 1), clamp(y, 0, SCREEN_HEIGHT - 1)

# ============================================================================
# INVENTORY MANAGER
# ============================================================================


class InventoryManager:
    def __init__(self):
        self.items = []
        self.load()

    def load(self):
        try:
            with open(INVENTORY_FILE, 'r') as f:
                self.items = json.load(f)
                if len(self.items) != 6:
                    raise Exception("Count mismatch")
        except:
            self.initialize_defaults()

    def initialize_defaults(self):
        self.items = [item.copy() for item in DEFAULT_INVENTORY]
        self.persist()

    def persist(self):
        try:
            with open(INVENTORY_FILE, 'w') as f:
                json.dump(self.items, f)
            return True
        except Exception as e:
            log("Persist error: {}".format(e))
            return False

    def get_all_items(self):
        return self.items

    def get_item(self, chest_id):
        for item in self.items:
            if item['chest_id'] == chest_id:
                return item
        return None

    def update_local_stock(self, chest_id, delta):
        for item in self.items:
            if item['chest_id'] == chest_id:
                item['current'] = clamp(item['current'] + delta, 0, 99)
                return item['current']
        return None

    def fix_chest_id(self, old_id, new_id):
        if old_id == new_id:
            return
        log("Fixing ID: {} -> {}".format(old_id, new_id))
        for i, item in enumerate(self.items):
            if item['chest_id'] == old_id:
                self.items[i]['chest_id'] = new_id
                break
        self.persist()

    def update_from_server(self, inventory_data):
        try:
            log("Updating Inventory from Server")
            gc.collect()
            self.items = []
            for item in inventory_data:
                self.items.append({
                    'chest_id': item.get('chest_id', 'Unknown'),
                    'item': item.get('item', 'Unknown'),
                    'current': item.get('current', 0),
                    'min_stock': item.get('min_stock', 1)
                })
            self.persist()
            gc.collect()
            return True
        except Exception as e:
            log("Update error: {}".format(e))
            return False

# ============================================================================
# BLE HANDLER
# ============================================================================


class BLEHandler:
    def __init__(self):
        self.ble = None
        self.is_connected = False
        self.pending_response = None
        self._rx_buffer = bytearray()
        self._incomplete_message = ""
        self._message_queue = []

        self._uart_service_uuid = UART_SERVICE_UUID
        self._tx_uuid = UART_TX_UUID
        self._rx_uuid = UART_RX_UUID
        self._tx_uuid_nodash = _uuid_undashed(self._tx_uuid)
        self._rx_uuid_nodash = _uuid_undashed(self._rx_uuid)
        self._tx_char = None
        self._rx_char = None
        self._client_handle = None

    def _has(self, obj, name):
        try:
            return hasattr(obj, name) and (getattr(obj, name) is not None)
        except:
            return False

    def initialize(self):
        try:
            log("Initializing BLE server as {}".format(DEVICE_NAME))
            self.ble = M5BLE.Device(DEVICE_NAME)
            self.ble.server.clear_services()
            self._tx_char = self.ble.server.create_characteristic(
                self._tx_uuid, True, False, True)
            self._rx_char = self.ble.server.create_characteristic(
                self._rx_uuid, False, True, False)
            self.ble.server.add_service(self._uart_service_uuid, [
                                        self._tx_char, self._rx_char])
            self.ble.server.on_connected(self._on_connected)
            self.ble.server.on_disconnected(self._on_disconnected)
            self.ble.server.on_receive(self._on_receive)
            self.ble.server.start(500000)
            log("BLE server started")
            return True
        except Exception as e:
            log("BLE Init Error: {}".format(e))
            return False

    def _on_connected(self, args):
        try:
            _, handle = args
            self._client_handle = handle
            self.is_connected = True
            log("BLE Connected")
            self._incomplete_message = ""
            self.pending_response = None
            try:
                machine.freq(120000000)
            except:
                pass
        except:
            pass

    def _on_disconnected(self, args):
        self.is_connected = False
        self._client_handle = None
        log("BLE Disconnected")
        try:
            machine.freq(120000000)
        except:
            pass

    def _on_receive(self, args):
        try:
            _, handle = args
            self._client_handle = handle or self._client_handle
            data = None
            try:
                if self._has(self._client_handle, "read"):
                    data = self._client_handle.read(self._rx_uuid)
            except:
                pass

            if not data and self._has(self.ble.server, "read"):
                data = self.ble.server.read(self._rx_uuid)

            if data:
                self._process_rx_data(data)
        except:
            pass

    def _process_rx_data(self, data):
        try:
            if isinstance(data, (bytes, bytearray)):
                text = data.decode('utf-8', 'ignore')
            else:
                text = str(data)
            self._incomplete_message += text
            if len(self._incomplete_message) > 4096:
                self._incomplete_message = ""
                return

            while '\n' in self._incomplete_message:
                idx = self._incomplete_message.index('\n')
                raw = self._incomplete_message[:idx].strip()
                self._incomplete_message = self._incomplete_message[idx+1:]
                if raw:
                    self._try_parse_json(raw)
        except:
            pass

    def _try_parse_json(self, raw_str):
        try:
            msg = json.loads(raw_str)
            if 'ack' in msg:
                self.pending_response = msg
            if msg.get('op') == 'config_update':
                self._message_queue.append(msg)
                debug_log("BLE", "Config queued, queue size: {}".format(len(self._message_queue)))
        except:
            pass

    def _server_notify_chunk(self, chunk):
        try:
            if self._client_handle:
                self._client_handle.write(chunk, self._tx_uuid)
                return
        except:
            pass
        try:
            self.ble.server.notify(self._tx_uuid, chunk)
        except:
            pass

    def send_update(self, payload):
        if not self.is_connected:
            return None, "Not connected"
        try:
            self.pending_response = None
            self._incomplete_message = ""
            json_data = json.dumps(payload)
            debug_log("TX", "Sending: {}...".format(json_data[:20]))
            data_bytes = (json_data + '\n').encode('utf-8')

            mtu = 23
            try:
                mtu = int(self.ble.get_mtu())
            except:
                pass
            chunk_size = min(180, max(20, mtu - 3))

            for i in range(0, len(data_bytes), chunk_size):
                self._server_notify_chunk(data_bytes[i:i+chunk_size])
                time.sleep_ms(30)

            start = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), start) < 5000:
                if self.pending_response:
                    if self.pending_response.get('ack'):
                        return self.pending_response, None
                    else:
                        return None, "API Error"
                time.sleep_ms(50)
                M5.update()
            return None, "Timeout"
        except Exception as e:
            return None, str(e)

    def request_config_check(self):
        if not self.is_connected:
            return False
        try:
            self.send_update({"op": "check_config"})
            return True
        except:
            return False

    def get_next_message(self):
        if self._message_queue:
            return self._message_queue.pop(0)
        return None

# ============================================================================
# UI MANAGER (GRID LAYOUT)
# ============================================================================


class InventoryUI:
    def __init__(self):
        self.tiles = []
        self.touch = TouchMapper(rotation=1)
        self.last_touch_xy = None
        self.touch_down_ms = 0
        self.on_interaction = None

    def _wrap_text(self, text, max_chars=10):
        if not text:
            return [""]

        # Split long words first
        words = text.split(' ')
        processed_words = []
        for w in words:
            if len(w) > max_chars:
                # Break into chunks
                for i in range(0, len(w), max_chars):
                    processed_words.append(w[i:i+max_chars])
            else:
                processed_words.append(w)

        # Reassemble into wrapped lines
        lines = []
        curr = ""
        for w in processed_words:
            # Fit words within line limit
            if len(curr) + len(w) + (1 if curr else 0) <= max_chars:
                curr += (" " if curr else "") + w
            else:
                if curr:
                    lines.append(curr)
                curr = w
        if curr:
            lines.append(curr)

        return lines[:2]

    def setup_grid(self, items):
        M5.Lcd.fillScreen(COLOR_WHITE)
        self.tiles = []

        # 3x2 grid layout
        tile_w = SCREEN_WIDTH // 3
        tile_h = SCREEN_HEIGHT // 2

        # Draw grid separators
        M5.Lcd.drawLine(tile_w, 0, tile_w, SCREEN_HEIGHT, COLOR_BLACK)
        M5.Lcd.drawLine(tile_w * 2, 0, tile_w * 2, SCREEN_HEIGHT, COLOR_BLACK)
        M5.Lcd.drawLine(0, tile_h, SCREEN_WIDTH, tile_h, COLOR_BLACK)

        positions = [
            (0, 0), (tile_w, 0), (tile_w*2, 0),
            (0, tile_h), (tile_w, tile_h), (tile_w*2, tile_h)
        ]

        for i, item in enumerate(items[:6]):
            x, y = positions[i]
            self._draw_tile_static(x, y, tile_w, tile_h, item)

            btn_size = 90
            btn_y = y + 180

            # Define touch zones
            minus_rect = (x + 15, btn_y, btn_size + 10, btn_size + 10)
            plus_rect = (x + tile_w - btn_size - 25, btn_y,
                         btn_size + 10, btn_size + 10)

            self.tiles.append({
                'chest_id': item['chest_id'],
                'rect': (x, y, tile_w, tile_h),
                'minus_zone': minus_rect,
                'plus_zone': plus_rect,
                'count_center': (x + (tile_w // 2), btn_y + 45)
            })

            self.update_tile_count(item['chest_id'], item['current'])

    def _draw_tile_static(self, x, y, w, h, item):
        # Item name (large font)
        M5.Lcd.setTextColor(COLOR_BLACK, COLOR_WHITE)
        M5.Lcd.setTextSize(4)

        lines = self._wrap_text(item['item'], max_chars=10)

        text_y = y + 15
        for line in lines:
            M5.Lcd.setCursor(x + 15, text_y)
            M5.Lcd.print(line)
            text_y += 45

        # Chest ID (left-aligned)
        M5.Lcd.setTextColor(COLOR_DARK_GRAY, COLOR_WHITE)
        M5.Lcd.setTextSize(3)
        loc_y = text_y + 15
        M5.Lcd.setCursor(x + 15, loc_y)
        M5.Lcd.print(item['chest_id'])

        # Min stock (right-aligned)
        min_val = item.get('min_stock', 0)
        if min_val > 0:
            min_str = "Min: " + str(min_val)
            # Calc text width (size 3 ≈ 18px/char)
            str_w = len(min_str) * 18
            min_x = x + w - str_w - 15
            M5.Lcd.setCursor(min_x, loc_y)
            M5.Lcd.print(min_str)

        # Buttons (bottom-anchored)
        btn_size = 90
        btn_y = y + 180

        # Minus Box
        M5.Lcd.fillRect(x + 20, btn_y, btn_size, btn_size, COLOR_BLACK)
        M5.Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
        M5.Lcd.setTextSize(5)
        M5.Lcd.setCursor(x + 45, btn_y + 25)
        M5.Lcd.print("-")

        # Plus Box
        plus_x = x + w - btn_size - 20
        M5.Lcd.fillRect(plus_x, btn_y, btn_size, btn_size, COLOR_BLACK)
        M5.Lcd.setCursor(plus_x + 25, btn_y + 25)
        M5.Lcd.print("+")

    def update_tile_count(self, chest_id, count):
        tile = None
        for t in self.tiles:
            if t['chest_id'] == chest_id:
                tile = t
                break
        if not tile:
            return

        cx, cy = tile['count_center']

        # Render count (padded to clear old digits)
        M5.Lcd.setTextColor(COLOR_BLACK, COLOR_WHITE)
        M5.Lcd.setTextSize(5)
        s = "{:^3}".format(count)  # Center-padded to 3 chars
        text_w = 3 * 30
        M5.Lcd.setCursor(cx - (text_w // 2), cy - 20)
        M5.Lcd.print(s)

    def _hit(self, x, y, rect):
        bx, by, bw, bh = rect
        return bx <= x < bx + bw and by <= y < by + bh

    def update(self):
        if M5.Touch.getCount() > 0:
            raw = M5.Touch.getTouchPointRaw()
            xy = self.touch.to_screen(raw)
            if xy:
                x, y = xy
                now = time.ticks_ms()
                if (now - self.touch_down_ms) > TAP_DEBOUNCE_MS:
                    self.touch_down_ms = now
                    self._handle_tap(x, y)

    def _handle_tap(self, x, y):
        for t in self.tiles:
            if self._hit(x, y, t['minus_zone']):
                if self.on_interaction:
                    self.on_interaction(t['chest_id'], -1)
                return
            if self._hit(x, y, t['plus_zone']):
                if self.on_interaction:
                    self.on_interaction(t['chest_id'], 1)
                return

# ============================================================================
# APP LOGIC
# ============================================================================


class InventoryApp:
    def __init__(self):
        self.inventory = InventoryManager()
        self.ui = InventoryUI()
        self.ble = BLEHandler()
        self.running = True
        self.last_activity = time.ticks_ms()
        self.last_config_check = 0
        self.pending_updates = {}

    def kill_peripherals(self):
        """Disable unused hardware to save power."""
        # Disable speaker amp
        try:
            M5.Speaker.end()
        except:
            # Fallback: mute
            try:
                M5.Speaker.setVolume(0)
            except:
                pass

        # Disable mic
        try:
            M5.Mic.end()
        except:
            pass

        # Disable LED
        try:
            M5.Power.setLed(0)
        except:
            pass

        # Disable vibration
        try:
            M5.Power.setVibration(0)
        except:
            pass

        # Disable Grove port power
        try:
            M5.Power.setExtOutput(False)
        except:
            pass

    def setup(self):
        # Disable WiFi (major power saving)
        try:
            wlan = network.WLAN(network.STA_IF)
            wlan.active(False)
            wlan_ap = network.WLAN(network.AP_IF)
            wlan_ap.active(False)
        except:
            pass

        # Set low CPU freq before init
        try:
            machine.freq(120000000)  # 120MHz (stable low-power)
        except:
            pass

        M5.begin()

        # Disable unused hardware post-init
        self.kill_peripherals()

        M5.Lcd.setRotation(1)
        self.ble.initialize()
        self.ui.on_interaction = self.handle_interaction
        self.ui.setup_grid(self.inventory.get_all_items())

    def handle_interaction(self, chest_id, delta):
        self.last_activity = time.ticks_ms()
        new_val = self.inventory.update_local_stock(chest_id, delta)
        if new_val is None:
            return

        self.ui.update_tile_count(chest_id, new_val)

        self.pending_updates[chest_id] = {
            'ts': time.ticks_ms(),
            'count': new_val,
            'item_name': self.inventory.get_item(chest_id)['item']
        }

    def process_pending_updates(self):
        now = time.ticks_ms()
        to_remove = []
        for chest_id, data in self.pending_updates.items():
            if time.ticks_diff(now, data['ts']) > AUTO_CONFIRM_DELAY_MS:
                log("Auto-saving {}".format(chest_id))
                self.send_update(chest_id, data['item_name'], data['count'])
                to_remove.append(chest_id)
        for cid in to_remove:
            del self.pending_updates[cid]

    def send_update(self, chest_id, item_name, count):
        payload = {
            "op": "inventory_update",
            "chest_id": chest_id,
            "item": item_name,
            "current": count,
            "batt": get_battery_percentage(),
            "ts": get_timestamp()
        }
        ack, error = self.ble.send_update(payload)
        if ack:
            log("Save success: {}".format(chest_id))
            self.inventory.persist()
            if 'correct_chest_id' in ack:
                new_id = ack['correct_chest_id']
                if new_id != chest_id:
                    self.inventory.fix_chest_id(chest_id, new_id)
                    self.ui.setup_grid(self.inventory.get_all_items())
        else:
            log("Save failed: {}".format(error))

    def check_for_config_updates(self):
        if len(self.pending_updates) > 0:
            return
        now = time.ticks_ms()
        if self.ble.is_connected and time.ticks_diff(now, self.last_config_check) > CONFIG_CHECK_INTERVAL_MS:
            self.last_config_check = now
            self.ble.request_config_check()

    def run(self):
        while self.running:
            time.sleep_ms(20)
            M5.update()
            self.ui.update()
            self.process_pending_updates()

            # Process queued config updates
            processed_config = False
            msg_count = 0
            while True:
                msg = self.ble.get_next_message()
                if not msg:
                    break

                msg_count += 1
                if msg.get('op') == 'config_update':
                    log("Config received (#{})".format(msg_count))
                    if len(self.pending_updates) == 0:
                        if self.inventory.update_from_server(msg.get('data', [])):
                            processed_config = True
                            self.last_activity = time.ticks_ms()
                    else:
                        log("Skipped: pending updates exist")

            # Redraw after config processing
            if processed_config:
                log("Processed {} config msgs, refreshing display...".format(msg_count))
                self.ui.setup_grid(self.inventory.get_all_items())
                M5.update()
                time.sleep_ms(100)  # E-ink refresh delay
                M5.update()
                log("Display refreshed")

            self.check_for_config_updates()

            # Auto power-off on timeout
            if time.ticks_diff(time.ticks_ms(), self.last_activity) > INACTIVITY_TIMEOUT_MS:
                log("Timeout. Powering off.")

                # Cleanup BLE
                if self.ble.ble and self.ble.ble.server:
                    try:
                        self.ble.ble.server.stop()
                    except:
                        pass

                # Hard shutdown (button wake only)
                M5.Power.powerOff()


if __name__ == '__main__':
    app = InventoryApp()
    app.setup()
    app.run()
