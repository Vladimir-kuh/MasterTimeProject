# booking_api/telegram_utils.py (ИСПРАВЛЕННАЯ ВЕРСИЯ)

import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def send_telegram_notification(chat_id: str, message: str) -> bool:
    """
    Отправляет уведомление в Telegram. Токен извлекается внутри функции
    для гарантии, что настройки Django уже загружены.

    :param chat_id: Telegram Chat ID мастера.
    :param message: Текст сообщения (в формате Markdown).
    :return: True, если отправка успешна, иначе False.
    """
    # 🚨 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Извлекаем токен здесь
    TELEGRAM_BOT_TOKEN = getattr(settings, "TELEGRAM_BOT_TOKEN", None)

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ошибка: TELEGRAM_BOT_TOKEN не установлен в settings.py")
        return False

    if not chat_id:
        # Для случаев, когда мастер не подключен к боту (chat_id = None)
        logger.warning("Ошибка: Chat ID мастера не указан.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
    }

    try:
        response = requests.post(url, data=payload, timeout=5)
        # Если Telegram возвращает 4xx или 5xx, будет возбуждено исключение RequestException
        response.raise_for_status()

        response_json = response.json()

        if response_json.get('ok'):
            logger.info(f"Уведомление успешно отправлено в чат {chat_id}.")
            return True
        else:
            # Сюда попадаем, если response.raise_for_status() не сработал (например, код 200 OK),
            # но Telegram API вернул {'ok': False}
            logger.error(f"Ошибка API Telegram: {response_json.get('description')}")
            return False

    except requests.exceptions.HTTPError as e:
        # Обрабатываем ошибки 4xx (Bad Request, Forbidden) и 5xx
        error_info = ""
        try:
            error_info = e.response.json().get('description', 'Неизвестная ошибка')
        except:
            pass

        logger.error(f"Ошибка HTTP ({e.response.status_code}) при отправке в Telegram: {error_info}")
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при отправке запроса в Telegram: {e}")
        return False