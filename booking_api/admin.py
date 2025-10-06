# booking_api/admin.py

from django.contrib import admin
from .models import (
    Organization, Employee, Service, Client,
    Appointment, EmployeeSchedule
)


# --- Настройка отображения моделей в админ-панели ---

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'segment_name', 'address')
    search_fields = ('name',)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization')
    list_filter = ('organization',)
    search_fields = ('name',)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'duration_minutes', 'price', 'is_active')
    list_filter = ('organization', 'is_active')
    search_fields = ('name',)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number')
    search_fields = ('name', 'phone_number')


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('client', 'employee', 'service', 'start_time', 'status')
    list_filter = ('organization', 'status', 'employee')
    search_fields = ('client__name', 'employee__name')
    # Добавление фильтра для времени начала/окончания
    date_hierarchy = 'start_time'


@admin.register(EmployeeSchedule)
class EmployeeScheduleAdmin(admin.ModelAdmin):
    list_display = ('employee', 'day_of_week', 'start_minutes_display', 'end_minutes_display')
    list_filter = ('employee', 'day_of_week')

    # Метод для удобного отображения минут в формате HH:MM
    def start_minutes_display(self, obj):
        h = obj.start_minutes // 60
        m = obj.start_minutes % 60
        return f"{h:02d}:{m:02d}"

    start_minutes_display.short_description = 'Начало работы'

    def end_minutes_display(self, obj):
        h = obj.end_minutes // 60
        m = obj.end_minutes % 60
        return f"{h:02d}:{m:02d}"

    end_minutes_display.short_description = 'Конец работы'