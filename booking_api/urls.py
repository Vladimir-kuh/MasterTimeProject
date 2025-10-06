# booking_api/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ServiceViewSet,
    AppointmentViewSet,
    EmployeeViewSet,
    # НОВЫЕ ИМПОРТЫ для APIView и ViewSet actions
    AnalyticsViewSet,
    TelegramAppointmentCreationView
)

# Создаем роутер
router = DefaultRouter()

# 1. Регистрация стандартных ViewSets
router.register(r'services', ServiceViewSet, basename='service')
# Маршрут services/telegram_catalog/ автоматически создается роутером!

router.register(r'appointments', AppointmentViewSet, basename='appointment')
# Маршрут appointments/available_slots/ автоматически создается роутером!

router.register(r'employees', EmployeeViewSet, basename='employee')

# Добавляем маршруты, сгенерированные роутером, в urlpatterns
urlpatterns = [
    # 1. Все маршруты ViewSets (CRUD, available_slots, telegram_catalog)
    path('', include(router.urls)),

    # 2. НОВЫЙ МАРШРУТ: Специальный эндпоинт для создания записи через Telegram
    # Адрес: /api/v1/appointments/telegram/ (если в главном urls.py используется 'api/v1/')
    path('appointments/telegram/', TelegramAppointmentCreationView.as_view(), name='telegram-appointment-create'),

    # 3. Маршрут для Аналитики (если он используется)
    # Адрес: /api/v1/analytics/
    path('analytics/', AnalyticsViewSet.as_view(), name='analytics'),
]