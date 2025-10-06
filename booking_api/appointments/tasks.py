from celery import shared_task
from django.core.management import call_command
import logging

# Настройка логирования для задач Celery
logger = logging.getLogger(__name__)


@shared_task
def send_appointment_reminders():
    """
    Celery Task: Запускает Django Management Command 'send_reminders'.

    Эта функция будет вызываться по расписанию Celery Beat (например, каждый час).
    Она изолирует Celery от деталей реализации команды.
    """
    logger.info("-> Запуск задачи send_appointment_reminders...")
    try:
        # call_command — это встроенный в Django способ вызова любой management command
        # по её имени ('send_reminders' в данном случае).
        call_command('send_reminders')
        logger.info("-> Задача send_appointment_reminders завершена успешно.")
    except Exception as e:
        # Логирование ошибок, если команда не смогла запуститься или упала
        logger.error(f"-> Ошибка при запуске send_reminders: {e}")
