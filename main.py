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
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================================================================
# ЗАГРУЗКА ТОКЕНА ИЗ .env
# ==================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")          # ← токен берётся отсюда
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

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
    """Главное меню с кнопкой Mini App."""
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
    """Кнопка «Назад»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="main_menu")]
    ])

# ==================================================================
# КОМАНДА /start
# ==================================================================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Приветствие при первом запуске."""
    name = message.from_user.first_name or "друг"

    text = (
        f"Привет, {name}! 👋\n\n"
        f"Это <b>LoveBudget</b> — приложение для пар, "
        f"которые хотят вести общий бюджет без ссор.\n\n"
        f"<b>Что умеет:</b>\n"
        f"💰 Общий кошелёк + личные деньги каждого\n"
        f"📊 Автоматический расчёт взносов по доходам\n"
        f"📌 Напоминания о постоянных платежах\n"
        f"🎯 Общие цели и список покупок\n"
        f"🔒 Приватные траты — партнёр видит сумму, но не категорию\n\n"
        f"Нажмите кнопку ниже, чтобы открыть приложение "
        f"и пригласить партнёра."
    )

    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

# ==================================================================
# КОМАНДА /help
# ==================================================================
@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Краткая инструкция."""
    text = (
        "<b>❓ Как пользоваться LoveBudget</b>\n\n"
        "<b>1. Откройте приложение</b>\n"
        "Нажмите «💰 Открыть бюджет» — откроется Mini App.\n\n"
        "<b>2. Пригласите партнёра</b>\n"
        "В приложении нажмите «Пригласить партнёра» — "
        "скопируйте ссылку и отправьте её второй половинке.\n\n"
        "<b>3. Внесите доходы</b>\n"
        "Укажите зарплаты обоих — приложение само рассчитает "
        "пропорцию взносов в общий кошелёк.\n\n"
        "<b>4. Добавьте постоянные траты</b>\n"
        "Аренда, коммуналка, подписки — чтобы видеть план на месяц.\n\n"
        "<b>5. Вносите траты</b>\n"
        "Каждая покупка — несколько секунд. "
        "Партнёр увидит изменения сразу.\n\n"
        "<b>6. Следите за лимитами и прогнозами</b>\n"
        "Приложение предупредит, если траты превышают план.\n\n"
        "Если что-то не работает — напишите в поддержку."
    )
    await message.answer(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# КОМАНДА /invite — приглашение партнёра
# ==================================================================
@dp.message(Command("invite"))
async def cmd_invite(message: Message):
    await send_invite(message)

@dp.callback_query(F.data == "invite")
async def cb_invite(call: CallbackQuery):
    await call.answer()
    await send_invite(call.message)

async def send_invite(message: Message):
    """Генерирует ссылку-приглашение для партнёра."""
    user_id = message.chat.id
    bot_username = (await bot.get_me()).username

    # Уникальный код приглашения (в будущем — из базы данных)
    invite_code = f"pair_{user_id}"

    invite_link = f"https://t.me/{bot_username}?start={invite_code}"

    text = (
        "<b>👥 Пригласите партнёра</b>\n\n"
        "Отправьте эту ссылку вашей второй половинке:\n\n"
        f"<code>{invite_link}</code>\n\n"
        "Когда партнёр перейдёт по ссылке и запустит бота, "
        "вы автоматически будете связаны как пара."
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
# КОМАНДА /budget — открыть Mini App
# ==================================================================
@dp.message(Command("budget"))
async def cmd_budget(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 Открыть бюджет",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ])
    await message.answer(
        "Нажмите кнопку ниже, чтобы открыть приложение:",
        reply_markup=kb
    )

# ==================================================================
# КОМАНДА /settings
# ==================================================================
@dp.message(Command("settings"))
async def cmd_settings(message: Message):
    await send_settings(message)

@dp.callback_query(F.data == "settings")
async def cb_settings(call: CallbackQuery):
    await call.answer()
    await send_settings(call.message)

async def send_settings(message: Message):
    """Заглушка настроек — в будущем данные из базы."""
    user = message.chat
    text = (
        "<b>⚙️ Настройки</b>\n\n"
        f"👤 Ваше имя: <b>{user.first_name}</b>\n"
        f"🆔 Ваш ID: <code>{user.id}</code>\n"
        f"👥 Партнёр: <i>не привязан</i>\n\n"
        "Чтобы пригласить партнёра — нажмите «👥 Пригласить партнёра» "
        "в главном меню.\n\n"
        "Остальные настройки (имена, доходы, пропорции) "
        "меняются внутри приложения."
    )
    await message.answer(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# КОМАНДА /about
# ==================================================================
@dp.message(Command("about"))
async def cmd_about(message: Message):
    await send_about(message)

@dp.callback_query(F.data == "about")
async def cb_about(call: CallbackQuery):
    await call.answer()
    await send_about(call.message)

async def send_about(message: Message):
    text = (
        "<b>ℹ️ О LoveBudget</b>\n\n"
        "LoveBudget — приложение для пар, которые хотят "
        "управлять деньгами вместе, не ссорясь.\n\n"
        "<b>Что внутри:</b>\n"
        "• Общий и личные кошельки\n"
        "• Пропорциональные взносы по доходам\n"
        "• Постоянные траты с напоминаниями\n"
        "• Лимиты по категориям и прогноз на месяц\n"
        "• Общие цели и список желанных покупок\n"
        "• Приватные траты\n\n"
        "<b>Версия:</b> 0.1.0 (бета)\n"
        "<b>Разработчик:</b> [ваше имя]\n\n"
        "Нашли баг или есть идея? Напишите: @ваш_контакт"
    )
    await message.answer(text, reply_markup=back_kb(), parse_mode="HTML")

# ==================================================================
# ОБРАБОТКА ГЛУБОКИХ ССЫЛОК (/start pair_XXX)
# ==================================================================
@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: Message, command: CommandObject):
    """Обработка перехода по ссылке-приглашению."""
    args = command.args  # например, "pair_123456789"

    if args and args.startswith("pair_"):
        inviter_id = args.replace("pair_", "")
        # В будущем: сохранить связь в базе данных
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
# КНОПКА «НАЗАД В МЕНЮ»
# ==================================================================
@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu_kb()
    )

# ==================================================================
# АДМИН-КОМАНДЫ (только для вас)
# ==================================================================
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ваш Telegram ID

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    # Заглушка — в будущем данные из БД
    await message.answer(
        "<b>📊 Статистика</b>\n\n"
        "Пользователей: <i>подключите БД</i>\n"
        "Пар: <i>подключите БД</i>\n"
        "Активных за неделю: <i>подключите БД</i>"
    )

# ==================================================================
# УСТАНОВКА КОМАНД В МЕНЮ БОТА
# ==================================================================
async def set_commands():
    """Устанавливает команды, которые видны в меню бота."""
    commands = [
        BotCommand(command="start",    description="Открыть LoveBudget"),
        BotCommand(command="help",     description="Как пользоваться"),
        BotCommand(command="invite",   description="Пригласить партнёра"),
        BotCommand(command="budget",   description="Открыть Mini App"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="about",    description="О боте"),
    ]
    await bot.set_my_commands(commands)
    logger.info("Команды установлены")

# ==================================================================
# ЗАПУСК
# ==================================================================
async def main():
    logger.info("Запуск LoveBudget...")
    await set_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")