from datetime import date, datetime, timedelta
from django.db.models import Q
from django.utils import timezone  # <--- Обязательный импорт
from .models import Employee, Service, Appointment


class BookingService:
    """Сервис, отвечающий за расчет доступного времени для бронирования."""

    def __init__(self, employee: Employee, service: Service, booking_date: date):
        self.employee = employee
        self.service = service
        self.booking_date = booking_date
        # Общая длительность услуги, включая буфер
        self.slot_duration = service.total_duration

    def _get_base_working_intervals(self):
        # Этот метод реализован в модели Employee и возвращает интервалы в минутах (корректно)
        return self.employee.get_working_intervals(self.booking_date)

    def _get_booked_intervals(self):
        """
        Получает все занятые интервалы (Appointment) на дату.

        Возвращает: [(start_minutes, end_minutes), ...]
        """
        # *** ИСПРАВЛЕНИЕ 1: Использование make_aware для создания aware-времени ***
        # Это устраняет RuntimeWarning и обеспечивает корректную фильтрацию в БД.
        start_of_day_aware = timezone.make_aware(
            datetime.combine(self.booking_date, datetime.min.time())
        )
        # Для фильтрации end_time используем 00:00 следующего дня,
        # чтобы охватить все записи, начинающиеся в текущий день.
        end_of_day_aware = start_of_day_aware + timedelta(days=1)

        # Получаем подтвержденные или ожидающие записи, исключая отмененные
        booked_appointments = Appointment.objects.filter(
            employee=self.employee,
            # Фильтруем по aware-времени
            start_time__gte=start_of_day_aware,
            start_time__lt=end_of_day_aware,
        ).exclude(status__in=['CANCELLED', 'COMPLETED']).order_by('start_time')

        booked_intervals = []
        for appt in booked_appointments:
            # Преобразуем aware-datetime в минуты от aware-полуночи
            start_minutes = (appt.start_time - start_of_day_aware).total_seconds() // 60
            end_minutes = (appt.end_time - start_of_day_aware).total_seconds() // 60
            booked_intervals.append((int(start_minutes), int(end_minutes)))

        return booked_intervals

    # --- _subtract_intervals остается без изменений, т.к. работает с минутами ---
    def _subtract_intervals(self, base_intervals, subtrahend_intervals):
        """
        Вычитает один набор интервалов из другого.
        """
        all_busy = sorted(subtrahend_intervals)
        free_intervals = []

        for base_start, base_end in base_intervals:
            current_start = base_start

            for busy_start, busy_end in all_busy:
                if current_start >= base_end:
                    break

                if base_end > busy_start and base_start < busy_end:
                    if current_start < busy_start:
                        free_intervals.append((current_start, busy_start))

                    current_start = max(current_start, busy_end)

            if current_start < base_end:
                free_intervals.append((current_start, base_end))

        return free_intervals

    def get_available_slots(self):
        """
        Основной метод. Генерирует конечный список доступных слотов.

        Возвращает: Список объектов datetime для доступного времени.
        """
        base_intervals = self._get_base_working_intervals()
        booked_intervals = self._get_booked_intervals()

        free_intervals = self._subtract_intervals(base_intervals, booked_intervals)

        available_slots = []

        # *** ИСПРАВЛЕНИЕ 2: Использование aware-времени для сравнения ***
        # Получаем aware-время "полуночи" для текущей даты
        start_of_day_aware = timezone.make_aware(
            datetime.combine(self.booking_date, datetime.min.time())
        )

        # Получаем aware-время "сейчас"
        current_time_aware = timezone.now()
        # ***************************************************************

        # 5. Нарезаем свободные интервалы на бронируемые слоты
        for free_start, free_end in free_intervals:
            slot_start_minutes = free_start

            # ВАЖНОЕ ИЗМЕНЕНИЕ: Здесь мы должны округлить *текущее* время,
            # чтобы начать нарезку с ближайшего возможного слота (только для Сегодня).
            if self.booking_date == current_time_aware.date():
                # Минуты от полуночи до текущего времени
                minutes_now = (current_time_aware - start_of_day_aware).total_seconds() // 60

                # Определяем ближайшую минуту, с которой нужно начать нарезку.
                # Мы должны начать не раньше текущего времени.
                # Если текущее время 09:39, а длительность слота 60 мин,
                # ближайший слот, возможно, 10:00.

                # Начинаем нарезку с текущего времени, округленного до шага слота.
                # Если 9:39 и шаг 30 мин, округление должно дать 9:30 или 10:00.
                # В большинстве систем бронирования округляют ВВЕРХ до ближайшего *шага*.

                # Пример (длит. 60 мин, сейчас 9:39):
                # floor = 579 // 60 * 60 = 540 (9:00)
                # ceil  = floor + 60 = 600 (10:00)

                # Используем потолочное округление для минут:
                # 9:39 (579 мин), длительность 60. Нам нужно 600 мин (10:00).
                # 579 + 60 - 1 = 638
                # 638 // 60 = 10.6
                # 10 * 60 = 600

                # slot_duration - 1 нужен для корректного округления:
                # 579 + 60 - 1 = 638. 638 // 60 = 10. 10 * 60 = 600.
                # 600 + 60 - 1 = 659. 659 // 60 = 10. 10 * 60 = 600.

                # Если текущее время уже совпадает с началом слота (например, 10:00)
                # 600 + 60 - 1 = 659. 659 // 60 = 10. 10 * 60 = 600. (Корректно)

                # Скорректированное начало = ceil(minutes_now / slot_duration) * slot_duration
                # Или просто:
                # minutes_now = 579 (9:39)
                # next_start = ((minutes_now + self.slot_duration - 1) // self.slot_duration) * self.slot_duration

                next_start_minutes = ((
                                                  int(minutes_now) + self.slot_duration - 1) // self.slot_duration) * self.slot_duration

                # Мы начинаем нарезку с самой поздней точки: начала рабочего интервала (free_start)
                # или округленного текущего времени (next_start_minutes).
                slot_start_minutes = max(free_start, next_start_minutes)

            # Конец ВАЖНОГО ИЗМЕНЕНИЯ: Проверка/Округление только для Сегодня.

            while slot_start_minutes + self.slot_duration <= free_end:
                # Слоты, которые начинаются после now() уже учтены в логике max(free_start, next_start_minutes)
                # поэтому дополнительная проверка "if slot_datetime > current_time_aware" больше не нужна,
                # если мы правильно округляем.

                slot_datetime = start_of_day_aware + timedelta(minutes=slot_start_minutes)
                available_slots.append(slot_datetime)

                # 6. Временное логирование для отладки
                if not available_slots:
                    print(
                        f"DEBUG NO SLOTS: Date: {self.booking_date}, Base Intervals: {base_intervals}, Booked Intervals: {booked_intervals}, Free Intervals: {free_intervals}")

                # Переходим к следующему слоту (шаг = длительность слота)
                slot_start_minutes += self.slot_duration

        return available_slots