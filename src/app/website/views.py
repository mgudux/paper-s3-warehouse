from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Item
from .forms import UpdateItemForm


def home(request):
    items = Item.objects.all()

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, "You have been logged in.")
            return redirect('home')

        messages.error(request, "There was an error logging in, try again.")

    return render(request, 'home.html', {'items': items})


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
    if request.method == "POST":
        form = UpdateItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Item has been updated!")
            return redirect('home')
        messages.warning(request, "Invalid form, please try again.")
    else:
        form = UpdateItemForm(instance=item)
    return render(request, "update_item.html", {"form": form})


def firmware_generator():
    pass


def inventory_update():
    pass


def health_check():
    pass
