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
