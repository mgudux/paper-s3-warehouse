from django.urls import path
from . import views

urlpatterns = [
    # Web Interface
    path('', views.home, name='home'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('update_item/<int:pk>', views.update_item, name='update_item'),
    path('update_device/<int:pk>', views.update_device, name='update_device'),
    path('analytics/', views.analytics, name='analytics'),
    path('backup_restore/', views.backup_restore, name='backup_restore'),
    path('stock_history/', views.stock_history, name='stock_history'),
    path('firmware/main.py', views.get_firmware_file, name='get_firmware'),

    # API Endpoints for BLE Gateway
    path('api/devices/register', views.api_register_device, name='api_register'),
    path('api/inventory/update', views.api_update_inventory, name='api_update_inventory'),
    path('api/devices/<str:mac_address>/updates', views.api_check_updates, name='api_check_updates'),
    path('api/last_update', views.api_last_update_timestamp, name='api_last_update'),
]
