from django.urls import path

from . import views

urlpatterns = [

    path('', views.home, name='home'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('update_item/<int:pk>', views.update_item, name='update_item')

]
