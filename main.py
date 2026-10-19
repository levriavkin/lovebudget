import os
import asyncio
import logging
import httpx
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, BotCommand
)
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage

# ==================================================================
# НАСТРОЙКИ
# ==================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://levriavkin.github.io/lovebudget/")
BACKEND_URL = os.getenv("BACKEND_URL", "https://lovebudget-u4ez.onrender.com")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================================================================
# КЛАВИАТУРЫ
# ==================================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Открыть бюджет", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="👥 Пригласить партнёра", callback_data="invite")]
    ])

def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])

# ==================================================================
# ОБРАБОТЧИКИ КОМАНД
# ==================================================================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    text = (
        f"Привет, {name}! 👋\n\n"
        f"Это <b>LoveBudget</b> — приложение для пар.\n"
        f"Нажмите кнопку ниже, чтобы открыть приложение."
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "<b>❓ Как пользоваться</b>\n\n"
        "1. Нажмите «💰 Открыть бюджет».\n"
        "2. Введите доход и сохраните.\n"
        "3. Нажмите «👥 Пригласить партнёра» и отправьте ссылку второй половинке."
    )
    await message.answer(text, reply_markup=back_kb(), parse_mode="HTML")

@dp.message(Command("invite"))
async def cmd_invite(message: Message):
    user_id = message.chat.id
    bot_username = (await bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start=pair_{user_id}"

    text = (
        "<b>👥 Пригласите партнёра</b>\n\n"
        "Отправьте эту ссылку вашей второй половинке:\n\n"
        f"<code>{invite_link}</code>"
    )
    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={invite_link}&text=Присоединяйся к нашему бюджету!")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    await message.answer(text, reply_markup=share_kb, parse_mode="HTML")

# ==================================================================
# ОБРАБОТЧИКИ КНОПОК
# ==================================================================

@dp.callback_query(F.data == "invite")
async def cb_invite(call: CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    bot_username = (await bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start=pair_{user_id}"

    text = (
        "<b>👥 Пригласите партнёра</b>\n\n"
        "Отправьте эту ссылку вашей второй половинке:\n\n"
        f"<code>{invite_link}</code>"
    )
    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={invite_link}&text=Присоединяйся к нашему бюджету!")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(text, reply_markup=share_kb, parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb())

# ==================================================================
# ОБРАБОТКА ССЫЛКИ-ПРИГЛАШЕНИЯ
# ==================================================================

@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject):
    args = command.args
    if args and args.startswith("pair_"):
        try:
            partner_id = int(args.replace("pair_", ""))
            user_id = message.from_user.id
            
            if partner_id == user_id:
                await message.answer("Нельзя пригласить самого себя 🙂")
                return

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{BACKEND_URL}/api/link_partner",
                    params={"user_id": user_id, "partner_id": partner_id},
                    timeout=10.0
                )
                
                if resp.status_code == 200:
                    await message.answer(
                        f"<b>🎉 Отлично!</b>\n\nВы успешно связаны как пара.\nОткройте приложение.",
                        reply_markup=main_menu_kb(),
                        parse_mode="HTML"
                    )
                else:
                    await message.answer("Ошибка сервера. Попробуйте позже.")
        except Exception as e:
            logger.error(f"Ошибка связывания: {e}")
            await message.answer("Сервер спит или недоступен. Подождите 30 секунд и попробуйте снова.")
    else:
        await cmd_start(message)

# ==================================================================
# ЗАПУСК
# ==================================================================

async def set_commands():
    commands = [
        BotCommand(command="start", description="Открыть LoveBudget"),
        BotCommand(command="help", description="Как пользоваться"),
        BotCommand(command="invite", description="Пригласить партнёра"),
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
