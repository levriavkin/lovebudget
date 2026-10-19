from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional
import time

# База данных (создастся сама)
DATABASE_URL = "sqlite:///./database.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

app = FastAPI()

# Разрешаем запросы с вашего сайта на GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- МОДЕЛИ ДАННЫХ ---
class User(SQLModel, table=True):
    id: int = Field(primary_key=True)  # Telegram ID
    partner_id: Optional[int] = None   # ID партнёра
    name: str = "Пользователь"
    income: float = 0.0

class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    amount: float
    category: str
    source: str  # shared, personalA, personalB
    timestamp: float

# Создаем таблицы при запуске
@app.on_event("startup")
def on_startup():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# --- ЭНДПОИНТЫ ---

@app.get("/")
def read_root():
    return {"status": "ok", "message": "LoveBudget Backend работает!"}

# 1. Синхронизация (получить данные пользователя, партнёра и все траты)
@app.get("/api/sync")
def sync_data(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        user = User(id=user_id)
        session.add(user)
        session.commit()
        session.refresh(user)

    partner = session.get(User, user.partner_id) if user.partner_id else None

    # Получаем траты обоих партнёров
    user_ids = [user.id]
    if partner:
        user_ids.append(partner.id)
    
    transactions = session.exec(select(Transaction).where(Transaction.user_id.in_(user_ids))).all()
    
    return {"user": user, "partner": partner, "transactions": transactions}

# 2. Сохранить настройки (имя, доход)
@app.post("/api/setup")
def setup_user(user_id: int, name: str, income: float, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        user = User(id=user_id)
    user.name = name
    user.income = income
    session.add(user)
    session.commit()
    return {"status": "success"}

# 3. Добавить трату
@app.post("/api/add_tx")
def add_transaction(user_id: int, amount: float, category: str, source: str, session: Session = Depends(get_session)):
    tx = Transaction(user_id=user_id, amount=amount, category=category, source=source, timestamp=time.time())
    session.add(tx)
    session.commit()
    return {"status": "success"}

# 4. Привязать партнёра (вызывается из бота)
@app.post("/api/link_partner")
def link_partner(user_id: int, partner_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    partner = session.get(User, partner_id)
    if not user or not partner:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    user.partner_id = partner_id
    partner.partner_id = user_id
    session.add(user)
    session.add(partner)
    session.commit()
    return {"status": "linked"}
# 5. Удалить трату (для редактирования)
@app.delete("/api/delete_tx")
def delete_transaction(tx_id: int, user_id: int, session: Session = Depends(get_session)):
    tx = session.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    
    # Проверка безопасности: удалять может только тот, кто создал
    if tx.user_id != user_id:
        raise HTTPException(status_code=403, detail="Нет прав на удаление")
    
    session.delete(tx)
    session.commit()
    return {"status": "deleted"}
