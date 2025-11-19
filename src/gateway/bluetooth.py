"""TODO: Implement BLE UART client to forward device updates to backend APIs."""

import asyncio  # noqa: F401

from aiohttp import ClientSession  # noqa: F401
from bleak import BleakClient  # noqa: F401
import shared.common as shared_common  # noqa: F401

# Coordinate BLE device discovery, message parsing, and HTTP forwarding routines here.
