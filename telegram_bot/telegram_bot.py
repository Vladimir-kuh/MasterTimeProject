import os
import requests
import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
import telegram
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
)
from dotenv import load_dotenv
from datetime import date, timedelta  # 👈 Оставляем timedelta
import calendar
import re
from typing import List, Dict, Any, Union  # 👈 Добавлен импорт для type hinting

# --- 0. Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# --- 1. Настройка и константы ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
BOT_PASSWORD = os.getenv("BOT_PASSWORD")
TOKEN_OBTAIN_URL = os.getenv("TOKEN_OBTAIN_URL")
TOKEN_REFRESH_URL = os.getenv("TOKEN_REFRESH_URL")

if not TELEGRAM_BOT_TOKEN or not API_BASE_URL:
    logger.critical("Необходимо установить TELEGRAM_BOT_TOKEN и API_BASE_URL в .env")
    raise ValueError("Необходимо установить TELEGRAM_BOT_TOKEN и API_BASE_URL в .env")

# URL-константы
SERVICES_URL = f"{API_BASE_URL}services/"
EMPLOYEES_URL = f"{API_BASE_URL}employees/"
SLOTS_URL = f"{API_BASE_URL}appointments/available_slots/"
APPOINTMENTS_URL = f"{API_BASE_URL}appointments/"

ORGANIZATION_ID = 1

# --- Переменные для динамического хранения токенов ---
GLOBAL_TOKENS = {
    'access': None,
    'refresh': None
}


# --- 2. Вспомогательные функции для токенов и API ---

def obtain_initial_tokens() -> bool:
    """Получает Access и Refresh токены при запуске."""
    global GLOBAL_TOKENS

    if not all([BOT_USERNAME, BOT_PASSWORD, TOKEN_OBTAIN_URL]):
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют BOT_USERNAME, BOT_PASSWORD или TOKEN_OBTAIN_URL.")
        return False

    logger.info("⏳ Получаю начальные Access и Refresh токены...")
    payload = {"username": BOT_USERNAME, "password": BOT_PASSWORD}
    try:
        response = requests.post(TOKEN_OBTAIN_URL, json=payload)
        response.raise_for_status()
        tokens = response.json()
        GLOBAL_TOKENS['access'] = tokens.get('access')
        GLOBAL_TOKENS['refresh'] = tokens.get('refresh')
        logger.info("✅ Токены успешно получены.")
        return True
    except requests.exceptions.RequestException as e:
        logger.fatal(f"ФАТАЛЬНАЯ ОШИБКА ПОЛУЧЕНИЯ ТОКЕНА: {e}")
        return False


def refresh_access_token() -> bool:
    """Обновляет Access Token, используя Refresh Token."""
    global GLOBAL_TOKENS
    if not GLOBAL_TOKENS['refresh']:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Отсутствует Refresh Token.")
        return False
    logger.info("⏳ Пытаюсь обновить Access Token...")
    try:
        response = requests.post(TOKEN_REFRESH_URL, json={'refresh': GLOBAL_TOKENS['refresh']})
        response.raise_for_status()
        new_tokens = response.json()
        GLOBAL_TOKENS['access'] = new_tokens.get('access')
        if 'refresh' in new_tokens:
            GLOBAL_TOKENS['refresh'] = new_tokens['refresh']
        logger.info("✅ Access Token успешно обновлен.")
        return True
    except requests.exceptions.RequestException as e:
        logger.fatal(f"ФАТАЛЬНАЯ ОШИБКА ОБНОВЛЕНИЯ ТОКЕНА: {e}")
        return False


def make_api_request(method: str, url: str, **kwargs) -> Union[requests.Response, None]:
    """Универсальный обработчик запросов с логикой обновления токена."""
    global GLOBAL_TOKENS
    logger.debug(f"API Запрос: {method} {url}, Параметры: {kwargs.get('params', 'Нет')}")

    def execute_request(current_access_token: str):
        headers = kwargs.pop('headers', {})
        if current_access_token:
            headers['Authorization'] = f"Bearer {current_access_token}"
        return requests.request(method, url, headers=headers, **kwargs)

    current_access = GLOBAL_TOKENS['access']
    if not current_access:
        if not obtain_initial_tokens() and not refresh_access_token():
            logger.error("Отсутствует Access Token и не удалось его получить/обновить.")
            return None
        current_access = GLOBAL_TOKENS['access']

    response = execute_request(current_access)

    if response.status_code == 401:
        logger.warning("⚠️ Получен 401 Unauthorized. Пытаюсь обновить токен...")
        if refresh_access_token():
            logger.info("🔄 Повторяю запрос с новым Access Token...")
            response = execute_request(GLOBAL_TOKENS['access'])
        else:
            logger.error("Не удалось обновить токен, запрос не выполнен.")
            return None

    logger.debug(f"API Ответ: Статус {response.status_code}")
    return response


# -----------------------------------------------------------
# 🌟 ИСПРАВЛЕННАЯ ФУНКЦИЯ: fetch_available_days
# -----------------------------------------------------------

def fetch_available_days(employee_id: str, year: int, month: int, service_id: str) -> set[str]:
    """
    Запрашивает у API доступность, делая отдельный запрос для каждого дня месяца,
    начиная с сегодняшнего дня.
    """
    first_day_of_month = date(year, month, 1)
    _, last_day_num = calendar.monthrange(year, month)
    last_day_of_month = date(year, month, last_day_num)
    today = date.today()

    available_days = set()

    # Начинаем цикл с сегодняшнего дня, если месяц - текущий, иначе - с 1-го числа
    if first_day_of_month.month == today.month and first_day_of_month.year == today.year:
        current_day = today
    else:
        current_day = first_day_of_month

    logger.info(f"Начинаю пошаговый запрос доступности для мастера {employee_id} ({year}-{month})...")

    while current_day <= last_day_of_month:

        if current_day.month != month:
            current_day += timedelta(days=1)
            continue

        date_str = current_day.strftime('%Y-%m-%d')

        params = {
            'org_id': ORGANIZATION_ID,
            'employee_id': employee_id,
            'service_id': service_id,
            'date': date_str,
        }

        response = make_api_request('GET', SLOTS_URL, params=params)

        if response is None:
            logger.error(f"API запрос для дня {date_str} не удался (Ошибка токена/подключения).")
            current_day += timedelta(days=1)
            continue

        # Мы НЕ используем response.raise_for_status() здесь,
        # так как даже 404/400 может быть полезен для отладки.

        if not response.ok:
            logger.error(
                f"❌ API запрос для дня {date_str} вернул ошибку: {response.status_code}. Ответ: {response.text[:100]}..."
            )
            current_day += timedelta(days=1)
            continue

        try:
            slots_data = response.json()

            # Логируем фактическое количество байт, чтобы сравнить с логами Django
            logger.debug(f"API Response Length for {date_str}: {len(response.content)} bytes.")

            # Если API вернул непустой список (есть свободные слоты), то день доступен.
            if isinstance(slots_data, list) and len(slots_data) > 0:
                available_days.add(date_str)
                logger.info(f"✅ Найдены слоты на {date_str}. (Кол-во: {len(slots_data)})")
            else:
                # Этот лог поймает дни с 200 140 байт, которые мы видели в логах Django
                logger.debug(f"❌ Слотов на {date_str} не найдено. Список слотов пуст.")

        except requests.exceptions.JSONDecodeError as e:
            # ЛОВИМ ОШИБКИ ДЕКОДИРОВАНИЯ JSON
            logger.error(f"🔴 ОШИБКА ДЕКОДИРОВАНИЯ JSON для {date_str}: {e}. Ответ: {response.text[:100]}...")

        except Exception as e:
            logger.error(f"🔴 Неизвестная ошибка обработки ответа для {date_str}: {e}. Ответ: {response.text[:100]}...")

        current_day += timedelta(days=1)

    logger.info(f"Финальный результат доступности ({year}-{month}): Найдено {len(available_days)} доступных дней.")
    return available_days


# -----------------------------------------------------------
# 🆕 НАВИГАЦИОННЫЕ КНОПКИ
# -----------------------------------------------------------

def get_navigation_keyboard(back_to_data: str = None) -> List[List[InlineKeyboardButton]]:
    """
    Создает ряд с кнопками навигации.
    """
    nav_row = []
    if back_to_data:
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=back_to_data))
    nav_row.append(InlineKeyboardButton("🏠 Главное меню", callback_data='MAIN_MENU'))
    return [nav_row]


# -----------------------------------------------------------
# 3. Основные команды (start, services, my_appointments)
# -----------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка команды /start"""
    user_name = update.effective_user.first_name or "Пользователь"

    keyboard = [
        [InlineKeyboardButton("✅ Записаться на услугу", callback_data='start_booking')],
        [InlineKeyboardButton("🗓️ Мои записи", callback_data='view_appointments')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"👋 Привет, {user_name}! Я бот для записи на услуги. Что бы вы хотели сделать?",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            f"👋 Привет, {user_name}! Я бот для записи на услуги. Что бы вы хотели сделать?",
            reply_markup=reply_markup
        )


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Получает и отображает список доступных услуг."""
    user_id = update.effective_user.id

    message = "Загружаю список услуг..."
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=message)
        except:
            await update.effective_message.reply_text(text=message)
    else:
        await update.message.reply_text(text=message)

    params = {'organization_id': ORGANIZATION_ID}
    response = make_api_request('GET', SERVICES_URL, params=params)

    if response is None or not response.ok:
        logger.error(
            f"User {user_id}: API request for services failed (Status {response.status_code if response else 'None'}).")
        error_message = "❌ Не удалось получить список услуг. Попробуйте позже."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)
        return

    services = response.json()
    keyboard = []
    message_text = "Выберите услугу для записи:"

    for service in services:
        service_id = service.get('id')
        name = service.get('name')
        price = service.get('price')
        if service_id and name:
            label = f"{name} ({price} ₽)" if price else name
            callback_data = f"service_{service_id}"
            keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])

    keyboard.extend(get_navigation_keyboard(back_to_data=None))

    if not services:
        message_text = "😔 В настоящее время нет доступных услуг."

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)


async def my_appointments_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрашивает номер телефона для просмотра записей."""

    context.user_data['awaiting_phone_for_view'] = True

    keyboard = [[KeyboardButton("Поделиться контактом", request_contact=True)]]
    reply_markup_reply = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    message = "📞 Чтобы просмотреть ваши записи, пожалуйста, отправьте свой номер телефона."

    if update.callback_query:
        query = update.callback_query

        try:
            await query.edit_message_text(
                text="➡️ Переход к просмотру записей. Пожалуйста, посмотрите на поле ввода ниже."
            )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение после callback'а 'Мои записи': {e}")

        await update.effective_chat.send_message(
            message,
            reply_markup=reply_markup_reply
        )
    else:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup_reply
        )


# -----------------------------------------------------------
# 4. Логика бронирования (Мастер, Календарь, Слоты, Финализация)
# -----------------------------------------------------------

async def show_employees_for_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Получает и отображает список мастеров, привязанных к выбранной услуге."""
    query = update.callback_query
    user_id = update.effective_user.id
    service_id = context.user_data.get('selected_service_id')

    if not service_id:
        await query.edit_message_text("❌ Ошибка: Услуга не выбрана.")
        return

    message_text = "🧑‍🔧 Загружаю список доступных мастеров..."
    await query.edit_message_text(text=message_text)

    params = {
        'organization_id': ORGANIZATION_ID,
        'service_id': service_id
    }

    try:
        response = make_api_request('GET', EMPLOYEES_URL, params=params)

        if response is None or not response.ok:
            logger.error(
                f"User {user_id}: API request for employees failed (Status {response.status_code if response else 'None'}).")
            await query.edit_message_text("❌ Извините, не удалось получить список мастеров для этой услуги.")
            return

        employees = response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"User {user_id}: Ошибка при запросе мастеров к API: {e}")
        await query.edit_message_text(
            "❌ Извините, произошла ошибка связи с сервером при получении списка мастеров.")
        return

    keyboard = []
    message_text = "👤 Выберите мастера, к которому вы хотите записаться:"

    for employee in employees:
        employee_id = employee.get('id')
        employee_name = employee.get('name')
        if employee_id and employee_name:
            callback_data = f"employee_{employee_id}"
            keyboard.append([InlineKeyboardButton(employee_name, callback_data=callback_data)])

    keyboard.extend(get_navigation_keyboard(back_to_data='start_booking'))

    if not employees:
        final_message = "😔 В настоящее время нет мастеров, оказывающих эту услугу."
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(final_message, reply_markup=reply_markup)
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=message_text, reply_markup=reply_markup)


def create_calendar(year: int, month: int, service_id: str, available_days: set[str]) -> InlineKeyboardMarkup:
    """
    Создает Inline Keyboard с календарем, выделяя только доступные дни.
    :param available_days: Множество строк 'YYYY-MM-DD' с доступными датами.
    """
    logger.info(f"Генерация календаря: {calendar.month_name[month]} {year}. Доступно дней: {len(available_days)}")

    # Устанавливаем локаль для корректного отображения названия месяца
    try:
        import locale
        locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')
        month_name = calendar.month_name[month].capitalize()
    except:
        month_name = calendar.month_name[month]

    header = [
        [
            InlineKeyboardButton("⬅️", callback_data=f'CALEND_PREV_{year}_{month}_{service_id}'),
            InlineKeyboardButton(f"{month_name} {year}", callback_data='IGNORE'),
            InlineKeyboardButton("➡️", callback_data=f'CALEND_NEXT_{year}_{month}_{service_id}'),
        ]
    ]
    # Используем русские названия дней недели
    week_days = [InlineKeyboardButton(day, callback_data='IGNORE') for day in
                 ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]]
    keyboard = [week_days]

    today = date.today()
    # Начинаем неделю с понедельника (0)
    month_calendar = calendar.Calendar(0).monthdatescalendar(year, month)

    for week in month_calendar:
        row = []
        for day in week:
            date_str = day.strftime("%Y-%m-%d")

            if day.month != month:
                row.append(InlineKeyboardButton(" ", callback_data='IGNORE'))
            elif day < today:
                # В календаре показываем, что прошлые дни недоступны
                row.append(InlineKeyboardButton("❌", callback_data='IGNORE'))
            elif date_str in available_days:
                # Доступный день, найденный через API
                callback_data = f'CALEND_DAY_{date_str}'
                row.append(InlineKeyboardButton(str(day.day), callback_data=callback_data))
            else:
                # Рабочий день, но без свободных слотов (включая выходные)
                row.append(InlineKeyboardButton("⚫", callback_data='IGNORE_DISABLED_DAY'))
        keyboard.append(row)

    keyboard.extend(get_navigation_keyboard(back_to_data='BACK_TO_EMPLOYEES'))

    return InlineKeyboardMarkup(header + keyboard)


async def show_calendar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отображает календарь, предварительно запрашивая доступные дни месяца."""
    now = date.today()
    query = update.callback_query

    current_service_id = context.user_data.get('selected_service_id')
    current_employee_id = context.user_data.get('selected_employee_id')

    if not all([current_service_id, current_employee_id]):
        error_msg = "❌ Ошибка: Услуга или мастер не выбраны. Начните запись снова."
        if query:
            await query.edit_message_text(error_msg)
        else:
            await update.effective_message.reply_text(error_msg)
        return

    current_year = context.user_data.get('calendar_year', now.year)
    current_month = context.user_data.get('calendar_month', now.month)

    context.user_data['calendar_year'] = current_year
    context.user_data['calendar_month'] = current_month

    message_text = "⏳ Загружаю доступность на месяц..."

    try:
        await query.edit_message_text(text=message_text)
    except Exception:
        await update.effective_message.reply_text(text=message_text)

    # Запрашиваем доступность у API
    available_days = fetch_available_days(current_employee_id, current_year, current_month, current_service_id)

    # Создаем клавиатуру с учетом доступности
    reply_markup = create_calendar(current_year, current_month, current_service_id, available_days)
    message_text = "🗓️ Выберите удобную дату для записи (**⚫** — нет слотов):"

    try:
        await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Failed to edit message in show_calendar_command: {e}")
        await update.effective_message.reply_text(text=message_text, reply_markup=reply_markup, parse_mode='Markdown')


async def show_available_slots(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Получает и отображает свободные слоты."""
    query = update.callback_query
    user_id = update.effective_user.id
    service_id = context.user_data.get('selected_service_id')
    selected_date = context.user_data.get('selected_date')
    employee_id = context.user_data.get('selected_employee_id')

    if not all([service_id, selected_date, employee_id]):
        logger.error(f"User {user_id}: Missing context data: {context.user_data}")
        await query.edit_message_text("❌ Ошибка: Не удалось найти выбранную услугу, мастера или дату.")
        return

    logger.info(f"User {user_id}: Requesting slots for Master ID {employee_id} on Date {selected_date}")

    message_text = f"🗓️ Вы выбрали **{selected_date}** (Мастер ID: {employee_id}).\nЗагружаю свободные слоты..."
    await query.edit_message_text(text=message_text, parse_mode='Markdown')

    params = {
        'org_id': ORGANIZATION_ID,
        'service_id': service_id,
        'date': selected_date,
        'employee_id': employee_id
    }

    try:
        response = make_api_request('GET', SLOTS_URL, params=params)

        if response is None:
            await query.edit_message_text("❌ Критическая ошибка авторизации. Попробуйте позже.")
            return

        response.raise_for_status()
        slot_data = response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"User {user_id}: Ошибка при запросе слотов к API: {e}")
        await query.edit_message_text(
            "❌ Извините, произошла ошибка при получении доступного времени. Попробуйте другую дату или услугу.")
        return

    available_slots = slot_data
    filtered_slots = []

    for slot_detail in available_slots:
        # Проверяем, что это словарь и содержит ключ 'time'
        if isinstance(slot_detail, dict) and 'time' in slot_detail:
            try:
                # Преобразование ISO-формата с 'Z' в корректный datetime объект
                dt_object = datetime.datetime.fromisoformat(slot_detail['time'].replace('Z', '+00:00'))
                time_str = dt_object.strftime('%H:%M')
                filtered_slots.append(time_str)
            except (ValueError, TypeError) as e:
                logger.error(f"Ошибка парсинга времени для слота: {slot_detail}. Ошибка: {e}")
                continue

    keyboard = []
    row = []

    for slot in filtered_slots:
        callback_data = f"SLOT_{slot}"
        row.append(InlineKeyboardButton(slot, callback_data=callback_data))
        if len(row) == 3:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.extend(get_navigation_keyboard(back_to_data='BACK_TO_CALENDAR'))

    if not filtered_slots:
        final_message = (
            f"😔 На дату **{selected_date}** нет свободных слотов для выбранного мастера.\n"
            "Пожалуйста, вернитесь в календарь и выберите другую дату."
        )
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(final_message, parse_mode='Markdown', reply_markup=reply_markup)
        return

    final_message = "⏰ Выберите удобное время для записи:"
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=final_message, reply_markup=reply_markup, parse_mode='Markdown')


async def finalize_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Собирает данные и отправляет POST-запрос на создание записи."""
    await update.message.reply_text(
        "Спасибо! Отправляю вашу запись на сервер...",
        reply_markup=telegram.ReplyKeyboardRemove()
    )
    user_id = update.effective_user.id
    client_name = context.user_data.get('client_name')
    client_phone_number = context.user_data.get('client_phone_number')
    service_id = context.user_data.get('selected_service_id')
    employee_id = context.user_data.get('selected_employee_id')
    selected_date = context.user_data.get('selected_date')
    selected_slot = context.user_data.get('selected_slot')

    client_chat_id = context.user_data.get('telegram_chat_id')

    # Время должно быть в формате ISO 8601 с информацией о часовом поясе
    # Поскольку Django API возвращает время в UTC, мы должны отправить в UTC или с TZ.
    # Простейший способ — добавить 'Z' (Zulu time, UTC)
    start_time_str = f"{selected_date}T{selected_slot}:00Z"

    if not all([client_name, client_phone_number, service_id, employee_id, start_time_str, client_chat_id]):
        logger.error(f"User {user_id}: Finalization failed due to missing data: {context.user_data}")
        await update.message.reply_text("❌ Критическая ошибка данных: Пожалуйста, начните запись сначала (/start).")
        context.user_data.clear()
        return

    payload = {
        "organization": ORGANIZATION_ID,
        "service": int(service_id),
        "employee": int(employee_id),
        "client_name": client_name,
        "client_phone_number": client_phone_number,
        "start_time": start_time_str,
        "client_chat_id": client_chat_id,
    }

    logger.debug(f"User {user_id}: Payload for POST: {payload}")

    try:
        response = make_api_request('POST', APPOINTMENTS_URL, json=payload)

        if response is None:
            await update.message.reply_text("❌ Критическая ошибка авторизации. Сервис недоступен.")
            return

        response_data = response.json()

        if response.status_code == 400:
            error_detail = response_data.get('time_slot') or response_data.get('non_field_errors') or response_data.get(
                'employee') or response_data
            logger.error(f"User {user_id}: HTTP 400 Error on finalization: {error_detail}")
            error_message = (
                "❌ **Ошибка при создании записи.**\n"
                "К сожалению, сервер ответил отказом.\n\n"
                f"**Детали:** {error_detail}\n\n"
                "Пожалуйста, начните запись сначала и проверьте доступность слота."
            )
            await update.message.reply_text(error_message, parse_mode='Markdown')
            return

        response.raise_for_status()

        logger.info(f"User {user_id}: ✅ Appointment successfully created. Response: {response_data}")

        employee_name = response_data.get('employee_name', f'Мастер ID: {employee_id}')

        context.user_data.clear()

        success_message = (
            f"✅ **Запись успешно создана!**\n\n"
            f"**Услуга:** {response_data.get('service_name', service_id)}\n"
            f"**Мастер:** {employee_name}\n"
            f"**Дата и время:** {selected_date} в {selected_slot}\n"
            f"**Клиент:** {client_name} ({client_phone_number})\n\n"
            "Мы будем ждать вас!"
        )
        await update.message.reply_text(success_message, parse_mode='Markdown')

    except requests.exceptions.RequestException as e:
        logger.error(f"User {user_id}: RequestException during finalization API call: {e}")
        await update.message.reply_text("❌ Ошибка связи с сервером. Попробуйте позже.")


# -----------------------------------------------------------
# 5. Вспомогательные функции для сбора данных клиента
# -----------------------------------------------------------

def clean_phone_number(phone: str) -> str:
    """Удаляет из номера телефона все, кроме цифр и знака '+' (если он в начале)."""
    cleaned = re.sub(r'\D', '', phone)
    if phone.startswith('+'):
        return '+' + cleaned
    return cleaned


async def request_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрашивает имя клиента."""
    context.user_data['awaiting_name'] = True
    context.user_data['telegram_chat_id'] = str(update.effective_user.id)

    keyboard = get_navigation_keyboard(back_to_data='BACK_TO_SLOTS')
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "📝 Введите ваше имя для записи:",
        reply_markup=reply_markup
    )


async def request_client_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запрашивает номер телефона клиента."""
    context.user_data['awaiting_phone'] = True
    context.user_data.pop('awaiting_name', None)

    keyboard = [[KeyboardButton("Поделиться контактом", request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "📞 Теперь, пожалуйста, отправьте ваш номер телефона (можно кнопкой 'Поделиться контактом'):",
        reply_markup=reply_markup
    )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка текстового ввода (имя или телефон для просмотра)"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get('awaiting_name'):
        context.user_data['client_name'] = text
        logger.info(f"User {user_id}: Name stored as '{text}'. Requesting phone.")
        await request_client_phone(update, context)

    elif context.user_data.get('awaiting_phone_for_view'):
        phone = clean_phone_number(text)
        context.user_data['awaiting_phone_for_view'] = False
        logger.info(f"User {user_id}: Phone stored as '{phone}' (contact view). Fetching appointments.")
        await fetch_and_display_appointments(update, context, phone)

    else:
        await update.message.reply_text("Я не знаю, что с этим делать. Начните с /start.")


async def handle_contact_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ввода контакта через кнопку Telegram."""
    user_id = update.effective_user.id
    contact = update.message.contact
    phone = clean_phone_number(contact.phone_number)

    if context.user_data.get('awaiting_phone'):
        context.user_data['client_phone_number'] = phone
        logger.info(f"User {user_id}: Phone stored as '{phone}' (contact for booking). Finalizing.")
        context.user_data.pop('awaiting_phone', None)
        context.user_data['telegram_chat_id'] = str(user_id)
        await finalize_appointment(update, context)

    elif context.user_data.get('awaiting_phone_for_view'):
        context.user_data['awaiting_phone_for_view'] = False
        logger.info(f"User {user_id}: Phone stored as '{phone}' (contact view). Fetching appointments.")
        await fetch_and_display_appointments(update, context, phone)

    else:
        await update.message.reply_text("Я не знаю, что с этим делать. Начните с /start.")


# -----------------------------------------------------------
# 6. Просмотр и отмена записи
# -----------------------------------------------------------

async def fetch_and_display_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE, phone_number: str) -> None:
    """Запрашивает список будущих записей и выводит их."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id}: Fetching appointments for phone number: {phone_number}")

    # Убедимся, что убираем ReplyKeyboard после ввода
    await update.message.reply_text("Проверяю ваши записи...", reply_markup=telegram.ReplyKeyboardRemove())

    response = make_api_request('GET', APPOINTMENTS_URL, params={'phone_number': phone_number})
    if response is None:
        await update.message.reply_text("❌ Критическая ошибка авторизации. Сервис недоступен.")
        return
    try:
        response.raise_for_status()
        appointments = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"User {user_id}: RequestException during appointments fetch: {e}")
        await update.message.reply_text("❌ Ошибка при связи с сервером. Попробуйте позже.")
        return

    message_parts = ["🗓️ **Ваши предстоящие записи:**"]
    keyboard = []

    if not appointments:
        message = "🔎 У вас нет предстоящих записей."
    else:
        for idx, appt in enumerate(appointments):
            app_id = appt.get('id')
            start_time_str = appt.get('start_time')

            try:
                dt_object = datetime.datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                display_time = dt_object.strftime('%Y-%m-%d в %H:%M')
            except:
                display_time = "Неизвестное время"

            message_parts.append(
                f"\n**{idx + 1}.** **{appt.get('service_name', 'Услуга')}**\n"
                f"   Мастер: {appt.get('employee_name', 'Не указан')}\n"
                f"   Время: {display_time}\n"
                f"   Статус: {appt.get('status', 'PENDING')}"
            )
            keyboard.append([InlineKeyboardButton(f"❌ Отменить запись {idx + 1}", callback_data=f"CANCEL_{app_id}")])
        message = "\n".join(message_parts)

    keyboard.extend(get_navigation_keyboard(back_to_data=None))

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.effective_message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')


async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отменяет выбранную запись."""
    query = update.callback_query
    app_id = query.data.split('_')[1]
    user_id = update.effective_user.id

    logger.info(f"User {user_id}: Cancelling appointment ID: {app_id}")

    try:
        response = make_api_request('PATCH', f"{APPOINTMENTS_URL}{app_id}/", json={'status': 'CANCELLED'})

        if response is None:
            await query.edit_message_text("❌ Ошибка авторизации. Невозможно отменить запись.")
            return

        response.raise_for_status()

        keyboard = get_navigation_keyboard(back_to_data='view_appointments')
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✅ Запись №{app_id} **успешно отменена**.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"User {user_id}: Appointment {app_id} cancelled.")

    except requests.exceptions.RequestException as e:
        logger.error(f"User {user_id}: RequestException during cancellation: {e}")
        await query.edit_message_text("❌ Ошибка связи с сервером при отмене записи. Попробуйте позже.")


# -----------------------------------------------------------
# 7. Обработка Callback-запросов
# -----------------------------------------------------------

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Основной обработчик всех Inline-кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    logger.info(f"User {user_id} pressed button: {data}")

    # --- Главное меню и начало записи ---
    if data == 'MAIN_MENU':
        await start_command(update, context)
    elif data == 'start_booking':
        await services_command(update, context)
    elif data == 'view_appointments':
        await my_appointments_command(update, context)

    # --- Услуги (service_) ---
    elif data.startswith('service_'):
        service_id = data.split('_')[1]
        context.user_data['selected_service_id'] = service_id
        # Очищаем все последующие шаги при смене услуги
        context.user_data.pop('selected_employee_id', None)
        context.user_data.pop('selected_date', None)
        context.user_data.pop('selected_slot', None)
        await show_employees_for_service(update, context)

    # --- Мастера (employee_) ---
    elif data.startswith('employee_'):
        employee_id = data.split('_')[1]
        context.user_data['selected_employee_id'] = employee_id
        # Очищаем дату/слот при смене мастера
        context.user_data.pop('selected_date', None)
        context.user_data.pop('selected_slot', None)

        # Сбрасываем календарь на текущий месяц
        today = date.today()
        context.user_data['calendar_year'] = today.year
        context.user_data['calendar_month'] = today.month

        await show_calendar_command(update, context)

    # --- Календарь (CALEND_) ---
    elif data.startswith('CALEND_PREV_') or data.startswith('CALEND_NEXT_'):
        parts = data.split('_')
        action = parts[1]
        year = int(parts[2])
        month = int(parts[3])
        service_id = parts[4]

        new_year, new_month = year, month

        if action == 'PREV':
            new_month -= 1
            if new_month < 1:
                new_month = 12
                new_year -= 1
        elif action == 'NEXT':
            new_month += 1
            if new_month > 12:
                new_month = 1
                new_year += 1

        context.user_data['calendar_year'] = new_year
        context.user_data['calendar_month'] = new_month

        # Перезапуск календаря для нового месяца
        await show_calendar_command(update, context)

    elif data.startswith('CALEND_DAY_'):
        selected_date_str = data.split('_')[2]
        context.user_data['selected_date'] = selected_date_str
        context.user_data.pop('selected_slot', None)
        await show_available_slots(update, context)

    elif data.startswith('SLOT_'):
        selected_slot_time = data.split('_')[1]
        context.user_data['selected_slot'] = selected_slot_time
        await request_client_name(update, context)

    # --- Навигация "Назад" ---
    elif data == 'BACK_TO_EMPLOYEES':
        await show_employees_for_service(update, context)
    elif data == 'BACK_TO_CALENDAR':
        await show_calendar_command(update, context)
    elif data == 'BACK_TO_SLOTS':
        # Перезапуск слотов (поскольку имя/телефон еще не введены)
        await show_available_slots(update, context)

    # --- Отмена записи ---
    elif data.startswith('CANCEL_'):
        await cancel_appointment(update, context)

    # --- Игнорирование ---
    elif data in ['IGNORE', 'IGNORE_DISABLED_DAY']:
        pass
    else:
        logger.warning(f"Unknown callback data received: {data}")
        await query.edit_message_text("Неизвестная команда. Начните с /start.")


# -----------------------------------------------------------
# 8. Точка входа
# -----------------------------------------------------------

def main() -> None:
    """Запуск бота."""

    # 1. Получение токенов
    if not obtain_initial_tokens():
        logger.critical("Бот не может запуститься без действительного Access Token.")
        return

    # 2. Создание приложения
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    logger.info("🤖 Бот запущен и готов к работе...")

    # --- Команды ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("services", services_command))

    # --- Callbacks (Inline-кнопки) ---
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # --- Обработка ввода (текст или контакт) ---
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact_input))

    # 3. Запуск
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()