import json
import re
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Prefetch
from django.contrib.postgres.search import TrigramSimilarity
from django.core.exceptions import ValidationError
from .models import Device, Item
from .forms import UpdateItemFormFull, UpdateItemFormBasic, UpdateDeviceForm
import logging

logger = logging.getLogger(__name__)

MAX_STOCK_VALUE = 99
MIN_STOCK_VALUE = 0
MAX_BATTERY_VALUE = 100
MAX_ITEM_NAME_LENGTH = 20
API_RATE_LIMIT_WINDOW = 60
API_RATE_LIMIT_MAX = 100

_rate_limit_cache = {}


def _check_rate_limit(identifier, max_requests=API_RATE_LIMIT_MAX, window=API_RATE_LIMIT_WINDOW):
    now = time.time()
    cutoff = now - window
    _rate_limit_cache[identifier] = [
        t for t in _rate_limit_cache.get(identifier, []) if t > cutoff
    ]
    if len(_rate_limit_cache.get(identifier, [])) >= max_requests:
        return False
    if identifier not in _rate_limit_cache:
        _rate_limit_cache[identifier] = []
    _rate_limit_cache[identifier].append(now)
    return True


def _validate_stock_value(value, field_name="stock"):
    try:
        val = int(value)
        return max(MIN_STOCK_VALUE, min(MAX_STOCK_VALUE, val))
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid {field_name} value: {value}")


def _validate_battery_value(value):
    if value is None:
        return None
    try:
        val = int(value)
        return max(0, min(MAX_BATTERY_VALUE, val))
    except (TypeError, ValueError):
        return None


def _sanitize_item_name(name):
    if not name:
        return "Unknown"
    name = ''.join(c for c in str(name) if c.isprintable())
    return name[:MAX_ITEM_NAME_LENGTH]


def _generate_config_payload(device):
    items = Item.objects.filter(device=device).order_by('-level', 'box')
    inventory_list = []
    for item in items:
        inventory_list.append({
            "chest_id": item.location_label(),
            "item": item.name,
            "current": item.stock,
            "min_stock": item.min_stock,
        })
    return {"inventory": inventory_list}


def item_search(query, search_history=False):
    ItemModel = Item.history if search_history else Item.objects

    if not query:
        return ItemModel.none()

    query = query.strip()
    row = level = box = None
    location_parsed = False

    # Try to parse location codes like R2-E3-K1 or K2E1R3 etc.
    matches = re.findall(r'([RrEeLlKkBb])[\s:]*(\d+)', query)
    if matches:
        location_parsed = True
        for prefix, number in matches:
            if prefix.upper() == 'R':
                row = number
            elif prefix.upper() in ['E', 'L']:
                level = number
            elif prefix.upper() in ['K', 'B']:
                box = number
    else:
        # Fall back to positional digit parsing (e.g. "2 3 1")
        location_match = re.search(
            r'(?P<row>\d)(?:\D*(?P<level>\d)(?:\D*(?P<box>\d))?)?', query)
        if location_match and location_match.group('row'):
            location_parsed = True
            row = location_match.group('row')
            level = location_match.group('level')
            box = location_match.group('box')

    if location_parsed:
        filters = Q()
        if row and int(row) != 0:
            filters &= Q(row=int(row))
        if level and int(level) != 0:
            filters &= Q(level=int(level))
        if box and int(box) != 0:
            filters &= Q(box=int(box))

        if filters:
            if search_history:
                results = ItemModel.filter(filters).order_by('-history_date')[:3000]
            else:
                results = ItemModel.filter(filters).order_by('row', 'level', 'box')
                results = results.select_related('device')
            if results.exists():
                return results

    # Fall back to fuzzy name search
    if search_history:
        return ItemModel.filter(name__icontains=query).order_by('-history_date')[:3000]

    items = (
        ItemModel
        .annotate(similarity=TrigramSimilarity('name', query))
        .filter(similarity__gt=0.17)
        .order_by('-similarity')[:10]
        .select_related('device')
    )
    return items


def home(request):
    search_query = request.GET.get('search', '').strip()
    if search_query:
        items = item_search(search_query)
        return render(request, 'home.html', {
            'search_query': search_query,
            'search_results': items,
            'is_search': True,
        })

    all_items = list(Item.objects.select_related('device').all())
    critical_count = sum(1 for i in all_items if i.stock_status() == 'Critical')
    low_count = sum(1 for i in all_items if i.stock_status() == 'Low')
    good_count = sum(1 for i in all_items if i.stock_status() == 'Good')

    total_stats = {
        'item_count': len(all_items),
        'critical_count': critical_count,
        'low_count': low_count,
        'good_count': good_count,
    }

    devices = Device.objects.filter(row__gt=0).prefetch_related(
        Prefetch('item_set', queryset=Item.objects.order_by('-level', 'box'))
    ).order_by('row', '-bottom_level', 'left_box')

    devices_by_row = {}
    for device in devices:
        devices_by_row.setdefault(device.row, []).append(device)

    rows_data = []
    for row_number in range(1, Device.max_rows + 1):
        devices_with_items = []
        for device in devices_by_row.get(row_number, []):
            items = list(device.item_set.all())
            crit = sum(1 for i in items if i.stock_status() == 'Critical')
            low = sum(1 for i in items if i.stock_status() == 'Low')
            good = sum(1 for i in items if i.stock_status() == 'Good')
            devices_with_items.append({
                'device': device,
                'items': items,
                'item_count': len(items),
                'critical_count': crit,
                'low_count': low,
                'good_count': good,
            })
        if devices_with_items:
            rows_data.append({'row_number': row_number, 'devices': devices_with_items})

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            request.session['last_activity'] = time.time()
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
    next_url = request.GET.get('next', None)
    if next_url:
        from django.utils.http import url_has_allowed_host_and_scheme
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
    return redirect('home')


def login_user(request):
    return redirect('home')


def update_item(request, pk):
    if request.method != "POST":
        return redirect('home')
    item = get_object_or_404(Item, pk=pk)
    FormClass = UpdateItemFormFull if request.user.is_authenticated else UpdateItemFormBasic
    form = FormClass(request.POST, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, "Item updated!")
    return redirect('home')


def analytics(request):
    from datetime import timedelta
    ninety_days_ago = timezone.now() - timedelta(days=90)
    items = Item.objects.select_related('device').all()

    top_consumed = []
    for item in items:
        total_consumed = 0
        history_records = list(
            item.history.filter(history_date__gte=ninety_days_ago).order_by('history_date')
        )
        if not history_records:
            continue

        pre_window = item.history.filter(
            history_date__lt=ninety_days_ago).order_by('-history_date').first()
        previous_stock = getattr(pre_window, 'stock', None) if pre_window else None

        for record in history_records:
            current_stock = getattr(record, 'stock', None)
            if current_stock is None:
                continue
            if previous_stock is not None and previous_stock > current_stock:
                total_consumed += previous_stock - current_stock
            previous_stock = current_stock

        if total_consumed > 0:
            top_consumed.append({
                'name': item.name,
                'location': item.location_label(),
                'total_consumed': total_consumed,
                'current_stock': item.stock,
                'min_stock': item.min_stock,
                'stock_status': item.stock_status(),
            })

    top_consumed = sorted(top_consumed, key=lambda x: x['total_consumed'], reverse=True)[:10]

    def is_critical(stock, threshold):
        return stock is not None and (stock <= 1 or stock <= threshold)

    top_critical = []
    for item in items:
        threshold = max(1, round(item.min_stock * 0.25))
        history_records = list(
            item.history.filter(history_date__gte=ninety_days_ago).order_by('history_date')
        )
        critical_seconds = 0
        now = timezone.now()

        pre_window = item.history.filter(
            history_date__lt=ninety_days_ago).order_by('-history_date').first()
        last_critical = is_critical(getattr(pre_window, 'stock', None), threshold) if pre_window else False
        last_time = ninety_days_ago

        for record in history_records:
            stock = getattr(record, 'stock', None)
            if stock is None:
                continue
            if last_critical:
                critical_seconds += max(0, (record.history_date - last_time).total_seconds())
            last_critical = is_critical(stock, threshold)
            last_time = record.history_date

        if last_critical:
            critical_seconds += max(0, (now - last_time).total_seconds())

        if not history_records and not pre_window and is_critical(item.stock, threshold):
            critical_seconds = (now - ninety_days_ago).total_seconds()

        critical_days = int(critical_seconds / 86400)
        if critical_days > 0:
            top_critical.append({
                'name': item.name,
                'location': item.location_label(),
                'critical_days': critical_days,
                'current_stock': item.stock,
                'min_stock': item.min_stock,
                'stock_status': item.stock_status(),
            })

    top_critical = sorted(top_critical, key=lambda x: x['critical_days'], reverse=True)[:10]

    return render(request, 'analytics.html', {
        'top_consumed': top_consumed,
        'top_critical': top_critical,
    })


def stock_history(request):
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    from itertools import chain

    search_query = request.GET.get('search', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    filter_type = request.GET.get('filter_type', 'all')
    page_number = int(request.GET.get('page', 1))
    per_page = 100
    max_records = 3000

    item_history = Item.history.all()
    device_history = Device.history.all()

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            item_history = item_history.filter(history_date__gte=date_from_obj)
            device_history = device_history.filter(history_date__gte=date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            item_history = item_history.filter(history_date__lt=date_to_obj)
            device_history = device_history.filter(history_date__lt=date_to_obj)
        except ValueError:
            pass

    if filter_type == 'item':
        device_history = Device.history.none()
    elif filter_type == 'device':
        item_history = Item.history.none()

    if search_query:
        item_history = item_search(search_query, search_history=True)
        device_history = Device.history.none()
        combined_history = list(item_history)
    else:
        item_history = item_history.select_related('history_user').order_by('-history_date')[:max_records]
        device_history = device_history.select_related('history_user').order_by('-history_date')[:max_records]
        combined_history = sorted(
            chain(item_history, device_history),
            key=lambda x: x.history_date,
            reverse=True
        )[:max_records]

    paginator = Paginator(combined_history, per_page)
    page_obj = paginator.get_page(page_number)

    for record in page_obj:
        if hasattr(record, 'name'):
            record.record_type = "Item"
            record.object_name = record.name
        else:
            record.record_type = "Device"
            record.object_name = record.mac_address

        history_user = getattr(record, 'history_user', None)
        record.changed_by = history_user.username if history_user else "Device"

        record.changes = []
        try:
            previous_record = record.prev_record
            if previous_record:
                diff = record.diff_against(previous_record)
                for change in diff.changes:
                    if change.field == 'battery_level':
                        continue
                    record.changes.append({
                        'field': change.field,
                        'old': change.old,
                        'new': change.new,
                    })
        except Exception as e:
            logger.debug(f"Could not get diff for record: {e}")

    return render(request, 'stock_history.html', {
        'combined_history': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
        'date_from': date_from,
        'date_to': date_to,
        'filter_type': filter_type,
    })


def update_device(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    device = get_object_or_404(Device, pk=pk)
    old_row, old_bottom, old_left = device.row, device.bottom_level, device.left_box

    form = UpdateDeviceForm(request.POST, instance=device)
    if not form.is_valid():
        return JsonResponse({'error': form.errors}, status=400)

    new_row = form.cleaned_data['row']
    new_bottom = form.cleaned_data['bottom_level']
    new_left = form.cleaned_data['left_box']

    new_footprint = set()
    for h in range(device.height):
        for w in range(device.width):
            new_footprint.add((new_row, new_bottom + h, new_left + w))

    conflict = None
    for other in Device.objects.exclude(pk=device.pk).filter(row=new_row):
        if set(other.footprint_boxes()) & new_footprint:
            conflict = other
            break

    if conflict and (conflict.row != old_row or conflict.bottom_level != old_bottom or conflict.left_box != old_left):
        return JsonResponse({
            'error': 'Position conflict detected',
            'conflict_device': {
                'mac_address': conflict.mac_address,
                'location': str(conflict),
            }
        })

    if conflict:
        Device.objects.filter(pk=conflict.pk).update(
            row=old_row, bottom_level=old_bottom, left_box=old_left)
        messages.success(request, "Device positions swapped successfully!")
    else:
        messages.success(request, "Device configuration has been updated!")

    Device.objects.filter(pk=device.pk).update(
        row=new_row, bottom_level=new_bottom, left_box=new_left)
    return JsonResponse({'success': True})


@login_required
def backup_restore(request):
    from django.core.management import call_command
    import os
    from datetime import datetime

    if request.method == "POST":
        action = request.POST.get('action')
        backup_file = request.POST.get('backup_file')

        if action == 'backup':
            try:
                call_command('dbbackup', '--noinput')
                messages.success(request, "Database backup created successfully!")
            except Exception as e:
                messages.error(request, f"Backup failed: {str(e)}")
        elif action == 'restore' and backup_file:
            try:
                call_command('dbrestore', '--noinput', '--input-filename', backup_file)
                messages.success(request, f"Database restored from {backup_file}!")
            except Exception as e:
                messages.error(request, f"Restore failed: {str(e)}")

        return redirect('home')

    backup_dir = settings.STORAGES['dbbackup']['OPTIONS']['location']
    backups = []
    if os.path.exists(backup_dir):
        all_files = []
        for filename in os.listdir(backup_dir):
            if filename.endswith('.psql.bin'):
                filepath = os.path.join(backup_dir, filename)
                all_files.append({
                    'filename': filename,
                    'filepath': filepath,
                    'size': os.path.getsize(filepath),
                    'date': datetime.fromtimestamp(os.path.getmtime(filepath)),
                    'mtime': os.path.getmtime(filepath),
                })
        all_files.sort(key=lambda x: x['mtime'], reverse=True)
        backups = all_files[:100]
        for old in all_files[100:]:
            try:
                os.remove(old['filepath'])
            except Exception:
                pass

    return render(request, 'backup.html', {'backups': backups})

@csrf_exempt
@require_http_methods(["POST"])
@transaction.atomic
def api_register_device(request):
    try:
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        if not _check_rate_limit(f"register_{client_ip}"):
            return JsonResponse({'error': 'Rate limited', 'ack': False}, status=429)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON', 'ack': False}, status=400)

        mac_address = data.get('mac_address', '').strip()
        if not mac_address:
            return JsonResponse({'error': 'MAC address required', 'ack': False}, status=400)

        if len(mac_address) > 50 or not all(c in '0123456789ABCDEFabcdef:- ' for c in mac_address):
            return JsonResponse({'error': 'Invalid MAC address format', 'ack': False}, status=400)

        existing_device = Device.objects.filter(mac_address=mac_address).first()

        if existing_device:
            items = list(existing_device.item_set.all())
            placeholders = [i for i in items if "Placeholder" in i.name]

            if len(placeholders) == 6:
                placeholders.sort(key=lambda x: x.name)
                top_lvl = existing_device.bottom_level + 1
                bot_lvl = existing_device.bottom_level
                left = existing_device.left_box

                target_slots = [
                    (top_lvl, left), (top_lvl, left + 1), (top_lvl, left + 2),
                    (bot_lvl, left), (bot_lvl, left + 1), (bot_lvl, left + 2),
                ]
                for placeholder, (lvl, box) in zip(placeholders, target_slots):
                    placeholder.level = lvl
                    placeholder.box = box
                    placeholder.save()

            return JsonResponse(_generate_config_payload(existing_device))

        # New device — find the next available row/position
        assigned_row = None
        assigned_left = None
        assigned_bottom = None

        for row_number in range(1, Device.max_rows + 1):
            occupied = set()
            for d in Device.objects.filter(row=row_number):
                occupied.update(d.footprint_boxes())

            for bottom in range(1, 4):
                for left in range(1, 5):
                    candidate = {
                        (row_number, bottom, left),
                        (row_number, bottom, left + 1),
                        (row_number, bottom + 1, left),
                        (row_number, bottom + 1, left + 1),
                    }
                    if not candidate & occupied:
                        assigned_row = row_number
                        assigned_bottom = bottom
                        assigned_left = left
                        break
                if assigned_row:
                    break
            if assigned_row:
                break

        if not assigned_row:
            device = Device.objects.create(
                mac_address=mac_address, row=0, bottom_level=1, left_box=1, height=2, width=2)
            return JsonResponse(_generate_config_payload(device))

        device = Device.objects.create(
            mac_address=mac_address,
            row=assigned_row,
            bottom_level=assigned_bottom,
            left_box=assigned_left,
            height=2,
            width=2,
        )

        top_lvl = assigned_bottom + 1
        bot_lvl = assigned_bottom
        items_data = [
            (top_lvl, assigned_left, "Placeholder 1"),
            (top_lvl, assigned_left + 1, "Placeholder 2"),
            (top_lvl, assigned_left + 2, "Placeholder 3"),
            (bot_lvl, assigned_left, "Placeholder 4"),
            (bot_lvl, assigned_left + 1, "Placeholder 5"),
            (bot_lvl, assigned_left + 2, "Placeholder 6"),
        ]
        for lvl, box, name in items_data:
            Item.objects.create(
                device=device, name=name, stock=1, min_stock=1,
                row=assigned_row, level=lvl, box=box,
            )

        return JsonResponse(_generate_config_payload(device))

    except Exception as e:
        logger.error(f"[REGISTER] Error: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def api_update_inventory(request):
    try:
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        if not _check_rate_limit(f"update_{client_ip}"):
            return JsonResponse({'error': 'Rate limited', 'ack': False}, status=429)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON', 'ack': False}, status=400)

        chest_id = str(data.get('chest_id', '')).strip()

        try:
            new_stock = _validate_stock_value(data.get('current', 0))
        except ValidationError as e:
            return JsonResponse({'error': str(e), 'ack': False}, status=400)

        battery = _validate_battery_value(data.get('batt'))

        # Parse chest_id like "R2-E3-K1" into row/level/box
        clean_id = chest_id.replace('R', '').replace('E', '').replace(
            'K', '').replace('L', '').replace('B', '')
        parts = clean_id.split('-')

        item = None
        if len(parts) == 3:
            try:
                r, l, b = parts
                with transaction.atomic():
                    item = Item.objects.select_for_update().filter(row=r, level=l, box=b).first()
            except Exception:
                pass

        if not item and 'item' in data:
            item_name = _sanitize_item_name(data['item'])
            with transaction.atomic():
                item = Item.objects.select_for_update().filter(name=item_name).first()

        if item:
            item.stock = new_stock
            item.save()

            if battery is not None and item.device:
                try:
                    item.device.battery_level = battery
                    item.device.save(update_fields=['battery_level'])
                except Exception:
                    pass

            return JsonResponse({
                'status': 'success',
                'ack': True,
                'correct_chest_id': item.location_label(),
            })

        return JsonResponse({'error': 'Item not found', 'ack': False}, status=404)

    except Exception as e:
        logger.error(f"[UPDATE] Error: {e}", exc_info=True)
        return JsonResponse({'error': str(e), 'ack': False}, status=500)


def api_check_updates(request, mac_address):
    try:
        device = get_object_or_404(Device, mac_address=mac_address)
        return JsonResponse(_generate_config_payload(device))
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_last_update_timestamp(request):
    try:
        latest_item = Item.objects.order_by('-last_modified').first()
        timestamp = latest_item.last_modified.isoformat() if latest_item else None
        return JsonResponse({'last_modified': timestamp})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
