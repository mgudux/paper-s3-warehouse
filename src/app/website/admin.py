import logging
from django.contrib import admin, messages
from .models import Item, Device

logger = logging.getLogger("website.inventory")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("mac_address", "row", "top_level",
                    "left_box", "width", "height")
    search_fields = ("mac_address",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "get_device_mac", "stock", "max_stock",
                    "row", "level", "box", "created_at")
    search_fields = ("name", "device__mac_address", "row", "level", "box")
    list_filter = ("row", "level", "box")

    def get_device_mac(self, obj):
        return obj.device.mac_address
    get_device_mac.short_description = 'Device MAC'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Your existing save_model code...
