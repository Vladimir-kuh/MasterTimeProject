# booking_api/admin.py

from django.contrib import admin
from django.utils.safestring import mark_safe
# Импортируем НОВЫЕ модели
from .models import (
    Organization, Employee, Service, Client,
    Appointment, EmployeeSchedule, ScheduleException, TimeBlocker
)
from datetime import timedelta


# --- Вспомогательные функции для отображения ЧЧ:ММ ---
def format_minutes_to_time(minutes):
    """Преобразует минуты от полуночи в строку формата HH:MM."""
    if minutes is None:
        return "N/A"
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


# --- 1. Встраивание Шаблона Расписания (EmployeeSchedule) в Мастера ---
class EmployeeScheduleInline(admin.TabularInline):
    model = EmployeeSchedule
    extra = 0  # Не показывать пустые формы по умолчанию
    min_num = 0
    max_num = 7
    verbose_name = "Шаблон расписания"
    verbose_name_plural = "Шаблон расписания на неделю (Пн-Вс)"

    # Поля с отображением ЧЧ:ММ
    fields = ('day_of_week', 'start_minutes', 'end_minutes')
    ordering = ('day_of_week',)


# --- Настройка отображения моделей в админ-панели ---

@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'segment_name', 'address')
    search_fields = ('name',)


# --- Employee (ОБНОВЛЕНО: ДОБАВЛЕН ИНЛАЙН) ---
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
    # ИНТЕГРАЦИЯ ШАБЛОНА
    inlines = [EmployeeScheduleInline]


# --- Service (Каталог Услуг) ---
@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'organization',
        'category',
        'base_duration',
        'buffer_time',
        'base_price',
        'total_duration_display',
        'is_active',
        'get_employees_list',
    )
    list_filter = ('organization', 'is_active', 'category')
    search_fields = ('name', 'description')
    filter_horizontal = ('employees',)

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

    def total_duration_display(self, obj):
        return f"{obj.total_duration} мин"

    total_duration_display.short_description = 'Общая Длительность'

    def get_employees_list(self, obj):
        return ", ".join([e.name for e in obj.employees.all()])

    get_employees_list.short_description = 'Обслуживают'


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_number')
    search_fields = ('name', 'phone_number')


# --- Appointment (Записи) ---
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

    def actual_duration_display(self, obj):
        return f"{obj.actual_duration} мин"

    actual_duration_display.short_description = 'Фактическая Длительность'

    def actual_price_display(self, obj):
        price = obj.actual_price
        return f"{price:,.2f}"

    actual_price_display.short_description = 'Фактическая Цена'


# --- EmployeeSchedule (Базовый Шаблон) ---
# Эта модель теперь не регистрируется с @admin.register, так как она встроена (Inline),
# но для возможности прямого просмотра или если вы захотите ее оставить,
# я сохранил ее логику отображения ЧЧ:ММ.
@admin.register(EmployeeSchedule)
class EmployeeScheduleAdmin(admin.ModelAdmin):
    list_display = ('employee', 'day_of_week', 'start_minutes_display', 'end_minutes_display')
    list_filter = ('employee', 'day_of_week')

    def start_minutes_display(self, obj):
        return format_minutes_to_time(obj.start_minutes)

    start_minutes_display.short_description = 'Начало работы'

    def end_minutes_display(self, obj):
        return format_minutes_to_time(obj.end_minutes)

    end_minutes_display.short_description = 'Конец работы'


# =========================================================================
# === НОВЫЕ АДМИН-КЛАССЫ ДЛЯ ПЛАВАЮЩИХ РАСПИСАНИЙ ===
# =========================================================================

# --- 2. Настройка Исключений (ScheduleException) ---
@admin.register(ScheduleException)
class ScheduleExceptionAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'is_day_off', 'new_hours_display')
    list_filter = ('employee', 'date')
    date_hierarchy = 'date'
    search_fields = ('employee__name',)

    fieldsets = (
        (None, {
            'fields': ('employee', 'date', 'has_new_hours'),
            'description': 'Если "Переопределить часы работы" ВЫКЛЮЧЕНО, весь день считается выходным.'
        }),
        ('Новые часы работы', {
            'fields': ('new_start_minutes', 'new_end_minutes'),
            'description': 'Используйте минуты от полуночи (напр., 540 для 09:00).',
            # Можно добавить классы для скрытия/отображения через JS, но здесь оставляем
            # открытым с четкой инструкцией.
        }),
    )

    def is_day_off(self, obj):
        return not obj.has_new_hours

    is_day_off.short_description = "Полный выходной?"
    is_day_off.boolean = True

    def new_hours_display(self, obj):
        if obj.has_new_hours:
            start_time = format_minutes_to_time(obj.new_start_minutes)
            end_time = format_minutes_to_time(obj.new_end_minutes)
            return f"{start_time} — {end_time}"
        return "N/A"

    new_hours_display.short_description = "Переопределенные часы"


# --- 3. Настройка Блокировки Времени (TimeBlocker) ---
@admin.register(TimeBlocker)
class TimeBlockerAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'start_time_display', 'end_time_display', 'reason')
    list_filter = ('employee', 'date')
    date_hierarchy = 'date'
    search_fields = ('employee__name', 'reason')

    fieldsets = (
        (None, {
            'fields': ('employee', 'date', 'start_minutes', 'end_minutes', 'reason'),
            'description': 'Блокировка времени в минутах от полуночи. Эти интервалы будут вычтены из рабочего дня.'
        }),
    )

    def start_time_display(self, obj):
        return format_minutes_to_time(obj.start_minutes)

    start_time_display.short_description = "Начало блокировки"

    def end_time_display(self, obj):
        return format_minutes_to_time(obj.end_minutes)

    end_time_display.short_description = "Конец блокировки"