from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.db.models import Q
from django.contrib.postgres.search import TrigramSimilarity
from .models import Device, Item
from .forms import UpdateItemFormFull, UpdateItemFormBasic
import re


def item_search(query, search_history=False):
    """
    Parse digits into row, level, box.
    Args:
        R1-E3-K3, R1-B3-K3, 1-3-3, K4, B4 K4, R1, B2, etc.
    Returns filtered Items
    """
    if search_history:
        ItemModel = Item.history
    else:
        ItemModel = Item.objects

    if not query:
        return ItemModel.none()

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
        # No prefixes found, use location parsing
        location_match = re.search(
            r'(?P<row>\d)(?:\D*(?P<level>\d)(?:\D*(?P<box>\d))?)?',
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
            results = ItemModel.filter(filters).order_by('row', 'level', 'box')
            # Only use select_related for non-historical queries
            if not search_history:
                results = results.select_related('device')
            if results.exists():
                return results

    # Item search by string (trigram similarity) as Fallback
    if search_history:
        # Historical records don't support annotate, use simple name search
        items = ItemModel.filter(name__icontains=query).order_by('-history_date')[:10]
    else:
        items = ItemModel.annotate(
            similarity=TrigramSimilarity('name', query)).filter(similarity__gt=0.17).order_by('-similarity')[:10]
        items = items.select_related('device')
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
        'item_count': Item.objects.all().count(),  # ✅ Use Item.objects
        'critical_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Critical"),
        'low_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Low"),
        'good_count': sum(1 for item in Item.objects.all() if item.stock_status() == "Good")
    }

    rows_data = []
    for row_number in range(1, Device.max_rows):
        devices_with_items = []

        for device in Device.objects.filter(row=row_number):
            items = Item.objects.filter(device=device)
            devices_with_items.append({
                'device': device,
                'items': items,
                'item_count': items.count(),
                'critical_count': sum(1 for item in items if item.stock_status() == "Critical"),
                'low_count': sum(1 for item in items if item.stock_status() == "Low"),
                'good_count': sum(1 for item in items if item.stock_status() == "Good")
            })
        if devices_with_items:
            rows_data.append({
                'row_number': row_number,
                'devices': devices_with_items
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
    return render(request, 'home.html', {
        'rows_data': rows_data,
        'total_stats': total_stats,
    })


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
    from itertools import chain
    from operator import attrgetter

    search_query = request.GET.get('search', '')

    item_history = Item.history.all()
    device_history = Device.history.all()

    if search_query:
        item_history = item_search(search_query, search_history=True)
        device_history = Device.history.none()

    combined_history = list(chain(item_history, device_history))
    combined_history = sorted(
        combined_history,
        key=attrgetter('history_date'),
        reverse=True
    )

    for record in combined_history:
        if isinstance(record, Item.history.model):
            record.record_type = "Item"
            record.object_name = record.name
        else:
            record.record_type = "Device"
            record.object_name = record.mac_address

        record.changes = []
        previous_record = record.prev_record
        if previous_record:
            store_previous_record = record.diff_against(previous_record)
            for change in store_previous_record.changes:
                record.changes.append({
                    'field': change.field,
                    'old': change.old,
                    'new': change.new
                })

    context = {
        'combined_history': combined_history
    }

    return render(request, 'stock_history.html', context)


def backup_restore(request):
    return redirect('home')


def firmware_generator():
    pass


def health_check():
    pass
