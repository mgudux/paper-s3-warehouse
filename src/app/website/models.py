from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from simple_history.models import HistoricalRecords, HistoricForeignKey
from django.db import models

ALLOWED_SIZES = {(2, 2), (2, 3)}  # height, width of device layout


class Device(models.Model):
    max_rows = 6  # Define your warehouse boundaries
    created_at = models.DateTimeField(auto_now_add=True)
    mac_address = models.CharField(max_length=50, unique=True)
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(max_rows)]
    )
    bottom_level = models.PositiveIntegerField(  # lowest possible box (bottom most box)
        validators=[MinValueValidator(1), MaxValueValidator(3)]
    )
    left_box = models.PositiveIntegerField(  # left-most box
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    height = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(2)]
    )
    width = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(3)]
    )
    history = HistoricalRecords(table_name="device_history")

    def footprint_boxes(self):
        levels = range(self.bottom_level, self.bottom_level + self.height)
        boxes = range(self.left_box, self.left_box + self.width)
        return (
            (self.row, level, box)
            for level in levels
            for box in boxes
        )

    def __str__(self):
        return (
            f"Ebenen: {self.bottom_level}-{self.bottom_level + self.height - 1} | "
            f"Kisten: {self.left_box}-{self.left_box + self.width - 1}"
        )

    def clean(self):
        super().clean()

        if (self.height, self.width) not in ALLOWED_SIZES:
            raise ValidationError(
                "Unsupported touch-zone layout, choose 2 as height and 2 or 3 as width")

        my_footprint = set(self.footprint_boxes())
        for device in Device.objects.exclude(pk=self.pk):
            other_footprint = set(device.footprint_boxes())
            check_overlap = my_footprint & other_footprint
            if check_overlap:  # & creates a new list when an element exists in both
                locations = ", ".join(
                    [f"R{r}-E{e}-K{k}" for r, e, k in check_overlap])
                raise ValidationError(
                    f"The devices {self.__str__()} and {device.__str__()} are overlapping at location: {locations}")


class Item(models.Model):
    last_modified = models.DateTimeField(auto_now=True)
    device = HistoricForeignKey(Device, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    stock = models.PositiveIntegerField()
    min_stock = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    # Define your warehouse boundaries here
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
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
        mac_address = getattr(self.device, "mac_address", "?")
        return (
            f"{self.name} {self.stock}/{self.min_stock} "
            f"R{self.row} E{self.level} K{self.box} {mac_address}"
        )

    def location_label(self):
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
        if (self.row, self.level, self.box) not in set(self.device.footprint_boxes()):
            raise ValidationError(
                f"Box at {self.location_label} with the name {self.name} lies outside the possible device area, please reinstall the firmware on the device {self.device.__str__()}")
