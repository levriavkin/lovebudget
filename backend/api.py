from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional
import time
import os
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from dotenv import load_dotenv

# --- НАСТРОЙКИ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://levriavkin.github.io/lovebudget/")
RENDER_URL = os.getenv("RENDER_URL", "https://lovebudget-u4ez.onrender.com") 

# ВАШ USERNAME БОТА (для ссылки-приглашения). 
# Замените 'lovebudget_bot' на реальный username вашего бота!
BOT_USERNAME = "love_budget_bot" 

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- БАЗА ДАННЫХ ---
DATABASE_URL = "sqlite:////tmp/database.db" 
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    partner_id: Optional[int] = None
    name: str = "Пользователь"
    income: float = 0.0

class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    amount: float
    category: str
    source: str
    timestamp: float

# --- БОТ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Открыть бюджет", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="👥 Пригласить партнёра", callback_data="invite")]
    ])

# --- ОБРАБОТЧИКИ БОТА (ВСЕ ЗАЩИЩЕНЫ) ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    try:
        name = message.from_user.first_name or "друг"
        await message.answer(f"Привет, {name}! 👋\n\nЭто LoveBudget. Нажми кнопку ниже.", reply_markup=get_main_kb())
    except Exception as e:
        logger.error(f"Ошибка в cmd_start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    try:
        await message.answer("Нажми «💰 Открыть бюджет» или «👥 Пригласить партнёра».", reply_markup=get_main_kb())
    except Exception as e:
        logger.error(f"Ошибка в cmd_help: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")

@dp.callback_query(lambda c: c.data == "invite")
async def cb_invite(call: types.CallbackQuery):
    try:
        await call.answer()
        user_id = call.from_user.id
        
        # Безопасное получение username
        try:
            bot_username = (await bot.get_me()).username
        except Exception:
            bot_username = BOT_USERNAME
            
        invite_link = f"https://t.me/{bot_username}?start=pair_{user_id}"
        
        text = f"<b>👥 Пригласите партнёра</b>\n\n<code>{invite_link}</code>"
        share_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={invite_link}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
        ])
        await call.message.edit_text(text, reply_markup=share_kb, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка в cb_invite: {e}")
        await call.message.answer("Ошибка при создании ссылки. Попробуйте позже.")

@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(call: types.CallbackQuery):
    try:
        await call.answer()
        await call.message.edit_text("Главное меню:", reply_markup=get_main_kb())
    except Exception as e:
        logger.error(f"Ошибка в cb_main_menu: {e}")
        await call.message.answer("Ошибка. Попробуйте позже.")

@dp.message(CommandStart(deep_link=True))
async def cmd_start_deeplink(message: types.Message, command: CommandObject):
    try:
        args = command.args
        if args and args.startswith("pair_"):
            partner_id = int(args.replace("pair_", ""))
            user_id = message.from_user.id
            
            if partner_id == user_id:
                await message.answer("Нельзя пригласить самого себя 🙂")
                return

            with Session(engine) as session:
                user = session.get(User, user_id)
                partner = session.get(User, partner_id)
                if not user: user = User(id=user_id); session.add(user)
                if not partner: partner = User(id=partner_id); session.add(partner)
                user.partner_id = partner_id
                partner.partner_id = user_id
                session.commit()
            
            await message.answer("🎉 Отлично! Вы связаны как пара.", reply_markup=get_main_kb())
        else:
            await cmd_start(message)
    except Exception as e:
        logger.error(f"Ошибка в cmd_start_deeplink: {e}")
        await message.answer("Ошибка связывания. Попробуйте позже.")

# --- FASTAPI APP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    webhook_url = f"{RENDER_URL}/webhook/{BOT_TOKEN}"
    #await bot.set_webhook(webhook_url, drop_pending_updates=True)
    logger.info(f"Webhook set to {webhook_url}")
    yield
    await bot.delete_webhook()
    await bot.session.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post(f"/webhook/{BOT_TOKEN}")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = types.Update(**update_data)
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return {"ok": False}

# --- API ДЛЯ ПРИЛОЖЕНИЯ ---
@app.get("/")
def read_root():
    return {"status": "ok", "message": "LoveBudget Full Service"}

@app.get("/api/sync")
def sync_data(user_id: int, session: Session = Depends(lambda: Session(engine))):
    user = session.get(User, user_id)
    if not user:
        user = User(id=user_id); session.add(user); session.commit(); session.refresh(user)
    partner = session.get(User, user.partner_id) if user.partner_id else None
    user_ids = [user.id]
    if partner: user_ids.append(partner.id)
    transactions = session.exec(select(Transaction).where(Transaction.user_id.in_(user_ids))).all()
    return {"user": user, "partner": partner, "transactions": transactions}

@app.post("/api/setup")
def setup_user(user_id: int, name: str, income: float, session: Session = Depends(lambda: Session(engine))):
    user = session.get(User, user_id)
    if not user: user = User(id=user_id)
    user.name = name; user.income = income
    session.add(user); session.commit()
    return {"status": "success"}

@app.post("/api/add_tx")
def add_transaction(user_id: int, amount: float, category: str, source: str, session: Session = Depends(lambda: Session(engine))):
    tx = Transaction(user_id=user_id, amount=amount, category=category, source=source, timestamp=time.time())
    session.add(tx); session.commit()
    return {"status": "success"}

@app.delete("/api/delete_tx")
def delete_transaction(tx_id: int, user_id: int, session: Session = Depends(lambda: Session(engine))):
    tx = session.get(Transaction, tx_id)
    if tx and tx.user_id == user_id:
        session.delete(tx); session.commit()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Не найдено")
