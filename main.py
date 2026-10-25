# -*- coding: utf-8 -*-
"""
БОТ "ПОРЕЙДИМСЯ" - ЧИСТАЯ ВЕРСИЯ
"""
import asyncio
import logging
import random
import datetime
import re
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.bot import DefaultBotProperties
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean,
    DateTime, BigInteger, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден!")
    exit()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///database.db")

BOT_NAME = "Порейдимся"
POLICY_URL = "https://telegra.ph/Telegram-bota-Rejd-Serdec-10-05"
SUPPORT_EMAIL = "igor_borysov@mail.ru"

TURN_TIMEOUT_SECONDS = 300
MAX_PREMIUM_USERS_FIRST_1000 = 1000

logging.basicConfig(level=logging.INFO)

# ========== БАЗА ДАННЫХ ==========
if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"sslmode": "require"})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

# ========== МОДЕЛИ ==========
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(64), nullable=False)
    class_name = Column(String(64), nullable=False)
    level = Column(Integer, default=1)
    experience = Column(Integer, default=0)
    
    age = Column(Integer, nullable=True)
    city = Column(String(100), nullable=True)
    mayak = Column(String(200), default="")
    red_flags = Column(String(300), default="")
    
    status = Column(String(20), default="idle")
    partner_tg_id = Column(BigInteger, nullable=True)
    
    full_dungeons = Column(Integer, default=0)
    early_exits = Column(Integer, default=0)
    
    last_daily = Column(DateTime, nullable=True)
    daily_streak = Column(Integer, default=0)
    
    consent_given = Column(Boolean, default=False)
    is_18plus = Column(Boolean, default=False)
    is_pioneer = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_active = Column(DateTime, default=datetime.datetime.utcnow)

class UserTag(Base):
    __tablename__ = "user_tags"
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    category = Column(String(50), nullable=False)
    tag = Column(String(50), nullable=False)

class DungeonSession(Base):
    __tablename__ = "dungeon_sessions"
    id = Column(Integer, primary_key=True)
    player1_tg_id = Column(BigInteger, nullable=False)
    player2_tg_id = Column(BigInteger, nullable=False)
    
    theme_key = Column(String(30), default="forest")
    current_phase = Column(Integer, default=1)
    current_question = Column(Integer, default=0)
    
    player1_answer = Column(Integer, nullable=True)
    player2_answer = Column(Integer, nullable=True)
    player1_ready = Column(Boolean, default=False)
    player2_ready = Column(Boolean, default=False)
    
    phase1_matches = Column(Integer, default=0)
    phase2_matches = Column(Integer, default=0)
    phase3_matches = Column(Integer, default=0)
    
    msg_stage = Column(Integer, default=0)
    player1_msg = Column(String(100), nullable=True)
    player2_msg = Column(String(100), nullable=True)
    
    flag_early_choice = Column(String(50), nullable=True)
    
    status = Column(String(20), default="active")
    last_activity = Column(DateTime, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Partnership(Base):
    __tablename__ = "partnerships"
    id = Column(Integer, primary_key=True)
    user1_tg_id = Column(BigInteger, nullable=False)
    user2_tg_id = Column(BigInteger, nullable=False)
    games_count = Column(Integer, default=0)
    last_played_at = Column(DateTime, default=datetime.datetime.utcnow)
    
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

# ========== УТИЛИТЫ ==========
def calculate_level(exp):
    thresholds = [(1, 0), (2, 100), (3, 300), (4, 600), (5, 1000), (6, 1600), (7, 2400), (8, 3500), (9, 4900), (10, 6700)]
    level = 1
    for lvl, threshold in thresholds:
        if exp >= threshold:
            level = lvl
    return level

def progress_to_next_level(exp):
    thresholds = [(1, 0), (2, 100), (3, 300), (4, 600), (5, 1000), (6, 1600), (7, 2400), (8, 3500), (9, 4900), (10, 6700)]
    current_level = calculate_level(exp)
    if current_level >= 10:
        return (exp, exp)
    current_threshold = 0
    next_threshold = exp
    for lvl, th in thresholds:
        if lvl == current_level:
            current_threshold = th
        if lvl == current_level + 1:
            next_threshold = th
            break
    return (exp - current_threshold, next_threshold - current_threshold)

def progress_bar(current, total, length=8):
    if total <= 0:
        return "▰" * length
    filled = int((current / total) * length)
    return "▰" * max(0, min(length, filled)) + "▱" * (length - max(0, min(length, filled)))

def contains_link(text):
    if not text:
        return False
    patterns = [r"https?://", r"www\.", r"t\.me/", r"@\w+", r"\.(com|ru|net|org|io|me)\b"]
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False

# ========== КЛАССЫ ==========
ALL_BASE_CLASSES = ["Рыцарь", "Тёмный Страж", "Варвар", "Волшебник", "Инженер", "Бард", "Тень", "Следопыт", "Жрец", "Друид"]

HYBRIDS = {
    tuple(sorted(["Рыцарь", "Жрец"])): ("🛡️ Паладин", "Ты — свет в броне. Честь и вера ведут тебя."),
    tuple(sorted(["Рыцарь", "Варвар"])): ("⚔️ Берсерк", "Ты — ярость в броне."),
    tuple(sorted(["Рыцарь", "Тёмный Страж"])): ("💀 Палач", "Ты — судьба предателей."),
    tuple(sorted(["Рыцарь", "Волшебник"])): ("✨ Магистр", "Ты — клинок и посох."),
    tuple(sorted(["Рыцарь", "Инженер"])): ("⚙️ Рыцарь-механик", "Ты — кузнец своей судьбы."),
    tuple(sorted(["Рыцарь", "Бард"])): ("🎭 Рыцарь-поэт", "Ты — слово и меч."),
    tuple(sorted(["Рыцарь", "Тень"])): ("🌒 Ночной страж", "Ты — щит в темноте."),
    tuple(sorted(["Рыцарь", "Следопыт"])): ("🏹 Рыцарь-разведчик", "Ты — честь на дороге."),
    tuple(sorted(["Рыцарь", "Друид"])): ("🌳 Хранитель рощи", "Ты — долг перед природой."),
    tuple(sorted(["Тёмный Страж", "Варвар"])): ("🔥 Кровопийца", "Ты — чистая ярость."),
    tuple(sorted(["Тёмный Страж", "Волшебник"])): ("🖤 Некромант", "Ты — смерть и знание."),
    tuple(sorted(["Тёмный Страж", "Инженер"])): ("⚙️ Инквизитор", "Ты — машина возмездия."),
    tuple(sorted(["Тёмный Страж", "Бард"])): ("🎭 Искуситель", "Ты — слово и тьма."),
    tuple(sorted(["Тёмный Страж", "Тень"])): ("🌑 Призрак", "Ты — неуловимый мститель."),
    tuple(sorted(["Тёмный Страж", "Следопыт"])): ("🏹 Каратель", "Ты — охота на зло."),
    tuple(sorted(["Тёмный Страж", "Жрец"])): ("⚖️ Судья", "Ты — строгость и вера."),
    tuple(sorted(["Тёмный Страж", "Друид"])): ("🍂 Тёмный друид", "Ты — природа и смерть."),
    tuple(sorted(["Варвар", "Волшебник"])): ("🔮 Шаман", "Ты — дикая магия."),
    tuple(sorted(["Варвар", "Инженер"])): ("🔨 Кузнец", "Ты — сила и мастерство."),
    tuple(sorted(["Варвар", "Бард"])): ("🥁 Скальд", "Ты — слава и ярость."),
    tuple(sorted(["Варвар", "Тень"])): ("🌪️ Дикарь", "Ты — инстинкты."),
    tuple(sorted(["Варвар", "Следопыт"])): ("🐺 Зверолов", "Ты — охота и сила."),
    tuple(sorted(["Варвар", "Жрец"])): ("🩸 Кровавый жрец", "Ты — ярость и вера."),
    tuple(sorted(["Варвар", "Друид"])): ("🐻 Берсерк природы", "Ты — первобытная сила."),
    tuple(sorted(["Волшебник", "Инженер"])): ("🔬 Артефактор", "Ты — магия и наука."),
    tuple(sorted(["Волшебник", "Бард"])): ("🎼 Маэстро", "Ты — магия слова."),
    tuple(sorted(["Волшебник", "Тень"])): ("🌫️ Иллюзионист", "Ты — магия скрытности."),
    tuple(sorted(["Волшебник", "Следопыт"])): ("🔭 Провидец", "Ты — магия пути."),
    tuple(sorted(["Волшебник", "Жрец"])): ("📿 Мистик", "Ты — магия и вера."),
    tuple(sorted(["Волшебник", "Друид"])): ("🌿 Друид-маг", "Ты — природа и знание."),
    tuple(sorted(["Инженер", "Бард"])): ("🎪 Изобретатель", "Ты — наука и шоу."),
    tuple(sorted(["Инженер", "Тень"])): ("🗝️ Взломщик", "Ты — механика скрытности."),
    tuple(sorted(["Инженер", "Следопыт"])): ("🧭 Картограф", "Ты — наука пути."),
    tuple(sorted(["Инженер", "Жрец"])): ("⚗️ Алхимик", "Ты — наука и вера."),
    tuple(sorted(["Инженер", "Друид"])): ("🌱 Садовник", "Ты — природа и техника."),
    tuple(sorted(["Бард", "Тень"])): ("🎩 Интриган", "Ты — обаяние и хитрость."),
    tuple(sorted(["Бард", "Следопыт"])): ("🎻 Странник", "Ты — песнь дорог."),
    tuple(sorted(["Бард", "Жрец"])): ("🕊️ Проповедник", "Ты — слово и вера."),
    tuple(sorted(["Бард", "Друид"])): ("🍃 Лесной бард", "Ты — песнь природы."),
    tuple(sorted(["Тень", "Следопыт"])): ("🌲 Лазутчик", "Ты — тихий охотник."),
    tuple(sorted(["Тень", "Жрец"])): ("🕯️ Служитель тайн", "Ты — скрытая вера."),
    tuple(sorted(["Тень", "Друид"])): ("🌑 Ночной друид", "Ты — тайны природы."),
    tuple(sorted(["Следопыт", "Жрец"])): ("🏕️ Пилигрим", "Ты — путь и вера."),
    tuple(sorted(["Следопыт", "Друид"])): ("🦌 Хранитель леса", "Ты — природа и путь."),
    tuple(sorted(["Жрец", "Друид"])): ("☯️ Шаман веры", "Ты — природа и вера."),
}

def get_hybrid_class(scores):
    items = sorted(scores.items(), key=lambda x: -x[1])
    top_score = items[0][1]
    top_classes = [c for c, sc in items if sc == top_score]
    if len(top_classes) >= 2:
        c1, c2 = top_classes[0], top_classes[1]
        pair = tuple(sorted([c1, c2]))
        if pair in HYBRIDS:
            _name, desc = HYBRIDS[pair]
            return (f"⚔️ {c1}-{c2}", desc)
        return (f"⚔️ {c1}-{c2}", f"Ты — смесь {c1} и {c2}. Редкое сочетание.")
    top1 = items[0][0]
    top2 = items[1][0]
    pair = tuple(sorted([top1, top2]))
    if pair in HYBRIDS:
        return HYBRIDS[pair]
    return ("🎭 Загадочный странник", "Ты — тот, кого ещё не описали.")
    # ========== КВИЗ 5x5 ==========
QUIZ = [
    {
        "text": "🚪 Ты заходишь в переполненную комнату. Что делаешь?",
        "options": [
            ("Сразу иду знакомиться и заявляю о себе", "Бард"),
            ("Встаю в стороне и наблюдаю", "Тень"),
            ("Иду к тому, кто выглядит одиноким", "Жрец"),
            ("Прохожу к центру, веду себя уверенно", "Рыцарь"),
            ("Оцениваю обстановку, выбираю выгодную позицию", "Тёмный Страж"),
        ]
    },
    {
        "text": "🗺️ Ты нашёл старую карту сокровищ. Что сделаешь?",
        "options": [
            ("Сразу отправляюсь на поиски", "Варвар"),
            ("Изучаю карту, проверяю подлинность", "Волшебник"),
            ("Составляю план и черчу маршрут", "Инженер"),
            ("Пытаюсь продать или обменять", "Бард"),
            ("Иду в одиночку, без лишних глаз", "Следопыт"),
        ]
    },
    {
        "text": "💔 Друг подвёл тебя. Твоя реакция?",
        "options": [
            ("Прощаю — все ошибаются", "Жрец"),
            ("Разбираюсь, почему так вышло", "Волшебник"),
            ("Обижаюсь, но виду не подаю", "Тень"),
            ("Говорю прямо, требую исправить", "Рыцарь"),
            ("Удаляю из жизни, как сухую ветку", "Друид"),
        ]
    },
    {
        "text": "🏕️ Какой отдых тебе ближе?",
        "options": [
            ("Поход с палаткой и костром", "Следопыт"),
            ("Экстремальные виды спорта, адреналин", "Варвар"),
            ("Вечеринка с друзьями до утра", "Бард"),
            ("Прогулка по городу, изучение нового", "Инженер"),
            ("Уединение вдали от всех", "Друид"),
        ]
    },
    {
        "text": "💎 Что ценишь в людях больше всего?",
        "options": [
            ("Честность", "Рыцарь"),
            ("Ум", "Волшебник"),
            ("Доброту", "Жрец"),
            ("Верность", "Тёмный Страж"),
            ("Свободу", "Друид"),
        ]
    },
]

# ========== ТЕГИ ==========
TAG_QUESTIONS = [
    {"category": "Развлечения", "question": "🎮 Как ты обычно проводишь свободное время?", "tags": ["Видеоигры", "Фильмы", "Книги", "Музыка", "Рисование", "Настольные игры"]},
    {"category": "Активности", "question": "🏃 Что из этого тебя заряжает энергией?", "tags": ["Спорт", "Походы", "Велоспорт", "Плавание", "Йога", "Танцы"]},
    {"category": "Путешествия", "question": "🌍 Если бы у тебя был портал в любую точку мира — куда бы ты шагнул?", "tags": ["✈️ Новое неизведанное", "🏕️ Лес, костёр и звёзды", "🏖️ Тёплый пляж", "🏔️ Горы и тишина", "🏙️ Шумный мегаполис", "🌿 Дикая природа"]},
    {"category": "Интеллект", "question": "🧠 Какая тема вызывает у тебя живой интерес?", "tags": ["Наука", "IT/Технологии", "Психология", "История", "Языки", "Философия"]},
    {"category": "Еда", "question": "🍽️ Что из этого ты предпочитаешь?", "tags": ["Кулинария", "Кофе", "Вино", "Фастфуд", "Суши", "ЗОЖ"]},
    {"category": "Личность", "question": "🧑‍🤝‍🧑 Как бы ты описал себя в компании?", "tags": ["Лидер", "Наблюдатель", "Эмпат", "Домосед", "Тусовщик", "Дипломат"]},
]

# ========== РЭД ФЛАГИ ==========
RED_FLAGS = [
    "🚬 Курение",
    "🍷 Алкоголь",
    "🎮 Компьютерные игры (много)",
    "📚 Саморазвитие (фанатичное)",
    "🗣️ Постоянные голосовые",
    "📵 Долгие ответы",
    "🎉 Сверхобщительность",
    "🤐 Замкнутость",
    "🤬 Мат",
    "🏛️ Политика",
    "🧠 Психология",
    "⛪ Религия",
]
MAX_RED_FLAGS = 2

# ========== FSM ==========
class Reg(StatesGroup):
    consent = State()
    nickname = State()
    age = State()
    city = State()
    mayak = State()
    tags = State()
    red_flags = State()

class Edit(StatesGroup):
    field = State()

class Exchange(StatesGroup):
    msg = State()

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ========== КЛАВИАТУРЫ ==========
def kb_consent():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен(-на)", callback_data="consent_yes")],
        [InlineKeyboardButton(text="📄 Политика конфиденциальности", url=POLICY_URL)],
    ])

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Профиль", callback_data="menu_profile"), InlineKeyboardButton(text="🔍 Найти напарника", callback_data="menu_search")],
        [InlineKeyboardButton(text="🎁 Ежедневный вход", callback_data="menu_daily")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")],
    ])

def kb_cancel_search():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="menu_cancel_search")],
    ])
def kb_profile():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти напарника", callback_data="menu_search")],
        [InlineKeyboardButton(text="✏️ Изменить анкету", callback_data="menu_edit")],
        [InlineKeyboardButton(text="🗑 Удалить меня", callback_data="menu_delete")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_back")],
    ])

def kb_edit():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ник", callback_data="edit_nickname"), InlineKeyboardButton(text="Возраст", callback_data="edit_age")],
        [InlineKeyboardButton(text="Город", callback_data="edit_city"), InlineKeyboardButton(text="Требование", callback_data="edit_mayak")],
        [InlineKeyboardButton(text="Теги", callback_data="edit_tags"), InlineKeyboardButton(text="Рэд флаги", callback_data="edit_borders")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu_profile")],
    ])

def kb_tags(cat_idx: int, tags: list, chosen: set):
    rows = []
    for i, tag in enumerate(tags):
        mark = "✅ " if i in chosen else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{tag}", callback_data=f"tag_{cat_idx}_{i}")])
    rows.append([InlineKeyboardButton(text="➡️ Дальше", callback_data=f"tag_ok_{cat_idx}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_red_flags(chosen: set):
    rows = []
    for i, rf in enumerate(RED_FLAGS):
        mark = "✅ " if i in chosen else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{rf}", callback_data=f"rf_{i}")])
    rows.append([InlineKeyboardButton(text=f"➡️ Готово ({len(chosen)}/{MAX_RED_FLAGS})", callback_data="rf_ok")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_question(options: list):
    rows = []
    for i, opt in enumerate(options):
        rows.append([InlineKeyboardButton(text=opt["text"][:60], callback_data=f"q_{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_after_dungeon():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎭 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu_back")],
    ])
    # ========== ХЕЛПЕРЫ БД ==========
def get_user(tg_id: int):
    with SessionLocal() as s:
        return s.query(User).filter_by(tg_id=tg_id).first()

def save_user(u: User):
    with SessionLocal() as s:
        s.merge(u)
        s.commit()

def get_user_tags(tg_id: int):
    with SessionLocal() as s:
        return s.query(UserTag).filter_by(user_id=tg_id).all()

def get_red_flags(u: User):
    if not u.red_flags:
        return []
    return [x for x in u.red_flags.split("|") if x]

def set_red_flags(u: User, items):
    u.red_flags = "|".join(items)
    save_user(u)

def is_user_ready_full(u: User) -> bool:
    return bool(u and u.class_name and u.age and u.city and u.mayak)

def render_profile(u: User) -> str:
    lvl = calculate_level(u.experience)
    cur, need = progress_to_next_level(u.experience)
    bar = progress_bar(cur, need, 10)
    tags = get_user_tags(u.tg_id)
    tags_str = ", ".join(t.tag for t in tags[:8]) if tags else "—"
    flags = get_red_flags(u)
    flags_str = ", ".join(flags) if flags else "—"
    pioneer = " 🏅 Первопроходец" if u.is_pioneer else ""
    streak = u.daily_streak or 0
    return (
        f"🎭 <b>{u.username}</b>{pioneer}\n"
        f"<b>{u.class_name}</b> · Уровень {lvl}\n"
        f"{bar} {cur}/{need}\n\n"
        f"📍 Город: {u.city or '—'}\n"
        f"🎂 Возраст: {u.age or '—'}\n"
        f"🌟 Требование к напарнику: {u.mayak or '—'}\n"
        f"🚩 Рэд флаги: {flags_str}\n"
        f"🏷 Теги: {tags_str}\n\n"
        f"🎲 Рейдов пройдено: {u.full_dungeons}\n"
        f"🔥 Стрик: {streak} дней"
    )

# ========== СТАРТ И СОГЛАСИЕ ==========
@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    u = get_user(msg.from_user.id)
    if u and u.consent_given:
        await msg.answer(
            f"👋 С возвращением, <b>{u.username}</b>!\n\n{render_profile(u)}",
            reply_markup=kb_main(),
        )
        return
    await msg.answer(
        "👋 Привет! Это бот <b>«Порейдимся»</b> — знакомства в стиле RPG.\n\n"
        "Прежде чем начать, нужно согласие на обработку персональных данных "
        "(152-ФЗ). Мы храним только то, что ты сам введёшь.\n\n"
        "Продолжая, ты подтверждаешь, что тебе 18+ и ты согласен(-на) с "
        "обработкой данных.",
        reply_markup=kb_consent(),
    )
    await state.set_state(Reg.consent)

@dp.callback_query(F.data == "consent_yes", Reg.consent)
async def cb_consent(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    with SessionLocal() as s:
        u = s.query(User).filter_by(tg_id=cb.from_user.id).first()
        if not u:
            count = s.query(User).count()
            u = User(
                tg_id=cb.from_user.id,
                username=cb.from_user.username or f"user_{cb.from_user.id}",
                class_name="🎭 Странник",
                consent_given=True,
                is_18plus=True,
                is_pioneer=(count < MAX_PREMIUM_USERS_FIRST_1000),
            )
            s.add(u)
        else:
            u.consent_given = True
            u.is_18plus = True
        s.commit()
    await cb.message.edit_text("✅ Согласие получено.\n\nКак тебя зовут? Введи ник (2–20 символов).")
    await state.set_state(Reg.nickname)

# ========== РЕГИСТРАЦИЯ ==========
@dp.message(Reg.nickname)
async def reg_nick(msg: Message, state: FSMContext):
    nick = (msg.text or "").strip()
    if not (2 <= len(nick) <= 20) or contains_link(nick):
        await msg.answer("❌ Ник должен быть 2–20 символов, без ссылок и @. Попробуй ещё раз.")
        return
    u = get_user(msg.from_user.id)
    u.username = nick
    save_user(u)
    await state.update_data(nickname=nick)
    await msg.answer("Сколько тебе лет? (только число)")
    await state.set_state(Reg.age)

@dp.message(Reg.age)
async def reg_age(msg: Message, state: FSMContext):
    try:
        age = int((msg.text or "").strip())
    except ValueError:
        await msg.answer("❌ Введи число, например: 22")
        return
    if not (18 <= age <= 99):
        await msg.answer("❌ Возраст от 18 до 99.")
        return
    u = get_user(msg.from_user.id)
    u.age = age
    save_user(u)
    await msg.answer("Из какого ты города?")
    await state.set_state(Reg.city)

@dp.message(Reg.city)
async def reg_city(msg: Message, state: FSMContext):
    city = (msg.text or "").strip()[:100]
    if len(city) < 2 or contains_link(city):
        await msg.answer("❌ Название города — 2–100 символов, без ссылок.")
        return
    u = get_user(msg.from_user.id)
    u.city = city
    save_user(u)
    await msg.answer("🌟 <b>Требование к напарнику</b>\nНапиши, кого бы ты хотел найти (до 200 символов).")
    await state.set_state(Reg.mayak)

@dp.message(Reg.mayak)
async def reg_mayak(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()[:200]
    if len(text) < 5 or contains_link(text):
        await msg.answer("❌ Требование — 5–200 символов, без ссылок.")
        return
    u = get_user(msg.from_user.id)
    u.mayak = text
    save_user(u)
    
    # ЗАПУСКАЕМ КВИЗ СРАЗУ ПОСЛЕ ТРЕБОВАНИЯ
    await msg.answer("🎯 Отлично! Теперь короткий квиз на класс (5 вопросов).")
    await send_quiz_question(msg, 0, {c: 0 for c in ALL_BASE_CLASSES}, state)

# ========== МЕНЮ ПРОФИЛЯ ==========
@dp.callback_query(F.data == "menu_profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not u or not u.consent_given:
        await cb.message.edit_text("Сначала /start")
        return
    await cb.message.edit_text(render_profile(u), reply_markup=kb_profile())

@dp.callback_query(F.data == "menu_back")
async def cb_back(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    await cb.message.edit_text(render_profile(u), reply_markup=kb_main())

@dp.callback_query(F.data == "menu_help")
async def cb_help(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text(
        "❓ <b>Помощь</b>\n\n"
        "🔍 Найти напарника — ищем по городу, возрасту ±2 и общим тегам.\n"
        "🎁 Ежедневный вход — получай опыт за стрик.\n"
        "🎭 Профиль — уровень, теги, рэд флаги.\n\n"
        "Команды: /setname /setage /setcity /setkey /settaboo\n"
        "/reset /delete_me /support /privacy",
        reply_markup=kb_main(),
    )

# ========== КОМАНДЫ И РЕДАКТИРОВАНИЕ ==========
@dp.message(Command("reset"))
async def cmd_reset(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🔄 Состояние сброшено. Нажми /start", reply_markup=kb_main())

@dp.message(Command("delete_me"))
async def cmd_delete_me(msg: Message):
    with SessionLocal() as s:
        s.query(UserTag).filter_by(user_id=msg.from_user.id).delete()
        s.query(User).filter_by(tg_id=msg.from_user.id).delete()
        s.query(DungeonSession).filter(
            (DungeonSession.player1_tg_id == msg.from_user.id) |
            (DungeonSession.player2_tg_id == msg.from_user.id)
        ).delete(synchronize_session=False)
        s.commit()
    await msg.answer("🗑 Все твои данные удалены. Напиши /start, чтобы начать заново.")

@dp.message(Command("support"))
async def cmd_support(msg: Message):
    await msg.answer(f"📧 Поддержка: {SUPPORT_EMAIL}")

@dp.message(Command("privacy"))
async def cmd_privacy(msg: Message):
    await msg.answer(f"📄 Политика конфиденциальности:\n{POLICY_URL}")

@dp.callback_query(F.data == "menu_edit")
async def cb_edit(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("✏️ Что меняем?", reply_markup=kb_edit())

@dp.callback_query(F.data.startswith("edit_"))
@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit_field(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    field = cb.data.split("_", 1)[1]
    
    if field == "tags":
        await state.update_data(tag_cat=0, tag_chosen=[], all_tags=[], is_editing=True)
        await send_tag_question(cb, state)
        return
        
    if field == "borders":
        await state.update_data(rf_chosen=[], is_editing=True)
        await cb.message.edit_text(
            "🚩 <b>Рэд флаги</b>\n\nВыбери до 2:",
            reply_markup=kb_red_flags(set()),
        )
        await state.set_state(Reg.red_flags)
        return
        
    await state.update_data(edit_field=field)
    prompts = {
        "nickname": "Новый ник (2–20 символов):",
        "age": "Новый возраст (18–99):",
        "city": "Новый город:",
        "mayak": "Новое требование к напарнику (5–200 символов):",
    }
    await cb.message.edit_text(prompts.get(field, "Введи значение:"))
    await state.set_state(Edit.field)

@dp.message(Edit.field)
async def edit_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    text = (msg.text or "").strip()
    u = get_user(msg.from_user.id)
    if field == "nickname":
        if not (2 <= len(text) <= 20) or contains_link(text):
            await msg.answer("❌ Ник 2–20 символов, без ссылок.")
            return
        u.username = text
    elif field == "age":
        try:
            a = int(text)
            if not (18 <= a <= 99): raise ValueError
        except ValueError:
            await msg.answer("❌ Возраст 18–99.")
            return
        u.age = a
    elif field == "city":
        if len(text) < 2 or contains_link(text):
            await msg.answer("❌ Город 2–100 символов.")
            return
        u.city = text
    elif field == "mayak":
        if len(text) < 5 or contains_link(text):
            await msg.answer("❌ Требование 5–200 символов.")
            return
        u.mayak = text
    save_user(u)
    await state.clear()
    await msg.answer("✅ Готово!", reply_markup=kb_main())
    await msg.answer(render_profile(u), reply_markup=kb_profile())

@dp.message(Command("setname"))
async def cmd_setname(msg: Message, state: FSMContext):
    await state.update_data(edit_field="nickname")
    await msg.answer("Новый ник:")
    await state.set_state(Edit.field)

@dp.message(Command("setage"))
async def cmd_setage(msg: Message, state: FSMContext):
    await state.update_data(edit_field="age")
    await msg.answer("Новый возраст:")
    await state.set_state(Edit.field)

@dp.message(Command("setcity"))
async def cmd_setcity(msg: Message, state: FSMContext):
    await state.update_data(edit_field="city")
    await msg.answer("Новый город:")
    await state.set_state(Edit.field)

@dp.message(Command("setkey"))
async def cmd_setkey(msg: Message, state: FSMContext):
    await state.update_data(edit_field="mayak")
    await msg.answer("Новое требование к напарнику:")
    await state.set_state(Edit.field)

@dp.message(Command("settaboo"))
async def cmd_settaboo(msg: Message, state: FSMContext):
    await state.update_data(rf_chosen=[])
    await msg.answer("🚩 Рэд флаги (до 2):", reply_markup=kb_red_flags(set()))
    await state.set_state(Reg.red_flags)
    # ========== ТЕГИ ==========
async def send_tag_question(msg_or_cb, state: FSMContext):
    data = await state.get_data()
    idx = data.get("tag_cat", 0)
    if idx >= len(TAG_QUESTIONS):
        await state.update_data(rf_chosen=[])
        text = "🚩 <b>Рэд флаги</b>\n\nОтметь до 2 пунктов — с чем точно не готов(-а) мириться в напарнике.\n3-й слот откроется на 5 уровне."
        if isinstance(msg_or_cb, CallbackQuery):
            await msg_or_cb.message.edit_text(text, reply_markup=kb_red_flags(set()))
        else:
            await msg_or_cb.answer(text, reply_markup=kb_red_flags(set()))
        await state.set_state(Reg.red_flags)
        return
        await state.set_state(Reg.tags)
    q = TAG_QUESTIONS[idx]
    text = f"🏷 <b>Теги · {idx+1}/{len(TAG_QUESTIONS)}</b>\n\n{q['question']}\n\nВыбери 1 тег:"
    kb = kb_tags(idx, q["tags"], set(data.get("tag_chosen", [])))
    if isinstance(msg_or_cb, CallbackQuery):
        await msg_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await msg_or_cb.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("tag_") & ~F.data.startswith("tag_ok_"))
async def cb_tag_toggle(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    _, cat_s, tag_s = cb.data.split("_")
    cat_i, tag_i = int(cat_s), int(tag_s)
    data = await state.get_data()
    chosen = set(data.get("tag_chosen", []))
    if tag_i in chosen:
        chosen.discard(tag_i)
    else:
        chosen = {tag_i}
    await state.update_data(tag_chosen=list(chosen))
    q = TAG_QUESTIONS[cat_i]
    await cb.message.edit_reply_markup(reply_markup=kb_tags(cat_i, q["tags"], chosen))


@dp.callback_query(F.data.startswith("tag_ok_"))
async def cb_tag_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    cat_idx = int(cb.data.split("_")[-1])
    data = await state.get_data()
    chosen = data.get("tag_chosen", [])
    
    if not chosen:
        await cb.answer("Выбери хотя бы 1 тег", show_alert=True)
        return
        
    all_tags = data.get("all_tags", [])
    q = TAG_QUESTIONS[cat_idx]
    cat_name = q["category"]
    
    # Удаляем старый тег этой категории, чтобы не было дублей
    all_tags = [t for t in all_tags if t[0] != cat_name]
    for tag_i in chosen:
        all_tags.append((cat_name, q["tags"][tag_i]))
        
    with SessionLocal() as s:
        s.query(UserTag).filter_by(user_id=cb.from_user.id).delete()
        for cat, tag in all_tags:
            s.add(UserTag(user_id=cb.from_user.id, category=cat, tag=tag))
        s.commit()
        
    if cat_idx + 1 >= len(TAG_QUESTIONS):
        if data.get("is_editing"):
            await state.clear()
            u = get_user(cb.from_user.id)
            await cb.message.edit_text("✅ Теги обновлены!", reply_markup=kb_main())
            await cb.message.answer(render_profile(u), reply_markup=kb_profile())
            return
            
    await state.update_data(
        tag_cat=cat_idx + 1,
        tag_chosen=[],
        all_tags=all_tags,
    )
    await send_tag_question(cb, state)
            return
            
    await state.update_data(
        tag_cat=cat_idx + 1,
        tag_chosen=[],
        all_tags=all_tags,
    )
    await send_tag_question(cb, state)
            
    await state.update_data(
        tag_cat=cat_idx + 1,
        tag_chosen=[],
        all_tags=all_tags,
    )
    await send_tag_question(cb, state)

# ========== РЭД ФЛАГИ ==========
@dp.callback_query(F.data.regexp(r"^rf_\d+$"), Reg.red_flags)
async def cb_rf_toggle(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    i = int(cb.data.split("_")[1])
    data = await state.get_data()
    chosen = set(data.get("rf_chosen", []))
    if i in chosen:
        chosen.discard(i)
    else:
        if len(chosen) >= MAX_RED_FLAGS:
            await cb.answer(f"Максимум {MAX_RED_FLAGS}", show_alert=True)
            return
        chosen.add(i)
    await state.update_data(rf_chosen=list(chosen))
    await cb.message.edit_reply_markup(reply_markup=kb_red_flags(chosen))

@dp.callback_query(F.data == "rf_ok", Reg.red_flags)
async def cb_rf_ok(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    chosen = data.get("rf_chosen", [])
    is_editing = data.get("is_editing", False)
    
    u = get_user(cb.from_user.id)
    set_red_flags(u, [RED_FLAGS[i] for i in chosen])
    await state.clear()
    
    if is_editing:
        await cb.message.edit_text("✅ Рэд флаги обновлены!", reply_markup=kb_main())
        await cb.message.answer(render_profile(u), reply_markup=kb_profile())
    else:
        await cb.message.edit_text("🎉 Регистрация завершена! Открываю профиль...")
        await bot.send_message(cb.from_user.id, render_profile(u), reply_markup=kb_main())

QUIZ_SCORES = {}

def _uid_from(target) -> int:
    if isinstance(target, CallbackQuery):
        return target.from_user.id
    if target.from_user:
        return target.from_user.id
    return target.chat.id

async def send_quiz_question(target, q_idx: int, scores: dict = None, state: FSMContext = None):
    _uid = _uid_from(target)
    if scores is None:
        scores = {c: 0 for c in ALL_BASE_CLASSES}
        
    if q_idx >= len(QUIZ):
        cls_name, cls_desc = get_hybrid_class(scores)
        u = get_user(_uid)
        if u:
            u.class_name = cls_name
            save_user(u)
            text = f"🎉 Твой класс: <b>{cls_name}</b>\n\n{cls_desc}\n\nТеперь выбери свои интересы (теги)."
            if isinstance(target, CallbackQuery):
                await target.message.edit_text(text)
            else:
                await target.answer(text)
            QUIZ_SCORES.pop(_uid, None)
            await state.update_data(tag_cat=0, tag_chosen=[], all_tags=[])
            await send_tag_question(target, state)
        else:
            QUIZ_SCORES.pop(_uid, None)
    else:
        q = QUIZ[q_idx]
        text = f"🎯 <b>Вопрос {q_idx+1}/{len(QUIZ)}</b>\n\n{q['text']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=opt_text[:60], callback_data=f"quiz_{q_idx}_{i}")]
            for i, (opt_text, cls) in enumerate(q["options"])
        ])
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text, reply_markup=kb)
        else:
            await target.answer(text, reply_markup=kb)
        QUIZ_SCORES[_uid] = {"idx": q_idx, "scores": scores}
       
    scores = st["scores"]
    cls = QUIZ[q_i]["options"][opt_i][1]
    scores[cls] = scores.get(cls, 0) + 1
    
    # ПЕРЕДАЕМ STATE ДАЛЬШЕ
    await send_quiz_question(cb, q_i + 1, scores, state)
    # ========== ПОИСК НАПАРНИКА ==========
@dp.callback_query(F.data == "menu_search")
# ========== ПОИСК НАПАРНИКА (КАСКАДНЫЙ) ==========
@dp.callback_query(F.data == "menu_search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not is_user_ready_full(u):
        await cb.message.edit_text("❌ Сначала заполни анкету (/start).", reply_markup=kb_main())
        return

    # Ставим статус "в поиске"
    u.status = "searching"
    save_user(u)
    
    msg = await cb.message.edit_text(
        "🔍 <b>Ищем напарника...</b>\n\nСтрогий поиск (город, возраст, интересы). Ждём 10 секунд...",
        reply_markup=kb_cancel_search()
    )
    
    # Запускаем фоновую задачу поиска
    asyncio.create_task(search_process(u.tg_id, msg.chat.id, msg.message_id))

async def search_process(tg_id: int, chat_id: int, msg_id: int):
    try:
        u = get_user(tg_id)
        if not u or u.status != "searching":
            return

        # ЭТАП 1: Строгий поиск (10 сек)
        await asyncio.sleep(10)
        partner = await find_partner(tg_id, strict=True, with_tags=True)
        
        # ЭТАП 2: Без тегов (ещё 10 сек)
        if not partner:
            u = get_user(tg_id) # обновляем данные
            if u.status != "searching": return
            try:
                await bot.edit_message_text(
                    "🔍 <b>Ищем напарника...</b>\n\nРасширяем поиск (город, возраст). Ждём ещё 10 секунд...",
                    chat_id=chat_id, message_id=msg_id, reply_markup=kb_cancel_search()
                )
            except Exception: pass
            await asyncio.sleep(10)
            partner = await find_partner(tg_id, strict=True, with_tags=False)

        # ЭТАП 3: Без возраста (ещё 10 сек)
        if not partner:
            u = get_user(tg_id)
            if u.status != "searching": return
            try:
                await bot.edit_message_text(
                    "🔍 <b>Ищем напарника...</b>\n\nРасширяем поиск (только город). Ждём ещё 10 секунд...",
                    chat_id=chat_id, message_id=msg_id, reply_markup=kb_cancel_search()
                )
            except Exception: pass
            await asyncio.sleep(10)
            partner = await find_partner(tg_id, strict=False, with_tags=False)

        # ЭТАП 4: Ищем всех подряд (ещё 10 сек)
        if not partner:
            u = get_user(tg_id)
            if u.status != "searching": return
            try:
                await bot.edit_message_text(
                    "🔍 <b>Ищем напарника...</b>\n\nИщем по всей базе. Последняя попытка...",
                    chat_id=chat_id, message_id=msg_id, reply_markup=kb_cancel_search()
                )
            except Exception: pass
            await asyncio.sleep(10)
            partner = await find_anyone(tg_id)

        # ИТОГ
        u = get_user(tg_id)
        if not u or u.status != "searching": return

        if partner:
            await start_dungeon_with(u, partner, chat_id, msg_id)
        else:
            u.status = "idle"
            save_user(u)
            try:
                await bot.edit_message_text(
                    "🔍 Пока никого не нашли. Попробуй позже — база растёт!",
                    chat_id=chat_id, message_id=msg_id, reply_markup=kb_main()
                )
            except Exception: pass

    except Exception as e:
        logging.error(f"Ошибка в поиске: {e}")
        u = get_user(tg_id)
        if u and u.status == "searching":
            u.status = "idle"
            save_user(u)

@dp.callback_query(F.data == "menu_cancel_search")
async def cb_cancel_search(cb: CallbackQuery):
    await cb.answer("Поиск отменен")
    u = get_user(cb.from_user.id)
    if u and u.status == "searching":
        u.status = "idle"
        save_user(u)
    await cb.message.edit_text("Поиск отменен. Возвращайся в меню!", reply_markup=kb_main())

# Хелперы для поиска
async def find_partner(tg_id: int, strict: bool, with_tags: bool):
    with SessionLocal() as s:
        u = s.query(User).filter_by(tg_id=tg_id).first()
        my_tags = {t.tag for t in s.query(UserTag).filter_by(user_id=tg_id).all()}
        
        query = s.query(User).filter(User.tg_id != tg_id, User.status == "idle", User.consent_given == True)
        
        if strict:
            query = query.filter(User.city == u.city)
            query = query.filter(User.age.between(u.age - 2, u.age + 2))
            
        candidates = query.all()
        for c in candidates:
            if with_tags:
                c_tags = {t.tag for t in s.query(UserTag).filter_by(user_id=c.tg_id).all()}
                if not (my_tags & c_tags):
                    continue
            return c
    return None

async def find_anyone(tg_id: int):
    with SessionLocal() as s:
        return s.query(User).filter(
            User.tg_id != tg_id, 
            User.status == "idle", 
            User.consent_given == True
        ).first()

async def start_dungeon_with(u: User, partner: User, chat_id: int, msg_id: int):
    with SessionLocal() as s:
        # Перепроверяем, не занял ли его кто-то другой за эти миллисекунды
        p_check = s.query(User).filter_by(tg_id=partner.tg_id).first()
        if not p_check or p_check.status != "idle":
            u = s.query(User).filter_by(tg_id=u.tg_id).first()
            u.status = "idle"
            s.commit()
            await bot.edit_message_text("Напарник только что нашел другого. Попробуй поиск еще раз!", chat_id=chat_id, message_id=msg_id, reply_markup=kb_main())
            return

        theme_key = random.choice(list(DUNGEONS.keys()))
        ds = DungeonSession(
            player1_tg_id=u.tg_id,
            player2_tg_id=partner.tg_id,
            theme_key=theme_key,
            status="active",
        )
        s.add(ds)
        u.status = "dungeon"
        p_check.status = "dungeon"
        u.partner_tg_id = partner.tg_id
        p_check.partner_tg_id = u.tg_id
        s.commit()
        ds_id = ds.id
        p1_name = u.username
        p2_name = p_check.username

    try:
        await bot.edit_message_text(f"🎉 Нашли напарника: <b>{p2_name}</b>!\nТема: {DUNGEONS[theme_key]['name']}\n\nНачинаем рейд…", chat_id=chat_id, message_id=msg_id)
        await bot.send_message(partner.tg_id, f"🎉 Тебя выбрал(-а) <b>{p1_name}</b>!\nТема: {DUNGEONS[theme_key]['name']}\n\nНачинаем рейд…")
    except Exception:
        pass
    await send_dungeon_question(ds_id)
   

# ========== ДАНЖ ==========
async def send_dungeon_question(ds_id: int):
    with SessionLocal() as s:
        ds = s.query(DungeonSession).get(ds_id)
        if not ds or ds.status != "active":
            return
        theme = DUNGEONS[ds.theme_key]
        phase = theme["phases"][ds.current_phase - 1]
        if ds.current_question == 0:
            intro = f"{phase['name']}\n\n{phase['intro']}"
            for tg in (ds.player1_tg_id, ds.player2_tg_id):
                try:
                    await bot.send_message(tg, intro)
                except Exception:
                    pass
        q_list = phase["questions"]
        if ds.current_question >= len(q_list):
            await advance_phase(ds_id)
            return
        q = q_list[ds.current_question]
        ds.player1_answer = None
        ds.player2_answer = None
        ds.player1_ready = False
        ds.player2_ready = False
        ds.last_activity = datetime.datetime.utcnow()
        s.commit()
        for tg in (ds.player1_tg_id, ds.player2_tg_id):
            try:
                await bot.send_message(tg, q["text"], reply_markup=kb_question(q["options"]))
            except Exception:
                pass

@dp.callback_query(F.data.regexp(r"^q_\d+$"))
async def cb_answer(cb: CallbackQuery):
    await cb.answer()
    i = int(cb.data.split("_")[1])
    with SessionLocal() as s:
        ds = s.query(DungeonSession).filter(
            ((DungeonSession.player1_tg_id == cb.from_user.id) | (DungeonSession.player2_tg_id == cb.from_user.id)) &
            (DungeonSession.status == "active")
        ).first()
        if not ds: return
        is_p1 = ds.player1_tg_id == cb.from_user.id
        if is_p1 and ds.player1_ready: return
        if (not is_p1) and ds.player2_ready: return
        if is_p1:
            ds.player1_answer = i
            ds.player1_ready = True
        else:
            ds.player2_answer = i
            ds.player2_ready = True
        ds.last_activity = datetime.datetime.utcnow()
        s.commit()
        if ds.player1_ready and ds.player2_ready:
            await cb.message.edit_reply_markup(reply_markup=None)
            await resolve_question(ds.id, s)

async def resolve_question(ds_id: int, s):
    ds = s.query(DungeonSession).get(ds_id)
    theme = DUNGEONS[ds.theme_key]
    phase = theme["phases"][ds.current_phase - 1]
    q = phase["questions"][ds.current_question]
    a1, a2 = ds.player1_answer, ds.player2_answer
    soft1 = q["options"][a1]["soft"]
    soft2 = q["options"][a2]["soft"]
    if a1 == a2:
        kind = "same"
        match = 1
    elif soft1 == soft2:
        kind = "soft"
        match = 1
    else:
        kind = "mixed"
        match = 0
    bridge = q["bridges"][kind]
    if ds.current_phase == 1: ds.phase1_matches += match
    elif ds.current_phase == 2: ds.phase2_matches += match
    else: ds.phase3_matches += match
    
    if ds.current_question == theme.get("flag_question") and not ds.flag_early_choice:
        ds.flag_early_choice = str(a1)
    flag_effects = theme.get("flag_effects", {})
    add_text = ""
    if ds.flag_early_choice in flag_effects:
        eff = flag_effects[ds.flag_early_choice]
        if eff["target_question"] == ds.current_question:
            add_text = "\n\n" + eff["add_text"]
    ds.current_question += 1
    ds.last_activity = datetime.datetime.utcnow()
    s.commit()
    for tg in (ds.player1_tg_id, ds.player2_tg_id):
        try:
            await bot.send_message(tg, bridge + add_text)
        except Exception:
            pass
    if ds.current_phase == 2 and ds.current_question >= len(phase["questions"]):
        ds.msg_stage = 1
        s.commit()
        for tg in (ds.player1_tg_id, ds.player2_tg_id):
            try:
                await bot.send_message(tg, "💬 Теперь вы можете обменяться одним сообщением. Напиши что-нибудь напарнику (до 100 символов).")
            except Exception:
                pass
        return
    if ds.current_question >= len(phase["questions"]):
        await advance_phase(ds_id, s)
    else:
        await send_dungeon_question(ds_id)

async def advance_phase(ds_id: int, s=None):
    own = s is None
    if own: s = SessionLocal()
    try:
        ds = s.query(DungeonSession).get(ds_id)
        ds.current_phase += 1
        ds.current_question = 0
        ds.last_activity = datetime.datetime.utcnow()
        if ds.current_phase > 3:
            ds.status = "finished"
            s.commit()
            await finish_dungeon(ds_id, s)
            return
        s.commit()
    finally:
        if own: s.close()
    await send_dungeon_question(ds_id)

# ========== ОБМЕН СООБЩЕНИЯМИ ==========
@dp.message(Exchange.msg)
async def exchange_msg(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()[:100]
    if not text:
        await msg.answer("Напиши текст до 100 символов.")
        return
    with SessionLocal() as s:
        ds = s.query(DungeonSession).filter(
            ((DungeonSession.player1_tg_id == msg.from_user.id) | (DungeonSession.player2_tg_id == msg.from_user.id)) &
            (DungeonSession.status == "active")
        ).first()
        if not ds:
            await state.clear()
            return
        is_p1 = ds.player1_tg_id == msg.from_user.id
        if is_p1: ds.player1_msg = text
        else: ds.player2_msg = text
        ds.msg_stage += 1
        ds.last_activity = datetime.datetime.utcnow()
        s.commit()
        if ds.msg_stage >= 3:
            other = ds.player2_tg_id if is_p1 else ds.player1_tg_id
            try:
                await bot.send_message(other, f"💬 Сообщение от напарника:\n\n{text}")
            except Exception:
                pass
            await state.clear()
            await send_dungeon_question(ds.id)
        else:
            await msg.answer("✅ Отправлено! Ждём ответ напарника.")

@dp.message(F.text, ~F.text.startswith("/"))
async def catch_exchange(msg: Message, state: FSMContext):
    current = await state.get_state()
    if current is not None: return
    with SessionLocal() as s:
        ds = s.query(DungeonSession).filter(
            ((DungeonSession.player1_tg_id == msg.from_user.id) | (DungeonSession.player2_tg_id == msg.from_user.id)) &
            (DungeonSession.status == "active") &
            (DungeonSession.msg_stage == 1)
        ).first()
    if ds:
        await state.set_state(Exchange.msg)
        await exchange_msg(msg, state)

# ========== ФИНАЛ ==========
async def finish_dungeon(ds_id: int, s):
    ds = s.query(DungeonSession).get(ds_id)
    total = ds.phase1_matches + ds.phase2_matches + ds.phase3_matches
    ratio = total / 11
    if ratio >= 0.75: verdict, desc, reward = "💖 Идеальный резонанс", "Вы совпали почти во всём.", 100
    elif ratio >= 0.5: verdict, desc, reward = "✨ Хорошая совместимость", "Вам есть о чём поговорить.", 70
    elif ratio >= 0.25: verdict, desc, reward = "🤔 Есть над чем подумать", "Совпадений немного, но они есть.", 40
    else: verdict, desc, reward = "💔 Слабый резонанс", "Вы слишком разные.", 20
    
    u1 = s.query(User).filter_by(tg_id=ds.player1_tg_id).first()
    u2 = s.query(User).filter_by(tg_id=ds.player2_tg_id).first()
    for u in (u1, u2):
        if u:
            u.experience += reward
            u.full_dungeons += 1
            u.status = "idle"
            u.partner_tg_id = None
    s.commit()
    text = f"🏁 <b>Финал рейда</b>\n\n{verdict}\n{desc}\n\nСовпадений: {total}/11\n✨ +{reward} опыта"
    for tg in (ds.player1_tg_id, ds.player2_tg_id):
        try:
            await bot.send_message(tg, text, reply_markup=kb_after_dungeon())
        except Exception:
            pass

# ========== ТАЙМАУТ ==========
async def timeout_worker():
    while True:
        try:
            await asyncio.sleep(60)
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=TURN_TIMEOUT_SECONDS)
            with SessionLocal() as s:
                stale = s.query(DungeonSession).filter(DungeonSession.status == "active", DungeonSession.last_activity < cutoff).all()
                for ds in stale:
                    ds.status = "finished"
                    for tg in (ds.player1_tg_id, ds.player2_tg_id):
                        u = s.query(User).filter_by(tg_id=tg).first()
                        if u:
                            u.status = "idle"
                            u.partner_tg_id = None
                    s.commit()
                    for tg in (ds.player1_tg_id, ds.player2_tg_id):
                        try:
                            await bot.send_message(tg, "⌛ Рейд прерван: слишком долго не было активности.", reply_markup=kb_main())
                        except Exception:
                            pass
        except Exception as e:
            logging.error(f"timeout_worker: {e}")

# ========== ВЕБ-СЕРВЕР И ЗАПУСК ==========
async def health_check(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    logging.info("Бот запускается…")
    asyncio.create_task(start_web_server())
    asyncio.create_task(timeout_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
        # ========== ПОДЗЕМЕЛЬЯ (ЧАСТЬ 1) ==========
DUNGEONS = {}

DUNGEONS["forest"] = {
    "name": "🌲 Лес оборотней",
    "phases": [
        {
            "name": "🏰 Таверна «Мрачные Врата»",
            "intro": "Дорога привела вас к старой таверне на краю леса. Свет в окнах горит тускло, но дверь открыта. Где-то внутри играет лютня. И пахнет дымом.",
            "questions": [
                {"text": "🌲 Вы входите. За дальним столом сидит охотник. Он смотрит на вас — и улыбается так, будто ждал именно вас.", "options": [{"text": "Подойду и заговорю первым", "soft": False}, {"text": "Сяду в стороне и понаблюдаю", "soft": True}, {"text": "Спрошу у трактирщика, кто это", "soft": True}], "bridges": {"same": "Охотник поднимает кружку и кивает вам. Трактирщик молча ставит перед вами две тарелки — будто вы уже были здесь раньше.", "soft": "Свечи догорают. Охотник встаёт и подходит к вашему столу — без приглашения. Садится напротив и молчит.", "mixed": "Трактирщик гасит свет. Охотник остаётся сидеть. Его тень на стене дрожит, хотя огня уже нет."}},
                {"text": "🍺 Охотник наливает вам. Он говорит о проклятии, что лежит на этом лесу. Говорит тихо — так, чтобы слышали только вы.", "options": [{"text": "Выпью и выслушаю до конца", "soft": True}, {"text": "Откажусь от выпивки, но слушаю", "soft": False}, {"text": "Задам ему прямой вопрос: «Ты кто такой?»", "soft": False}], "bridges": {"same": "Он досказывает историю до конца. Последние слова — про женщину, которая исчезла здесь три года назад. Он не говорит, кем она была.", "soft": "Он замолкает и смотрит в окно. За стеклом — лес. И что-то светится между деревьями. Тускло. Ждёт.", "mixed": "Он резко встаёт и идёт к выходу. У двери оборачивается: «Утром пойдём. Не задерживайся». И выходит в темноту."}},
                {"text": "🌙 Ночь. Вы просыпаетесь от воя. За окном — луна. Охотник стоит и смотрит на неё. Не двигается.", "options": [{"text": "Подойду и спрошу, всё ли в порядке", "soft": True}, {"text": "Разбужу напарника", "soft": True}, {"text": "Тихо возьму оружие", "soft": False}], "bridges": {"same": "Он оборачивается. Его глаза в темноте кажутся жёлтыми. Но он просто улыбается: «Пора».", "soft": "Вой стихает так же внезапно, как и начался. Утром вы находите охотника у дверей — с рюкзаком и двумя факелами.", "mixed": "Ночь прошла без сна. Охотник ждёт вас на крыльце. Молча. Он не спрашивает, спали ли вы."}}
            ]
        },
        {
            "name": "🌲 Мрачная глушь",
            "intro": "Утро. Лес встречает вас тишиной — даже птицы молчат. Охотник идёт впереди. Тропа узкая. Деревья смыкаются над головой.",
            "questions": [
                {"text": "🌲 Тропа раздваивается. Одна дорога — освещённая, широкая. Вторая — тёмная, но короче. Охотник ждёт вашего решения.", "options": [{"text": "Пойду по светлой — не хочу рисковать", "soft": True}, {"text": "Пойду по тёмной — быстрее дойдём", "soft": False}, {"text": "Спрошу у охотника, какой путь он выберет", "soft": True}], "bridges": {"same": "Тропа выводит к ручью. Вода чёрная, но чистая. Охотник набирает её в флягу и молча передаёт вам.", "soft": "Лес расступается. Впереди — поляна. На ней что-то лежит. Охотник ускоряет шаг.", "mixed": "Вы выходите к ручью. Охотник оглядывается: «Кто-то шёл за нами». Вы не слышите шагов, но верите ему."}},
                {"text": "🐺 Из кустов выходит волк. Раненый. Он не нападает — просто смотрит. Ждёт.", "options": [{"text": "Помогу — вдруг он не опасен", "soft": True}, {"text": "Обойду стороной", "soft": True}, {"text": "Добью — нельзя оставлять за спиной", "soft": False}], "bridges": {"same": "Волк уходит в чащу. Охотник смотрит ему вслед и говорит: «Он вернётся». И больше ничего.", "soft": "На снегу остаётся кровавый след. Охотник идёт по нему, не оборачиваясь. Вы — следом.", "mixed": "Тишина. Охотник достаёт нож и режет метку на дереве: «Здесь мы были». Его руки не дрожат."}},
                {"text": "🏚️ Между деревьями — хижина. Старая, но не заброшенная. Из трубы идёт дым. Кто-то был здесь совсем недавно.", "options": [{"text": "Останусь и подожду хозяина", "soft": True}, {"text": "Позову напарника — осмотрим вместе", "soft": True}, {"text": "Обыщу и уйду", "soft": False}], "bridges": {"same": "В углу — детская игрушка. Охотник берёт её в руки. Долго молчит. Потом кладёт обратно.", "soft": "На столе — карта. Охотник сворачивает её и убирает в карман. Не объясняет, зачем.", "mixed": "Он бросает спичку в очаг. Огонь вспыхивает — и тут же гаснет. «Идём», — говорит он. И выходит."}},
                {"text": "👤 Из темноты выходит старик. Сгорбленный. Он говорит: «Не ходите дальше. Там — смерть».", "options": [{"text": "Поблагодарю и поверну назад", "soft": True}, {"text": "Пойду дальше — я не верю ему", "soft": False}, {"text": "Спрошу, откуда он знает", "soft": False}], "bridges": {"same": "Старик смотрит на охотника. Долго. Потом уходит в туман. Охотник не провожает его взглядом.", "soft": "Охотник говорит: «Он врёт. Всегда врёт». Но голос у него дрожит. Впервые за всё время.", "mixed": "Старик хрипит: «Ты привёл их сюда». Охотник молчит. Он не отрицает."}}
            ]
        },
        {
            "name": "🐺 Жилище оборотня",
            "intro": "Ночь. Луна полная. Вы выходите на поляну. И видите его — охотника. Он стоит в центре. И больше не улыбается.",
            "questions": [
                {"text": "🌕 Его глаза светятся жёлтым. Он снимает плащ. Под ним — шрамы. Много.", "options": [{"text": "Атакую первым", "soft": False}, {"text": "Спрошу, что он хочет", "soft": True}, {"text": "Притворюсь, что не заметил", "soft": True}], "bridges": {"same": "Он опускается на колени. Земля под ним трескается. «Теперь ты знаешь».", "soft": "Он говорит: «Я не трону вас. Мне нужна помощь». Голос — как у человека, который давно не просил.", "mixed": "Он снимает плащ и молчит. Шрамы говорят сами за себя."}},
                {"text": "🐺 Оборотень говорит: «Я помогу вам. Но вы должны сохранить мою тайну».", "options": [{"text": "Соглашусь — он помог нам", "soft": True}, {"text": "Откажусь — нельзя доверять монстру", "soft": False}, {"text": "Соглашусь, но решу потом", "soft": False}], "bridges": {"same": "Он встаёт и идёт вперёд. Деревья расступаются перед ним. Он не боится леса.", "soft": "Он говорит: «Спасибо». Впервые за всё время — искренне. Не как охотник, а как человек.", "mixed": "Он замирает. «Если соврёшь — я найду тебя». Он не угрожает. Он просто говорит правду."}},
                {"text": "🌿 Оборотень говорит: «Есть способ снять проклятие. Но цветок растёт только в логове того, кто меня проклял. Я не могу идти туда один».", "options": [{"text": "Помогу — он заслужил шанс", "soft": True}, {"text": "Откажусь — это слишком опасно", "soft": False}, {"text": "Спрошу, что он даст взамен", "soft": False}], "bridges": {"same": "Вы идёте к логову. Чем ближе, тем темнее лес. Оборотень молчит. Он знает, что там.", "soft": "Он ведёт вас потайной тропой. Через час вы видите вход в пещеру. Из неё тянет холодом.", "mixed": "Он говорит: «Я подожду здесь». Садится на камень. И действительно ждёт — сколько бы это ни заняло."}},
                {"text": "🏡 Вы вернулись в деревню. Жители собрались на площади. Оборотень стоит рядом. Они не знают, кто он.", "options": [{"text": "Скажу правду — пусть решают", "soft": False}, {"text": "Совру, чтобы защитить оборотня", "soft": True}, {"text": "Спрошу напарника — пусть решает", "soft": True}], "bridges": {"same": "Толпа молчит. Оборотень кладёт руку вам на плечо. Разворачивается. И уходит в лес. Навсегда.", "soft": "Староста кивает. Ворота закрываются за вашими спинами. Вы остаётесь вдвоём.", "mixed": "Никто не двигается. Только ветер гонит пыль по площади. И оборотень смотрит на вас — долго. Ждёт."}}
            ]
        },
    ],
    "flag_question": 0,
    "flag_options": ["Помогу — вдруг он не опасен", "Обойду стороной", "Добью — нельзя оставлять за спиной"],
    "flag_effects": {
        "0": {"target_question": 7, "add_text": "Рядом с охотником — волк. Тот самый. Он смотрит на вас. Он помнит."},
        "1": {"target_question": 7, "add_text": "Рядом с охотником — волк. Тот самый. Он не враг, но и не друг."},
        "2": {"target_question": 7, "add_text": "Рядом с охотником — волк. Мёртвыми глазами смотрит на вас. Хотя должен быть мёртв."},
    }
}

DUNGEONS["bay"] = {
    "name": "⚓ Бухта призрачных кораблей",
    "phases": [
        {"name": "🌊 Покинутый берег", "intro": "Вы выходите на берег. Туман стоит стеной.", "questions": [
            {"text": "🌫️ Волны лениво накатывают на песок. Куда идёте?", "options": [{"text": "Пойду вдоль берега", "soft": True}, {"text": "Сразу к кораблям", "soft": False}, {"text": "Останусь до рассвета", "soft": True}], "bridges": {"same": "Волны выбрасывают обломок мачты.", "soft": "Туман сгущается.", "mixed": "Из воды выходит фигура."}},
            {"text": "🕯️ На берегу — старый фонарь.", "options": [{"text": "Возьму его", "soft": False}, {"text": "Оставлю", "soft": True}, {"text": "Затушу", "soft": False}], "bridges": {"same": "Фонарь гаснет.", "soft": "Из тумана выходят двое.", "mixed": "Кто-то окликает вас."}},
            {"text": "👤 Выходит старик. Говорит: «Не ходите туда».", "options": [{"text": "Спрошу, кто «они»", "soft": False}, {"text": "Пойду дальше", "soft": True}, {"text": "Предложу пойти с нами", "soft": True}], "bridges": {"same": "Старик исчезает.", "soft": "Он даёт амулет.", "mixed": "Он смеётся."}}
        ]},
        {"name": "🪝 Обломки кораблей", "intro": "Туман расходится. Вы у корабля.", "questions": [
            {"text": "⚓ Следы ведут к люку.", "options": [{"text": "Поднимусь на палубу", "soft": False}, {"text": "Обойду по кругу", "soft": True}, {"text": "Окликну", "soft": False}], "bridges": {"same": "На палубе карта.", "soft": "Люк приоткрыт.", "mixed": "Из трюма пение."}},
            {"text": "📜 В каюте судовой журнал. «Он среди нас».", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Закрою и уйду", "soft": True}, {"text": "Покажу напарнику", "soft": True}], "bridges": {"same": "Журнал рассыпается.", "soft": "Свеча догорает.", "mixed": "Дверь закрывается."}},
            {"text": "🔔 Звенит колокол.", "options": [{"text": "Спущусь в трюм", "soft": False}, {"text": "Останусь", "soft": True}, {"text": "Стукну по палубе", "soft": False}], "bridges": {"same": "Колокол стихает.", "soft": "Появляется фигура.", "mixed": "Колокол падает."}},
            {"text": "🕳️ Перед вами люк.", "options": [{"text": "Спущусь один", "soft": False}, {"text": "Осмотрю люк", "soft": True}, {"text": "Обойду", "soft": True}], "bridges": {"same": "Внизу коридор.", "soft": "Люк закрыт.", "mixed": "Что-то тянет вниз."}}
        ]},
        {"name": "👻 Корабль адмирала призраков", "intro": "Главный корабль.", "questions": [
            {"text": "🌑 Адмирал у штурвала.", "options": [{"text": "Заговорю", "soft": False}, {"text": "Подожду", "soft": True}, {"text": "Достану оружие", "soft": False}], "bridges": {"same": "Глаза как дыры.", "soft": "«Я ждал вас».", "mixed": "Корабль тонет."}},
            {"text": "💀 «Отдайте имя».", "options": [{"text": "Отдам своё", "soft": True}, {"text": "Откажусь", "soft": False}, {"text": "Спрошу зачем", "soft": False}], "bridges": {"same": "Море стихает.", "soft": "Он улыбается.", "mixed": "Вода закипает."}},
            {"text": "🌊 Корабль тонет. Одна шлюпка.", "options": [{"text": "Уступлю место", "soft": True}, {"text": "Прыгну первым", "soft": False}, {"text": "Грести по очереди", "soft": True}], "bridges": {"same": "Шлюпка отходит.", "soft": "Берег близко.", "mixed": "Вода холодная."}},
            {"text": "🏝️ Вы на берегу.", "options": [{"text": "Передохну", "soft": True}, {"text": "Осмотрюсь", "soft": False}, {"text": "Поищу воду", "soft": False}], "bridges": {"same": "Солнце встаёт.", "soft": "Амулет тёплый.", "mixed": "Каждый думает о своём."}}
        ]}
    ],
    "flag_question": 1,
    "flag_options": ["Возьму его", "Оставлю", "Затушу"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "Адмирал смотрит на фонарь."}, "1": {"target_question": 7, "add_text": "Адмирал смотрит на пустые руки."}, "2": {"target_question": 7, "add_text": "Адмирал смотрит на вас с тьмой в глазах."}}
}

DUNGEONS["desert"] = {
    "name": "🏜️ Пустыня оставленных надежд",
    "phases": [
        {"name": "🌴 Оазис надежды", "intro": "Солнце в зените.", "questions": [
            {"text": "🌴 Человек у источника.", "options": [{"text": "Подойду", "soft": True}, {"text": "Наберу воды", "soft": False}, {"text": "Сяду рядом", "soft": True}], "bridges": {"same": "«Вы первые».", "soft": "Протягивает флягу.", "mixed": "Уходит в пустыню."}},
            {"text": "🥖 Лепёшка.", "options": [{"text": "Откажусь", "soft": True}, {"text": "Возьму", "soft": False}, {"text": "Разделю", "soft": True}], "bridges": {"same": "«Будьте осторожны».", "soft": "Рассказывает о городе.", "mixed": "«Вы вернётесь»."}},
            {"text": "💧 «Возьмите меня».", "options": [{"text": "Возьму", "soft": True}, {"text": "Откажу", "soft": False}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Идёт рядом.", "soft": "Остаётся.", "mixed": "Смотрит вслед."}}
        ]},
        {"name": "🔥 Жестокие дюны", "intro": "Только песок.", "questions": [
            {"text": "🔥 Караван.", "options": [{"text": "Подойду", "soft": True}, {"text": "Обойду", "soft": False}, {"text": "Оружие наготове", "soft": False}], "bridges": {"same": "Дают воду.", "soft": "«Идите на север».", "mixed": "«Не ходите к храму»."}},
            {"text": "👤 Человек без сознания.", "options": [{"text": "Отдам воду", "soft": True}, {"text": "Пройду мимо", "soft": False}, {"text": "Смочу губы", "soft": True}], "bridges": {"same": "«Там ответы».", "soft": "Не просыпается.", "mixed": "«Не ходи»."}},
            {"text": "🐍 Змея.", "options": [{"text": "Отдам еду", "soft": True}, {"text": "Прогоню", "soft": False}, {"text": "Убью", "soft": False}], "bridges": {"same": "След к храму.", "soft": "Исчезает.", "mixed": "Смотрит на вас."}},
            {"text": "⚱️ Колодец.", "options": [{"text": "Спущусь первым", "soft": False}, {"text": "Пусть он", "soft": False}, {"text": "Вместе", "soft": True}], "bridges": {"same": "На дне монеты.", "soft": "Вода холодная.", "mixed": "Верёвка обрывается."}}
        ]},
        {"name": "🏛️ Утонувший в песках храм", "intro": "Храм.", "questions": [
            {"text": "🏛️ У входа.", "options": [{"text": "Войду", "soft": False}, {"text": "Обойду", "soft": True}, {"text": "Подожду", "soft": True}], "bridges": {"same": "Факелы горят.", "soft": "Боковой вход.", "mixed": "Утром иначе."}},
            {"text": "👑 Статуя.", "options": [{"text": "Брошу монету", "soft": True}, {"text": "Не буду", "soft": False}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Чаша наполняется.", "soft": "Дым.", "mixed": "Фигура ждёт."}},
            {"text": "💀 «Один останется».", "options": [{"text": "Останусь я", "soft": True}, {"text": "Пусть он", "soft": False}, {"text": "Откажусь", "soft": True}], "bridges": {"same": "Камни падают.", "soft": "Стены рушатся.", "mixed": "Вдвоём."}},
            {"text": "🌅 Вы вышли.", "options": [{"text": "Передохну", "soft": True}, {"text": "Осмотрюсь", "soft": False}, {"text": "Поищу воду", "soft": False}], "bridges": {"same": "Идёте на восток.", "soft": "Ровный песок.", "mixed": "Каждый своей дорогой."}}
        ]}
    ],
    "flag_question": 2,
    "flag_options": ["Возьму", "Откажу", "Спрошу напарника"],
    "flag_effects": {"0": {"target_question": 8, "add_text": "Фигура: «Милосердие — редкость»."}, "1": {"target_question": 8, "add_text": "Фигура: «Здесь каждый выживает сам»."}, "2": {"target_question": 8, "add_text": "Фигура: «Может, хорошо. А может, плохо»."}}
}

DUNGEONS["jungle"] = {
    "name": "🌴 Королевские Джунгли",
    "phases": [
        {"name": "🏕️ Лагерь экспедиции", "intro": "Лагерь.", "questions": [
            {"text": "🌴 Входите.", "options": [{"text": "К командиру", "soft": False}, {"text": "Понаблюдаю", "soft": True}, {"text": "К рабочим", "soft": True}], "bridges": {"same": "«Отдохните».", "soft": "Никто не вернулся.", "mixed": "Кто-то ходит."}},
            {"text": "📜 Ночью человек.", "options": [{"text": "Спрошу", "soft": False}, {"text": "Поблагодарю", "soft": True}, {"text": "Расскажу командиру", "soft": False}], "bridges": {"same": "Уходит.", "soft": "Его нет утром.", "mixed": "«Забудь»."}},
            {"text": "🔥 Утром.", "options": [{"text": "Инициатива", "soft": False}, {"text": "Напарник выберет", "soft": True}, {"text": "Плечо к плечу", "soft": True}], "bridges": {"same": "Лагерь исчезает.", "soft": "Лианы.", "mixed": "Рёв."}}
        ]},
        {"name": "🌿 Непроходимые джунгли", "intro": "Час. Два. Три.", "questions": [
            {"text": "🌿 Стена лиан.", "options": [{"text": "Рубить", "soft": False}, {"text": "Искать обход", "soft": True}, {"text": "Осмотреть", "soft": True}], "bridges": {"same": "Тропа.", "soft": "Ручей.", "mixed": "Рычание."}},
            {"text": "🐒 Обезьяны.", "options": [{"text": "Отобрать", "soft": False}, {"text": "Обмен", "soft": True}, {"text": "Оставить", "soft": True}], "bridges": {"same": "Камень.", "soft": "Сумка цела.", "mixed": "Идёт следом."}},
            {"text": "💀 Тело.", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Похороню", "soft": True}, {"text": "Отдам командиру", "soft": False}], "bridges": {"same": "«Он не зверь».", "soft": "Земля мягкая.", "mixed": "Рвёт страницу."}},
            {"text": "🌊 Река.", "options": [{"text": "Первым", "soft": False}, {"text": "Пусть он", "soft": False}, {"text": "Вместе", "soft": True}], "bridges": {"same": "Кости на дне.", "soft": "Течение.", "mixed": "Мокрые. Живые."}}
        ]},
        {"name": "🐆 Логово зверя", "intro": "Пещера.", "questions": [
            {"text": "🐆 У входа.", "options": [{"text": "Войду", "soft": False}, {"text": "Подожду", "soft": True}, {"text": "Огонь", "soft": False}], "bridges": {"same": "Зверь ждёт.", "soft": "Он ушёл.", "mixed": "Боится."}},
            {"text": "👁️ «Вы за камнем?»", "options": [{"text": "Правда", "soft": False}, {"text": "Совру", "soft": False}, {"text": "Спрошу откуда знает", "soft": True}], "bridges": {"same": "Пропускает.", "soft": "«Смелость».", "mixed": "Молчит."}},
            {"text": "🔥 «Кто возьмёт?»", "options": [{"text": "Я", "soft": True}, {"text": "Пусть он", "soft": False}, {"text": "Откажемся", "soft": True}], "bridges": {"same": "Светится.", "soft": "«Запомню».", "mixed": "«Трусы»."}},
            {"text": "🌅 Вы вышли.", "options": [{"text": "Обниму", "soft": True}, {"text": "Отойду", "soft": False}, {"text": "Промолчу", "soft": True}], "bridges": {"same": "Тишина.", "soft": "Джунгли замолкают.", "mixed": "Рядом."}}
        ]}
    ],
    "flag_question": 1,
    "flag_options": ["Спрошу", "Поблагодарю", "Расскажу командиру"],
    "flag_effects": {"0": {"target_question": 8, "add_text": "Зверь: «Ты знал. Смело»."}, "1": {"target_question": 8, "add_text": "Зверь: «Мудрость. Или трусость»."}, "2": {"target_question": 8, "add_text": "Зверь: «Ты предал. Запомню»."}}
}

DUNGEONS["artist"] = {
    "name": "🎨 Мастерская Художника",
    "phases": [
        {"name": "🖌️ Мастерская", "intro": "Холсты двигаются.", "questions": [
            {"text": "🖌️ Тень.", "options": [{"text": "Поймаю", "soft": False}, {"text": "Осмотрю холсты", "soft": True}, {"text": "К большой картине", "soft": True}], "bridges": {"same": "Мокрый след.", "soft": "Люди смотрят.", "mixed": "Воздух густой."}},
            {"text": "🪑 Палитра.", "options": [{"text": "Возьму", "soft": False}, {"text": "Осмотрюсь", "soft": True}, {"text": "К холсту", "soft": True}], "bridges": {"same": "Тёплая.", "soft": "Кто-то жил.", "mixed": "Свет ровный."}},
            {"text": "💨 Существо.", "options": [{"text": "Успокою", "soft": True}, {"text": "Нападу", "soft": False}, {"text": "Позову напарника", "soft": True}], "bridges": {"same": "Кивает.", "soft": "Плачет.", "mixed": "Взгляд меняется."}}
        ]},
        {"name": "🖼️ Нарисованные пейзажи", "intro": "Вы внутри картины.", "questions": [
            {"text": "🌄 Идеальный мир.", "options": [{"text": "Дальше", "soft": False}, {"text": "Поищу жителей", "soft": True}, {"text": "Сломать идеальность", "soft": False}], "bridges": {"same": "Как музей.", "soft": "Утоптанная тропа.", "mixed": "Ветка исчезает."}},
            {"text": "👤 Существа поют.", "options": [{"text": "Послушаю", "soft": True}, {"text": "Обойду", "soft": True}, {"text": "Где Художник?", "soft": False}], "bridges": {"same": "«Он ждал».", "soft": "Тише.", "mixed": "Показывает на замок."}},
            {"text": "🏚️ Дом.", "options": [{"text": "Загляну", "soft": False}, {"text": "Постучусь", "soft": True}, {"text": "Послушаю", "soft": True}], "bridges": {"same": "Старик.", "soft": "«Уходите».", "mixed": "«Он счастлив»."}},
            {"text": "🛤️ Развилка.", "options": [{"text": "К замку", "soft": False}, {"text": "В лес", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Свет ярче.", "soft": "Старая кисть.", "mixed": "Остаётся одна."}}
        ]},
        {"name": "🏰 Сказочный замок", "intro": "Художник на троне.", "questions": [
            {"text": "🎨 «Я не вернусь».", "options": [{"text": "Почему?", "soft": True}, {"text": "Ты разрушаешь реальность", "soft": False}, {"text": "Промолчу", "soft": True}], "bridges": {"same": "«Здесь всё».", "soft": "«Здесь живу».", "mixed": "«Не понимаете»."}},
            {"text": "💔 «Меня не приняли».", "options": [{"text": "Это иллюзия", "soft": False}, {"text": "Промолчу", "soft": True}, {"text": "Пробовал изменить?", "soft": True}], "bridges": {"same": "«Не вышло».", "soft": "Песня.", "mixed": "«Не думал»."}},
            {"text": "⚖️ «Я умру».", "options": [{"text": "Останусь", "soft": True}, {"text": "Уйду", "soft": False}, {"text": "Пусть напарник", "soft": True}], "bridges": {"same": "Светится.", "soft": "«Разумно».", "mixed": "Не ожидал."}},
            {"text": "🚪 У портала.", "options": [{"text": "Убедить закрыть", "soft": True}, {"text": "Уйти", "soft": False}, {"text": "Нарисовать дверь", "soft": True}], "bridges": {"same": "Портал гаснет.", "soft": "Мир пострадает.", "mixed": "Дверь появляется."}}
        ]}
    ],
    "flag_question": 2,
    "flag_options": ["Успокою", "Нападу", "Позову напарника"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Ты понял. Спасибо»."}, "1": {"target_question": 7, "add_text": "«Ты ударил. Я видел»."}, "2": {"target_question": 7, "add_text": "«Ты не один»."}}
}

DUNGEONS["inferno"] = {
    "name": "🔥 Цитадель Инферно",
    "phases": [
        {"name": "🚪 Демонические врата", "intro": "Врата дышат.", "questions": [
            {"text": "🔥 Врата.", "options": [{"text": "Войду", "soft": False}, {"text": "Поищу вход", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Лестница вниз.", "soft": "Дверь приоткрыта.", "mixed": "Страж."}},
            {"text": "👤 Страж.", "options": [{"text": "Назову первым", "soft": True}, {"text": "Совру", "soft": False}, {"text": "Откажусь", "soft": False}], "bridges": {"same": "«Он ждёт».", "soft": "«Все врут».", "mixed": "«Роскошь»."}},
            {"text": "🌑 Зал.", "options": [{"text": "Подойду", "soft": False}, {"text": "Подожду", "soft": True}, {"text": "Поищу выходы", "soft": True}], "bridges": {"same": "«Ждал».", "soft": "Семь дверей.", "mixed": "«Выберите»."}}
        ]},
        {"name": "🛤️ Тропа греха", "intro": "Семь дверей.", "questions": [
            {"text": "💰 Жадность.", "options": [{"text": "Возьму", "soft": False}, {"text": "Нет", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Пыль.", "soft": "Дыхание.", "mixed": "Тени."}},
            {"text": "📖 Знание.", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Закрою", "soft": True}, {"text": "Сожгу", "soft": False}], "bridges": {"same": "Пепел.", "soft": "Пусто.", "mixed": "Крик."}},
            {"text": "❤️‍🔥 Похоть.", "options": [{"text": "Подойду", "soft": False}, {"text": "Уйду", "soft": True}, {"text": "Спрошу зачем", "soft": False}], "bridges": {"same": "Кольцо.", "soft": "«Помню».", "mixed": "«Ты хотел»."}},
            {"text": "🔮 Гордость.", "options": [{"text": "Посмотрю", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Разобью", "soft": False}], "bridges": {"same": "Дым.", "soft": "Осколки.", "mixed": "Отражение."}}
        ]},
        {"name": "🏚️ Цитадель Предательства", "intro": "Развалины.", "questions": [
            {"text": "🏚️ «Что вы готовы отдать?»", "options": [{"text": "Спрошу что", "soft": True}, {"text": "Потребую отпустить", "soft": False}, {"text": "Промолчу", "soft": True}], "bridges": {"same": "«Слово».", "soft": "«Жаль убивать».", "mixed": "Выхода нет."}},
            {"text": "🔥 «Кто останется?»", "options": [{"text": "Я", "soft": True}, {"text": "Откажусь", "soft": False}, {"text": "Отсрочку", "soft": False}], "bridges": {"same": "Красным.", "soft": "«Люблю смелых».", "mixed": "«Трус»."}},
            {"text": "💀 «Убей напарника».", "options": [{"text": "Откажусь", "soft": True}, {"text": "Что конкретно?", "soft": False}, {"text": "Пусть напарник", "soft": False}], "bridges": {"same": "Искра.", "soft": "Стены рушатся.", "mixed": "Пол трескается."}},
            {"text": "🌅 Вы выбрались.", "options": [{"text": "Передохну", "soft": True}, {"text": "Отойду", "soft": False}, {"text": "Осмотрюсь", "soft": False}], "bridges": {"same": "Пепел.", "soft": "Птицы.", "mixed": "В свою сторону."}}
        ]}
    ],
    "flag_question": 3,
    "flag_options": ["Возьму", "Нет", "Спрошу напарника"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Все берут. Жалеют»."}, "1": {"target_question": 7, "add_text": "«Не такой, как все»."}, "2": {"target_question": 7, "add_text": "«Твоя слабость»."}}
}

DUNGEONS["cathedral"] = {
    "name": "🕯️ Собор Тёмной Владычицы",
    "phases": [
        {"name": "💎 Кристальная тропа", "intro": "Кристаллы поют.", "questions": [
            {"text": "💎 Тропа.", "options": [{"text": "Быстрее", "soft": False}, {"text": "Послушаю", "soft": True}, {"text": "Подниму кристалл", "soft": True}], "bridges": {"same": "Вас ждут.", "soft": "Свет.", "mixed": "Кто-то идёт."}},
            {"text": "👤 Жрица.", "options": [{"text": "Что оставить?", "soft": False}, {"text": "Оставлю", "soft": True}, {"text": "Откажусь", "soft": False}], "bridges": {"same": "Дверь открывается.", "soft": "Шевелится.", "mixed": "«Все возвращаются»."}},
            {"text": "🕯️ Внутри.", "options": [{"text": "К алтарю", "soft": False}, {"text": "Осмотрюсь", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "«Ждала».", "soft": "Тени.", "mixed": "«Ответ — это вы»."}}
        ]},
        {"name": "🌉 Мост над Бездной", "intro": "Бездна.", "questions": [
            {"text": "🌉 Мост.", "options": [{"text": "Первым", "soft": False}, {"text": "Вместе", "soft": True}, {"text": "Загляну вниз", "soft": False}], "bridges": {"same": "Тишина.", "soft": "Уважает смелых.", "mixed": "Себя."}},
            {"text": "👁️ Зеркало.", "options": [{"text": "Посмотрю", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Плюну", "soft": False}], "bridges": {"same": "Осколки.", "soft": "Замолкает.", "mixed": "Улыбается."}},
            {"text": "🕯️ Свеча.", "options": [{"text": "Затушу", "soft": False}, {"text": "Оставлю", "soft": True}, {"text": "Возьму", "soft": False}], "bridges": {"same": "Темнее.", "soft": "Страх уходит.", "mixed": "Ждёт."}},
            {"text": "🌑 «Один вопрос».", "options": [{"text": "О будущем", "soft": False}, {"text": "О напарнике", "soft": False}, {"text": "Откажусь", "soft": True}], "bridges": {"same": "«Ложь».", "soft": "«Мудрее».", "mixed": "«Не тот»."}}
        ]},
        {"name": "🌙 Покои Ночи", "intro": "Тьма.", "questions": [
            {"text": "🌙 Трон.", "options": [{"text": "Зачем мы здесь?", "soft": True}, {"text": "Промолчу", "soft": True}, {"text": "Потребую объяснений", "soft": False}], "bridges": {"same": "«Решается всё».", "soft": "«Страх — честность».", "mixed": "Стены дышат."}},
            {"text": "🖤 «Кого выбрать?»", "options": [{"text": "Напарника", "soft": True}, {"text": "Меня", "soft": False}, {"text": "Откажусь", "soft": True}], "bridges": {"same": "Что-то изменилось.", "soft": "«Люблю смелых».", "mixed": "«Все жалеют»."}},
            {"text": "🔥 «Предай принципы».", "options": [{"text": "Откажусь", "soft": True}, {"text": "Что предать?", "soft": False}, {"text": "Соглашусь", "soft": False}], "bridges": {"same": "Свет.", "soft": "Стены рушатся.", "mixed": "Дрожит."}},
            {"text": "🌅 Руины.", "options": [{"text": "За руку", "soft": True}, {"text": "Отойду", "soft": False}, {"text": "Сяду", "soft": True}], "bridges": {"same": "Свет.", "soft": "Свобода.", "mixed": "Так и должно быть."}}
        ]}
    ],
    "flag_question": 5,
    "flag_options": ["Затушу", "Оставлю", "Возьму"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Смело. И глупо»."}, "1": {"target_question": 7, "add_text": "«Спасибо»."}, "2": {"target_question": 7, "add_text": "«Верни»."}}
}
DUNGEONS["valley"] = {
    "name": "🏔️ Непроходимая долина",
    "phases": [
        {"name": "🛤️ Дорога в долину", "intro": "Туман.", "questions": [
            {"text": "🏔️ Тропа.", "options": [{"text": "Первым", "soft": False}, {"text": "Шаг в шаг", "soft": True}, {"text": "Подожду", "soft": True}], "bridges": {"same": "Тёплый камень.", "soft": "Ждёт.", "mixed": "Не достигает дна."}},
            {"text": "👤 Старик.", "options": [{"text": "Найму", "soft": True}, {"text": "Откажусь", "soft": False}, {"text": "Расспрошу", "soft": True}], "bridges": {"same": "Не оглядывается.", "soft": "«Все умирают».", "mixed": "Идёт молча."}},
            {"text": "🌫️ Ночь.", "options": [{"text": "Выйду один", "soft": False}, {"text": "Притворюсь спящим", "soft": True}, {"text": "Костёр ярче", "soft": False}], "bridges": {"same": "Тишина.", "soft": "Костёр потушен.", "mixed": "Дыхание."}}
        ]},
        {"name": "🧱 Каменный лабиринт", "intro": "Туман расходится.", "questions": [
            {"text": "🧱 Три коридора.", "options": [{"text": "К солнцу", "soft": False}, {"text": "К луне", "soft": True}, {"text": "К звезде", "soft": True}], "bridges": {"same": "Свет.", "soft": "Холоднее.", "mixed": "Развилка."}},
            {"text": "🕳️ Трещина.", "options": [{"text": "Спущусь первым", "soft": False}, {"text": "Осмотрю", "soft": True}, {"text": "Вместе", "soft": True}], "bridges": {"same": "Древние рисунки.", "soft": "Сломалось.", "mixed": "Дыхание."}},
            {"text": "⚙️ Механизм.", "options": [{"text": "Первый рычаг", "soft": False}, {"text": "Второй", "soft": True}, {"text": "Обход", "soft": True}], "bridges": {"same": "В воду.", "soft": "Тайный проход.", "mixed": "Смеётся."}},
            {"text": "🌊 Река.", "options": [{"text": "Переплыву", "soft": False}, {"text": "Поищу мост", "soft": True}, {"text": "Верёвку", "soft": True}], "bridges": {"same": "Открыта.", "soft": "Держит.", "mixed": "Держитесь."}}
        ]},
        {"name": "💰 Сокровищница", "intro": "Зал с золотом.", "questions": [
            {"text": "💰 Сокровища.", "options": [{"text": "Возьму", "soft": False}, {"text": "Не возьму", "soft": True}, {"text": "Осмотрю", "soft": False}], "bridges": {"same": "Мёртвое.", "soft": "Ждут.", "mixed": "Звон."}},
            {"text": "👑 Скелет.", "options": [{"text": "Прочитаю свиток", "soft": False}, {"text": "Оставлю", "soft": True}, {"text": "Похороню", "soft": True}], "bridges": {"same": "Стёрто.", "soft": "Железо.", "mixed": "Ваше имя."}},
            {"text": "🗡️ Голос.", "options": [{"text": "Откажемся", "soft": True}, {"text": "Возьму и останусь", "soft": True}, {"text": "Оставлю напарника", "soft": False}], "bridges": {"same": "Свободны.", "soft": "«Достойно».", "mixed": "Тень."}},
            {"text": "🌅 Вы выбрались.", "options": [{"text": "Передохну", "soft": True}, {"text": "Подышать", "soft": False}, {"text": "Осмотрюсь", "soft": False}], "bridges": {"same": "Оседает.", "soft": "Полынь.", "mixed": "Чистое небо."}}
        ]}
    ],
    "flag_question": 1, "flag_options": ["Найму", "Откажусь", "Расспрошу"],
    "flag_effects": {"0": {"target_question": 9, "add_text": "«Доверился. Глупость и смелость»."}, "1": {"target_question": 9, "add_text": "«Разумно. Но одиноко»."}, "2": {"target_question": 9, "add_text": "«Знание — сила»."}}
}

DUNGEONS["ziggurat"] = {
    "name": "🏛️ Зиккурат Ложных Идолов",
    "phases": [
        {"name": "🔬 Лаборатория", "intro": "Подвал.", "questions": [
            {"text": "🔬 Дневник.", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Закрою", "soft": True}, {"text": "Осмотрюсь", "soft": False}], "bridges": {"same": "Ключ.", "soft": "Шорох.", "mixed": "Кто-то здесь."}},
            {"text": "🌀 Портал.", "options": [{"text": "Войду", "soft": False}, {"text": "Изучу", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Земля уходит.", "soft": "Ждёт.", "mixed": "Голос."}},
            {"text": "🌫️ Голос.", "options": [{"text": "Прислушаюсь", "soft": True}, {"text": "Отвернусь", "soft": False}, {"text": "Отвечу", "soft": False}], "bridges": {"same": "Открывается.", "soft": "«Не готов».", "mixed": "«Войди»."}}
        ]},
        {"name": "🌌 Странное небо", "intro": "Небо.", "questions": [
            {"text": "🌌 Звёзды.", "options": [{"text": "Любуюсь", "soft": True}, {"text": "Изучаю", "soft": False}, {"text": "Ищу знакомое", "soft": True}], "bridges": {"same": "Указывает путь.", "soft": "Останавливается.", "mixed": "Падает."}},
            {"text": "🗿 Статуи.", "options": [{"text": "Сломаю свою", "soft": True}, {"text": "Сломаю его", "soft": False}, {"text": "Мимо", "soft": True}], "bridges": {"same": "Рушатся.", "soft": "Исчезает.", "mixed": "Улыбается."}},
            {"text": "💔 Без лица.", "options": [{"text": "Оставлю себя", "soft": True}, {"text": "Оставлю его", "soft": False}, {"text": "Уйду вместе", "soft": True}], "bridges": {"same": "Тишина.", "soft": "Ничего.", "mixed": "«Поздно»."}},
            {"text": "🪞 Зеркало.", "options": [{"text": "Посмотрю", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Разобью", "soft": False}], "bridges": {"same": "Трескается.", "soft": "Гаснет.", "mixed": "Улыбается."}}
        ]},
        {"name": "👑 Зиккурат", "intro": "Зиккурат.", "questions": [
            {"text": "👑 Трон.", "options": [{"text": "Поднимусь", "soft": False}, {"text": "Откажусь", "soft": True}, {"text": "Обойду", "soft": True}], "bridges": {"same": "Рушится.", "soft": "Тишина.", "mixed": "Не отпустит."}},
            {"text": "🎭 Зеркала.", "options": [{"text": "Зайду", "soft": False}, {"text": "Мимо", "soft": True}, {"text": "Окликну", "soft": False}], "bridges": {"same": "На другой стороне.", "soft": "Поют.", "mixed": "Рука."}},
            {"text": "💀 «Ты — ложный идол».", "options": [{"text": "Соглашусь", "soft": True}, {"text": "Спорю", "soft": False}, {"text": "Засмеюсь", "soft": False}], "bridges": {"same": "Дрожит.", "soft": "Трескается.", "mixed": "Заваливает."}},
            {"text": "💥 Рушится.", "options": [{"text": "К трещине", "soft": True}, {"text": "Вглубь", "soft": False}, {"text": "Схвачу его и прыгну", "soft": True}], "bridges": {"same": "Выбрались.", "soft": "Тупик.", "mixed": "Воронка."}}
        ]}
    ],
    "flag_question": 1, "flag_options": ["Войду", "Изучу", "Спрошу напарника"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Смелость. Или глупость»."}, "1": {"target_question": 7, "add_text": "«Мудрость. Или страх»."}, "2": {"target_question": 7, "add_text": "«Не один. Важно»."}}
}

DUNGEONS["underwater"] = {
    "name": "🌊 Подводная сокровищница",
    "phases": [
        {"name": "🕳️ Пещера глубин", "intro": "Холод.", "questions": [
            {"text": "🕳️ Надпись.", "options": [{"text": "Войду", "soft": False}, {"text": "Поищу вход", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Дно.", "soft": "Ждёт.", "mixed": "Смотрит."}},
            {"text": "🐚 Ракушка.", "options": [{"text": "Возьму", "soft": True}, {"text": "Оставлю", "soft": False}, {"text": "Где дом?", "soft": False}], "bridges": {"same": "Тишина.", "soft": "Солёная.", "mixed": "«Ты дома»."}},
            {"text": "👤 Утопленник.", "options": [{"text": "Помогу", "soft": True}, {"text": "Опасно", "soft": False}, {"text": "Что оставил?", "soft": True}], "bridges": {"same": "Чище.", "soft": "Ждёт.", "mixed": "«Утонешь»."}}
        ]},
        {"name": "💧 Водопад Желаний", "intro": "Течёт вверх.", "questions": [
            {"text": "💧 Надпись.", "options": [{"text": "Для себя", "soft": False}, {"text": "Для напарника", "soft": True}, {"text": "Не буду", "soft": True}], "bridges": {"same": "Принято.", "soft": "Слушает.", "mixed": "«Все так говорят»."}},
            {"text": "🐟 Рыбы.", "options": [{"text": "Подпою", "soft": True}, {"text": "Заткну уши", "soft": False}, {"text": "Окликну", "soft": False}], "bridges": {"same": "В голове.", "soft": "Оборвалась.", "mixed": "Смотрит."}},
            {"text": "🔒 Сундук.", "options": [{"text": "Сломаю", "soft": False}, {"text": "Вскрою", "soft": True}, {"text": "Оставлю", "soft": True}], "bridges": {"same": "Пусто.", "soft": "Монета.", "mixed": "«Ты боишься»."}},
            {"text": "🌊 Течение.", "options": [{"text": "К берегу", "soft": True}, {"text": "Сам", "soft": False}, {"text": "Вглубь", "soft": False}], "bridges": {"same": "Близко.", "soft": "Живые.", "mixed": "Кто-то остался."}}
        ]},
        {"name": "👑 Сокровищница героев", "intro": "Портреты.", "questions": [
            {"text": "👑 Сокровища.", "options": [{"text": "Возьму", "soft": False}, {"text": "Не возьму", "soft": True}, {"text": "Рассмотрю", "soft": True}], "bridges": {"same": "Тускнеют.", "soft": "«Достойно».", "mixed": "Ждёт."}},
            {"text": "🗡️ Меч.", "options": [{"text": "Возьму", "soft": False}, {"text": "Откажусь", "soft": True}, {"text": "Кого помнит?", "soft": False}], "bridges": {"same": "Замолкает.", "soft": "Звон.", "mixed": "«Последним»."}},
            {"text": "💎 Алмаз.", "options": [{"text": "Возьму", "soft": False}, {"text": "Забыть", "soft": True}, {"text": "Что забыл?", "soft": True}], "bridges": {"same": "Не понимает.", "soft": "Память.", "mixed": "Закрыли глаза."}},
            {"text": "🌅 Выход.", "options": [{"text": "Правду", "soft": True}, {"text": "Совру", "soft": False}, {"text": "«Ничего»", "soft": True}], "bridges": {"same": "«Я тоже».", "soft": "«Спасибо».", "mixed": "«Врёшь»."}}
        ]}
    ],
    "flag_question": 2, "flag_options": ["Помогу", "Опасно", "Что оставил?"],
    "flag_effects": {"0": {"target_question": 10, "add_text": "«Он обрёл покой»."}, "1": {"target_question": 10, "add_text": "«Он ждал»."}, "2": {"target_question": 10, "add_text": "«Честно. Но не милосердно»."}}
}

DUNGEONS["coast"] = {
    "name": "🏝️ Скалистое побережье",
    "phases": [
        {"name": "🗼 Маяк Одиночества", "intro": "Маяк.", "questions": [
            {"text": "🗼 Записка.", "options": [{"text": "Поднимусь", "soft": False}, {"text": "Осмотрюсь", "soft": True}, {"text": "Вместе", "soft": True}], "bridges": {"same": "Ждут.", "soft": "«…бойся».", "mixed": "Шаги."}},
            {"text": "🔥 Смотритель.", "options": [{"text": "Соглашусь", "soft": True}, {"text": "Свет важен", "soft": False}, {"text": "Что видел?", "soft": False}], "bridges": {"same": "«Понял».", "soft": "Смотрит.", "mixed": "«Узнаешь»."}},
            {"text": "👁️ Движение.", "options": [{"text": "Подойду", "soft": False}, {"text": "Издалека", "soft": True}, {"text": "Крикну", "soft": False}], "bridges": {"same": "Волны.", "soft": "Тюлень.", "mixed": "Тень."}}
        ]},
        {"name": "🌅 Берег лучей", "intro": "Рассвет.", "questions": [
            {"text": "🌅 Всё красиво.", "options": [{"text": "Останусь", "soft": True}, {"text": "Дальше", "soft": False}, {"text": "Искупаюсь", "soft": True}], "bridges": {"same": "Видно дно.", "soft": "Дышите.", "mixed": "Тропа."}},
            {"text": "🐚 Ракушки.", "options": [{"text": "Открою", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Исчез.", "soft": "Песок.", "mixed": "«Ты слышал»."}},
            {"text": "⚓ Корабль.", "options": [{"text": "Поднимусь", "soft": False}, {"text": "Останусь", "soft": True}, {"text": "Обыщу берег", "soft": True}], "bridges": {"same": "Карта.", "soft": "Ждёт.", "mixed": "Пение."}},
            {"text": "⛈️ Буря.", "options": [{"text": "В укрытие", "soft": True}, {"text": "Посмотрю", "soft": False}, {"text": "Поищу укрытие", "soft": False}], "bridges": {"same": "Свет.", "soft": "Волны.", "mixed": "Сильнее."}}
        ]},
        {"name": "⚔️ Корабль орков", "intro": "Орки.", "questions": [
            {"text": "⚔️ Окружают.", "options": [{"text": "Оружие", "soft": False}, {"text": "На месте", "soft": True}, {"text": "Заговорю", "soft": True}], "bridges": {"same": "Вождь.", "soft": "Не нападают.", "mixed": "«Смельчаки»."}},
            {"text": "🤝 Пропустить.", "options": [{"text": "Пропущу", "soft": True}, {"text": "Откажусь", "soft": False}, {"text": "Куда идут?", "soft": False}], "bridges": {"same": "Мимо.", "soft": "«Мудро».", "mixed": "Ждут."}},
            {"text": "🗡️ Дуэль.", "options": [{"text": "Я", "soft": False}, {"text": "Напарник", "soft": False}, {"text": "Откажемся", "soft": True}], "bridges": {"same": "Честно.", "soft": "«Трусы. Живые».", "mixed": "Указывает."}},
            {"text": "💀 Убегают.", "options": [{"text": "Обернусь", "soft": False}, {"text": "К маяку", "soft": False}, {"text": "Замру", "soft": True}], "bridges": {"same": "Живы.", "soft": "Ничего.", "mixed": "Тишина."}}
        ]}
    ],
    "flag_question": 1, "flag_options": ["Соглашусь", "Свет важен", "Что видел?"],
    "flag_effects": {"0": {"target_question": 10, "add_text": "«Принял тьму. Готов»."}, "1": {"target_question": 10, "add_text": "«Есть за что бороться»."}, "2": {"target_question": 10, "add_text": "«Теперь знаешь»."}}
}

DUNGEONS["steam"] = {
    "name": "🚂 Паровое подземелье",
    "phases": [
        {"name": "🚂 Паровые тоннели", "intro": "Дверь.", "questions": [
            {"text": "🔧 Тоннель.", "options": [{"text": "На звук", "soft": False}, {"text": "Осмотрю", "soft": True}, {"text": "У входа", "soft": True}], "bridges": {"same": "Гудение.", "soft": "Кто-то рядом.", "mixed": "Туман."}},
            {"text": "🚪 Комната.", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Осмотрю", "soft": True}, {"text": "Закрою", "soft": True}], "bridges": {"same": "Пустые.", "soft": "Приятные.", "mixed": "Дом."}},
            {"text": "👤 Голос.", "options": [{"text": "Пойду", "soft": False}, {"text": "Стоп", "soft": True}, {"text": "Вместе", "soft": True}], "bridges": {"same": "Тишина.", "soft": "Стоите.", "mixed": "Испугался."}}
        ]},
        {"name": "🚇 Метро", "intro": "Платформа.", "questions": [
            {"text": "🚂 Поезд.", "options": [{"text": "Войду", "soft": False}, {"text": "Осмотрю", "soft": True}, {"text": "Дальше", "soft": True}], "bridges": {"same": "Дом.", "soft": "Нет номера.", "mixed": "Трогается."}},
            {"text": "🎵 Музыка.", "options": [{"text": "Войду", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Прислушаюсь", "soft": False}], "bridges": {"same": "Пусто.", "soft": "Оборвалась.", "mixed": "Детство."}},
            {"text": "🪞 Зеркало.", "options": [{"text": "Посмотрю", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Разобью", "soft": False}], "bridges": {"same": "Рука.", "soft": "Образ.", "mixed": "Трещины."}},
            {"text": "🚇 Уходит.", "options": [{"text": "Прыгну", "soft": False}, {"text": "Останусь", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Едете.", "soft": "Пусто.", "mixed": "Останавливается."}}
        ]},
        {"name": "🎈 Парящие платформы", "intro": "Зал.", "questions": [
            {"text": "🎭 Творец.", "options": [{"text": "Соглашусь", "soft": False}, {"text": "Откажусь", "soft": True}, {"text": "Что имеешь в виду?", "soft": False}], "bridges": {"same": "Улыбается.", "soft": "Смеётся.", "mixed": "Пар."}},
            {"text": "🌀 Видение.", "options": [{"text": "Останусь", "soft": False}, {"text": "Не настоящее", "soft": True}, {"text": "Подвох?", "soft": False}], "bridges": {"same": "Кулаки.", "soft": "Гудит.", "mixed": "Заметил."}},
            {"text": "⚔️ «Выбирайте».", "options": [{"text": "В иллюзию", "soft": False}, {"text": "Искать выход", "soft": True}, {"text": "Пусть напарник", "soft": True}], "bridges": {"same": "Свет.", "soft": "Удушливый.", "mixed": "Отступает."}},
            {"text": "💥 Атака.", "options": [{"text": "Сосредоточусь", "soft": True}, {"text": "Сломаю пульт", "soft": False}, {"text": "Трубы", "soft": False}], "bridges": {"same": "Взрывы.", "soft": "Искры.", "mixed": "Пар."}}
        ]}
    ],
    "flag_question": 4, "flag_options": ["Войду", "Отвернусь", "Прислушаюсь"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Музыка в тебе. Навсегда»."}, "1": {"target_question": 7, "add_text": "«Ты сильнее»."}, "2": {"target_question": 7, "add_text": "«Боишься мечты»."}}
}

DUNGEONS["city"] = {
    "name": "🏙️ Загадочный город",
    "phases": [
        {"name": "🔮 Телепорт", "intro": "Арка.", "questions": [
            {"text": "🌀 Площадь.", "options": [{"text": "Осмотрюсь", "soft": True}, {"text": "Вперёд", "soft": False}, {"text": "К арке", "soft": False}], "bridges": {"same": "Нет пути.", "soft": "Взгляд.", "mixed": "Один."}},
            {"text": "🏛️ Дома.", "options": [{"text": "Постучу", "soft": False}, {"text": "Обойду", "soft": True}, {"text": "Подожду", "soft": True}], "bridges": {"same": "Тишина.", "soft": "Переулок.", "mixed": "Свет."}},
            {"text": "👤 Фигура.", "options": [{"text": "Что имеешь в виду?", "soft": False}, {"text": "Дальше", "soft": False}, {"text": "Позову напарника", "soft": True}], "bridges": {"same": "«Не готов».", "soft": "Смеётся.", "mixed": "Отступает."}}
        ]},
        {"name": "🚪 Врата загадок", "intro": "Врата.", "questions": [
            {"text": "🚪 Чаша.", "options": [{"text": "Опущу руку", "soft": False}, {"text": "Откажусь", "soft": True}, {"text": "Загляну", "soft": True}], "bridges": {"same": "Не двигается.", "soft": "Испаряется.", "mixed": "Образ."}},
            {"text": "🏛️ Фрески.", "options": [{"text": "Рассмотрю", "soft": True}, {"text": "Мимо", "soft": False}, {"text": "Поищу себя", "soft": False}], "bridges": {"same": "Пусто.", "soft": "Гаснут.", "mixed": "Другой."}},
            {"text": "🪞 Зеркало.", "options": [{"text": "Посмотрю", "soft": False}, {"text": "Отвернусь", "soft": True}, {"text": "Разобью", "soft": False}], "bridges": {"same": "Горит.", "soft": "Тускнеет.", "mixed": "Старше."}},
            {"text": "🔔 Колокол.", "options": [{"text": "Ударю", "soft": False}, {"text": "Мимо", "soft": True}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "Слова.", "soft": "Обиделся.", "mixed": "Дважды."}}
        ]},
        {"name": "🎡 Площадь чудес", "intro": "Фонтан.", "questions": [
            {"text": "🎡 Люди.", "options": [{"text": "Подойду", "soft": False}, {"text": "Понаблюдаю", "soft": True}, {"text": "Кто они?", "soft": False}], "bridges": {"same": "Ярче.", "soft": "Не было.", "mixed": "«Остались»."}},
            {"text": "🌟 Сияющая.", "options": [{"text": "Останусь", "soft": False}, {"text": "Вернусь", "soft": True}, {"text": "Если откажусь?", "soft": False}], "bridges": {"same": "Тускнеет.", "soft": "Отступает.", "mixed": "«Силой»."}},
            {"text": "🌀 «Забыть или помнить?»", "options": [{"text": "Забуду", "soft": True}, {"text": "Помнить", "soft": False}, {"text": "Пусть напарник", "soft": True}], "bridges": {"same": "Не помните.", "soft": "Несите.", "mixed": "Вместе."}},
            {"text": "💥 Рушится.", "options": [{"text": "Закрою глаза", "soft": True}, {"text": "Бороться", "soft": False}, {"text": "Схвачу напарника", "soft": True}], "bridges": {"same": "Проснулись.", "soft": "Помните.", "mixed": "Вдвоём."}}
        ]}
    ],
    "flag_question": 0, "flag_options": ["Осмотрюсь", "Вперёд", "К арке"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Мудрость. Или страх»."}, "1": {"target_question": 7, "add_text": "«Смелость. Или глупость»."}, "2": {"target_question": 7, "add_text": "«Твой выбор»."}}
}

DUNGEONS["volcano"] = {
    "name": "🌋 Вулкан волнений",
    "phases": [
        {"name": "🥾 Тропа на вершину", "intro": "Вулкан.", "questions": [
            {"text": "🌲 Лес.", "options": [{"text": "Напролом", "soft": False}, {"text": "Обход", "soft": True}, {"text": "На дерево", "soft": False}], "bridges": {"same": "Наблюдает.", "soft": "Шаги.", "mixed": "Другая группа."}},
            {"text": "⚔️ Приключенцы.", "options": [{"text": "Отступлю", "soft": True}, {"text": "Вместе или никто", "soft": False}, {"text": "Обойду", "soft": True}], "bridges": {"same": "Смотрят вслед.", "soft": "«Не отставайте».", "mixed": "Не последняя."}},
            {"text": "🪨 Обрыв.", "options": [{"text": "Первым", "soft": False}, {"text": "Шаг в шаг", "soft": True}, {"text": "Подожду", "soft": True}], "bridges": {"same": "Держит.", "soft": "Осыпается.", "mixed": "Ветер."}}
        ]},
        {"name": "🔥 Раскалённые уступы", "intro": "Вершина.", "questions": [
            {"text": "🔥 Жерло.", "options": [{"text": "По уступам", "soft": True}, {"text": "По верёвке", "soft": False}, {"text": "Другой спуск", "soft": False}], "bridges": {"same": "Дышит.", "soft": "Быстро.", "mixed": "Нет."}},
            {"text": "🪨 Обвал.", "options": [{"text": "Прыгну", "soft": False}, {"text": "На месте", "soft": True}, {"text": "В трещину", "soft": True}], "bridges": {"same": "Живы.", "soft": "Прошли.", "mixed": "Бьют."}},
            {"text": "🏕️ Лагерь.", "options": [{"text": "Прочитаю", "soft": False}, {"text": "Осмотрю", "soft": True}, {"text": "Оставлю", "soft": True}], "bridges": {"same": "Тишина.", "soft": "Карта.", "mixed": "«Ждёт ответа»."}},
            {"text": "🌫️ Карниз.", "options": [{"text": "Первым", "soft": False}, {"text": "Вместе", "soft": True}, {"text": "Отступлю", "soft": True}], "bridges": {"same": "Держит.", "soft": "Помогает.", "mixed": "Рушится."}}
        ]},
        {"name": "🌋 Лавовое озеро", "intro": "Озеро.", "questions": [
            {"text": "🌋 Элементал.", "options": [{"text": "Кто он?", "soft": True}, {"text": "Промолчу", "soft": True}, {"text": "Почему проснулся?", "soft": False}], "bridges": {"same": "Усталость.", "soft": "«Мир громче».", "mixed": "«Надоели»."}},
            {"text": "🔥 «Мир полон боли».", "options": [{"text": "О хорошем", "soft": True}, {"text": "Логика", "soft": False}, {"text": "Показать нас", "soft": True}], "bridges": {"same": "Тускнеет.", "soft": "Слушает.", "mixed": "Внимательнее."}},
            {"text": "⚔️ Маг.", "options": [{"text": "Остановить", "soft": True}, {"text": "Отступлю", "soft": False}, {"text": "Спрошу напарника", "soft": True}], "bridges": {"same": "«Пеняйте на себя».", "soft": "Светится.", "mixed": "«Минута»."}},
            {"text": "💥 Ритуал.", "options": [{"text": "Разорву руны", "soft": True}, {"text": "К выходу", "soft": False}, {"text": "Крикнуть ему", "soft": True}], "bridges": {"same": "Стираете.", "soft": "Грохот.", "mixed": "Уходит."}}
        ]}
    ],
    "flag_question": 1, "flag_options": ["Отступлю", "Вместе или никто", "Обойду"],
    "flag_effects": {"0": {"target_question": 7, "add_text": "«Мудро. Но без славы»."}, "1": {"target_question": 7, "add_text": "«Достойно»."}, "2": {"target_question": 7, "add_text": "«Хитро. И одиноко»."}}
}
# ========== ВЕБ-СЕРВЕР И ЗАПУСК ==========
async def health_check(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    logging.info("Бот запускается…")
    asyncio.create_task(start_web_server())
    asyncio.create_task(timeout_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен")
