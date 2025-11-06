from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

ALLOWED_SIZES = {(1, 1), (2, 2), (2, 3), (2, 4)}  # height, width


class Device(models.Model):
    mac_address = models.CharField(max_length=50, unique=True)
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    top_level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    left_box = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    width = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    height = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )

    def footprint_boxes(self):
        levels = range(self.top_level, self.top_level + self.height)
        boxes = range(self.left_box, self.left_box + self.width)
        return (
            (self.row, level, box)
            for level in levels
            for box in boxes
        )

    def layout(self):
        return self.width, self.height


class Item(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    stock = models.PositiveIntegerField()
    max_stock = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    box = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )

    def __str__(self):
        device_mac = getattr(self.device, "mac_address", "?")
        return (
            f"{self.name} {self.stock}/{self.max_stock} "
            f"R{self.row} L{self.level} B{self.box} {device_mac}"
        )

    def location_label(self):
        return f"R{self.row}-E{self.level}-K{self.box}"

    def is_full(self):
        return self.stock is not None and self.stock >= (self.max_stock or 0)

    def clean(self):
        super().clean()
        if self.device.layout() not in ALLOWED_SIZES:
            raise ValidationError(
                "Unsupported touch-zone layout from device script."
            )
        if (self.row, self.level, self.box) not in set(self.device.footprint_boxes()):
            raise ValidationError("Box lies outside the device footprint.")
