from datetime import datetime, date, timedelta # Добавлен timedelta
from django.db.models import Q
from django.utils import timezone
from .models import Employee, Service

# Импортируем наш новый класс-сервис для расчета слотов
from .services import BookingService

# --- ДОБАВЛЕНЫ ИМПОРТЫ ДЛЯ ЛОГИРОВАНИЯ ---
import traceback
import logging
logger = logging.getLogger('booking_debug')
# ------------------------------------------

SLOT_STEP_MINUTES = 30


def calculate_available_slots(organization_id, service_id, date_str, employee_id=None):
    # ... (Весь ваш код Шага 1 и 2 без изменений)

    # 3. Итерация по каждому мастеру и использование BookingService
    all_available_slots = []

    for employee in employees:
        try:
            # Создаем экземпляр сервиса
            booking_service = BookingService(
                employee=employee,
                service=service,
                booking_date=target_date
            )

            # Получаем слоты (список объектов datetime)
            available_slots = booking_service.get_available_slots()

            # Форматируем результат для API
            for slot_time in available_slots:
                # ВНИМАНИЕ: Здесь мы не знаем end_time без дополнительного расчета,
                # но для простоты API часто возвращают только start_time.
                # Если нужен end_time, его можно легко рассчитать:
                slot_end = slot_time + timedelta(minutes=service.total_duration)

                all_available_slots.append({
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "time": slot_time.isoformat(),
                    "end_time": slot_end.isoformat(),
                })

        except Exception as e:
            # *** КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: ЛОГИРОВАНИЕ ПОЛНОГО TRACEBACK ***
            logger.error(f"FATAL ERROR: Ошибка при расчете слотов для {employee.name} на {date_str}")
            logger.error(traceback.format_exc())
            # **********************************************************
            continue  # Переходим к следующему мастеру

    # 4. Возвращаем отсортированный результат
    all_available_slots.sort(key=lambda x: (x['time'], x['employee_name']))

    return all_available_slots