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
