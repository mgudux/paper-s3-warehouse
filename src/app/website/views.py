from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import Device, Item
from .forms import UpdateItemFormFull, UpdateItemFormBasic


def home(request):
    # Groups Items by non-empty Devices
    devices_with_items = []

    for device in Device.objects.all():
        items = Item.objects.filter(device=device)
        devices_with_items.append({
            'device': device,
            'items': items,
            'item_count': items.count(),
            'critical_count': sum(1 for item in items if item.stock_status() == "Critical"),
            'low_count': sum(1 for item in items if item.stock_status() == "Low")
        })

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "You have been logged in.")
            return redirect('home')

        messages.error(request, "There was an error logging in, try again.")

    return render(request, 'home.html', {'devices_with_items': devices_with_items})


def logout_user(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('home')


def login_user(request):
    return redirect('home')


def show_item_details(request, pk):
    item_details = Item.objects.get(id=pk)
    return render(request, 'item.html', {'item_details': item_details})


def update_item(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if request.user.is_authenticated:
        FormClass = UpdateItemFormFull
    else:
        FormClass = UpdateItemFormBasic
    if request.method == "POST":
        form = FormClass(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Item has been updated!")
            return redirect('home')
        messages.warning(request, "Invalid form, please try again.")
    else:
        form = FormClass(instance=item)
    return render(request, "update_item.html", {"form": form})


def firmware_generator():
    pass


def health_check():
    pass
