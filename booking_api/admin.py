# booking_api/admin.py

from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import (
    Organization, Employee, Service, Client,
    Appointment, EmployeeSchedule
)
from datetime import timedelta


# --- Настройка отображения моделей в админ-панели ---

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'segment_name', 'address')
    search_fields = ('name',)


# --- Employee (ОБНОВЛЕНО: Добавлен Telegram ID) ---
@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'telegram_chat_id')
    list_filter = ('organization',)
    search_fields = ('name', 'telegram_chat_id')
    fieldsets = (
        (None, {
            'fields': ('organization', 'name')
        }),
        ('Интеграция', {
            'fields': ('telegram_chat_id',),
            'description': 'Chat ID используется для отправки мгновенных уведомлений о новых записях.'
        }),
    )


# --- Service (ИСПРАВЛЕНО: Учтены новые названия полей и добавлены @property) ---
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'organization',
        'category',
        'base_duration',  # <-- ИСПРАВЛЕНО
        'buffer_time',
        'base_price',  # <-- ИСПРАВЛЕНО
        'total_duration_display',  # Отображение общей длительности
        'is_active',
        'get_employees_list',
    )
    list_filter = ('organization', 'is_active', 'category')
    search_fields = ('name', 'description')
    filter_horizontal = ('employees',)  # Удобный виджет для M2M поля

    # Расширенное отображение формы редактирования
    fieldsets = (
        (None, {
            'fields': ('organization', 'name', 'category', 'description', 'is_active')
        }),
        ('Ценообразование и Длительность', {
            'fields': ('base_price', 'base_duration', 'buffer_time'),
            'description': 'Общая длительность записи = Базовая длительность + Буферное время.'
        }),
        ('Сотрудники', {
            'fields': ('employees',)
        }),
    )

    # Отображение общей длительности (использует @property total_duration из models.py)
    def total_duration_display(self, obj):
        return f"{obj.total_duration} мин"

    total_duration_display.short_description = 'Общая Длительность'

    # Отображение списка сотрудников
    def get_employees_list(self, obj):
        return ", ".join([e.name for e in obj.employees.all()])

    get_employees_list.short_description = 'Обслуживают'


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number')
    search_fields = ('name', 'phone_number')


# --- Appointment (ОБНОВЛЕНО: Добавлены кастомные поля и адрес) ---
@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        'client',
        'employee',
        'service',
        'start_time',
        'end_time',
        'status',
        'actual_price_display',
        'actual_duration_display',
        'client_chat_id'
    )
    list_filter = ('organization', 'status', 'employee')
    search_fields = ('client__name', 'employee__name', 'service__name')
    date_hierarchy = 'start_time'

    #  добавить кнопку удаления
    actions = ['delete_selected']
    fieldsets = (
        (None, {
            'fields': ('organization', 'client', 'employee', 'service', 'address', 'status')
        }),
        ('Время', {
            'fields': ('start_time', 'end_time')
        }),
        ('Ручное переопределение', {
            'fields': ('custom_duration', 'custom_price'),
            'description': mark_safe(
                '<p style="color:red;">Заполняйте только, если хотите изменить цену/длительность от базовой услуги. '
                'Если поле пустое, будет использоваться цена/длительность из Каталога Услуг.</p>'
            )
        }),
    )

    # Отображение фактической длительности
    def actual_duration_display(self, obj):
        return f"{obj.actual_duration} мин"

    actual_duration_display.short_description = 'Фактическая Длительность'

    # Отображение фактической цены
    def actual_price_display(self, obj):
        price = obj.actual_price
        # Форматирование цены (можно добавить валюту)
        return f"{price:,.2f}"

    actual_price_display.short_description = 'Фактическая Цена'


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