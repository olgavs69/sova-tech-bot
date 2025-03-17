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
from aiogram.types import Message, CallbackQuery, InputFile, BufferedInputFile, InlineKeyboardMarkup, \
    InlineKeyboardButton
from openpyxl.styles import NamedStyle, Font
from openpyxl.workbook import Workbook
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import config as cf
from pydub import AudioSegment
import asyncpg
import re
import json

from src.basic.revenue_analysis.make_excel import create_revenue_excel
from src.basic.revenue_analysis.graphics_for_pdf import  analys_revenue_pdf_router
from src.basic.revenue_analysis.make_excel import analys_revenue_excel_router

from src.basic.trade_turnover.make_excel import trade_turnover_excel_report_router
from src.basic.trade_turnover.graphics_for_pdf import trade_turnover_pdf_router

from src.basic.trade_turnover_for_various_objects.make_excel import trade_turnover_for_various_objects_excel_router
from src.basic.trade_turnover_for_various_objects.graphics_for_pdf import trade_turnover_for_various_objects_pdf_router

from src.basic.forecasting_losses.make_excel import forecasting_losses_excel_router
from src.basic.forecasting_losses.graphics_for_pdf import forecasting_losses_pdf_router

from src.basic.inventory.graphics_for_pdf import inventory_pdf_router
from src.basic.inventory.make_excel import inventory_excel_router

from src.basic.foodcost_of_products_storehouse.graphics_for_pdf import foodcost_of_products_storehouse_pdf_router
from src.basic.foodcost_of_products_storehouse.make_excel import foodcost_of_products_storehouse_excel_router

from src.basic.foodcost_of_products_dishes.make_excel import foodcost_of_products_dishes_excel_router
from src.basic.foodcost_of_products_dishes.graphics_for_pdf import foodcost_of_products_dishes_pdf_router


# Класс состояний для FSM
class MailingStates(StatesGroup):
    waiting_for_time = State()


# Класс для управления подписками
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
    "user": "postgres",
    "password": "0000",
    "database": "warehouse",
    "host": "localhost"
}

# Инициализация worker
notification_gsworker = NotificationGoogleSheetsWorker()

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


# Функция для сохранения подписки в БД
async def save_subscription(user_id: int, time: str):
    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute(
        """
        INSERT INTO subscriptions (user_id, time)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE 
        SET time = $2;
        """, user_id, time
    )
    await conn.close()


# Функция для получения подписки из БД
async def get_subscription(user_id: int):
    conn = await asyncpg.connect(**DB_CONFIG)
    result = await conn.fetchrow("SELECT time FROM subscriptions WHERE user_id = $1", user_id)
    await conn.close()
    return result


# Функция для удаления подписки из БД
async def delete_subscription(user_id: int):
    conn = await asyncpg.connect(**DB_CONFIG)
    await conn.execute("DELETE FROM subscriptions WHERE user_id = $1", user_id)
    await conn.close()


# Обработчик команды /start
@router.message(Command("start"))
async def start_command(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    has_token = False  # Логика проверки наличия токена

    # Отправляем сообщение с клавиатурой
    await message.answer(
        "Привет! Я бот, который поможет вам задать вопрос.",
        reply_markup=get_markup(user_id, has_token)
    )


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

    return types.InlineKeyboardMarkup(inline_keyboard=inline_kb)


# Обработчик подписки на рассылку
@router.callback_query(F.data == 'register_mailing')
async def handle_register_subscription(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик для кнопки 'Подписаться на рассылку уведомлений'"""
    user_id = callback_query.from_user.id
    if notification_gsworker.contains_id(user_id):
        await callback_query.answer("Вы уже подписаны на рассылку!")
    else:
        notification_gsworker.add_id(user_id)
        await callback_query.answer("Вы успешно подписались на рассылку уведомлений 📩")
        await callback_query.message.answer("Введите время для рассылки в формате ЧЧ:ММ (например, 12:00):")
        await state.set_state(MailingStates.waiting_for_time)


# Обработчик отписки от рассылки
@router.callback_query(F.data == 'unregister')
async def handle_unregister_subscription(callback_query: CallbackQuery):
    """Обработчик для кнопки 'Отписаться от рассылки уведомлений'"""
    user_id = callback_query.from_user.id
    if not notification_gsworker.contains_id(user_id):
        await callback_query.answer("Вы не подписаны на рассылку!")
    else:
        notification_gsworker.remove_id(user_id)
        await delete_subscription(user_id)
        await callback_query.answer("Вы успешно отписались от рассылки уведомлений ❌")
        await callback_query.message.edit_reply_markup(get_markup(user_id, has_token=False))


# Обработчик ввода времени
@router.message(MailingStates.waiting_for_time)
async def process_time_input(message: Message, state: FSMContext):
    """Обработка ввода времени и сохранение подписки в БД"""
    user_time = message.text.strip()

    # Проверяем формат времени (ЧЧ:ММ)
    if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", user_time):
        await message.answer("Некорректный формат! Введите время в формате ЧЧ:ММ, например 08:30")
        return

    user_id = message.from_user.id

    # Сохраняем подписку в БД
    try:
        await save_subscription(user_id, user_time)
        logging.info(f"Настройки рассылки сохранены: user_id {user_id}, время {user_time}")
        await message.answer(f"Вы выбрали время '{user_time}'. Настройки сохранены!")
    except Exception as e:
        logging.error(f"Ошибка при сохранении подписки в БД: {e}")
        await message.answer("Произошла ошибка при сохранении подписки. Попробуйте снова.")

    # Сброс состояния после завершения процесса
    await state.clear()


# Обработчик отправки вопроса
@router.callback_query(F.data == 'send_question')
async def handle_send_question_button(callback_query: CallbackQuery):
    """Обработчик нажатия на кнопку 'Задать вопрос'"""
    user_id = callback_query.from_user.id
    if user_id in waiting_for_question:
        await callback_query.answer("Вы уже задали вопрос. Пожалуйста, дождитесь ответа.")
        return

    waiting_for_question.add(user_id)
    await callback_query.answer("Отправьте ваш вопрос в виде текста или голосового сообщения.")


# Обработчик текстовых и голосовых сообщений
@router.message(F.text | F.voice)
async def handle_question_message(message: Message):
    """Обработка текстовых и голосовых сообщений"""
    user_id = message.from_user.id
    if user_id not in waiting_for_question:
        return

    waiting_for_question.remove(user_id)

    if message.text:
        answer = await get_mistral_answer(message.text)
        await message.answer(f"Ответ от нейросети: {answer}")
    elif message.voice:
        await message.answer("Обрабатываю голосовое сообщение...")
        file_id = message.voice.file_id
        file = await message.bot.get_file(file_id)
        file_path = f"files/voices/{file.file_id}.ogg"
        await message.bot.download_file(file.file_path, file_path)
        recognized_text = await recognize_speech_from_audio(file_path)
        answer = await get_mistral_answer(recognized_text)
        await message.answer(f"Ответ от нейросети: {answer}")

    await message.answer("Вы можете задать новый вопрос, нажав кнопку 'Задать вопрос'.")


# Функция для получения ответа от модели Mistral
async def get_mistral_answer(question: str) -> str:
    """Получаем ответ от модели Mistral через API Replicate"""
    response = replicate.run(
        "meta/meta-llama-3-8b-instruct",
        input={
            "prompt": f"Ты — русскоязычный помощник. Отвечай на русском: {question}",
            "max_length": 200
        }
    )
    return "".join(response)


# Функция для распознавания речи из аудио
async def recognize_speech_from_audio(file_path: str) -> str:
    """Распознавание речи из аудиофайла"""
    recognizer = sr.Recognizer()
    try:
        audio = AudioSegment.from_ogg(file_path)
        wav_path = file_path.replace(".ogg", ".wav")
        audio.export(wav_path, format="wav")
        with sr.AudioFile(wav_path) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="ru-RU")
        return text
    except Exception as e:
        logging.error(f"Ошибка при распознавании речи: {e}")
        return "Не удалось распознать речь."





# Основная функция для запуска бота
async def main() -> None:
    """Основная функция для запуска бота"""
    bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp.include_router(router)
    dp.include_router(analys_revenue_pdf_router)  # Подключаем роутер для PDF
    dp.include_router(analys_revenue_excel_router)  # Подключаем роутер для Excel
    dp.include_router(trade_turnover_excel_report_router)
    dp.include_router(trade_turnover_pdf_router)
    dp.include_router(trade_turnover_for_various_objects_pdf_router)
    dp.include_router(trade_turnover_for_various_objects_excel_router)
    dp.include_router(foodcost_of_products_dishes_pdf_router)
    dp.include_router(foodcost_of_products_dishes_excel_router)
    dp.include_router(foodcost_of_products_storehouse_excel_router)
    dp.include_router(foodcost_of_products_storehouse_pdf_router)
    dp.include_router(forecasting_losses_pdf_router)
    dp.include_router(forecasting_losses_excel_router)
    dp.include_router(inventory_pdf_router)
    dp.include_router(inventory_excel_router)
    await bot.delete_webhook()

    try:
        logging.info('Бот запущен!')
        await dp.start_polling(bot)
    except (CancelledError, KeyboardInterrupt, SystemExit):
        dp.shutdown()
        logging.info('Бот остановлен')

if __name__ == '__main__':
    asyncio.run(main())



