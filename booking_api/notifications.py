# booking_api/notifications.py

from django.core.mail import send_mail
from django.conf import settings


def send_appointment_confirmation(appointment):
    """
    Отправляет подтверждение записи на email клиента.
    """

    # 1. Формирование темы и тела письма
    subject = f'Подтверждение записи в {appointment.organization.name}'

    # Форматирование времени в удобном виде
    time_str = appointment.start_time.strftime('%Y-%m-%d в %H:%M')

    message = (
        f'Здравствуйте, {appointment.client.name}!\n\n'
        f'Ваша запись успешно создана и ожидает подтверждения.\n'
        f'Организация: {appointment.organization.name}\n'
        f'Услуга: {appointment.service.name}\n'
        f'Мастер: {appointment.employee.name}\n'
        f'Время: {time_str}\n\n'
        f'Статус записи: {appointment.get_status_display()}\n\n'
        f'Спасибо за выбор нашей платформы!'
    )

    # 2. Получение адресатов
    from_email = settings.DEFAULT_FROM_EMAIL or 'noreply@mastertime.com'
    recipient_list = [appointment.client.phone_number]  # Здесь мы используем телефон для теста,
    # но в реальной системе здесь был бы email

    # 3. Отправка письма (в консоль, благодаря настройкам)
    try:
        send_mail(
            subject,
            message,
            from_email,
            recipient_list,
            fail_silently=False,
        )
        print(f"Уведомление отправлено клиенту: {appointment.client.phone_number}")
    except Exception as e:
        print(f"Ошибка при отправке уведомления: {e}")