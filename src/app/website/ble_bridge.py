import asyncio
import json
import logging
import sys
import time
import hashlib
from typing import Optional, Dict, Set

import aiohttp
from bleak import BleakScanner, BleakClient

DEVICE_NAME_PREFIX = "PaperS3-Inventory"  # BLE device name prefix
API_BASE_URL = "http://127.0.0.1:8000"

# API Paths
URL_REGISTER = "/api/devices/register"
URL_UPDATE_INVENTORY = "/api/inventory/update"
URL_CHECK_UPDATES = "/api/devices/{}/updates"

# Nordic UART Service UUIDs
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# Chunk settings
BLE_CHUNK_SIZE = 20
CHUNK_DELAY_MS = 20

# Periodic config sync interval (in secs)
CONFIG_CHECK_INTERVAL = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Bridge")


=========================================


class DeviceHandler:
    """Handles a single device connection, independently"""

    def __init__(self, address, api_url):
        self.address = address
        self.api_url = api_url
        self.client: Optional[BleakClient] = None
        self.rx_buffer = bytearray()
        self.last_config_hash = None
        self.log = logging.getLogger(f"Dev-{address[-5:]}")
        self.last_send_time = 0

    def _compute_inventory_hash(self, inventory: list) -> str:
        data = json.dumps(inventory, sort_keys=True)
        return hashlib.md5(data.encode()).hexdigest()

    async def run(self):
        self.log.info(f"Connecting to {self.address}...")

        try:
            async with BleakClient(self.address, timeout=20.0) as client:
                self.client = client
                self.log.info("✓ Connected")

                await client.start_notify(UART_TX_UUID, self.notification_handler)

                # Register with server
                await self.register_device()

                # Start periodic config sync
                config_task = asyncio.create_task(self.periodic_config_check())

                # Keep-alive loop
                while client.is_connected:
                    await asyncio.sleep(1.0)

                config_task.cancel()

        except Exception as e:
            self.log.error(f"Connection error: {e}")
        finally:
            self.log.info("Disconnected")

    def notification_handler(self, sender, data: bytearray):
        try:
            self.rx_buffer.extend(data)
            while b"\n" in self.rx_buffer:
                idx = self.rx_buffer.index(b"\n")
                msg = self.rx_buffer[:idx]
                self.rx_buffer = self.rx_buffer[idx + 1:]
                if msg:
                    asyncio.create_task(self.process_message(msg))
        except Exception as e:
            self.log.error(f"RX Error: {e}")

    async def process_message(self, message: bytearray):
        try:
            json_str = message.decode("utf-8").strip()
            if not json_str:
                return

            payload = json.loads(json_str)
            op = payload.get("op")

            if op == "inventory_update":
                await self.handle_inventory_update(payload)
            elif op == "check_config":
                await self.send_response({"ack": True})
                await self.check_and_send_config_updates()

        except Exception as e:
            self.log.error(f"Msg Error: {e}")

    async def handle_inventory_update(self, payload: dict):
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}{URL_UPDATE_INVENTORY}"
                api_payload = {
                    "chest_id": payload.get('chest_id'),
                    "item": payload.get("item"),
                    "current": payload.get("current"),
                    "batt": payload.get("batt"),
                    "ts": payload.get("ts"),
                }

                async with session.post(url, json=api_payload) as response:
                    if response.status == 200:
                        res = await response.json()
                        self.log.info(f"✓ Updated {payload.get('chest_id')}")

                        ack = {"ack": True}
                        if "correct_chest_id" in res:
                            ack["correct_chest_id"] = res["correct_chest_id"]

                        await self.send_response(ack)

                        # Device processing delay
                        await asyncio.sleep(0.2)
                        await self.check_and_send_config_updates()
                    else:
                        self.log.error(f"API Error: {response.status}")
                        await self.send_response({"ack": False, "error": "API Error"})

        except Exception as e:
            self.log.error(f"Update failed: {e}")
            await self.send_response({"ack": False, "error": "Conn Error"})

    async def check_and_send_config_updates(self):
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}{URL_CHECK_UPDATES.format(self.address)}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        inv = data.get("inventory", [])
                        new_hash = self._compute_inventory_hash(inv)

                        if new_hash != self.last_config_hash:
                            self.log.info(f"Config changed (hash: {new_hash[:8]}), updating device")
                            await self.send_response({"op": "config_update", "data": inv})
                            self.last_config_hash = new_hash
                        else:
                            self.log.debug("Config unchanged, no update sent")
        except Exception as e:
            self.log.error(f"Config check failed: {e}")

    async def periodic_config_check(self):
        while True:
            await asyncio.sleep(CONFIG_CHECK_INTERVAL)
            if self.client and self.client.is_connected:
                await self.check_and_send_config_updates()

    async def register_device(self):
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}{URL_REGISTER}"
                async with session.post(url, json={"mac_address": self.address}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        inv = data.get("inventory", [])
                        self.last_config_hash = self._compute_inventory_hash(
                            inv)
                        await self.send_response({"op": "config_update", "data": inv})
                        self.log.info("Registered & Configured")
        except Exception as e:
            self.log.error(f"Registration failed: {e}")

    async def send_response(self, response: dict):
        if not self.client or not self.client.is_connected:
            return

        try:
            json_str = json.dumps(response)
            data = (json_str + "\n").encode("utf-8")

            # Per-device rate limiting
            now = time.time()
            if now - self.last_send_time < 0.05:
                await asyncio.sleep(0.05)

            for i in range(0, len(data), BLE_CHUNK_SIZE):
                chunk = data[i:i+BLE_CHUNK_SIZE]
                await self.client.write_gatt_char(UART_RX_UUID, chunk, response=True)
                await asyncio.sleep(CHUNK_DELAY_MS / 1000.0)

            self.last_send_time = time.time()
        except Exception as e:
            self.log.error(f"TX Failed: {e}")


class BridgeManager:
    def __init__(self):
        self.active_devices: Dict[str, asyncio.Task] = {}

    async def run(self):
        logger.info("========================================")
        logger.info("   Multi-Device BLE Bridge Started")
        logger.info("========================================")

        while True:
            try:
                # Scan for BLE devices
                devices = await BleakScanner.discover(timeout=5.0)

                # Filter by name prefix
                target_devices = [
                    d for d in devices
                    if d.name and (d.name == DEVICE_NAME_PREFIX or d.name.startswith(DEVICE_NAME_PREFIX))
                ]

                # Connect to discovered devices
                for dev in target_devices:
                    addr = dev.address

                    # Skip if already connected
                    if addr not in self.active_devices:
                        logger.info(f"Found new device: {dev.name} ({addr})")

                        # Spawn handler task
                        handler = DeviceHandler(addr, API_BASE_URL)
                        task = asyncio.create_task(handler.run())

                        # Cleanup callback on disconnect
                        task.add_done_callback(
                            lambda t, a=addr: self.cleanup_device(a))

                        self.active_devices[addr] = task

                # Status logging
                if self.active_devices:
                    logger.info(
                        f"Active connections: {len(self.active_devices)}")
                else:
                    logger.debug("No devices connected. Scanning...")

            except Exception as e:
                logger.error(f"Scanner loop error: {e}")

            # Scan interval
            await asyncio.sleep(5.0)

    def cleanup_device(self, address):
        """Cleanup on device disconnect."""
        if address in self.active_devices:
            logger.info(f"Cleaning up task for {address}")
            del self.active_devices[address]


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy())

    while True:
        try:
            manager = BridgeManager()
            asyncio.run(manager.run())
        except KeyboardInterrupt:
            logger.info("Bridge stopped by user.")
            break
        except Exception as e:
            logger.error(f"BRIDGE CRASHED: {e}")
            logger.info("Restarting bridge in 5 seconds...")
            time.sleep(5)
