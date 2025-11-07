from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

ALLOWED_SIZES = {(2, 2), (2, 3)}  # height, width of device layout


class Device(models.Model):
    mac_address = models.CharField(max_length=50, unique=True)
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    bottom_level = models.PositiveIntegerField(  # lowest possible box (bottom most box)
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    left_box = models.PositiveIntegerField(  # left-most box
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    height = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(2)]
    )
    width = models.PositiveIntegerField(
        validators=[MinValueValidator(2), MaxValueValidator(3)]
    )

    def footprint_boxes(self):
        levels = range(self.bottom_level, self.bottom_level + self.height)
        boxes = range(self.left_box, self.left_box + self.width)
        return (
            (self.row, level, box)
            for level in levels
            for box in boxes
        )

    def layout(self):
        return self.height, self.width

    def __str__(self):
        return (
            f"R{self.row}-E{self.bottom_level}-K{self.left_box} "
            f"[{self.height}x{self.width}: "
            f"E{self.bottom_level}-{self.bottom_level + self.height - 1}, "
            f"K{self.left_box}-{self.left_box + self.width - 1}]"
        )

    def clean(self):
        super().clean()
        my_footprint = set(self.footprint_boxes())
        for device in Device.objects.exclude(pk=self.pk):
            other_footprint = set(device.footprint_boxes())
            check_overlap = my_footprint & other_footprint
            if check_overlap:  # & creates a new list when an element exists in both
                locations = ", ".join(
                    [f"R{r}-E{e}-K{k}" for r, e, k in check_overlap])
                raise ValidationError(
                    f"Overlapping devices found at: {locations}")


class Item(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    stock = models.PositiveIntegerField()
    min_stock = models.PositiveIntegerField(
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
        mac_address = getattr(self.device, "mac_address", "?")
        return (
            f"{self.name} {self.stock}/{self.min_stock} "
            f"R{self.row} L{self.level} B{self.box} {mac_address}"
        )

    def location_label(self):
        return f"R{self.row}-E{self.level}-K{self.box}"

    def stock_status(self):
        if self.stock >= round(self.min_stock*1.25):
            return "Good"
        elif self.stock <= self.min_stock:
            return "Low"
        elif self.stock == 0 or self.stock <= round(self.min_stock*0.25):
            return "Critical"
        else:
            return "Normal"

    def clean(self):
        super().clean()
        if self.device.layout() not in ALLOWED_SIZES:
            raise ValidationError(
                "Unsupported touch-zone layout, choose 2 as height and 2 or 3 as width")
        if (self.row, self.level, self.box) not in set(self.device.footprint_boxes()):
            raise ValidationError(
                "Box lies outside the possible device area, check item locations")
