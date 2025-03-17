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


# Множество пользователей, ожидающих ввода
waiting_for_question = set()


# Установите API-ключ для Replicate
os.environ["REPLICATE_API_TOKEN"] = "r8_TaFGkUSHUTT5nRm6YlFTiW9XxnbYJ6N0ZB0tE"
replicate.api_token = os.environ["REPLICATE_API_TOKEN"]


ai_answer = Router()


# Обработчик отправки вопроса
@ai_answer.callback_query(F.data == 'send_question')
async def handle_send_question_button(callback_query: CallbackQuery):
    """Обработчик нажатия на кнопку 'Задать вопрос'"""
    user_id = callback_query.from_user.id
    if user_id in waiting_for_question:
        await callback_query.answer("Вы уже задали вопрос. Пожалуйста, дождитесь ответа.")
        return

    waiting_for_question.add(user_id)
    await callback_query.answer("Отправьте ваш вопрос в виде текста или голосового сообщения.")


# Обработчик текстовых и голосовых сообщений
@ai_answer.message(F.text | F.voice)
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