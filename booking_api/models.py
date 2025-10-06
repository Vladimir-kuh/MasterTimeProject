# booking_api/models.py

from django.db import models
# Необходимые импорты для валидации в EmployeeSchedule:
from django.core.validators import MinValueValidator, MaxValueValidator


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


# --- Модель 2: Сотрудник/Мастер ---
class Employee(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Имя Сотрудника/Мастера")

    class Meta:
        verbose_name = "Сотрудник/Мастер"
        verbose_name_plural = "Сотрудники/Мастера"

    def __str__(self):
        return f"{self.name} ({self.organization.name})"


# --- Модель 3: Услуга/Работа ---
class Service(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, verbose_name="Организация")
    name = models.CharField(max_length=255, verbose_name="Название Услуги/Работы")
    duration_minutes = models.IntegerField(verbose_name="Длительность (мин)")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Цена")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    employees = models.ManyToManyField(Employee, related_name='services')


    employees = models.ManyToManyField(
        Employee,
        related_name='services',
        verbose_name="Сотрудники, оказывающие услугу"
    )

    class Meta:
        verbose_name = "Услуга/Работа"
        verbose_name_plural = "Услуги/Работы"

    def __str__(self):
        return f"{self.name} - {self.price} ({self.organization.name})"


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
    service = models.ForeignKey(Service, on_delete=models.PROTECT)

    start_time = models.DateTimeField(verbose_name="Время начала")
    end_time = models.DateTimeField(verbose_name="Время окончания")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING', verbose_name="Статус")

    class Meta:
        verbose_name = "Запись/Бронирование"
        verbose_name_plural = "Записи/Бронирования"
        # Запрет двух записей у одного мастера в одно и то же время
        constraints = [
            models.UniqueConstraint(fields=['employee', 'start_time'], name='unique_employee_time')
        ]

    def __str__(self):
        return f"Запись {self.organization.name} на {self.start_time.strftime('%Y-%m-%d %H:%M')}"


# --- Модель 6: Рабочее Расписание Мастера (Критично для расчета слотов) ---
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
    # 1440 минут = 24 часа. Используем валидаторы для защиты данных.
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
        # У одного мастера может быть только одно расписание на каждый день
        unique_together = ('employee', 'day_of_week')

    def __str__(self):
        # Используем get_day_of_week_display() для вывода читаемого названия дня
        return f"{self.employee.name} - {self.get_day_of_week_display()}"