# booking_api/management/commands/send_reminders.py

import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

# Предполагаем, что ваша модель называется Appointment
# Замените 'booking_api.models' на ваш реальный путь, если он другой
from booking_api.models import Appointment
from booking_api.telegram_utils import send_telegram_notification  # Используем существующую утилиту

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Отправляет напоминания клиентам о предстоящих записях.'

    def handle(self, *args, **options):
        # 1. Получаем смещение из настроек
        offset_hours = getattr(settings, 'CLIENT_REMINDER_OFFSET_HOURS', 24)

        # 2. Определяем временное окно
        now = timezone.now()

        # Напоминание отправляется за 24 часа (или сколько указано)
        # Мы ищем записи, которые начнутся ровно через OFFSET часов
        reminder_time = now + timedelta(hours=offset_hours)

        # Ищем записи в узком окне (например, 1 минута)
        # Это предотвращает отправку дубликатов, если команда запускается несколько раз
        time_start_window = reminder_time
        time_end_window = reminder_time + timedelta(minutes=1)

        logger.info(f"Запуск проверки напоминаний. Ищем записи между {time_start_window} и {time_end_window}.")

        # 3. Запрос к базе данных
        try:
            # ПРИМЕЧАНИЕ: Здесь нужно убедиться, что ваша модель Appointment имеет поле
            # start_time (DateTimeField) и client_chat_id (CharField)
            reminders_to_send = Appointment.objects.filter(
                start_time__gte=time_start_window,
                start_time__lt=time_end_window,
                is_client_reminder_sent=False,  # <-- Добавим это поле в модель позже!
                # Убедитесь, что запись подтверждена, если у вас есть статус
                status='CONFIRMED',  # ПРИМЕР: фильтр по подтвержденным записям
            ).select_related('employee', 'service')

            if not reminders_to_send.exists():
                logger.info("Напоминаний для отправки не найдено.")
                return

            # 4. Отправка уведомлений
            for appointment in reminders_to_send:

                # 🚨 ВАЖНО: Chat ID клиента должен быть привязан к его профилю или записи
                # Предполагаем, что у вас есть поле client_chat_id
                client_chat_id = appointment.client_chat_id

                if not client_chat_id:
                    logger.warning(
                        f"Клиент для записи ID {appointment.id} не имеет Chat ID. Напоминание не отправлено.")
                    continue

                # Формируем сообщение
                message = (
                    f"⏰ **Напоминание о записи!**\n\n"
                    f"Вы записаны на услугу **{appointment.service.name}** "
                    f"к мастеру **{appointment.employee.name}**.\n"
                    f"Время: **{appointment.start_time.astimezone(timezone.get_current_timezone()).strftime('%d.%m %H:%M')}**\n"
                    f"Ожидаем Вас!"
                )

                logger.info(f"Попытка отправить напоминание клиенту {client_chat_id} для записи ID {appointment.id}.")

                if send_telegram_notification(client_chat_id, message):
                    # Если отправка успешна, помечаем запись как "напоминание отправлено"
                    appointment.is_client_reminder_sent = True
                    appointment.save(update_fields=['is_client_reminder_sent'])
                    logger.info(f"Напоминание для записи ID {appointment.id} успешно отправлено.")
                else:
                    logger.error(f"Не удалось отправить напоминание для записи ID {appointment.id}.")

        except Exception as e:
            logger.error(f"Критическая ошибка при выполнении команды send_reminders: {e}")