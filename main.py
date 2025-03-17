import os
import replicate
import asyncio
import logging
from asyncio import CancelledError
import speech_recognition as sr
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
import config as cf
from src.mailing.data.notification.notification_google_sheets_worker import notification_gsworker
from pydub import AudioSegment
import asyncpg
import re

class MailingStates(StatesGroup):
    waiting_for_time = State()

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

DB_CONFIG = {
    "user": "postgress",
    "password": "0000",
    "database": "warehouse",
    "host": "host"
}

# Класс состояний для FSM
class SubscriptionState(StatesGroup):
    choosing_type = State()
    choosing_day = State()
    choosing_time = State()

# Функция для сохранения подписки в БД
async def save_subscription(user_id: int, sub_type: str, weekday: int | None, time: str):
    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute(
        """
        INSERT INTO subscriptions (user_id, subscription_type, weekday, time)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE 
        SET subscription_type = $2, weekday = $3, time = $4;
        """, user_id, sub_type, weekday, time
    )
    await conn.close()


notification_gsworker = NotificationGoogleSheetsWorker()  # Это строка инициализирует worker

# Установка уровня логирования
logging.basicConfig(level=logging.INFO)

# Множество пользователей, ожидающих ввода
waiting_for_question = set()

# Инициализация роутеров
router = Router(name=__name__)
dp = Dispatcher()

# Установите API-ключ для Replicate
os.environ["REPLICATE_API_TOKEN"] = "r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE"
replicate.api_token = os.environ["REPLICATE_API_TOKEN"]

@router.message(MailingStates.waiting_for_time)
async def process_time_input(message: Message, state: FSMContext):
    """Обработка ввода времени и сохранение подписки в БД"""
    user_time = message.text.strip()

    # Проверяем формат времени (ЧЧ:ММ)
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", user_time):
        await message.answer("Некорректный формат! Введите время в формате ЧЧ:ММ, например 08:30")
        return

    data = await state.get_data()  # Получаем данные из состояния
    period = data.get("period")  # Тип подписки (daily, weekdays, weekly, monthly)
    weekday = data.get("weekday")  # День недели для еженедельной подписки (если есть)
    user_id = message.from_user.id  # ID пользователя

    # Сохраняем подписку в БД
    try:
        await save_subscription(user_id, period, weekday, user_time)
        logging.info(f"Настройки рассылки сохранены: user_id {user_id}, период {period}, день {weekday}, время {user_time}")
        await message.answer(f"Вы выбрали период '{period}' и время '{user_time}'. Настройки сохранены!")
    except Exception as e:
        logging.error(f"Ошибка при сохранении подписки в БД: {e}")
        await message.answer("Произошла ошибка при сохранении подписки. Попробуйте снова.")

    # Сброс состояния после завершения процесса
    await state.clear()

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
        btn = [types.InlineKeyboardButton(text='Подписаться на рассылку уведомлений 📩', callback_data='register_mailing')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Сформировать отчёт 📊', callback_data='generate_report')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Сгенерировать примерный отчёт 📑', callback_data='generate_sample_report')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Сформировать отчёт по JSON 📊', callback_data='generate_json_report')]
    inline_kb.append(btn)

    btn = [types.InlineKeyboardButton(text='Задать вопрос ❓', callback_data='send_question')]
    inline_kb.append(btn)

    return types.InlineKeyboardMarkup(inline_keyboard=inline_kb)  # Передаем inline_keyboard


async def get_mistral_answer(question: str) -> str:
    """Получаем ответ от модели Mistral через API Replicate"""
    response = replicate.run(
        "meta/meta-llama-3-8b-instruct",  # Пример другой модели
        input={
            "prompt": f"Ты — русскоязычный помощник. Отвечай на русском: {question}",
            "max_length": 200
        }
    )
    return "".join(response)


async def recognize_speech_from_audio(file_path: str) -> str:
    """Распознавание речи из аудиофайла"""
    recognizer = sr.Recognizer()

    # Конвертируем OGG в WAV
    try:
        audio = AudioSegment.from_ogg(file_path)
        wav_path = file_path.replace(".ogg", ".wav")
        audio.export(wav_path, format="wav")
        logging.info(f"Конвертирование OGG в WAV завершено: {wav_path}")
    except Exception as e:
        logging.error(f"Ошибка при конвертации файла {file_path}: {e}")
        return "Не удалось обработать голосовое сообщение."

    # Используем speech_recognition для обработки WAV файла
    try:
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="ru-RU")
        logging.info(f"Распознанный текст: {text}")
        return text
    except sr.UnknownValueError:
        logging.error("Не удалось распознать речь.")
        return "Не удалось распознать речь."
    except sr.RequestError as e:
        logging.error(f"Ошибка API распознавания речи: {e}")
        return "Ошибка распознавания речи."




@router.message(Command("start"))
async def start_command(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    # Проверим, есть ли у пользователя токен
    has_token = False  # Например, заменить на вашу логику проверки наличия токена

    # Отправляем сообщение с клавиатурой
    await message.answer(
        "Привет! Я бот, который поможет вам задать вопрос.",
        reply_markup=get_markup(user_id, has_token)
    )


@router.callback_query(F.data == "send_question")
async def handle_send_question_button(callback_query: CallbackQuery):
    """Обработчик нажатия на кнопку 'Задать вопрос'"""
    user_id = callback_query.from_user.id
    logging.info(f"Пользователь {user_id} выбрал 'Задать вопрос'. Добавляем в список ожидания.")

    # Проверяем, находится ли пользователь уже в процессе ожидания
    if user_id in waiting_for_question:
        await callback_query.message.answer("Вы уже задали вопрос. Пожалуйста, дождитесь ответа или задайте новый вопрос.")
        return

    # Добавляем пользователя в множество
    waiting_for_question.add(user_id)
    logging.info(f"Множество после добавления пользователя {user_id}: {waiting_for_question}")
    await callback_query.message.answer("Отправьте ваш вопрос в виде текста или голосового сообщения.")


@router.message(F.text | F.voice)
async def handle_question_message(message: Message):
    """Обработка текстовых и голосовых сообщений"""
    user_id = message.from_user.id
    logging.info(f"Сообщение от {user_id}, проверка состояния перед обработкой: {waiting_for_question}")

    if user_id not in waiting_for_question:
        logging.info(f"Пользователь {user_id} не в ожидании вопроса, игнорируем сообщение.")
        return

    # Убираем пользователя из множества после получения вопроса
    waiting_for_question.remove(user_id)
    logging.info(f"Множество после обработки сообщения: {waiting_for_question}")

    if message.text:
        # Получаем ответ от модели Mistral
        answer = await get_mistral_answer(message.text)
        await message.answer(f"Ответ от нейросети: {answer}")
    elif message.voice:
        await message.answer("Обрабатываю голосовое сообщение...")

        # Загружаем файл голосового сообщения
        file_id = message.voice.file_id
        file = await message.bot.get_file(file_id)
        file_path = f"files/voices/{file.file_id}.ogg"
        await message.bot.download_file(file.file_path, file_path)
        logging.info(f"Файл загружен: {file_path}")

        # Преобразуем голос в текст
        recognized_text = await recognize_speech_from_audio(file_path)

        # Получаем ответ от модели Mistral
        answer = await get_mistral_answer(recognized_text)
        await message.answer(f"Ответ от нейросети: {answer}")

    # После того как ответ получен, пользователь может задать новый вопрос
    await message.answer("Вы можете задать новый вопрос, нажав кнопку 'Задать вопрос'.")

@router.callback_query(F.data == "register_mailing")
async def handle_register_subscription(callback_query: CallbackQuery):
    """Обработчик для кнопки 'Подписаться на рассылку уведомлений'"""
    user_id = callback_query.from_user.id
    logging.info(f"Текущий список подписчиков: {notification_gsworker.subscribed_ids}")
    logging.info(f"Пользователь {user_id} хочет подписаться")

    # Проверяем, подписан ли уже пользователь на рассылку
    if not notification_gsworker.contains_id(user_id):
        notification_gsworker.add_id(user_id)
        logging.info(f"Пользователь {user_id} подписался на рассылку.")
        await callback_query.answer("Вы успешно подписались на рассылку уведомлений 📩")
    else:
        await callback_query.answer("Вы уже подписаны на рассылку уведомлений 📩")

    # Предлагаем выбрать периодичность рассылки
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Ежедневно", callback_data="period_daily")],
        [types.InlineKeyboardButton(text="По будням (пн-пт)", callback_data="period_weekdays")],
        [types.InlineKeyboardButton(text="Еженедельно", callback_data="period_weekly")],
        [types.InlineKeyboardButton(text="Ежемесячно", callback_data="period_monthly")]  # Monthly option
    ])

    await callback_query.message.answer(
        "Выберите периодичность рассылки уведомлений:",
        reply_markup=markup
    )



@router.callback_query(F.data == "period_daily")
async def set_daily_time(callback_query: CallbackQuery):
    """Обработчик для выбора ежедневной рассылки"""
    await callback_query.message.answer("Выберите время для ежедневной рассылки (например, 12:00).")


@router.callback_query(F.data == "period_weekdays")
async def set_weekdays_time(callback_query: CallbackQuery):
    """Обработчик для выбора рассылки по будням"""
    await callback_query.message.answer("Выберите время для рассылки по будням (например, 12:00).")


@router.callback_query(F.data == "period_weekly")
async def set_weekly_time(callback_query: CallbackQuery):
    """Обработчик для выбора еженедельной рассылки"""
    days_of_week = [
        ("Понедельник", "weekly_monday"),
        ("Вторник", "weekly_tuesday"),
        ("Среда", "weekly_wednesday"),
        ("Четверг", "weekly_thursday"),
        ("Пятница", "weekly_friday"),
        ("Суббота", "weekly_saturday"),
        ("Воскресенье", "weekly_sunday")
    ]

    # Создаем список кнопок
    buttons = [
        [types.InlineKeyboardButton(text=day, callback_data=callback)]
        for day, callback in days_of_week
    ]

    # Проверяем, что клавиатура не пустая
    if not buttons:
        await callback_query.answer("Ошибка: невозможно создать клавиатуру.")
        return

    markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback_query.message.answer(
        "Выберите день недели для еженедельной рассылки:",
        reply_markup=markup
    )



@router.callback_query(F.data.startswith("weekly_"))
async def set_weekly_time_and_day(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик для выбора времени и дня недели еженедельной рассылки"""
    day_of_week = callback_query.data.split("_")[1]  # Извлекаем день недели
    await state.update_data(weekday=day_of_week)  # Сохраняем день недели

    await callback_query.message.answer(f"Вы выбрали {day_of_week.capitalize()}.\nТеперь введите время для рассылки (например, 12:00):")
    await state.set_state(MailingStates.waiting_for_time)  # Переключаем состояние


@router.callback_query(F.data == "period_monthly")
async def set_monthly_day(callback_query: CallbackQuery):
    """Обработчик для выбора ежемесячной рассылки"""
    markup = types.InlineKeyboardMarkup(inline_keyboard=[])

    # Генерация кнопок для выбора числа месяца
    for day in range(1, 32):
        markup.inline_keyboard.append([types.InlineKeyboardButton(text=str(day), callback_data=f"monthly_{day}")])

    # Pass the list of buttons to `inline_keyboard`
    await callback_query.message.answer(
        "Выберите число месяца для ежемесячной рассылки:",
        reply_markup=markup
    )




@router.callback_query(F.data.startswith("monthly_"))
async def set_monthly_time_and_day(callback_query: CallbackQuery):
    """Обработчик для выбора времени ежемесячной рассылки"""
    day_of_month = callback_query.data.split("_")[1]  # Извлекаем число месяца
    await callback_query.message.answer(f"Вы выбрали {day_of_month} число месяца.\nТеперь выберите время для рассылки.")


@router.callback_query(F.data == "period_monthly")
async def set_monthly_time(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик выбора времени для ежемесячной рассылки"""
    await callback_query.message.answer("Введите время для ежемесячной рассылки (например, 12:00):")
    await state.set_state(MailingStates.waiting_for_time)  # Переключаем состояние


# Пример обновления состояния и логики при выборе времени
@router.message(MailingStates.waiting_for_time)
async def process_time_input(message: Message, state: FSMContext):
    """Обработка ввода времени"""
    user_time = message.text.strip()

    # Проверяем формат времени (ЧЧ:ММ)
    import re
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", user_time):
        await message.answer("Некорректный формат! Введите время в формате ЧЧ:ММ, например 08:30")
        return

    data = await state.get_data()  # Получаем данные из состояния
    period = data.get("period")  # Достаем сохраненный период

    # Сохраняем выбранное время
    await state.update_data(time=user_time)

    # Подтверждаем пользователю
    await message.answer(f"Вы выбрали период '{period}' и время '{user_time}'. Настройки сохранены!")

    # Сброс состояния после завершения процесса
    await state.clear()
    logging.info(f"Настройки рассылки сохранены: период {period}, время {user_time}")


@router.callback_query(F.data.startswith("period_"))
async def set_time(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик выбора типа подписки и времени"""
    period = callback_query.data.split("_")[1]  # Извлекаем период (daily, weekdays, weekly, monthly)
    await state.update_data(period=period)  # Сохраняем выбранный период

    await callback_query.message.answer("Введите время в формате ЧЧ:ММ (например, 12:00):")
    await state.set_state(MailingStates.waiting_for_time)  # Переключаем состояние


@router.message(MailingStates.waiting_for_time)
async def process_time_input(message: Message, state: FSMContext):
    """Обработка ввода времени"""
    user_time = message.text.strip()

    # Проверяем формат времени (ЧЧ:ММ)
    import re
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", user_time):
        await message.answer("Некорректный формат! Введите время в формате ЧЧ:ММ, например 08:30")
        return

    data = await state.get_data()  # Получаем данные из состояния
    period = data.get("period")  # Достаем сохраненный период

    # Сохраняем выбранное время
    await state.update_data(time=user_time)

    # Подтверждаем пользователю
    await message.answer(f"Вы выбрали период '{period}' и время '{user_time}'. Настройки сохранены!")

    # Сброс состояния после завершения процесса
    await state.clear()
    logging.info(f"Настройки рассылки сохранены: период {period}, время {user_time}")


@router.callback_query(lambda c: c.data == "register_mailing")
async def register_mailing(callback_query: CallbackQuery):
    """Регистрация на рассылку уведомлений"""
    user_id = callback_query.from_user.id
    if notification_gsworker.contains_id(user_id):
        await callback_query.answer("Вы уже подписаны на рассылку!")
    else:
        notification_gsworker.add_id(user_id)
        await save_subscription(user_id, "daily", None, "09:00")  # Пример подписки на ежедневную рассылку в 09:00
        await callback_query.answer("Вы успешно подписались на рассылку уведомлений 📩")
        await callback_query.message.edit_reply_markup(get_markup(user_id, has_token=False))


@router.callback_query(lambda c: c.data == "unregister")
async def unregister_mailing(callback_query: CallbackQuery):
    """Отписка от рассылки уведомлений"""
    user_id = callback_query.from_user.id
    if not notification_gsworker.contains_id(user_id):
        await callback_query.answer("Вы не подписаны на рассылку!")
    else:
        notification_gsworker.remove_id(user_id)
        await save_subscription(user_id, "none", None, None)  # Удаляем подписку из БД
        await callback_query.answer("Вы успешно отписались от рассылки уведомлений ❌")
        await callback_query.message.edit_reply_markup(get_markup(user_id, has_token=False))


@router.callback_query(lambda c: c.data == "send_question")
async def send_question(callback_query: CallbackQuery):
    """Отправка вопроса в поддержку"""
    user_id = callback_query.from_user.id
    await callback_query.answer("Напишите ваш вопрос. Мы постараемся помочь.")
    await callback_query.message.edit_reply_markup()  # Убираем клавиатуру

    # Переходим в состояние ожидания вопроса
    await MailingStates.waiting_for_time.set()


# Обработчик для получения вопроса от пользователя
@dp.message_handler(state=MailingStates.waiting_for_time)
async def process_question(message: Message, state: FSMContext):
    user_question = message.text.strip()
    await message.answer(f"Ваш вопрос: {user_question}\nМы постараемся ответить на него в ближайшее время.")
    await state.clear()

@router.callback_query(lambda c: c.data == "generate_report")
async def generate_report(callback_query: CallbackQuery):
    """Генерация отчета"""
    user_id = callback_query.from_user.id
    await callback_query.answer("Отчёт генерируется, пожалуйста, подождите...")

    # Добавьте логику генерации отчета, например, запрос в БД или внешний API
    # Важно, чтобы отчёт был сгенерирован до того, как отправим его пользователю.

    # Пример создания отчёта
    report_content = "Это пример отчёта. Реализуйте логику формирования отчёта."

    await callback_query.message.answer(report_content)


@router.callback_query(lambda c: c.data == "generate_sample_report")
async def generate_sample_report(callback_query: CallbackQuery):
    """Генерация примерного отчета"""
    user_id = callback_query.from_user.id
    await callback_query.answer("Пример отчёта генерируется...")

    # Пример содержания отчёта
    sample_report = "Это примерный отчёт. Вы можете увидеть его содержание здесь."

    await callback_query.message.answer(sample_report)


@router.callback_query(lambda c: c.data == "generate_json_report")
async def generate_json_report(callback_query: CallbackQuery):
    """Генерация отчета в формате JSON"""
    user_id = callback_query.from_user.id
    await callback_query.answer("Отчёт в формате JSON генерируется...")

    # Пример содержания отчёта в JSON
    json_report = {"report": {"status": "success", "data": [1, 2, 3, 4]}}

    # Преобразуем в строку JSON
    import json
    json_content = json.dumps(json_report)

    await callback_query.message.answer(f"Отчёт в формате JSON:\n{json_content}")

async def include_routers() -> None:
    """Подключаем все роутеры"""
    dp.include_router(router)


async def main() -> None:
    """Основная функция для запуска бота"""
    bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await include_routers()
    await bot.delete_webhook()

    try:
        logging.info('Бот запущен!')
        await dp.start_polling(bot)
    except (CancelledError, KeyboardInterrupt, SystemExit):
        dp.shutdown()
        logging.info('Бот остановлен')


if __name__ == '__main__':
    asyncio.run(main())

