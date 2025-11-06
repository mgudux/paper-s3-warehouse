from django import forms
from .models import Item


class UpdateItemForm(forms.ModelForm):
    class Meta:
        model = Item
        # editable fields
        fields = ["name", "stock", "max_stock", "row", "level", "box"]
