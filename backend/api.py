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

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://levriavkin.github.io/lovebudget/")
RENDER_URL = os.getenv("RENDER_URL", "https://lovebudget-u4ez.onrender.com") 
BOT_USERNAME = "love_budget_bot" 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- БАЗА ДАННЫХ ---
# ВАЖНО: Я изменил название базы на database_v3.db, чтобы старые данные не ломали новые таблицы
DATABASE_URL = "sqlite:////tmp/database_v3.db" 
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# --- МОДЕЛИ ---
class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    partner_id: Optional[int] = None
    name: str = "Пользователь"
    personal_income: float = 0.0 # Личные деньги
    shared_income: float = 0.0   # Взнос в общий котёл

class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int # ID одного из партнёров (для привязки к паре)
    name: str
    limit_amount: float = 0.0

class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    amount: float
    category: str
    description: str = ""
    source: str # shared (общий) или personal (личный)
    timestamp: float

class ScheduledIncome(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int
    name: str
    amount: float
    day_of_month: int

class FixedExpense(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int
    name: str
    amount: float
    day_of_month: int

class Debt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int
    lender_id: int # Кто дал
    borrower_id: int # Кто взял
    amount: float
    description: str
    is_paid: bool = False
    created_at: float

# --- БОТ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Открыть бюджет", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text="👥 Пригласить партнёра", callback_data="invite")]
    ])

async def notify_partner(user_id: int, text: str):
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user and user.partner_id:
            try: await bot.send_message(chat_id=user.partner_id, text=f"🔔 {text}")
            except: pass

# --- ОБРАБОТЧИКИ БОТА ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject = None):
    user_id = message.from_user.id
    args = command.args if command else None

    if args and args.startswith("pair_"):
        try:
            partner_id = int(args.replace("pair_", ""))
            if partner_id == user_id: return await message.answer("Нельзя пригласить себя 🙂")
            
            with Session(engine) as session:
                user = session.get(User, user_id) or User(id=user_id)
                partner = session.get(User, partner_id) or User(id=partner_id)
                user.partner_id = partner_id; partner.partner_id = user_id
                session.add(user); session.add(partner); session.commit()
            await message.answer("🎉 Вы связаны как пара!", reply_markup=get_main_kb())
        except Exception as e:
            await message.answer("Ошибка связывания.")
    else:
        name = message.from_user.first_name or "друг"
        await message.answer(f"Привет, {name}! 👋", reply_markup=get_main_kb())

@dp.callback_query(lambda c: c.data == "invite")
async def cb_invite(call: types.CallbackQuery):
    await call.answer()
    invite_link = f"https://t.me/{BOT_USERNAME}?start=pair_{call.from_user.id}"
    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", url=f"https://t.me/share/url?url={invite_link}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    await call.message.edit_text(f"<b>👥 Ссылка:</b>\n<code>{invite_link}</code>", reply_markup=share_kb, parse_mode="HTML")

@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(call: types.CallbackQuery):
    await call.answer()
    await call.message.edit_text("Меню:", reply_markup=get_main_kb())

# --- FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    await bot.set_webhook(f"{RENDER_URL}/webhook/{BOT_TOKEN}", drop_pending_updates=True)
    yield
    await bot.delete_webhook(); await bot.session.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.post(f"/webhook/{BOT_TOKEN}")
async def telegram_webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# --- API ---
def get_pair_id(user_id: int, session: Session):
    user = session.get(User, user_id)
    if user and user.partner_id:
        return min(user_id, user.partner_id) # Возвращаем ID младшего партнёра как ключ пары
    return user_id

@app.get("/api/sync")
def sync_data(user_id: int, session: Session = Depends(lambda: Session(engine))):
    user = session.get(User, user_id)
    if not user:
        user = User(id=user_id); session.add(user); session.commit(); session.refresh(user)
    
    partner = session.get(User, user.partner_id) if user.partner_id else None
    pair_id = get_pair_id(user_id, session)
    
    user_ids = [user.id] + ([partner.id] if partner else [])
    transactions = session.exec(select(Transaction).where(Transaction.user_id.in_(user_ids))).all()
    
    # Скрываем личные транзакции партнёра
    visible_transactions = [tx for tx in transactions if tx.source == 'shared' or tx.user_id == user_id]

    return {
        "user": user, 
        "partner": partner, 
        "pair_id": pair_id,
        "transactions": visible_transactions
    }

@app.post("/api/setup")
def setup_user(user_id: int, name: str, personal: float, shared: float, session: Session = Depends(lambda: Session(engine))):
    user = session.get(User, user_id)
    if not user: user = User(id=user_id)
    user.name = name; user.personal_income = personal; user.shared_income = shared
    session.add(user); session.commit()
    return {"status": "success"}

@app.post("/api/add_tx_notify")
async def add_transaction_notify(user_id: int, amount: float, category: str, description: str = "", source: str = "shared", session: Session = Depends(lambda: Session(engine))):
    tx = Transaction(user_id=user_id, amount=amount, category=category, description=description, source=source, timestamp=time.time())
    session.add(tx); session.commit()
    await notify_partner(user_id, f"Трата: {category} на {amount} ₽.")
    return {"status": "success"}

# --- КАТЕГОРИИ (ОБЩИЕ) ---
@app.post("/api/add_category")
def add_category(user_id: int, name: str, limit: float = 0.0, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    existing = session.exec(select(Category).where(Category.pair_id == pair_id, Category.name == name)).first()
    if existing:
        existing.limit_amount = limit; session.add(existing)
    else:
        session.add(Category(pair_id=pair_id, name=name, limit_amount=limit))
    session.commit()
    return {"status": "success"}

@app.get("/api/get_categories")
def get_categories(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    return session.exec(select(Category).where(Category.pair_id == pair_id)).all()

# --- АНАЛИТИКА (Только общие траты) ---
@app.get("/api/category_analytics")
def category_analytics(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    user_ids = [user_id]
    user = session.get(User, user_id)
    if user.partner_id: user_ids.append(user.partner_id)
    
    txs = session.exec(select(Transaction).where(Transaction.user_id.in_(user_ids), Transaction.source == 'shared')).all()
    stats = {}
    for tx in txs: stats[tx.category] = stats.get(tx.category, 0) + tx.amount
    return stats

# --- ПЛАН (ОБЩИЙ) ---
@app.post("/api/add_fixed")
def add_fixed(user_id: int, name: str, amount: float, day: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    session.add(FixedExpense(pair_id=pair_id, name=name, amount=amount, day_of_month=day))
    session.commit(); return {"status": "success"}

@app.get("/api/get_fixed")
def get_fixed(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    # Сортируем по дню месяца
    return sorted(session.exec(select(FixedExpense).where(FixedExpense.pair_id == pair_id)).all(), key=lambda x: x.day_of_month)

@app.post("/api/schedule_income")
def add_schedule_income(user_id: int, name: str, amount: float, day: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    session.add(ScheduledIncome(pair_id=pair_id, name=name, amount=amount, day_of_month=day))
    session.commit(); return {"status": "success"}

@app.get("/api/get_schedule_income")
def get_schedule_income(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    return session.exec(select(ScheduledIncome).where(ScheduledIncome.pair_id == pair_id)).all()

# --- ДОЛГИ ---
@app.post("/api/add_debt")
def add_debt(lender_id: int, borrower_id: int, amount: float, description: str, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(lender_id, session)
    session.add(Debt(pair_id=pair_id, lender_id=lender_id, borrower_id=borrower_id, amount=amount, description=description, created_at=time.time()))
    session.commit(); return {"status": "success"}

@app.get("/api/get_debts")
def get_debts(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    return session.exec(select(Debt).where(Debt.pair_id == pair_id, Debt.is_paid == False)).all()
# --- РУЧНОЕ ПОПОЛНЕНИЕ БАЛАНСА ---
@app.post("/api/add_manual_income")
async def add_manual_income(user_id: int, amount: float, source: str, description: str = "Пополнение", session: Session = Depends(lambda: Session(engine))):
    # Создаем транзакцию с отрицательной суммой (или используем type='income', если поменяли модель)
    # В нашей текущей модели Transaction все траты идут в минус, поэтому для дохода используем отрицательную сумму
    # Но лучше создать отдельную транзакцию дохода. 
    # Для простоты (чтобы не ломать текущую логику баланса) мы просто увеличим доход пользователя в базе.
    
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    if source == "shared":
        user.shared_income += amount
    else:
        user.personal_income += amount
        
    session.add(user)
    session.commit()
    
    # Отправляем уведомление партнёру
    await notify_partner(user_id, f"Пополнение бюджета ({'Общий' if source == 'shared' else 'Личный'}): +{amount} ₽ ({description}).")
    
    return {"status": "success"}    
