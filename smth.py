import os
import tempfile
import speech_recognition as sr
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.markdown import hbold
from pydub import AudioSegment
import asyncio
import logging
import config as cf  # Убедитесь, что TOKEN здесь правильный

# Установка уровня логирования
logging.basicConfig(level=logging.INFO)

TEMP_DIR = r'C:\WORK\sova_rest_bot\sova_rest_bot-master\files\voices'

# Создание бота и диспетчера
bot = Bot(token='7515032749:AAG84O4mCALPRsviMJv--l7NVUkMghm-Adw')
dp = Dispatcher()
router = Router()

waiting_for_question = set()  # Множество пользователей, ожидающих ввода

def get_report_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Создать PDF отчёт", callback_data="create_pdf")],
        [InlineKeyboardButton(text="📊 Создать Excel отчёт", callback_data="create_excel")]
    ])

# Обработчик команды /start
@router.message(F.text.lower() == "/start")
async def send_welcome(message: Message):
    report_text = """
📍 Объект: Демо Ресторан
📊 Отчёт: Выручка Показатели
📅 Период: Прошлая неделя

Выручка: 1 500 000 руб

Динамика неделя: -5%
Динамика месяц: +4%
Динамика год: +8%

План: 5 000 000 руб
Факт: 3 000 000 руб
Прогноз: 4 500 000 руб
    """

    # Отправляем сообщение с отчётом и кнопками
    await message.answer(report_text, reply_markup=get_report_markup())


async def main() -> None:
    logging.info('Запуск бота...')
    dp.include_router(router)  # Убедитесь, что router подключен к диспетчеру
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
