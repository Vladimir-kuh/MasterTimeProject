# booking_api/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from datetime import timedelta


import logging
logger = logging.getLogger('booking_debug')


# --- Модель 1: Организация (Салон, Шиномонтаж и т.д.) ---
class Organization(models.Model):
    name = models.CharField(max_length=255, verbose_name="Название организации")
    segment_name = models.CharField(max_length=50, default="Салон", verbose_name="Имя сегмента (для адаптивности)")
    address = models.TextField(verbose_name="Адрес")

    class Meta:
        verbose_name = "Организация"
        verbose_name_plural = "Организации"

    def __str__(self):
        return self.name


# --- Модель 2: Сотрудник/Мастер (С МЕТОДОМ РАСЧЕТА РАСПИСАНИЯ) ---
class Employee(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Имя Сотрудника/Мастера")
    telegram_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Telegram Chat ID для уведомлений"
    )

    class Meta:
        verbose_name = "Сотрудник/Мастер"
        verbose_name_plural = "Сотрудники/Мастера"

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    def get_working_intervals(self, date):
        """
        Возвращает список рабочих интервалов (в минутах от 00:00)
        для мастера на указанную дату, учитывая шаблон и исключения.

        Возвращаемый формат: [(start_minutes_1, end_minutes_1), (start_minutes_2, end_minutes_2), ...]
        """

        # 1. Проверка Исключений (ScheduleException - Высший приоритет)
        try:
            exception = self.exceptions.get(date=date)

            # Если это полный выходной
            if not exception.has_new_hours:
                return []

            # Если это неполный день (переопределение)
            base_intervals = [
                (exception.new_start_minutes, exception.new_end_minutes)
            ]

        except ScheduleException.DoesNotExist:
            # 2. Получение Шаблона (EmployeeSchedule - Приоритет по умолчанию)
            day_of_week = date.weekday()  # Понедельник=0, Воскресенье=6
            try:
                schedule = self.employeeschedule_set.get(day_of_week=day_of_week)
                base_intervals = [
                    (schedule.start_minutes, schedule.end_minutes)
                ]
            except self.employeeschedule_set.model.DoesNotExist:
                return []

        # 3. Учет Блокировок (TimeBlocker - Вычитание)
        blockers = self.blocked_times.filter(date=date).order_by('start_minutes')

        final_intervals = []
        for start, end in base_intervals:
            current_start = start

            for blocker in blockers:
                block_start = blocker.start_minutes
                block_end = blocker.end_minutes

                # Если рабочий интервал начинается ДО блокировки, добавляем свободное время
                if current_start < block_start:
                    final_intervals.append((current_start, min(end, block_start)))

                # Сдвигаем текущую точку отсчета за конец блокировки
                current_start = max(current_start, block_end)

            # Добавляем оставшееся время после всех блокировок
            if current_start < end:
                final_intervals.append((current_start, end))

        # Важно: Здесь (или в отдельном сервисе) должна быть логика вычитания
        # уже существующих записей (Appointment) из final_intervals.
        logger.warning(f"DEBUG_SCHED: Мастер {self.name}, Дата {date.isoformat()}")
        logger.warning(f"DEBUG_SCHED: Базовый интервал (до блокировок): {base_intervals}")
        if blockers.exists():
            logger.warning(f"DEBUG_SCHED: Блокировки: {blockers.values('start_minutes', 'end_minutes')}")
        logger.warning(f"DEBUG_SCHED: ФИНАЛЬНЫЕ РАБОЧИЕ ИНТЕРВАЛЫ: {final_intervals}")

        return final_intervals


# --- Модель 3: Каталог Услуг ---
class Service(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Название услуги (Обязательно)")
    category = models.CharField(max_length=100, blank=True, null=True, verbose_name="Категория")

    base_duration = models.IntegerField(
        verbose_name="Базовая Длительность (мин)",
        validators=[MinValueValidator(1)],
        help_text="Фактическое время оказания услуги в минутах."
    )
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Базовая Цена (руб./валюта)",
        validators=[MinValueValidator(0)]
    )
    buffer_time = models.IntegerField(
        default=0,
        verbose_name="Буферное Время (мин)",
        validators=[MinValueValidator(0)],
        help_text="Время, добавляемое автоматически после услуги (например, на уборку)."
    )

    description = models.TextField(blank=True, null=True, verbose_name="Описание для клиента")
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    employees = models.ManyToManyField(
        Employee,
        related_name='services',
        verbose_name="Сотрудники, оказывающие услугу"
    )

    class Meta:
        verbose_name = "Услуга (Каталог)"
        verbose_name_plural = "Услуги (Каталог)"
        unique_together = ('organization', 'name')

    def __str__(self):
        return f"{self.name} ({self.total_duration} мин, {self.base_price} руб.)"

    @property
    def total_duration(self):
        """Расчет общей длительности, включая буфер."""
        return self.base_duration + self.buffer_time


# --- Модель 4: Клиент ---
class Client(models.Model):
    name = models.CharField(max_length=255, verbose_name="Имя Клиента")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="Телефон")

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"

    def __str__(self):
        return self.name


# --- Модель 5: Запись/Бронирование ---
class Appointment(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Ожидает подтверждения'),
        ('CONFIRMED', 'Подтверждена'),
        ('CANCELLED', 'Отменена'),
        ('COMPLETED', 'Завершена'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    service = models.ForeignKey(Service, on_delete=models.PROTECT, verbose_name="Выбранная Услуга")

    start_time = models.DateTimeField(verbose_name="Время начала")
    end_time = models.DateTimeField(verbose_name="Время окончания")

    custom_duration = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
        verbose_name="Фактическая длительность (мин, с учетом буфера)"
    )
    custom_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
        verbose_name="Фактическая цена"
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', verbose_name="Статус")
    address = models.CharField(max_length=255, default="", verbose_name="Адрес оказания услуги")

    is_client_reminder_sent = models.BooleanField(
        default=False,
        verbose_name="Напоминание клиенту отправлено"
    )
    client_chat_id = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="Telegram Chat ID клиента"
    )

    class Meta:
        verbose_name = "Запись/Бронирование"
        verbose_name_plural = "Записи/Бронирования"
        constraints = [
            models.UniqueConstraint(fields=['employee', 'start_time'], name='unique_employee_time')
        ]

    def __str__(self):
        return f"Запись {self.organization.name} на {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    @property
    def actual_duration(self):
        """Возвращает фактическую общую длительность (с буфером или кастомную)."""
        return self.custom_duration if self.custom_duration is not None else self.service.total_duration

    @property
    def actual_price(self2):
        """Возвращает фактическую цену (кастомную или базовую)."""
        return self2.custom_price if self2.custom_price is not None else self2.service.base_price

    def save(self, *args, **kwargs):
        """Переопределяем save() для автоматического расчета end_time."""

        duration_minutes = self.actual_duration
        self.end_time = self.start_time + timedelta(minutes=duration_minutes)

        super().save(*args, **kwargs)


# --- Модель 6: Рабочее Расписание Мастера (Базовый шаблон) ---
class EmployeeSchedule(models.Model):
    WEEKDAY_CHOICES = [
        (0, 'Понедельник'),
        (1, 'Вторник'),
        (2, 'Среда'),
        (3, 'Четверг'),
        (4, 'Пятница'),
        (5, 'Суббота'),
        (6, 'Воскресенье'),
    ]

    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, verbose_name="Сотрудник/Мастер")
    day_of_week = models.IntegerField(choices=WEEKDAY_CHOICES, verbose_name="День недели")

    start_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        verbose_name="Начало работы (минуты от 00:00)"
    )
    end_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        verbose_name="Конец работы (минуты от 00:00)"
    )

    class Meta:
        verbose_name = "Расписание Мастера"
        verbose_name_plural = "Расписания Мастеров"
        unique_together = ('employee', 'day_of_week')

    def __str__(self):
        return f"{self.employee.name} - {self.get_day_of_week_display()}"


# --- Модель 7: Исключение Расписания (Переопределение или Выходной) ---
class ScheduleException(models.Model):
    employee = models.ForeignKey(
        'Employee',
        on_delete=models.CASCADE,
        related_name='exceptions',
        verbose_name="Сотрудник/Мастер"
    )
    date = models.DateField(
        verbose_name="Дата исключения"
    )

    has_new_hours = models.BooleanField(
        default=False,
        verbose_name="Переопределить часы работы"
    )

    new_start_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        null=True, blank=True,
        verbose_name="Новое начало работы (минуты от 00:00)"
    )
    new_end_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        null=True, blank=True,
        verbose_name="Новый конец работы (минуты от 00:00)"
    )

    class Meta:
        verbose_name = "Исключение в расписании"
        verbose_name_plural = "Исключения в расписании"
        unique_together = ('employee', 'date')

    def __str__(self):
        if not self.has_new_hours:
            return f"{self.employee.name} - Выходной ({self.date})"

        start_time_str = f"{self.new_start_minutes // 60:02d}:{(self.new_start_minutes % 60):02d}" if self.new_start_minutes is not None else "N/A"
        end_time_str = f"{self.new_end_minutes // 60:02d}:{(self.new_end_minutes % 60):02d}" if self.new_end_minutes is not None else "N/A"
        return f"{self.employee.name} - Смена часов {start_time_str}-{end_time_str} ({self.date})"


# --- Модель 8: Блокировка Времени (Перерыв в течение дня) ---
class TimeBlocker(models.Model):
    employee = models.ForeignKey(
        'Employee',
        on_delete=models.CASCADE,
        related_name='blocked_times',
        verbose_name="Сотрудник/Мастер"
    )
    date = models.DateField(
        verbose_name="Дата блокировки"
    )

    start_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        verbose_name="Начало блокировки (минуты от 00:00)"
    )
    end_minutes = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        verbose_name="Конец блокировки (минуты от 00:00)"
    )

    reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Причина блокировки (для администрации)"
    )

    class Meta:
        verbose_name = "Блокировка Времени"
        verbose_name_plural = "Блокировки Времени"
        #index_together = [['employee', 'date']]
        indexes = [
            models.Index(fields=['employee', 'date']),
        ]
    def __str__(self):
        return f"Блокировка {self.employee.name} на {self.date}"