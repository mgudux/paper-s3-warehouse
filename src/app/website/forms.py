from django import forms
from . import models


class UpdateItemFormFull(forms.ModelForm):
    class Meta:
        model = models.Item
        fields = ["name", "stock", "min_stock"]


class UpdateItemFormBasic(forms.ModelForm):
    class Meta:
        model = models.Item
        fields = ["stock"]


class UpdateDeviceForm(forms.ModelForm):
    class Meta:
        model = models.Device
        fields = ["row", "bottom_level", "left_box"]
        widgets = {
            'row': forms.Select(choices=[(i, str(i)) for i in range(1, 7)]),
            'bottom_level': forms.Select(choices=[(1, '1'), (3, '3')]),
            'left_box': forms.Select(choices=[(1, '1'), (4, '4')]),
        }
