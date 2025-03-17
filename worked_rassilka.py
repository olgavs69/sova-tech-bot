import asyncio
import logging
from asyncio import CancelledError

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
import asyncpg
from datetime import datetime, time

import config as cf
from src.mailing.data.notification.notification_google_sheets_worker import notification_gsworker
from src.mailing.notifications.select_report import subscribe_notifications, setup_routers_select_reports
from src.sound_and_text_ai.ai_answers import ai_answer

from src.mailing.notifications.keyboards import periodicity_kb, timezone_kb, weekdays_kb

# Настройка бота
bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Множество пользователей, ожидающих ввода
waiting_for_question = set()


# Класс состояний для FSM
class MailingStates(StatesGroup):
    waiting_for_time = State()


class Form(StatesGroup):
    choosing_time = State()


class SubscriptionState(StatesGroup):
    choosing_frequency = State()
    choosing_type = State()
    choosing_day = State()
    choosing_timezone = State()
    choosing_monthly_day = State()  # Новый state для выбора дня месяца
    choosing_time = State()


# Инициализация worker
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


DB_CONFIG = cf.DB_CONFIG


async def init_db_pool():
    return await asyncpg.create_pool(cf.DB_LINK)


db_pool = None

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
        "Привет! Я бот компании SOVA-TECH.\nВыберите один из пункт меню: ",
        reply_markup=get_markup(user_id, has_token)
    )


# Роутер с клавишами
def get_markup(user_id: int, has_token: bool) -> types.InlineKeyboardMarkup:
    """Создаём клавиатуру с несколькими кнопками в зависимости от состояния пользователя"""
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
        btn = [
            types.InlineKeyboardButton(text='Подписаться на рассылку уведомлений 📩', callback_data='register_mailing')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Сформировать отчёт 📊', callback_data='generate_report')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Задать вопрос ❓', callback_data='send_question')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Посмотреть текущие подписки 📅', callback_data='show_subscriptions')]
    inline_kb.append(btn)

    return types.InlineKeyboardMarkup(inline_keyboard=inline_kb)


# Обработчик подписки на рассылку
@subscribe_notifications.callback_query(F.data.startswith('subscribe_'))
async def handle_subscribe(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик для выбора 'Подписаться на рассылку'"""
    # Извлекаем тип отчёта из callback_data
    report_type = callback_query.data.replace("subscribe_", "", 1)
    logging.info(f"Пользователь выбрал подписаться на рассылку для типа: {report_type}")

    # Сохраняем тип отчёта в состоянии
    await state.update_data(report_type=report_type)

    # Уведомляем пользователя
    await callback_query.answer(f"Вы выбрали подписаться на рассылку для типа: {report_type}")

    # Перенаправляем пользователя на выбор периодичности рассылки
    keyboard = periodicity_kb
    await callback_query.message.answer("Выберите периодичность рассылки:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("sub_"))
async def choose_subscription_type(callback_query: CallbackQuery, state: FSMContext):
    sub_type = callback_query.data.split("_")[1]

    await state.update_data(sub_type=sub_type)

    if sub_type == "daily":
        await state.update_data(frequency="Ежедневно")
    elif sub_type == "workdays":
        await state.update_data(frequency="По будням (Пн-Пт)")
    elif sub_type == "weekly":
        await state.update_data(frequency="Еженедельно")
    elif sub_type == "monthly":
        await state.update_data(frequency="Ежемесячно")

    # Сначала запрашиваем часовую зону
    await state.set_state(SubscriptionState.choosing_timezone)
    await callback_query.message.answer("Выберите ваш часовой пояс:", reply_markup=timezone_kb)


@router.callback_query(F.data.startswith("tz_"))
async def choose_timezone(callback_query: CallbackQuery, state: FSMContext):
    timezone_offset = int(callback_query.data.split("_")[1])
    await state.update_data(timezone_offset=timezone_offset)

    # Получаем данные о типе подписки
    data = await state.get_data()
    sub_type = data.get("sub_type")

    if sub_type == "weekly":
        # Для еженедельной подписки запрашиваем день недели
        await state.set_state(SubscriptionState.choosing_day)
        days_kb = weekdays_kb
        await callback_query.message.answer("Выберите день недели:", reply_markup=days_kb)
    elif sub_type == "monthly":
        # Для ежемесячной подписки запрашиваем день месяца
        await state.set_state(SubscriptionState.choosing_monthly_day)
        await callback_query.message.answer("Введите число месяца (от 1 до 31), в которое хотите получать рассылку.")
    else:
        # Для ежедневной и по будням подписки сразу запрашиваем время
        await state.set_state(SubscriptionState.choosing_time)
        await callback_query.message.answer("Теперь введите время рассылки в формате HH:MM.")


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


@router.message(SubscriptionState.choosing_monthly_day)
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


async def save_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    try:
        hour, minute = map(int, time_str.split(":"))
        input_time = time(hour, minute)  # Время без учёта часового пояса

        # Получаем сохранённые данные (включая часовой пояс)
        data = await state.get_data()
        timezone_offset = data.get("timezone_offset", 0)  # По умолчанию UTC+0

        # Преобразуем время с учётом часового пояса пользователя
        adjusted_hour = (hour - timezone_offset) % 24  # Вычитаем или добавляем часовой пояс
        adjusted_time = time(adjusted_hour, minute)

        sub_type = data.get("sub_type")
        frequency = data.get("frequency")
        weekday = data.get("weekday", None)
        day_of_month = data.get("day_of_month", None)

        # Логирование для проверки корректности данных
        logging.info(f"Adjusted time: {adjusted_time}")

        # Сохраняем подписку с временем в UTC
        await save_subscription(
            message.from_user.id, sub_type=sub_type,
            periodicity=frequency,
            weekday=weekday,
            day_of_month=day_of_month,
            time_obj=adjusted_time,
            timezone_offset=timezone_offset
        )

        await message.answer(f"Вы подписались на {frequency}. Время рассылки (ваше локальное): {time_str}.")
        await state.clear()

    except ValueError:
        await message.answer("Неверный формат времени. Пожалуйста, используйте формат HH:MM.")


@router.callback_query(F.data == 'show_subscriptions')
async def show_subscriptions(callback_query: CallbackQuery):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        # Извлекаем подписки для текущего пользователя
        subscriptions = await conn.fetch(''' 
            SELECT subscription_type, periodicity, weekday, day_of_month, time
            FROM subscriptions
            WHERE user_id = $1
        ''', callback_query.from_user.id)

        if not subscriptions:
            await callback_query.message.answer("Вы не подписаны ни на одну рассылку.")
            return

        # Формируем список подписок
        buttons = []
        for sub in subscriptions:
            subscription_text = f"{sub['subscription_type']} ({sub['periodicity']})"
            if sub['weekday'] is not None:
                weekday_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
                subscription_text += f" - {weekday_names[sub['weekday']]}"

            if sub['day_of_month'] is not None:
                subscription_text += f" - {sub['day_of_month']} число месяца"
            subscription_text += f" - Время: {sub['time']}"

            # Создаем кнопку для каждой подписки
            buttons.append([types.InlineKeyboardButton(text=subscription_text,
                                                       callback_data=f"subscription_{sub['subscription_type']}_{sub['time']}")])

        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback_query.message.answer("Ваши подписки:", reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Error fetching subscriptions: {e}")
        await callback_query.message.answer("Произошла ошибка при извлечении подписок. Попробуйте позже.")
    finally:
        await conn.close()


async def execute_db_query(query: str, *args):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        return await conn.fetch(query, *args)
    except Exception as e:
        logging.error(f"DB error: {e}")
        return None
    finally:
        await conn.close()


@router.callback_query(F.data.startswith("unsubscribe_"))
async def unsubscribe(callback_query: CallbackQuery):
    # Разбираем данные из callback_data
    subscription_data = callback_query.data.split("_")

    if len(subscription_data) < 3:
        await callback_query.message.answer("Невозможно получить данные для отмены подписки.")
        return

    subscription_type = subscription_data[1]
    time_str = subscription_data[2]

    # Выводим для диагностики
    print(f"Полученные данные: subscription_type={subscription_type}, time_str={time_str}")

    # Убираем лишние символы, если время включает секунды
    if len(time_str) > 5:
        time_str = time_str[:5]  # Берем только первые 5 символов (HH:MM)

    try:
        # Преобразуем строку времени в объект time
        time_obj = datetime.strptime(time_str, '%H:%M').time()  # Используем формат без секунд
    except ValueError:
        await callback_query.message.answer(f"Некорректное время для подписки: {time_str}. Ожидаемый формат - HH:MM.")
        return

    # Удаляем подписку из базы данных
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        # Запрос, который использует объект time, а не строку
        await conn.execute(''' 
            DELETE FROM subscriptions 
            WHERE user_id = $1 AND subscription_type = $2 AND time = $3
        ''', callback_query.from_user.id, subscription_type, time_obj)

        await callback_query.message.answer(f"Вы успешно отменили подписку на {subscription_type} в {time_str}.")
    except Exception as e:
        logging.error(f"Ошибка при удалении подписки: {e}")
        await callback_query.message.answer("Произошла ошибка при удалении подписки. Попробуйте позже.")
    finally:
        await conn.close()


# Обработчик нажатия на кнопку подписки
@router.callback_query(F.data.startswith("subscription_"))
async def manage_subscription(callback_query: CallbackQuery):
    # Извлекаем данные из callback_data
    subscription_data = callback_query.data.split("_")
    subscription_type = subscription_data[1]
    time = subscription_data[2]

    # Для примера, показываем информацию о подписке
    await callback_query.message.answer(f"Вы выбрали подписку: {subscription_type} - Время: {time}.")

    # Создадим клавиатуру для управления подпиской
    buttons = [
        [InlineKeyboardButton(text="Удалить подписку ❌", callback_data=f"unsubscribe_{subscription_type}_{time}")],
        [InlineKeyboardButton(text="Назад ↩️", callback_data="back_to_subscriptions")]  # Кнопка назад

    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback_query.message.answer("Что вы хотите сделать с этой подпиской?", reply_markup=keyboard)


@router.callback_query(F.data == "back_to_subscriptions")
async def back_to_subscriptions(callback_query: CallbackQuery):
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        # Извлекаем подписки для текущего пользователя
        subscriptions = await conn.fetch(''' 
            SELECT subscription_type, periodicity, weekday, day_of_month, time
            FROM subscriptions
            WHERE user_id = $1
        ''', callback_query.from_user.id)

        if not subscriptions:
            await callback_query.message.answer("Вы не подписаны ни на одну рассылку.")
            return

        # Формируем список подписок
        subscriptions_text = ""
        buttons = []
        for sub in subscriptions:
            subscription_text = f"{sub['subscription_type']} ({sub['periodicity']})"
            if sub['weekday'] is not None:
                weekday_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
                subscription_text += f" - {weekday_names[sub['weekday']]}"
            if sub['day_of_month'] is not None:
                subscription_text += f" - {sub['day_of_month']} число месяца"
            subscription_text += f" - Время: {sub['time']}"

            # Создаем кнопку для каждой подписки
            buttons.append([InlineKeyboardButton(text=subscription_text,
                                                 callback_data=f"subscription_{sub['subscription_type']}_{sub['time']}")])

            subscriptions_text += f"{subscription_text}\n"

        # Добавляем кнопку для возврата к списку подписок
        buttons.append([InlineKeyboardButton(text="Назад к подпискам", callback_data="show_subscriptions")])

        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        # Отправляем сообщение с подписками и клавиатурой
        await callback_query.message.answer(f"Вот ваши подписки:\n{subscriptions_text}", reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Error fetching subscriptions: {e}")
        await callback_query.message.answer("Произошла ошибка при извлечении подписок. Попробуйте позже.")
    finally:
        await conn.close()


@router.callback_query(F.data.startswith("unsubscribe_"))
async def unsubscribe(callback_query: CallbackQuery):
    # Извлекаем данные из callback_data
    subscription_data = callback_query.data.split("_")
    subscription_type = subscription_data[1]
    time_str = subscription_data[2]

    try:
        # Преобразуем строку времени в объект time
        time_obj = datetime.strptime(time_str, '%H:%M').time()  # Используем формат без секунд
    except ValueError:
        await callback_query.message.answer("Некорректное время для подписки.")
        return

    # Удаляем подписку из базы данных
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        # Запрос, который использует объект time, а не строку
        await conn.execute(''' 
            DELETE FROM subscriptions 
            WHERE user_id = $1 AND subscription_type = $2 AND time = $3
        ''', callback_query.from_user.id, subscription_type, time_obj)

        await callback_query.message.answer(f"Вы успешно отменили подписку на {subscription_type} в {time_str}.")
    except Exception as e:
        logging.error(f"Failed to unsubscribe: {e}")
        await callback_query.message.answer("Произошла ошибка при удалении подписки. Попробуйте позже.")
    finally:
        await conn.close()


# Определяем состояния
class TimeInputState(StatesGroup):
    waiting_for_offset = State()
    waiting_for_time = State()


@subscribe_notifications.message(SubscriptionState.choosing_time)
async def process_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    logging.info(f"User inputted time: {time_str}")

    try:
        hour, minute = map(int, time_str.split(":"))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Некорректное время.")

        input_time = time(hour, minute)

        data = await state.get_data()
        timezone_offset = data.get("timezone_offset", 0)
        adjusted_hour = (hour - timezone_offset) % 24
        adjusted_time = time(adjusted_hour, minute)

        logging.info(f"Adjusted time (with timezone offset): {adjusted_time}")

        sub_type = data.get("sub_type")
        frequency = data.get("frequency")
        weekday = data.get("weekday", None)
        day_of_month = data.get("day_of_month", None)
        report_type = data.get("report_type", "unknown")  # Получаем тип отчёта из состояния

        # Сохраняем подписку с указанием типа отчёта
        await save_subscription(
            message.from_user.id, sub_type=sub_type,
            periodicity=frequency,
            weekday=weekday,
            day_of_month=day_of_month,
            time_obj=adjusted_time,
            timezone_offset=timezone_offset,
            report_type=report_type,
            token='sample_token'
        )

        await message.answer(f"Вы подписались на {frequency}. Время рассылки (ваше локальное): {time_str}.")
        await state.clear()

    except ValueError as e:
        logging.error(f"Invalid time format entered: {time_str}. Error: {e}")
        await message.answer(f"Ошибка: {e}. Пожалуйста, введите корректное время в формате HH:MM.")


async def save_subscription(user_id, sub_type, periodicity, weekday, day_of_month, time_obj, timezone_offset,
                            report_type, token):
    # Логирование перед сохранением
    logging.info(f"Saving subscription for user {user_id}: sub_type={sub_type}, periodicity={periodicity}, "
                 f"weekday={weekday}, day_of_month={day_of_month}, time={time_obj}, report_type={report_type}, token={token}")

    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        # Вставляем новую подписку
        await conn.execute(''' 
        INSERT INTO subscriptions(user_id, subscription_type, periodicity, weekday, day_of_month, time, timezone_offset, report_type, token)
        VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ''', user_id, sub_type, periodicity, weekday, day_of_month, time_obj, timezone_offset, report_type, token)

        logging.info(f"Subscription for user {user_id} saved successfully.")
    except Exception as e:
        logging.error(f"Failed to save subscription: {e}")
    finally:
        await conn.close()


async def main() -> None:
    bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp.include_router(router)
    setup_routers_select_reports()
    dp.include_router(subscribe_notifications)
    dp.include_router(ai_answer)
    await bot.delete_webhook()

    try:
        logging.info('Бот запущен!')
        await dp.start_polling(bot)
    except (CancelledError, KeyboardInterrupt, SystemExit):
        dp.shutdown()
        logging.info('Бот остановлен')


if __name__ == "__main__":
    # Запуск бота
    asyncio.run(main())
