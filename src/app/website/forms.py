from django import forms
from . import models


class UpdateItemForm(forms.ModelForm):
    class Meta:
        model = models.Item
        # editable fields
        fields = ["name", "stock", "min_stock", "row", "level", "box"]
