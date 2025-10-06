# booking_api/notifications.py

from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import logging
from .telegram_utils import send_telegram_notification  # НОВЫЙ ИМПОРТ

logger = logging.getLogger(__name__)


def send_appointment_confirmation(appointment):
    """
    Отправляет подтверждение записи клиенту (email/SMS - по вашему старому коду)
    И отправляет мгновенное уведомление мастеру (Telegram - новое требование).
    """

    # Получение локализованного времени начала и окончания
    start_time_local = timezone.localtime(appointment.start_time)
    end_time_local = timezone.localtime(appointment.end_time)

    # -------------------------------------------------------------
    # 1. МГНОВЕННОЕ УВЕДОМЛЕНИЕ МАСТЕРУ (TELEGRAM)
    # -------------------------------------------------------------
    master = appointment.employee

    print(
        f"--- DEBUG NOTIFY: Проверка мастера {master.id}. Chat ID: {master.telegram_chat_id}")  # <-- Должно быть в логе Django

    if master and master.telegram_chat_id:
        # Используем @property actual_duration и actual_price из модели Appointment
        print("--- DEBUG NOTIFY: Попытка отправки Telegram-уведомления...") # <-- Должно быть в логе Django

        notification_message = (
            f"🔔 *НОВАЯ ЗАПИСЬ!* ({appointment.organization.name}) 🔔\n\n"
            f"📅 Дата и Время: {start_time_local.strftime('%Y-%m-%d в %H:%M')}\n"
            f"⏳ Завершение: {end_time_local.strftime('%H:%M')} (Всего: {appointment.actual_duration} мин)\n"
            f"🛠 Услуга: {appointment.service.name}\n"
            f"💵 Цена: {appointment.actual_price:,.2f} руб.\n\n"
            f"👤 Клиент: {appointment.client.name}\n"
            f"📞 Телефон: {appointment.client.phone_number}\n"
            f"📍 Адрес: {appointment.address or 'Не указан'}"
        )

        # Вызываем функцию отправки
        send_telegram_notification(master.telegram_chat_id, notification_message)

    else:
        print(f"--- DEBUG NOTIFY: Мастер {master.id} не имеет Chat ID. Пропускаю.")  # <-- Должно быть в логе Django
    # -------------------------------------------------------------
    # 2. УВЕДОМЛЕНИЕ КЛИЕНТУ (EMAIL/SMS) - Адаптация вашего старого кода
    # -------------------------------------------------------------

    subject = f'Подтверждение записи в {appointment.organization.name}'

    # Форматирование времени в удобном виде
    time_str = start_time_local.strftime('%Y-%m-%d в %H:%M')

    message = (
        f'Здравствуйте, {appointment.client.name}!\n\n'
        f'Ваша запись успешно создана.\n'
        f'Организация: {appointment.organization.name}\n'
        f'Услуга: {appointment.service.name}\n'
        f'Мастер: {master.name if master else "Не назначен"}\n'
        f'Время: {time_str}\n'
        f'Общая длительность: {appointment.actual_duration} мин\n'
        f'Фактическая цена: {appointment.actual_price:,.2f} руб\n\n'
        f'Статус записи: {appointment.get_status_display()}\n\n'
        f'Спасибо за выбор нашей платформы!'
    )

    from_email = settings.DEFAULT_FROM_EMAIL or 'noreply@mastertime.com'
    # Внимание: Для реальной отправки email здесь должен быть email клиента,
    # а не phone_number. Оставляем phone_number, как в вашем исходном коде
    # для сохранения логики тестирования, но добавляем предупреждение.

    # В идеальной системе: recipient_list = [appointment.client.email]
    # Предполагаем, что Client.phone_number - это место для тестового вывода
    recipient_list = [appointment.client.phone_number]

    try:
        send_mail(
            subject,
            message,
            from_email,
            recipient_list,
            fail_silently=False,
        )
        logger.info(f"Подтверждение отправлено клиенту: {appointment.client.phone_number}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления клиенту: {e}")