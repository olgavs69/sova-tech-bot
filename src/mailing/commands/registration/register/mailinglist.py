import os
import replicate
import asyncio
import logging
from asyncio import CancelledError
import speech_recognition as sr
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.dispatcher import router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
import config as cf
from src.mailing.data.notification.notification_google_sheets_worker import notification_gsworker
from pydub import AudioSegment

from src.basic.keyboards.keyboards import get_markup


@router.callback_query(F.data == "register_mailing")
async def handle_register_subscription(callback_query: CallbackQuery):
    """Обработчик для кнопки 'Подписаться на рассылку уведомлений'"""
    user_id = callback_query.from_user.id

    # Проверим, подписан ли уже пользователь на рассылку
    if not notification_gsworker.contains_id(user_id):
        # Если не подписан, добавляем в список
        notification_gsworker.add_id(user_id)
        logging.info(f"Пользователь {user_id} подписался на рассылку.")
        await callback_query.answer("Вы успешно подписались на рассылку уведомлений 📩")
    else:
        # Если уже подписан, уведомим об этом
        await callback_query.answer("Вы уже подписаны на рассылку уведомлений 📩")

    # Предлагаем выбрать периодичность рассылки
    markup = types.InlineKeyboardMarkup()

    markup.add(
        types.InlineKeyboardButton("Ежедневно", callback_data="period_daily"),
        types.InlineKeyboardButton("По будням (пн-пт)", callback_data="period_weekdays"),
        types.InlineKeyboardButton("Еженедельно", callback_data="period_weekly"),
        types.InlineKeyboardButton("Ежемесячно", callback_data="period_monthly")
    )

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
    markup = types.InlineKeyboardMarkup()
    days_of_week = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]

    # Генерация кнопок для выбора дня недели
    for day in days_of_week:
        markup.add(types.InlineKeyboardButton(day, callback_data=f"weekly_{day.lower()}"))

    await callback_query.message.answer(
        "Выберите день недели для еженедельной рассылки:",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("weekly_"))
async def set_weekly_time_and_day(callback_query: CallbackQuery):
    """Обработчик для выбора времени и дня недели еженедельной рассылки"""
    day_of_week = callback_query.data.split("_")[1]  # Извлекаем день недели
    await callback_query.message.answer(f"Вы выбрали {day_of_week.capitalize()}.\nТеперь выберите время для рассылки.")


@router.callback_query(F.data == "period_monthly")
async def set_monthly_day(callback_query: CallbackQuery):
    """Обработчик для выбора ежемесячной рассылки"""
    markup = types.InlineKeyboardMarkup()

    # Генерация кнопок для выбора числа месяца
    for day in range(1, 32):
        markup.add(types.InlineKeyboardButton(str(day), callback_data=f"monthly_{day}"))

    await callback_query.message.answer(
        "Выберите число месяца для ежемесячной рассылки:",
        reply_markup=markup
    )


@router.callback_query(F.data.startswith("monthly_"))
async def set_monthly_time_and_day(callback_query: CallbackQuery):
    """Обработчик для выбора времени ежемесячной рассылки"""
    day_of_month = callback_query.data.split("_")[1]  # Извлекаем число месяца
    await callback_query.message.answer(f"Вы выбрали {day_of_month} число месяца.\nТеперь выберите время для рассылки.")
