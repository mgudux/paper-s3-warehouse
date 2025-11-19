from django import forms
from . import models


class UpdateItemFormFull(forms.ModelForm):
    class Meta:
        model = models.Item
        fields = ["name", "stock", "min_stock"]
        labels = {
            'name': 'Item Name',
            'stock': 'Current Stock',
            'min_stock': 'Minimum Stock',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter item name'}),
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter current stock'}),
            'min_stock': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter minimum stock'}),
        }


class UpdateItemFormBasic(forms.ModelForm):
    class Meta:
        model = models.Item
        fields = ["stock"]
        labels = {
            'stock': 'Current Stock',
        }
        widgets = {
            'stock': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter current stock'}),
        }


class UpdateDeviceForm(forms.ModelForm):
    class Meta:
        model = models.Device
        fields = ["bottom_level", "left_box"]
        labels = {
            'bottom_level': 'Unterste Ebene (Bottom Level)',
            'left_box': 'Linke Kiste (Left Box)',
        }
        help_texts = {
            'bottom_level': 'Die unterste Ebene, auf der das Gerät beginnt (1 oder 3). Das Gerät hat immer eine Höhe von 2 Ebenen.',
            'left_box': 'Die am weitesten links liegende Kiste, bei der das Gerät beginnt (1 oder 4). Das Gerät hat immer eine Breite von 3 Kisten.',
        }
        widgets = {
            'bottom_level': forms.Select(
                choices=[(1, '1'), (3, '3')],
                attrs={'class': 'form-select'}
            ),
            'left_box': forms.Select(
                choices=[(1, '1'), (4, '4')],
                attrs={'class': 'form-select'}
            ),
        }
