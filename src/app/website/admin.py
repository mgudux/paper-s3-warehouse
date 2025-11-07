import logging
from django.contrib import admin, messages
from .models import Item, Device

logger = logging.getLogger("website.inventory")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("mac_address", "row", "top_level", "left_box",
                    "width", "height", "get_layout")
    search_fields = ("mac_address",)
    list_filter = ("row", "width", "height")

    def get_layout(self, obj):
        """Display the device layout"""
        return f"{obj.height}x{obj.width}"
    get_layout.short_description = "Layout"


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "get_device_mac", "stock", "min_stock",
                    "row", "level", "box", "created_at")
    search_fields = ("name", "device__mac_address", "row", "level", "box")
    list_filter = ("row", "level", "box")

    def get_device_mac(self, obj):
        """Display the MAC address of the associated device"""
        return obj.device.mac_address if obj.device else "-"
    get_device_mac.short_description = "Device MAC"
    get_device_mac.admin_order_field = "device__mac_address"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.stock_status() in ["Warning", "Critical"]:
            location = obj.location_label()
            logger.warning(f"Stock {obj.stock_status()}: device_name=%s item_name=%s stock=%s min_stock=%s location=%s",
                           obj.device,
                           obj.name,
                           obj.stock,
                           obj.min_stock,
                           location,
                           )
            self.message_user(
                request,
                f"{obj.stock_status()}: Item '{obj.name}' at {location} has stock {obj.stock} below the minimum of {obj.min_stock}.",
                level=messages.WARNING,
            )
