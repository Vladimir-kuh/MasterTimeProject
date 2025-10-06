# booking_api/utils.py (ИСЛАВЛЕННАЯ ВЕРСИЯ)

from datetime import datetime, time, timedelta, date
from django.db.models import Q
from django.utils import timezone
from .models import EmployeeSchedule, Appointment, Service, Employee

# Длительность интервала (шаг), с которым мы будем предлагать слоты (в минутах)
SLOT_STEP_MINUTES = 30


def minutes_to_time(minutes):
    """Преобразует общее количество минут от полуночи в объект time."""
    return time(hour=minutes // 60, minute=minutes % 60)


def time_to_minutes(time_obj):
    """Преобразует объект time в общее количество минут от полуночи."""
    return time_obj.hour * 60 + time_obj.minute


def calculate_available_slots(organization_id, service_id, date_str, employee_id=None):
    """
    Рассчитывает доступные слоты для конкретного мастера (если указан) или для всех
    мастеров организации на заданную дату.
    """

    # 1. Подготовка данных и проверка
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return {"error": "Неверный формат даты. Используйте ГГГГ-ММ-ДД."}, 400

    if target_date < timezone.now().date():
        return {"error": "Невозможно забронировать прошедшую дату."}, 400

    try:
        service = Service.objects.get(pk=service_id)
        slot_duration = service.duration_minutes
    except Service.DoesNotExist:
        return {"error": f"Услуга с ID={service_id} не найдена."}, 404

    day_of_week = target_date.weekday()  # Понедельник=0, Воскресенье=6

    # Контейнер для хранения всех свободных слотов
    all_available_slots = []

    # 2. Получение расписаний для ОДНОГО МАСТЕРА

    schedule_filter = Q(employee__organization_id=organization_id, day_of_week=day_of_week)

    if employee_id:
        schedule_filter &= Q(employee_id=employee_id)

    schedules = EmployeeSchedule.objects.filter(schedule_filter).select_related('employee')

    if not schedules.exists():
        # Если расписания нет для конкретного мастера в этот день
        return []

    # 3. Итерация по каждому мастеру (теперь это либо 0, либо 1 мастер)
    for schedule in schedules:
        employee = schedule.employee

        # Переводим начало/конец рабочего дня в объекты datetime (для работы с UTC)
        start_minutes = schedule.start_minutes
        end_minutes = schedule.end_minutes

        # Создаем объекты datetime в UTC для начала и конца рабочего дня
        # target_datetime_start представляет 00:00:00 этого дня в UTC
        target_datetime_start = timezone.make_aware(datetime.combine(target_date, time(0, 0)))

        # Начало работы: 00:00:00 + start_minutes
        shift_start = target_datetime_start + timedelta(minutes=start_minutes)
        # Конец работы: 00:00:00 + end_minutes
        shift_end = target_datetime_start + timedelta(minutes=end_minutes)

        # Если смена переходит на следующий день, это нужно учесть, но для простоты:
        # предполагаем, что end_minutes > start_minutes
        if shift_end <= shift_start:
            continue  # Пропускаем невалидное расписание

        # 4. Получение всех существующих записей (занятых слотов) на этот день
        booked_appointments = Appointment.objects.filter(
            employee=employee,
            start_time__date=target_date,
            # Статусы, которые блокируют бронирование: PENDING (ожидает), CONFIRMED (подтверждена)
            status__in=['PENDING', 'CONFIRMED']
        ).order_by('start_time')

        # 5. Генерация потенциальных слотов (от начала смены до конца)

        current_time_slot = shift_start

        while current_time_slot + timedelta(minutes=slot_duration) <= shift_end:
            slot_end = current_time_slot + timedelta(minutes=slot_duration)

            is_booked = False

            # Проверка, не пересекается ли потенциальный слот с существующими записями
            for booked in booked_appointments:
                # Условие конфликта (пересечения):
                # Слот начинается до того, как запись заканчивается (current_time_slot < booked.end_time)
                # И слот заканчивается после того, как запись начинается (slot_end > booked.start_time)
                if current_time_slot < booked.end_time and slot_end > booked.start_time:
                    is_booked = True
                    break  # Слот занят, переходим к следующему

            # 6. Если слот свободен, добавляем его в список
            if not is_booked:
                # Добавляем свободный слот
                all_available_slots.append({
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    # Время должно быть в формате ISO 8601 для API (с часовым поясом)
                    "time": current_time_slot.isoformat(),
                    "end_time": slot_end.isoformat(),  # Полезно знать, когда закончится
                })

            # Переходим к следующему потенциальному времени с шагом SLOT_STEP_MINUTES
            current_time_slot += timedelta(minutes=SLOT_STEP_MINUTES)

    # 7. Возвращаем отсортированный результат
    # Сортируем по времени, затем по имени мастера
    all_available_slots.sort(key=lambda x: (x['time'], x['employee_name']))

    return all_available_slots