# booking_api/utils.py (ИСЛАВЛЕННАЯ ВЕРСИЯ)

from datetime import datetime, time, timedelta, date
from django.db.models import Q
from django.utils import timezone
from .models import EmployeeSchedule, Appointment, Service, Employee

# Длительность интервала (шаг), с которым мы будем предлагать слоты (в минутах)
# Этот шаг определяет, как часто мастер может начинать работу (например, в 10:00, 10:30, 11:00)
SLOT_STEP_MINUTES = 30


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

    now = timezone.now()
    is_today = (target_date == now.date())

    if target_date < now.date():
        return {"error": "Невозможно забронировать прошедшую дату."}, 400

    try:
        service = Service.objects.get(pk=service_id)
        # ИСПРАВЛЕНО: Берем полную длительность (Базовая Длительность + Буфер)
        required_duration = service.total_duration
    except Service.DoesNotExist:
        return {"error": f"Услуга с ID={service_id} не найдена."}, 404

    day_of_week = target_date.weekday()

    all_available_slots = []

    # 2. Определение мастеров и расписаний

    schedule_filter = Q(employee__organization_id=organization_id, day_of_week=day_of_week)

    if employee_id:
        # Если передан ID, ищем расписание только для этого мастера
        schedule_filter &= Q(employee_id=employee_id)
    else:
        # Если ID не передан, фильтруем по мастерам, которые оказывают эту услугу
        schedule_filter &= Q(employee__services=service)

    schedules = EmployeeSchedule.objects.filter(schedule_filter).select_related('employee')

    if not schedules.exists():
        return []

    # 3. Итерация по каждому мастеру
    for schedule in schedules:
        employee = schedule.employee

        start_minutes = schedule.start_minutes
        end_minutes = schedule.end_minutes

        # Создаем объекты datetime (в UTC) для начала и конца рабочего дня
        target_datetime_start = timezone.make_aware(datetime.combine(target_date, time(0, 0)))

        # Начало работы в UTC
        shift_start = target_datetime_start + timedelta(minutes=start_minutes)
        # Конец работы в UTC
        shift_end = target_datetime_start + timedelta(minutes=end_minutes)

        if shift_end <= shift_start:
            continue

        # 4. Настройка начального времени для поиска слотов

        # Если сегодня, начинаем поиск с ближайшего шага, который больше текущего времени
        if is_today:
            # Сначала округляем текущее время (now) вверх до ближайшего шага (SLOT_STEP_MINUTES)
            now_minutes = now.hour * 60 + now.minute

            # Рассчитываем, сколько минут осталось до следующего шага
            remainder = now_minutes % SLOT_STEP_MINUTES
            next_start_minutes = now_minutes - remainder + SLOT_STEP_MINUTES

            # Конвертируем в объект datetime для сравнения
            next_start_time = target_datetime_start + timedelta(minutes=next_start_minutes)

            # Выбираем: либо начало смены, либо время после округления (если смена уже началась)
            current_time_slot = max(shift_start, next_start_time)
        else:
            # Если не сегодня, начинаем с начала смены
            current_time_slot = shift_start

        # 5. Получение всех существующих записей (занятых слотов) на этот день
        booked_appointments = Appointment.objects.filter(
            employee=employee,
            start_time__date=target_date,
            status__in=['PENDING', 'CONFIRMED']
        ).order_by('start_time')

        # 6. Генерация и проверка потенциальных слотов

        # required_duration - это полная длительность услуги, включая буфер.

        # Условие цикла: Слот + полная длительность услуги должны закончиться до конца смены
        while current_time_slot + timedelta(minutes=required_duration) <= shift_end:
            slot_end = current_time_slot + timedelta(minutes=required_duration)

            # Проверка: если начало слота в прошлом (могло быть пропущено в п.4, но перепроверяем)
            if is_today and current_time_slot < now:
                current_time_slot += timedelta(minutes=SLOT_STEP_MINUTES)
                continue

            is_booked = False

            # Проверка конфликта с существующими записями
            for booked in booked_appointments:
                # Условие конфликта (пересечения):
                # Слот начинается до того, как запись заканчивается
                # И слот заканчивается после того, как запись начинается
                if current_time_slot < booked.end_time and slot_end > booked.start_time:
                    is_booked = True
                    break

            # 7. Если слот свободен, добавляем его
            if not is_booked:
                all_available_slots.append({
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "time": current_time_slot.isoformat(),
                    "end_time": slot_end.isoformat(),
                })

            # Переходим к следующему потенциальному времени с шагом SLOT_STEP_MINUTES
            current_time_slot += timedelta(minutes=SLOT_STEP_MINUTES)

    # 8. Возвращаем отсортированный результат
    all_available_slots.sort(key=lambda x: (x['time'], x['employee_name']))

    return all_available_slots