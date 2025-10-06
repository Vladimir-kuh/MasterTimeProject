# booking_api/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ServiceViewSet, AppointmentViewSet, EmployeeViewSet

# Создаем роутер
router = DefaultRouter()

# 1. Регистрация стандартных CRUD-маршрутов для Услуг
router.register(r'services', ServiceViewSet, basename='services') # Добавляем маршрут для услуг

router.register(r'appointments', AppointmentViewSet, basename='appointments')  # Добавляем маршрут для записей

router.register(r'employees', EmployeeViewSet) # Добавляем маршрут для сотрудников

# Добавляем маршруты, сгенерированные роутером, в urlpatterns
urlpatterns = [
    path('', include(router.urls)), # Включаем все маршруты из роутера
]