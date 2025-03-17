import asyncio
import logging
from asyncio import CancelledError
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
import config as cf


from src.mailing.notifications.select_report import subscribe_notifications, setup_routers_select_reports
from src.sound_and_text_ai.ai_answers import ai_answer
from src.mailing.notifications.subscribe_mailing import subcsribe_mailing_router

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


# Инициализация worker
notification_gsworker = NotificationGoogleSheetsWorker()

# Установка уровня логирования
logging.basicConfig(level=logging.INFO)


# Инициализация роутеров
router = Router(name=__name__)
dp = Dispatcher()


# Обработчик команды /start
@router.message(Command("start"))
async def start_command(message: Message):
    """Обработчик команды /start"""
    user_id = message.from_user.id
    has_token = False  # Логика проверки наличия токена

    # Отправляем сообщение с клавиатурой
    await message.answer(
        "Привет! Я бот компании SOVA-TECH.\nВыберите один из пункт меню: ",
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

    btn = [types.InlineKeyboardButton(text='Посмотреть текущие подписки 📅', callback_data='show_subscriptions')]
    inline_kb.append(btn)

    return types.InlineKeyboardMarkup(inline_keyboard=inline_kb)





async def main() -> None:
    bot = Bot(token=cf.TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp.include_router(router)
    setup_routers_select_reports()
    dp.include_router(subscribe_notifications)
    dp.include_router(ai_answer)
    dp.include_router(subcsribe_mailing_router)
    await bot.delete_webhook()

    try:
        logging.info('Бот запущен!')
        await dp.start_polling(bot)
    except (CancelledError, KeyboardInterrupt, SystemExit):
        dp.shutdown()
        logging.info('Бот остановлен')


if __name__ == '__main__':
    asyncio.run(main())



