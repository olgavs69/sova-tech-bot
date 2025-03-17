import os
import replicate
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, \
    InlineKeyboardMarkup
import asyncpg
from datetime import datetime, time

import config as cf
from src.mailing.data.notification.notification_google_sheets_worker import notification_gsworker
from pydub import AudioSegment
import re

# Настройка бота
bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Множество пользователей, ожидающих ввода
waiting_for_question = set()

# Установка API-ключа для Replicate
os.environ["REPLICATE_API_TOKEN"] = "r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE"
replicate.api_token = os.environ["REPLICATE_API_TOKEN"]

# Класс состояний для FSM
class MailingStates(StatesGroup):
    waiting_for_time = State()

class SubscriptionState(StatesGroup):
    choosing_frequency = State()
    choosing_type = State()
    choosing_day = State()
    choosing_monthly_day = State()
    choosing_time = State()

class NotificationGoogleSheetsWorker:
    def __init__(self):
        self.subscribed_ids = []  # Список для хранения ID пользователей

    def contains_id(self, user_id: int) -> bool:
        """Проверка наличия ID в списке подписок"""
        return user_id in self.subscribed_ids

    def add_id(self, user_id: int) -> None:
        """Добавление ID пользователя в список подписок"""
        if user_id not in self.subscribed_ids:
            self.subscribed_ids.append(user_id)
            logging.info(f"User {user_id} added to subscription list.")

    def remove_id(self, user_id: int) -> None:
        """Удаление ID пользователя из списка подписок"""
        if user_id in self.subscribed_ids:
            self.subscribed_ids.remove(user_id)
            logging.info(f"User {user_id} removed from subscription list.")

# Настройки БД
DB_CONFIG = {
    'user': 'postgres',  # Correct username
    'password': '0000',  # Correct password
    'database': 'warehouse_of_goods',
    'host': 'localhost',  # or your DB host if remote
    'port': '5432'  # or your DB port
}

async def init_db_pool():
    return await asyncpg.create_pool("postgresql://postgres:0000@localhost/warehouse_of_goods")

db_pool = None  # Глобальный пул

async def save_subscription(user_id, sub_type, periodicity, weekday, day_of_month, time_str):
    try:
        hour, minute = map(int, time_str.split(":"))
        time_obj = time(hour, minute)
    except ValueError:
        raise ValueError("Неверный формат времени. Пожалуйста, используйте HH:MM.")

    global db_pool
    if db_pool is None:
        db_pool = await init_db_pool()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO subscriptions (user_id, subscription_type, sub_type, periodicity, weekday, day_of_month, time)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id) DO UPDATE 
            SET subscription_type = $2, sub_type = $3, periodicity = $4, weekday = $5, day_of_month = $6, time = $7
            """,
            user_id, sub_type, sub_type, periodicity, weekday, day_of_month, time_obj
        )

# Инициализация worker
notification_gsworker = NotificationGoogleSheetsWorker()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создание роутера и диспетчера
router = Router(name=__name__)

# Обработчик команды /start
@router.message(Command("start"))
async def start_command(message: Message):
    user_id = message.from_user.id
    has_token = False  # Логика проверки наличия токена

    await message.answer(
        "Привет! Я бот, который поможет вам задать вопрос.",
        reply_markup=get_markup(user_id, has_token)
    )

# Роутер с клавишами
def get_markup(user_id: int, has_token: bool) -> types.InlineKeyboardMarkup:
    inline_kb = []

    if not has_token:
        btn = [types.InlineKeyboardButton(text='Меню отчётов', callback_data='server_report_authorization')]
        inline_kb.append(btn)
    else:
        btn = [types.InlineKeyboardButton(text='Меню отчётов', callback_data='analytics_report_begin')]
        inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Меню тех-поддержки 🛠', callback_data='techsupport_menu')]
    inline_kb.append(btn)

    if notification_gsworker.contains_id(user_id):
        btn = [types.InlineKeyboardButton(text='Отписаться от рассылки уведомлений ❌', callback_data='unregister')]
    else:
        btn = [types.InlineKeyboardButton(text='Подписаться на рассылку уведомлений 📩', callback_data='register_mailing')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Сформировать отчёт 📊', callback_data='generate_report')]
    inline_kb.append(btn)

    return types.InlineKeyboardMarkup(inline_keyboard=inline_kb)

# Обработчик подписки на рассылку
@router.callback_query(F.data == 'register_mailing')
async def subscribe_to_mailing(callback_query: CallbackQuery, state: FSMContext):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Ежедневно", callback_data="sub_daily")],
        [types.InlineKeyboardButton(text="По будням (Пн-Пт)", callback_data="sub_workdays")],
        [types.InlineKeyboardButton(text="Еженедельно", callback_data="sub_weekly")],
        [types.InlineKeyboardButton(text="Ежемесячно", callback_data="sub_monthly")]
    ])
    await callback_query.message.answer("Выберите периодичность рассылки:", reply_markup=keyboard)

@dp.message(Command("subscribe"))
async def choose_subscription(message: types.Message, state: FSMContext):
    buttons = [
        [KeyboardButton("Ежедневно"), KeyboardButton("По будням")],
        [KeyboardButton("Еженедельно"), KeyboardButton("Ежемесячно")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите периодичность:", reply_markup=keyboard)
    await state.set_state(SubscriptionState.choosing_frequency)


@router.callback_query(F.data.startswith("sub_"))
async def choose_subscription_type(callback_query: CallbackQuery, state: FSMContext):
    sub_type = callback_query.data.split("_")[1]

    await state.update_data(sub_type=sub_type)

    if sub_type == "weekly":
        await state.update_data(frequency="Еженедельно")
        await state.set_state(SubscriptionState.choosing_day)

        # Создаём клавиатуру с днями недели
        days_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Понедельник", callback_data="day_0")],
            [InlineKeyboardButton(text="Вторник", callback_data="day_1")],
            [InlineKeyboardButton(text="Среда", callback_data="day_2")],
            [InlineKeyboardButton(text="Четверг", callback_data="day_3")],
            [InlineKeyboardButton(text="Пятница", callback_data="day_4")],
            [InlineKeyboardButton(text="Суббота", callback_data="day_5")],
            [InlineKeyboardButton(text="Воскресенье", callback_data="day_6")]
        ])

        await callback_query.message.answer("Выберите день недели:", reply_markup=days_kb)


@router.callback_query(F.data.startswith("day_"))
async def choose_weekday(callback_query: CallbackQuery, state: FSMContext):
    weekday = int(callback_query.data.split("_")[1])  # Получаем число от 0 до 6
    await state.update_data(weekday=weekday)

    logging.info(f"Selected weekday: {weekday}")

    await state.set_state(SubscriptionState.choosing_time)
    await callback_query.message.answer("Теперь введите время рассылки в формате HH:MM.")


@router.message(SubscriptionState.choosing_day)
async def choose_weekday(message: Message, state: FSMContext):
    days_of_week = {
        "Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5, "Воскресенье": 6
    }
    day_text = message.text.strip()

    if day_text not in days_of_week:
        await message.answer("Пожалуйста, выберите день недели из списка.")
        return

    # Сохраняем выбранный день
    await state.update_data(weekday=days_of_week[day_text])
    logging.info(f"Selected weekday: {day_text} ({days_of_week[day_text]})")

    # Запрашиваем у пользователя время
    await message.answer("Теперь введите время рассылки в формате HH:MM.")
    await state.set_state(SubscriptionState.choosing_time)


@router.message(SubscriptionState.choosing_day)
async def choose_weekday_or_day(message: Message, state: FSMContext):
    try:
        value = int(message.text)
        data = await state.get_data()
        logging.info(f"Received data: {data}")

        if "weekly" in data:  # Если выбрана еженедельная подписка
            if value < 0 or value > 6:
                raise ValueError("В неделе только дни с 0 (понедельник) до 6 (воскресенье).")
            await state.update_data(weekday=value)
            logging.info(f"Updated data with weekday={value}. State: {await state.get_data()}")
            await message.answer("Теперь выберите время рассылки в формате HH:MM.")
            await state.set_state(SubscriptionState.choosing_time)
        elif "monthly" in data:  # Если выбрана ежемесячная подписка
            if value < 1 or value > 31:
                raise ValueError("В месяце только числа с 1 по 31.")
            await state.update_data(day_of_month=value)
            logging.info(f"Updated data with day_of_month={value}. State: {await state.get_data()}")
            await message.answer("Теперь выберите время рассылки в формате HH:MM.")
            await state.set_state(SubscriptionState.choosing_time)
    except ValueError as e:
        await message.answer(str(e))


@router.callback_query(F.data == "sub_monthly")
async def choose_monthly_day(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик выбора ежемесячной подписки"""
    await state.update_data(sub_type="monthly", frequency="Ежемесячно")
    await state.set_state(SubscriptionState.choosing_day)
    await callback_query.message.answer("Введите число месяца (от 1 до 31), в которое хотите получать рассылку.")
    logging.info(f"User {callback_query.from_user.id} selected 'Ежемесячно' for subscription.")


@router.message(SubscriptionState.choosing_day)
async def choose_day_of_month(message: Message, state: FSMContext):
    """Обработчик выбора дня месяца для подписки"""
    try:
        day = int(message.text.strip())  # Получаем день месяца
        logging.info(f"User {message.from_user.id} is trying to set day: {day}")  # Логируем, что пользователь ввел

        if 1 <= day <= 31:  # Проверка корректности числа
            await state.update_data(day_of_month=day)
            await state.set_state(SubscriptionState.choosing_time)  # Переходим к выбору времени
            await message.answer("Теперь введите время рассылки в формате HH:MM.")
            logging.info(f"User {message.from_user.id} successfully set day of month to {day}.")
        else:
            await message.answer("Введите корректное число от 1 до 31.")
            logging.warning(f"User {message.from_user.id} entered invalid day value: {message.text}")
    except ValueError:
        await message.answer("Введите число месяца цифрами (например, 15).")
        logging.error(f"User {message.from_user.id} entered invalid day value: {message.text}")  # Логируем ошибку


@router.message(SubscriptionState.choosing_time)
async def save_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        # Проверяем, что время соответствует формату HH:MM
        hour, minute = map(int, time_str.split(":"))
        time_obj = time(hour, minute)

        # Логируем данные из состояния перед сохранением
        data = await state.get_data()
        logging.info(f"State data before saving: {data}")

        sub_type = data.get("sub_type")
        frequency = data.get("frequency")
        weekday = data.get("weekday", None)  # День недели (если есть)
        day_of_month = data.get("day_of_month", None)  # Число месяца (если есть)

        if not frequency:
            await message.answer("Периодичность не была выбрана. Пожалуйста, выберите периодичность рассылки.")
            return

        logging.info(f"Saving subscription with weekday={weekday}, day_of_month={day_of_month}, time={time_str}")

        # Сохраняем в базу данных
        await save_subscription(
            message.from_user.id, sub_type=sub_type,
            periodicity=frequency,
            weekday=weekday,
            day_of_month=day_of_month,
            time_str=time_str
        )

        await message.answer(f"Время для рассылки установлено на {time_str}.")
        await state.clear()  # Завершаем состояние

    except ValueError:
        await message.answer("Неверный формат времени. Пожалуйста, используйте формат HH:MM.")


async def on_start():
    logging.info("Бот запущен.")
    await dp.start_polling(bot)


# Главная асинхронная функция для запуска
async def main():
    logging.info("Запуск бота...")
    dp.include_router(router)  # Подключаем роутер в диспетчер
    await on_start()  # Запуск polling


if __name__ == "__main__":
    # Запуск бота
    asyncio.run(main())