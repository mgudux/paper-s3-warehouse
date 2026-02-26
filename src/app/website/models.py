from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from simple_history.models import HistoricalRecords, HistoricForeignKey
from django.db import models

ALLOWED_SIZES = {(2, 2), (2, 3)}  # (height, width) device grid sizes


class Device(models.Model):
    max_rows = 6  # Warehouse row limit

    created_at = models.DateTimeField(auto_now_add=True)
    mac_address = models.CharField(max_length=50, unique=True)

    # Allow row=0 for unassigned devices
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)]
    )
    bottom_level = models.PositiveIntegerField(  # Bottom-most level
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    left_box = models.PositiveIntegerField(  # Left-most box column
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    height = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(2)]
    )
    width = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(3)]
    )
    battery_level = models.PositiveIntegerField(
        null=True, blank=True,
        validators=[MaxValueValidator(100)]
    )
    history = HistoricalRecords(table_name="device_history")

    def footprint_boxes(self):
        """Returns set of (row, level, box) tuples occupied by this device."""
        # Row 0 = no grid footprint
        if self.row == 0:
            return []

        levels = range(self.bottom_level, self.bottom_level + self.height)
        boxes = range(self.left_box, self.left_box + self.width)
        return (
            (self.row, level, box)
            for level in levels
            for box in boxes
        )

    def __str__(self):
        top_level = self.bottom_level + self.height - 1
        right_box = self.left_box + self.width - 1
        return f"MAC: {self.mac_address} | R{self.row} | E{self.bottom_level}-{top_level} | K{self.left_box}-{right_box} |"

    def clean(self):
        super().clean()
        if (self.height, self.width) not in ALLOWED_SIZES:
            raise ValidationError(
                "Unsupported touch-zone layout, choose 2 as height and 2 or 3 as width")


class Item(models.Model):
    last_modified = models.DateTimeField(auto_now=True)
    device = HistoricForeignKey(Device, on_delete=models.CASCADE)
    name = models.CharField(max_length=20)
    stock = models.PositiveIntegerField(
        validators=[MaxValueValidator(99)]
    )
    min_stock = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )

    # Allow row=0 for warehouse entrance items
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(6)]
    )
    level = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    box = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    history = HistoricalRecords(
        table_name="item_history",
        excluded_fields=['last_modified'],
    )

    def __str__(self):
        return f"{self.name} ({self.stock})"

    def location_label(self):
        if self.row == 0:
            return "Lager-Eingang (R0)"
        return f"R{self.row}-E{self.level}-K{self.box}"

    def stock_status(self):
        if self.stock <= 1 or self.stock <= round(self.min_stock * 0.25):
            return "Critical"
        elif self.stock < self.min_stock:
            return "Low"
        else:
            return "Good"

    def clean(self):
        super().clean()
        if self.row == 0:
            return

        if (self.row, self.level, self.box) not in set(self.device.footprint_boxes()):
            pass
