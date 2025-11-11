import logging
from django.contrib import admin, messages
from .models import Item, Device

logger = logging.getLogger("website.inventory")


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("get_name", "mac_address", "row", "bottom_level", "left_box",
                    "height", "width", "created_at")
    search_fields = ("mac_address",)
    list_filter = ("row", "height", "width")

    @admin.display(description="Name")
    def get_name(self, obj):
        return obj.__str__()


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "get_device_name", "get_device_mac", "stock", "min_stock",
                    "row", "level", "box", "last_modified")
    search_fields = ("name", "device__mac_address", "row", "level", "box")
    list_filter = ("row", "level", "box")

    @admin.display(description="Device MAC", ordering="device__mac_address")
    def get_device_mac(self, obj):
        return obj.device.mac_address if obj.device else None

    @admin.display(description="Device Name")
    def get_device_name(self, obj):
        return obj.device.__str__() if obj.device else None

    @admin.display(description="Device Name")
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.stock_status() in ["Low", "Critical"]:
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
                f"Stock {obj.stock_status()}: Item '{obj.name}' at {location} has stock {obj.stock} below the minimum of {obj.min_stock}.",
                level=messages.WARNING,
            )
