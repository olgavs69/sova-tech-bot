import os
import tempfile
import speech_recognition as sr
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery
from pydub import AudioSegment
import asyncio
import logging
import replicate

# Установите API-ключ для Replicate
os.environ["REPLICATE_API_TOKEN"] = "r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE"

# Настроим логирование
logging.basicConfig(level=logging.INFO)

TEMP_DIR = r'C:\WORK\sova_rest_bot\sova_rest_bot-master\files\voices'

# Создание бота и диспетчера
bot = Bot(token='7515032749:AAG84O4mCALPRsviMJv--l7NVUkMghm-Adw')
dp = Dispatcher()
router = Router()

waiting_for_question = set()  # Множество пользователей, ожидающих ввода

def get_markup() -> types.InlineKeyboardMarkup:
    inline_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text='Задать вопрос ❓', callback_data='send_question')]
    ])
    return inline_kb

# Функция для использования модели на Replicate
def get_mistral_answer(question):
    response = replicate.run(
        "meta/meta-llama-3-8b-instruct",  # Используем модель Meta
        input={
            "prompt": f"Ты — русскоязычный помощник. Отвечай на русском: {question}",
            "max_length": 200
        }
    )
    return "".join(response)

async def recognize_speech(voice: types.Voice) -> str:
    """Распознает голосовое сообщение в текст"""
    recognizer = sr.Recognizer()
    file_id = voice.file_id
    logging.info(f"Получено голосовое сообщение. Файл: {file_id}")

    # Загружаем файл голосового сообщения
    file = await bot.get_file(file_id)
    file_path = file.file_path
    file_bytes = await bot.download_file(file_path)

    # Сохраняем файл
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg", dir=TEMP_DIR) as temp_ogg:
        temp_ogg.write(file_bytes.getvalue())
        temp_ogg.flush()
        temp_ogg.close()
        logging.info(f"Голосовое сообщение сохранено в {temp_ogg.name}")

        # Конвертируем OGG в WAV
        audio = AudioSegment.from_file(temp_ogg.name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=TEMP_DIR) as temp_wav:
            audio.export(temp_wav.name, format="wav")
            logging.info(f"Голосовое сообщение конвертировано в {temp_wav.name}")

            # Распознаем речь
            with sr.AudioFile(temp_wav.name) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data, language="ru-RU")
                    logging.info(f"Распознанный текст: {text}")
                except sr.UnknownValueError:
                    text = "Речь не была распознана."
                    logging.error(f"Ошибка распознавания: Речь не была распознана.")
                except sr.RequestError:
                    text = "Ошибка сервиса распознавания."
                    logging.error(f"Ошибка запроса к сервису распознавания.")

    return text

@router.message(F.text == "/start")
async def start_command(message: Message):
    """Обрабатываем команду /start"""
    await message.answer(
        "Привет! Я бот, готовый ответить на ваши вопросы. Нажмите кнопку ниже, чтобы задать вопрос.",
        reply_markup=get_markup()
    )

@router.callback_query(F.data == 'send_question')
async def handle_question_callback(callback: CallbackQuery):
    """Обработка нажатия кнопки 'Задать вопрос'"""
    user_id = callback.from_user.id
    logging.info(f"Пойман callback от пользователя {user_id}. Добавляю в очередь.")
    waiting_for_question.add(user_id)
    logging.info(f"Пользователь {user_id} добавлен в очередь. Текущее состояние: {waiting_for_question}")
    await callback.message.answer("Отправьте ваш вопрос в виде текста или голосового сообщения:")
    await callback.answer()  # Закрываем всплывающее уведомление

@router.message(F.text)
async def handle_text_message(message: Message):
    """Обработка текстовых сообщений"""
    user_id = message.from_user.id
    logging.info(f"Получено текстовое сообщение от пользователя {user_id}: {message.text}")

    if user_id not in waiting_for_question:
        logging.info(f"Пользователь {user_id} не в ожидании, игнорируем сообщение.")
        return  # Игнорируем сообщения, если не ждали вопроса от пользователя

    logging.info(f"Пользователь {user_id} в ожидании. Обрабатываем сообщение.")
    waiting_for_question.remove(user_id)
    logging.info(f"Пользователь {user_id} удален из очереди. Текущее состояние: {waiting_for_question}")

    # Отправляем сообщение и получаем ответ от модели
    await message.answer(f"Вы задали вопрос: {message.text}")
    answer = get_mistral_answer(message.text)
    await message.answer(f"Ответ: {answer}")

@router.message(F.voice)
async def handle_voice_message(message: Message):
    """Обработка голосовых сообщений"""
    user_id = message.from_user.id
    logging.info(f"Получено голосовое сообщение от пользователя {user_id}")

    if user_id not in waiting_for_question:
        logging.info(f"Пользователь {user_id} не в ожидании, игнорируем сообщение.")
        return  # Игнорируем сообщения, если не ждали вопроса от пользователя

    logging.info(f"Пользователь {user_id} в ожидании. Обрабатываем голосовое сообщение.")
    waiting_for_question.remove(user_id)
    logging.info(f"Пользователь {user_id} удален из очереди. Текущее состояние: {waiting_for_question}")

    await message.answer("Обрабатываю голосовое сообщение...")
    text = await recognize_speech(message.voice)
    await message.answer(f"Вы задали голосовой вопрос: {text}")
    answer = get_mistral_answer(text)
    await message.answer(f"Ответ: {answer}")

async def main() -> None:
    logging.info('Запуск бота...')
    dp.include_router(router)  # Убедитесь, что router подключен к диспетчеру
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
