from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional
import time
import os
import logging
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime
import calendar

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, CommandObject
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
DATABASE_URL = "sqlite:////tmp/database_v5.db" # Снова обновили версию БД
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# --- МОДЕЛИ ---
class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    partner_id: Optional[int] = None
    name: str = "Пользователь"
    personal_income: float = 0.0 
    shared_income: float = 0.0   

class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int 
    name: str
    limit_amount: float = 0.0

class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    amount: float
    category: str
    description: str = ""
    source: str 
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
    last_charged_month: Optional[str] = None # Чтобы не списывать дважды в месяц

class Debt(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pair_id: int
    lender_id: Optional[int] = None 
    borrower_id: Optional[int] = None 
    name: str = "Партнёр" 
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

async def notify_user(user_id: int, text: str):
    try: await bot.send_message(chat_id=user_id, text=f"🔔 {text}")
    except: pass

# --- АВТОМАТИЗАЦИЯ (CRON) ---
async def check_fixed_expenses():
    """Фоновая задача: проверяет, не пора ли списать постоянные траты или напомнить о них."""
    while True:
        try:
            now = datetime.now()
            current_day = now.day
            current_month_str = now.strftime("%Y-%m")
            days_in_month = calendar.monthrange(now.year, now.month)[1]
            
            with Session(engine) as session:
                all_fixed = session.exec(select(FixedExpense)).all()
                
                for fx in all_fixed:
                    # 1. УВЕДОМЛЕНИЕ ЗА ДЕНЬ ДО СПИСАНИЯ
                    # Если сегодня (день - 1) равен дню списания
                    is_tomorrow = (current_day + 1 == fx.day_of_month) or (current_day == days_in_month and fx.day_of_month == 1)
                    if is_tomorrow:
                        # Находим пользователей пары, чтобы отправить уведомление
                        users = session.exec(select(User).where((User.id == fx.pair_id) | (User.partner_id == fx.pair_id))).all()
                        for u in users:
                            await notify_user(u.id, f"Завтра спишется {fx.amount} ₽ за «{fx.name}». Не забудьте пополнить бюджет!")

                    # 2. АВТОМАТИЧЕСКОЕ СПИСАНИЕ
                    # Если сегодня день списания и мы еще не списывали в этом месяце
                    if current_day == fx.day_of_month and fx.last_charged_month != current_month_str:
                        # Ищем, кто из партнеров инициирует (берем первого)
                        user = session.get(User, fx.pair_id)
                        if user:
                            tx = Transaction(
                                user_id=fx.pair_id, 
                                amount=fx.amount, 
                                category="Постоянные траты", 
                                description=f"Авто: {fx.name}", 
                                source="shared", 
                                timestamp=time.time()
                            )
                            session.add(tx)
                            fx.last_charged_month = current_month_str
                            session.add(fx)
                            session.commit()
                            
                            # Уведомляем о списании
                            await notify_user(fx.pair_id, f"✅ Автоматически списано {fx.amount} ₽ за «{fx.name}».")
                            
        except Exception as e:
            logger.error(f"Cron error: {e}")
            
        await asyncio.sleep(3600) # Проверяем каждый час

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

# --- FASTAPI ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    await bot.set_webhook(f"{RENDER_URL}/webhook/{BOT_TOKEN}", drop_pending_updates=True)
    
    # Запускаем фоновую задачу
    asyncio.create_task(check_fixed_expenses())
    logger.info("Фоновая задача автоплатежей запущена")
    
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
        return min(user_id, user.partner_id) 
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
    visible_transactions = [tx for tx in transactions if tx.source == 'shared' or tx.user_id == user_id]

    return {"user": user, "partner": partner, "pair_id": pair_id, "transactions": visible_transactions}

@app.post("/api/add_tx_notify")
async def add_transaction_notify(user_id: int, amount: float, category: str, description: str = "", source: str = "shared", session: Session = Depends(lambda: Session(engine))):
    tx = Transaction(user_id=user_id, amount=amount, category=category, description=description, source=source, timestamp=time.time())
    session.add(tx); session.commit()
    await notify_partner(user_id, f"Трата: {category} на {amount} ₽.")
    return {"status": "success"}

@app.post("/api/add_manual_income")
async def add_manual_income(user_id: int, amount: float, source: str, description: str = "Пополнение", session: Session = Depends(lambda: Session(engine))):
    user = session.get(User, user_id)
    if not user: raise HTTPException(status_code=404, detail="Пользователь не найден")
    if source == "shared": user.shared_income += amount
    else: user.personal_income += amount
    session.add(user); session.commit()
    await notify_partner(user_id, f"Пополнение: +{amount} ₽.")
    return {"status": "success"}

# --- КАТЕГОРИИ И АНАЛИТИКА ---
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

# --- ПЛАН ---
@app.post("/api/add_fixed")
def add_fixed(user_id: int, name: str, amount: float, day: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    session.add(FixedExpense(pair_id=pair_id, name=name, amount=amount, day_of_month=day))
    session.commit(); return {"status": "success"}

@app.get("/api/get_fixed")
def get_fixed(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    fixes = session.exec(select(FixedExpense).where(FixedExpense.pair_id == pair_id)).all()
    sorted_fixes = sorted(fixes, key=lambda x: x.day_of_month)
    total_amount = sum(f.amount for f in sorted_fixes)
    return {"items": sorted_fixes, "total": total_amount}

# --- ДОЛГИ ---
@app.post("/api/add_debt")
def add_debt(user_id: int, amount: float, description: str, name: str = "Партнёр", is_plus: bool = True, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    user = session.get(User, user_id)
    
    if name == "Партнёр":
        lender = user_id if is_plus else (user.partner_id if user and user.partner_id else 0)
        borrower = (user.partner_id if user and user.partner_id else 0) if is_plus else user_id
    else:
        lender = user_id if is_plus else None
        borrower = None if is_plus else user_id
    
    debt = Debt(pair_id=pair_id, lender_id=lender, borrower_id=borrower, name=name, amount=amount, description=description, created_at=time.time())
    session.add(debt); session.commit()
    return {"status": "success"}

@app.get("/api/get_debts")
def get_debts(user_id: int, session: Session = Depends(lambda: Session(engine))):
    pair_id = get_pair_id(user_id, session)
    return session.exec(select(Debt).where(Debt.pair_id == pair_id, Debt.is_paid == False)).all()

@app.post("/api/update_debt")
def update_debt(debt_id: int, amount: float, is_paid: bool, session: Session = Depends(lambda: Session(engine))):
    debt = session.get(Debt, debt_id)
    if debt:
        if amount > 0: # Если сумма не 0, обновляем
            debt.amount = amount
        debt.is_paid = is_paid
        session.add(debt); session.commit()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Долг не найден")
