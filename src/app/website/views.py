from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from .models import Device, Item
from .forms import UpdateItemFormFull, UpdateItemFormBasic
import re


def item_search(query):
    """
    Parse digits into row, level, box.
    Args:
        R1-E3-K3, R1-B3-K3, 1-3-3, K4, B4 K4, R1, B2, etc.
    Returns filtered Items
    """
    if not query:
        return Item.objects.none()

    query = query.strip()
    row = level = box = None
    location_parsed = False

    # Find all prefix+number pairs (like "R1, B2" or "B4 K4")
    matches = re.findall(r'([RrEeLlKkBb])[\s:]*(\d+)', query)

    if matches:
        # Found prefixed values, assign based on prefix
        location_parsed = True
        for prefix, number in matches:
            if prefix.upper() in ['R']:
                row = number
            elif prefix.upper() in ['E', 'L']:
                level = number
            elif prefix.upper() in ['K', 'B']:
                box = number
    else:
        # No prefixes found, use positional parsing
        location_match = re.search(
            r'(?P<row>\d{1,3})(?:\D+(?P<level>\d{1,3})(?:\D+(?P<box>\d{1,3}))?)?',
            query
        )
        if location_match and location_match.group('row'):
            location_parsed = True
            row = location_match.group('row')
            level = location_match.group('level')
            box = location_match.group('box')

    if location_parsed:
        # Build filter to search items in database
        filters = Q()
        if row and int(row) != 0:
            filters &= Q(row=int(row))
        if level and int(level) != 0:
            filters &= Q(level=int(level))
        if box and int(box) != 0:
            filters &= Q(box=int(box))

        # Query if we have valid filters
        if filters:
            results = Item.objects.filter(filters).select_related(
                'device').order_by('row', 'level', 'box')
            if results.exists():
                return results

    # Item search by string (trigram similarity) as Fallback
    items = Item.objects.select_related('device').annotate(
        similarity=TrigramSimilarity('name', query)).filter(similarity__gt=0.15).order_by('-similarity')[:10]
    return items


def home(request):

    search_query = request.GET.get('search', '').strip()
    # If search query exists, use search results
    if search_query:
        items = item_search(search_query)
        context = {
            'search_query': search_query,
            'search_results': items,
            'is_search': True
        }
        return render(request, 'home.html', context)

    total_stats = {
        'item_count': Item.objects.all().count(),
        'critical_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Critical"),
        'low_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Low"),
        'good_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Good")
    }

    devices_with_items = []
    for device in Device.objects.all():
        items = Item.objects.filter(device=device)
        devices_with_items.append({
            'device': device,
            'items': items,
            'item_count': items.count(),
            'critical_count': sum(1 for item in items if item.stock_status() == "Critical"),
            'low_count': sum(1 for item in items if item.stock_status() == "Low"),
            'good_count': sum(1 for item in items if item.stock_status() == "Good")
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
        else:
            messages.warning(request, "Invalid form, please try again.")
    else:
        form = FormClass(instance=item)
    return render(request, "update_item.html", {"form": form})


def analytics(request):
    return redirect('home')


def stock_history(request):
    return redirect('home')


def backup_restore(request):
    return redirect('home')


def firmware_generator():
    pass


def health_check():
    pass
