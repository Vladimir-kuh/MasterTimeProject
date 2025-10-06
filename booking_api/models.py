# booking_api/models.py

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from datetime import timedelta


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


# --- Модель 2: Сотрудник/Мастер (ОБНОВЛЕНО) ---
class Employee(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Имя Сотрудника/Мастера")
    # NEW: Поле для привязки Telegram ID мастера
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


# --- Модель 3: Каталог Услуг (ЗНАЧИТЕЛЬНО ОБНОВЛЕНО) ---
class Service(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Название услуги (Обязательно)")

    # NEW: Добавлено поле Категория (Необязательно)
    category = models.CharField(max_length=100, blank=True, null=True, verbose_name="Категория")

    # NEW: Базовая Длительность (Обязательно)
    base_duration = models.IntegerField(
        verbose_name="Базовая Длительность (мин)",
        validators=[MinValueValidator(1)],
        help_text="Фактическое время оказания услуги в минутах."
    )

    # NEW: Базовая Цена (Обязательно)
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Базовая Цена (руб./валюта)",
        validators=[MinValueValidator(0)]
    )

    # NEW: Буферное Время (Необязательно)
    buffer_time = models.IntegerField(
        default=0,
        verbose_name="Буферное Время (мин)",
        validators=[MinValueValidator(0)],
        help_text="Время, добавляемое автоматически после услуги (например, на уборку)."
    )

    # NEW: Описание (Необязательно)
    description = models.TextField(blank=True, null=True, verbose_name="Описание для клиента")

    # Статус (Активна/Скрыта)
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    # Сотрудники, оказывающие услугу (оставлено без изменений)
    employees = models.ManyToManyField(
        Employee,
        related_name='services',
        verbose_name="Сотрудники, оказывающие услугу"
    )

    class Meta:
        verbose_name = "Услуга (Каталог)"
        verbose_name_plural = "Услуги (Каталог)"
        unique_together = ('organization', 'name')  # Добавим уникальность внутри организации

    def __str__(self):
        return f"{self.name} ({self.total_duration} мин, {self.base_price} руб.)"

    @property
    def total_duration(self):
        """Расчет общей длительности, включая буфер."""
        return self.base_duration + self.buffer_time


# --- Модель 4: Клиент (Без изменений) ---
class Client(models.Model):
    name = models.CharField(max_length=255, verbose_name="Имя Клиента")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="Телефон")

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"

    def __str__(self):
        return self.name


# --- Модель 5: Запись/Бронирование (ОБНОВЛЕНО) ---
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

    # Связь с обновленной моделью Service
    service = models.ForeignKey(Service, on_delete=models.PROTECT, verbose_name="Выбранная Услуга")

    start_time = models.DateTimeField(verbose_name="Время начала")

    # NEW: Поле end_time будет рассчитываться автоматически, но хранится для фиксации.
    end_time = models.DateTimeField(verbose_name="Время окончания")

    # NEW: Поля для хранения ручных изменений цены/длительности
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
    address = models.CharField(max_length=255, default="",
                               verbose_name="Адрес оказания услуги")  # Добавил поле для адреса

    class Meta:
        verbose_name = "Запись/Бронирование"
        verbose_name_plural = "Записи/Бронирования"
        # Запрет двух записей у одного мастера в одно и то же время
        constraints = [
            # Уникальность по мастеру и времени начала - может быть спорным из-за буфера,
            # но в простейшем случае оставляем как было, полагаясь на логику расчета end_time.
            models.UniqueConstraint(fields=['employee', 'start_time'], name='unique_employee_time')
        ]

    def __str__(self):
        return f"Запись {self.organization.name} на {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    @property
    def actual_duration(self):
        """Возвращает фактическую общую длительность (с буфером или кастомную)."""
        return self.custom_duration if self.custom_duration is not None else self.service.total_duration

    @property
    def actual_price(self):
        """Возвращает фактическую цену (кастомную или базовую)."""
        return self.custom_price if self.custom_price is not None else self.service.base_price

    def save(self, *args, **kwargs):
        """Переопределяем save() для автоматического расчета end_time."""

        # Расчет end_time на основе фактической длительности
        duration_minutes = self.actual_duration
        self.end_time = self.start_time + timedelta(minutes=duration_minutes)

        super().save(*args, **kwargs)


# --- Модель 6: Рабочее Расписание Мастера (Без изменений) ---
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

    # Рабочий интервал (в минутах от начала дня)
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