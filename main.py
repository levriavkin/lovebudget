import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, BotCommand
)
from aiogram.filters import Command, CommandStart, CommandObject  # ← Добавлен CommandObject
from aiogram.fsm.storage.memory import MemoryStorage

# ==================================================================
# ЗАГРУЗКА ДАННЫХ ИЗ .env
# ==================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")

# ==================================================================
# ЛОГИРОВАНИЕ
# ==================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==================================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ==================================================================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================================================================
# КЛАВИАТУРЫ
# ==================================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 Открыть бюджет",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )],
        [
            InlineKeyboardButton(text="👥 Пригласить партнёра", callback_data="invite"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")
        ],
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
            InlineKeyboardButton(text="ℹ️ О боте", callback_data="about")
        ]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])

# ==================================================================
# КОМАНДА /start
# ==================================================================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    text = (
        f"Привет, {name}! 👋\n\n"
        f"Это <b>LoveBudget</b> — приложение для пар, "
        f"которые хотят вести общий бюджет без ссор.\n\n"
        f"Нажмите кнопку ниже, чтобы открыть приложение."
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

# ==================================================================
# ОБРАБОТКА ГЛУБОКИХ ССЫЛОК (/start pair_XXX)
# ==================================================================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject):
    args = command.args
    if args and args.startswith("pair_"):
        inviter_id = args.replace("pair_", "")
        await message.answer(
            f"<b>🎉 Отлично!</b>\n\n"
            f"Вы присоединились к общему бюджету.\n"
            f"Теперь откройте приложение, чтобы настроить его вместе.",
            reply_markup=main_menu_kb(),
            parse_mode="HTML"
        )
    else:
        await cmd_start(message)

# ==================================================================
# КОМАНДА /help
# ==================================================================
@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>❓ Как пользоваться LoveBudget</b>\n\n"
        "1. Нажмите «💰 Открыть бюджет».\n"
        "2. Настройте имена и доходы.\n"
        "3. Вносите траты — они появятся в истории."
    )
    await message.answer(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# ПРИГЛАШЕНИЕ ПАРТНЁРА
# ==================================================================
@dp.message(Command("invite"))
async def cmd_invite(message: Message):
    await send_invite(message)

@dp.callback_query(F.data == "invite")
async def cb_invite(call: CallbackQuery):
    await call.answer()
    await send_invite(call.message)

async def send_invite(message: Message):
    user_id = message.chat.id
    bot_username = (await bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start=pair_{user_id}"

    text = (
        "<b>👥 Пригласите партнёра</b>\n\n"
        "Отправьте эту ссылку вашей второй половинке:\n\n"
        f"<code>{invite_link}</code>"
    )
    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📤 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={invite_link}&text=Присоединяйся к нашему общему бюджету!"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    await message.answer(text, reply_markup=share_kb, parse_mode="HTML")

# ==================================================================
# НАСТРОЙКИ
# ==================================================================
@dp.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    await call.answer()
    text = f"<b>⚙️ Настройки</b>\n\nВаш ID: <code>{call.from_user.id}</code>"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# О БОТЕ
# ==================================================================
@dp.callback_query(F.data == "about")
async def cb_about(call: CallbackQuery):
    await call.answer()
    text = "<b>ℹ️ О LoveBudget</b>\n\nВерсия: 0.1.0 (бета)"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# НАЗАД В МЕНЮ
# ==================================================================
@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_kb()
    )

# ==================================================================
# ЗАПУСК
# ==================================================================
async def set_commands():
    commands = [
        BotCommand(command="start",    description="Открыть LoveBudget"),
        BotCommand(command="help",     description="Как пользоваться"),
        BotCommand(command="invite",   description="Пригласить партнёра"),
    ]
    await bot.set_my_commands(commands)

async def main():
    logger.info("Запуск LoveBudget...")
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")