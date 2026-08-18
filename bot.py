#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HR-бот для анонимного Pulse-опроса сотрудников
Оценка лояльности (eNPS) и вовлеченности
Все ответы анонимны и доступны только админу
"""

import sqlite3
import random
import time
import json
import logging
from datetime import datetime, timedelta
import os
import sys

try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware
    from aiogram.types import (
        InlineKeyboardMarkup, InlineKeyboardButton, 
        ReplyKeyboardMarkup, KeyboardButton, 
        ReplyKeyboardRemove
    )
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
except ImportError:
    os.system("pip install aiogram==2.25.1")
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware
    from aiogram.types import (
        InlineKeyboardMarkup, InlineKeyboardButton, 
        ReplyKeyboardMarkup, KeyboardButton, 
        ReplyKeyboardRemove
    )
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMINS = [1024761707

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ===================== СОСТОЯНИЯ =====================
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_department = State()
    waiting_for_position = State()
    waiting_for_phone = State()

class SurveyStates(StatesGroup):
    answering = State()
    waiting_for_comment = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_edit_save = State()
    waiting_for_question_delete = State()
    waiting_for_admin_add = State()
    waiting_for_feedback = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._create_indexes()
    
    def _create_tables(self):
        # Сотрудники (личные данные)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                department TEXT,
                position TEXT,
                phone TEXT,
                registered_at TEXT,
                is_admin INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_active TEXT
            )
        ''')
        
        # Вопросы для пульс-опроса
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                category TEXT DEFAULT 'Лояльность',
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        ''')
        
        # Ответы на пульс-опрос (АНОНИМНЫЕ - без user_id!)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                answer_score INTEGER,
                comment TEXT,
                date TEXT,
                department TEXT,
                user_hash TEXT
            )
        ''')
        
        # Для отслеживания, кто уже прошел опрос (без привязки к ответам)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_participants (
                user_id INTEGER PRIMARY KEY,
                last_survey_date TEXT,
                survey_hash TEXT
            )
        ''')
        
        # Активные опросы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_surveys (
                user_id INTEGER PRIMARY KEY,
                questions TEXT,
                current_index INTEGER,
                total_answered INTEGER,
                start_time INTEGER,
                answers TEXT
            )
        ''')
        
        # Обратная связь (анонимная)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                rating INTEGER,
                date TEXT,
                department TEXT,
                status TEXT DEFAULT 'new'
            )
        ''')
        self.conn.commit()
    
    def _create_indexes(self):
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_answers_date ON survey_answers(date)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_answers_dept ON survey_answers(department)')
        self.conn.commit()
    
    # ---- Сотрудники ----
    def register_employee(self, user_id, full_name, department, position, phone=None):
        self.cursor.execute('''
            INSERT OR REPLACE INTO employees 
            (user_id, full_name, department, position, phone, registered_at, last_active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, full_name, department, position, phone, datetime.now().isoformat(), datetime.now().isoformat()))
        self.conn.commit()
        return True
    
    def is_admin(self, user_id):
        self.cursor.execute('SELECT is_admin FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result is not None and result[0] == 1
    
    def is_registered(self, user_id):
        self.cursor.execute('SELECT user_id FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_employee(self, user_id):
        self.cursor.execute('SELECT * FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()
    
    def get_all_employees(self):
        self.cursor.execute('''
            SELECT user_id, full_name, department, position, phone, is_active 
            FROM employees ORDER BY full_name
        ''')
        return self.cursor.fetchall()
    
    def set_admin(self, user_id, is_admin=True):
        self.cursor.execute('UPDATE employees SET is_admin = ? WHERE user_id = ?', (1 if is_admin else 0, user_id))
        self.conn.commit()
    
    def update_active_status(self, user_id):
        self.cursor.execute('UPDATE employees SET last_active = ? WHERE user_id = ?', 
                           (datetime.now().isoformat(), user_id))
        self.conn.commit()
    
    def get_employee_department(self, user_id):
        self.cursor.execute('SELECT department FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    # ---- Вопросы для опроса ----
    def add_survey_question(self, question_text, category="Лояльность"):
        self.cursor.execute('''
            INSERT INTO survey_questions (question_text, category, created_at)
            VALUES (?, ?, ?)
        ''', (question_text, category, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_all_survey_questions(self):
        self.cursor.execute('SELECT * FROM survey_questions WHERE is_active = 1 ORDER BY id')
        return self.cursor.fetchall()
    
    def get_question_by_id(self, question_id):
        self.cursor.execute('SELECT * FROM survey_questions WHERE id = ?', (question_id,))
        return self.cursor.fetchone()
    
    def update_question(self, question_id, question_text, category):
        self.cursor.execute('''
            UPDATE survey_questions SET question_text = ?, category = ?
            WHERE id = ?
        ''', (question_text, category, question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('UPDATE survey_questions SET is_active = 0 WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def count_questions(self):
        self.cursor.execute('SELECT COUNT(*) FROM survey_questions WHERE is_active = 1')
        return self.cursor.fetchone()[0]
    
    # ---- Анонимные ответы ----
    def save_anonymous_answer(self, question_id, answer_score, comment, department, user_hash):
        self.cursor.execute('''
            INSERT INTO survey_answers (question_id, answer_score, comment, date, department, user_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (question_id, answer_score, comment, datetime.now().isoformat(), department, user_hash))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def mark_participant(self, user_id, survey_hash):
        self.cursor.execute('''
            INSERT OR REPLACE INTO survey_participants (user_id, last_survey_date, survey_hash)
            VALUES (?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), survey_hash))
        self.conn.commit()
    
    def has_participated(self, user_id):
        self.cursor.execute('SELECT user_id FROM survey_participants WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_anonymous_stats(self):
        """Получение анонимной статистики для админа"""
        # Общая статистика
        self.cursor.execute('''
            SELECT 
                COUNT(*) as total_answers,
                AVG(answer_score) as avg_score,
                MIN(answer_score) as min_score,
                MAX(answer_score) as max_score,
                COUNT(DISTINCT department) as dept_count
            FROM survey_answers
        ''')
        general = self.cursor.fetchone()
        
        # Распределение по оценкам
        self.cursor.execute('''
            SELECT answer_score, COUNT(*) as count
            FROM survey_answers
            GROUP BY answer_score
            ORDER BY answer_score
        ''')
        distribution = self.cursor.fetchall()
        
        # По отделам
        self.cursor.execute('''
            SELECT department, COUNT(*) as count, AVG(answer_score) as avg_score
            FROM survey_answers
            GROUP BY department
            ORDER BY avg_score DESC
        ''')
        by_department = self.cursor.fetchall()
        
        # Комментарии
        self.cursor.execute('''
            SELECT comment, date, department
            FROM survey_answers
            WHERE comment IS NOT NULL AND comment != ''
            ORDER BY date DESC
            LIMIT 20
        ''')
        comments = self.cursor.fetchall()
        
        return general, distribution, by_department, comments
    
    # ---- Активные опросы ----
    def save_active_survey(self, user_id, question_ids, current_index, total_answered, start_time, answers):
        self.cursor.execute('''
            INSERT OR REPLACE INTO active_surveys (user_id, questions, current_index, total_answered, start_time, answers)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, json.dumps(question_ids), current_index, total_answered, start_time, json.dumps(answers)))
        self.conn.commit()
    
    def get_active_survey(self, user_id):
        self.cursor.execute('SELECT questions, current_index, total_answered, start_time, answers FROM active_surveys WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return json.loads(result[0]), result[1], result[2], result[3], json.loads(result[4])
        return None, 0, 0, None, None
    
    def clear_active_survey(self, user_id):
        self.cursor.execute('DELETE FROM active_surveys WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    # ---- Обратная связь (анонимная) ----
    def save_anonymous_feedback(self, text, rating, department):
        self.cursor.execute('''
            INSERT INTO feedback (text, rating, date, department)
            VALUES (?, ?, ?, ?)
        ''', (text, rating, datetime.now().isoformat(), department))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_all_feedback(self):
        self.cursor.execute('''
            SELECT id, text, rating, date, department, status
            FROM feedback
            ORDER BY date DESC
            LIMIT 50
        ''')
        return self.cursor.fetchall()

# ===================== БАЗА ДАННЫХ =====================
db = Database()

# ===================== ВОПРОСЫ ДЛЯ PULSE-ОПРОСА =====================
def init_survey_questions():
    if db.count_questions() > 0:
        return
    
    questions = [
        "Насколько вы удовлетворены своей работой в компании? (1-10)",
        "Как вы оцениваете уровень поддержки со стороны руководства? (1-10)",
        "Насколько вы чувствуете себя вовлеченным в жизнь компании? (1-10)",
        "Как вы оцениваете возможности для профессионального роста? (1-10)",
        "Насколько вы довольны уровнем заработной платы? (1-10)",
        "Как вы оцениваете атмосферу в коллективе? (1-10)",
        "Насколько вы довольны условиями труда? (1-10)",
        "Как вы оцениваете баланс между работой и личной жизнью? (1-10)",
        "Насколько вы гордитесь тем, что работаете в нашей компании? (1-10)",
        "Порекомендовали бы вы нашу компанию как место работы друзьям? (1-10)"
    ]
    
    for q in questions:
        db.add_survey_question(q, "Лояльность")
    
    logging.info(f"✅ Добавлено {len(questions)} вопросов для Pulse-опроса")

# ===================== КЛАВИАТУРЫ =====================
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📝 Пройти опрос"),
        KeyboardButton("📊 Статистика")
    )
    keyboard.add(
        KeyboardButton("💬 Анонимный отзыв"),
        KeyboardButton("ℹ️ Помощь")
    )
    
    if db.is_admin(user_id):
        keyboard.add(KeyboardButton("⚙️ Админ-панель"))
    
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📢 Рассылка"),
        KeyboardButton("➕ Добавить вопрос")
    )
    keyboard.add(
        KeyboardButton("✏️ Редактировать вопрос"),
        KeyboardButton("❌ Удалить вопрос")
    )
    keyboard.add(
        KeyboardButton("👥 Сотрудники"),
        KeyboardButton("📊 Анонимная статистика")
    )
    keyboard.add(
        KeyboardButton("👑 Назначить админа"),
        KeyboardButton("💬 Отзывы")
    )
    keyboard.add(KeyboardButton("🔙 Главное меню"))
    return keyboard

def get_rating_keyboard(question_id):
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(1, 11):
        emoji = "🔴" if i <= 3 else "🟡" if i <= 7 else "🟢"
        buttons.append(InlineKeyboardButton(f"{emoji} {i}", callback_data=f"rate_{i}_{question_id}"))
    
    for i in range(0, len(buttons), 5):
        keyboard.add(*buttons[i:i+5])
    
    return keyboard

# ===================== ОБРАБОТЧИКИ =====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    
    if not db.is_registered(user_id):
        await message.answer(
            "🌟 *Добро пожаловать в систему Pulse-опроса!*\n\n"
            "Здесь вы можете анонимно оценить свою удовлетворенность работой.\n\n"
            "📌 *Важно:*\n"
            "✅ Все ответы полностью анонимны\n"
            "✅ Данные видны только HR-отделу\n"
            "✅ Опрос занимает 2-3 минуты\n\n"
            "Для начала заполните анкету:",
            parse_mode="Markdown"
        )
        await message.answer("👤 Введите ваше *полное имя* (ФИО):", parse_mode="Markdown")
        await RegistrationStates.waiting_for_name.set()
    else:
        db.update_active_status(user_id)
        employee = db.get_employee(user_id)
        
        await message.answer(
            f"👋 *С возвращением, {employee[1]}!*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )

# ===================== РЕГИСТРАЦИЯ =====================
@dp.message_handler(state=RegistrationStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("🏢 Введите ваш *отдел*:", parse_mode="Markdown")
    await RegistrationStates.waiting_for_department.set()

@dp.message_handler(state=RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await message.answer("💼 Введите вашу *должность*:", parse_mode="Markdown")
    await RegistrationStates.waiting_for_position.set()

@dp.message_handler(state=RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await message.answer("📱 *Поделитесь контактом* (или нажмите 'Пропустить'):", 
                        parse_mode="Markdown",
                        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                            KeyboardButton("📱 Поделиться контактом", request_contact=True),
                            KeyboardButton("⏭ Пропустить")
                        ))
    await RegistrationStates.waiting_for_phone.set()

@dp.message_handler(content_types=['contact'], state=RegistrationStates.waiting_for_phone)
async def process_phone_contact(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number
    data = await state.get_data()
    
    db.register_employee(
        message.from_user.id,
        data['full_name'],
        data['department'],
        data['position'],
        phone
    )
    
    await state.finish()
    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"👤 {data['full_name']}\n"
        f"🏢 {data['department']}\n"
        f"💼 {data['position']}\n\n"
        "Теперь вы можете пройти анонимный опрос!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message_handler(state=RegistrationStates.waiting_for_phone)
async def process_phone_skip(message: types.Message, state: FSMContext):
    if message.text == "⏭ Пропустить":
        data = await state.get_data()
        db.register_employee(
            message.from_user.id,
            data['full_name'],
            data['department'],
            data['position']
        )
        
        await state.finish()
        await message.answer(
            f"✅ *Регистрация завершена!*\n\n"
            f"👤 {data['full_name']}\n"
            f"🏢 {data['department']}\n"
            f"💼 {data['position']}\n\n"
            "Теперь вы можете пройти анонимный опрос!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(message.from_user.id)
        )
    else:
        await message.answer("Используйте кнопку 'Поделиться контактом' или 'Пропустить'.")

# ===================== ГЛАВНОЕ МЕНЮ =====================
@dp.message_handler(lambda message: message.text in [
    "📝 Пройти опрос", "📊 Статистика", "💬 Анонимный отзыв",
    "ℹ️ Помощь", "⚙️ Админ-панель"
])
async def handle_menu(message: types.Message):
    user_id = message.from_user.id
    
    if message.text == "📝 Пройти опрос":
        await start_survey(message, user_id)
    
    elif message.text == "📊 Статистика":
        await show_user_stats(message, user_id)
    
    elif message.text == "💬 Анонимный отзыв":
        await message.answer(
            "💬 *Анонимный отзыв*\n\n"
            "Напишите ваши пожелания, идеи или замечания.\n"
            "Ваше сообщение будет полностью анонимным!",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_feedback.set()
    
    elif message.text == "ℹ️ Помощь":
        await message.answer(
            "ℹ️ *Помощь*\n\n"
            "📝 *Пройти опрос* - анонимная оценка лояльности (10 вопросов)\n"
            "📊 *Статистика* - ваша личная статистика участия\n"
            "💬 *Анонимный отзыв* - оставить анонимное сообщение\n"
            "⚙️ *Админ-панель* - управление опросом (только для HR)\n\n"
            "Все ответы полностью анонимны! 🕵️",
            parse_mode="Markdown"
        )
    
    elif message.text == "⚙️ Админ-панель":
        if db.is_admin(user_id):
            await message.answer(
                "⚙️ *Панель администратора*\n\n"
                "Управление анонимным Pulse-опросом:",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer("⛔ У вас нет прав администратора.")

# ===================== АНОНИМНЫЙ ОТЗЫВ =====================
@dp.message_handler(state=AdminStates.waiting_for_feedback)
async def process_feedback(message: types.Message, state: FSMContext):
    department = db.get_employee_department(message.from_user.id) or "Не указан"
    
    db.save_anonymous_feedback(
        message.text,
        rating=0,
        department=department
    )
    
    await state.finish()
    await message.answer(
        "✅ *Спасибо за ваш анонимный отзыв!* 🙌\n\n"
        "Ваше мнение поможет нам стать лучше.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ===================== ОПРОС =====================
async def start_survey(message: types.Message, user_id):
    if db.count_questions() == 0:
        await message.answer("❌ Вопросы для опроса еще не загружены.")
        return
    
    # Проверяем, участвовал ли уже сегодня
    if db.has_participated(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Пройти заново", callback_data="restart_survey"),
            InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu")
        )
        await message.answer(
            "⚠️ *Вы уже проходили опрос*\n\n"
            "Хотите пройти его заново?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    # Проверяем незавершенный опрос
    questions, current_index, total_answered, start_time, answers = db.get_active_survey(user_id)
    
    if questions and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_survey"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="restart_survey")
        )
        await message.answer("⏳ У вас есть незавершенный опрос.", reply_markup=keyboard)
        return
    
    # Начинаем новый опрос
    all_questions = db.get_all_survey_questions()
    
    await message.answer(
        "📝 *Анонимный Pulse-опрос*\n\n"
        "Оцените каждый вопрос по шкале от 1 до 10:\n"
        "🔴 1-3 - Неудовлетворен\n"
        "🟡 4-7 - Частично удовлетворен\n"
        "🟢 8-10 - Полностью удовлетворен\n\n"
        "Все ответы анонимны! 🕵️",
        parse_mode="Markdown"
    )
    
    question_ids = [q[0] for q in all_questions]
    db.save_active_survey(user_id, question_ids, 0, 0, int(time.time()), [])
    await send_survey_question(message, user_id, 0)

async def send_survey_question(message: types.Message, user_id, index):
    questions, current_index, total_answered, start_time, answers = db.get_active_survey(user_id)
    
    if not questions or index >= len(questions):
        await finish_survey(message, user_id)
        return
    
    question_id = questions[index]
    question = db.get_question_by_id(question_id)
    
    if not question:
        await message.answer("❌ Ошибка загрузки вопроса.")
        return
    
    text = f"📝 *Вопрос {index + 1} из {len(questions)}*\n\n"
    text += f"*{question[1]}*\n\n"
    text += "Оцените от 1 до 10:"
    
    keyboard = get_rating_keyboard(question_id)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('rate_'))
async def handle_survey_answer(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    rating = int(data[1])
    question_id = int(data[2])
    
    questions, current_index, total_answered, start_time, answers = db.get_active_survey(user_id)
    
    if not questions:
        await callback_query.answer("❌ Опрос не найден")
        return
    
    # Сохраняем ответ
    answers.append({
        'question_id': question_id,
        'rating': rating,
        'timestamp': time.time()
    })
    
    current_index += 1
    total_answered += 1
    
    db.save_active_survey(user_id, questions, current_index, total_answered, start_time, answers)
    
    # Показываем подтверждение
    await callback_query.answer(f"✅ Оценка {rating} сохранена")
    
    # Показываем следующий вопрос или завершаем
    if current_index >= len(questions):
        await finish_survey(callback_query.message, user_id)
    else:
        await callback_query.message.delete()
        await send_survey_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'continue_survey')
async def continue_survey(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    questions, current_index, total_answered, start_time, answers = db.get_active_survey(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await send_survey_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'restart_survey')
async def restart_survey(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    db.clear_active_survey(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await start_survey(callback_query.message, user_id)

@dp.callback_query_handler(lambda c: c.data == 'back_to_menu')
async def back_to_menu_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    await callback_query.message.delete()
    await callback_query.message.answer(
        "🔙 Возврат в меню",
        reply_markup=get_main_keyboard(user_id)
    )

async def finish_survey(message: types.Message, user_id):
    questions, current_index, total_answered, start_time, answers = db.get_active_survey(user_id)
    
    if not answers or total_answered == 0:
        await message.answer("❌ Опрос не был начат.")
        return
    
    # Сохраняем анонимные ответы
    department = db.get_employee_department(user_id) or "Не указан"
    
    # Генерируем анонимный хэш для этого опроса
    import hashlib
    survey_hash = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]
    
    for answer in answers:
        db.save_anonymous_answer(
            answer['question_id'],
            answer['rating'],
            "",  # Комментарий пока пустой
            department,
            survey_hash
        )
    
    # Отмечаем, что пользователь прошел опрос
    db.mark_participant(user_id, survey_hash)
    db.clear_active_survey(user_id)
    
    # Рассчитываем средний балл
    total_score = sum(a['rating'] for a in answers)
    avg_score = total_score / len(answers)
    
    # Определяем уровень лояльности
    if avg_score >= 8:
        level = "🟢 Высокий уровень лояльности!"
        emoji = "🌟"
    elif avg_score >= 5:
        level = "🟡 Средний уровень лояльности"
        emoji = "📊"
    else:
        level = "🔴 Низкий уровень лояльности. Мы работаем над улучшением!"
        emoji = "💪"
    
    await message.answer(
        f"✅ *Опрос завершен!*\n\n"
        f"{emoji} {level}\n\n"
        f"📊 Ваш средний балл: {avg_score:.1f}/10\n"
        f"📝 Всего вопросов: {len(answers)}\n\n"
        "Спасибо за участие! Ваше мнение важно для нас. 🙌\n\n"
        "Все ответы полностью анонимны! 🕵️",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

# ===================== СТАТИСТИКА =====================
async def show_user_stats(message: types.Message, user_id):
    if db.has_participated(user_id):
        await message.answer(
            "📊 *Ваша статистика*\n\n"
            "✅ Вы уже прошли анонимный опрос.\n"
            "Спасибо за ваше участие! 🙌\n\n"
            "Все ответы полностью анонимны 🕵️",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "📊 *Статистика*\n\n"
            "Вы еще не проходили опрос.\n"
            "Нажмите '📝 Пройти опрос', чтобы принять участие.",
            parse_mode="Markdown"
        )

# ===================== АДМИН-ПАНЕЛЬ =====================
@dp.message_handler(lambda message: message.text in [
    "📢 Рассылка", "➕ Добавить вопрос", "✏️ Редактировать вопрос",
    "❌ Удалить вопрос", "👥 Сотрудники", "📊 Анонимная статистика",
    "👑 Назначить админа", "💬 Отзывы", "🔙 Главное меню"
])
async def handle_admin_buttons(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    if message.text == "🔙 Главное меню":
        await message.answer("🔙 Возврат", reply_markup=get_main_keyboard(user_id))
    
    elif message.text == "📢 Рассылка":
        await message.answer("📢 Введите текст для рассылки всем сотрудникам:")
        await AdminStates.waiting_for_broadcast.set()
    
    elif message.text == "➕ Добавить вопрос":
        await message.answer(
            "📝 *Добавление вопроса для Pulse-опроса*\n\n"
            "Введите текст вопроса:",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_question_add.set()
    
    elif message.text == "✏️ Редактировать вопрос":
        questions = db.get_all_survey_questions()
        if not questions:
            await message.answer("❌ Вопросов нет.")
            return
        
        text = "✏️ *Выберите вопрос для редактирования*\n\n"
        for q in questions[:15]:
            text += f"ID: {q[0]}. {q[1][:50]}...\n"
        text += "\nВведите ID вопроса:"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_question_edit.set()
    
    elif message.text == "❌ Удалить вопрос":
        questions = db.get_all_survey_questions()
        if not questions:
            await message.answer("❌ Вопросов нет.")
            return
        
        text = "❌ *Удаление вопроса*\n\n"
        for q in questions[:15]:
            text += f"ID: {q[0]}. {q[1][:50]}...\n"
        text += "\nВведите ID вопроса для удаления:"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_question_delete.set()
    
    elif message.text == "👥 Сотрудники":
        employees = db.get_all_employees()
        if not employees:
            await message.answer("👥 Нет сотрудников.")
            return
        
        text = "👥 *Список сотрудников*\n\n"
        for user_id, name, dept, pos, phone, active in employees:
            status = "🟢" if active else "🔴"
            text += f"{status} *{name}*\n"
            text += f"   📊 {dept} | {pos}\n"
            if phone:
                text += f"   📱 {phone}\n"
            text += "\n"
        
        await message.answer(text, parse_mode="Markdown")
    
    elif message.text == "📊 Анонимная статистика":
        general, distribution, by_department, comments = db.get_anonymous_stats()
        
        text = "📊 *Анонимная статистика Pulse-опроса*\n"
        text += "*Все данные анонимны*\n\n"
        
        if general:
            text += f"📝 Всего ответов: {general[0] or 0}\n"
            text += f"📈 Средний балл: {general[1] or 0:.1f}/10\n"
            text += f"📉 Минимальный балл: {general[2] or 0}\n"
            text += f"📈 Максимальный балл: {general[3] or 0}\n"
            text += f"🏢 Отделов: {general[4] or 0}\n\n"
        
        # Распределение оценок
        if distribution:
            text += "📊 *Распределение оценок:*\n"
            for score, count in distribution:
                bar = "█" * min(count, 20)
                text += f"{score} баллов: {bar} ({count})\n"
            text += "\n"
        
        # По отделам
        if by_department:
            text += "🏢 *По отделам:*\n"
            for dept, count, avg_score in by_department:
                text += f"📊 {dept}: {avg_score:.1f}/10 ({count} ответов)\n"
            text += "\n"
        
        # Комментарии
        if comments:
            text += "💬 *Анонимные комментарии:*\n\n"
            for comment, date, dept in comments[:10]:
                d = datetime.fromisoformat(date).strftime("%d.%m %H:%M")
                text += f"📝 {comment[:200]}\n"
                text += f"   🏢 {dept} | 🕐 {d}\n\n"
        
        await message.answer(text, parse_mode="Markdown")
    
    elif message.text == "👑 Назначить админа":
        employees = db.get_all_employees()
        text = "👑 *Назначение администратора*\n\nВведите ID пользователя:\n\n"
        for user_id, name, dept, pos, phone, active in employees[:10]:
            is_admin = db.is_admin(user_id)
            status = "✅ Админ" if is_admin else "👤 Сотрудник"
            text += f"ID: `{user_id}` | {name} | {status}\n"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_admin_add.set()
    
    elif message.text == "💬 Отзывы":
        feedbacks = db.get_all_feedback()
        if not feedbacks:
            await message.answer("💬 Нет отзывов.")
            return
        
        text = "💬 *Анонимные отзывы*\n\n"
        for fb in feedbacks[:20]:
            date = datetime.fromisoformat(fb[3]).strftime("%d.%m %H:%M")
            text += f"📝 {fb[1][:200]}\n"
            text += f"   🏢 {fb[4]} | 🕐 {date}\n\n"
        
        await message.answer(text, parse_mode="Markdown")

# ===================== АДМИН: РАССЫЛКА =====================
@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    employees = db.get_all_employees()
    sent = 0
    
    for user_id, name, dept, pos, phone, active in employees:
        if active:
            try:
                await bot.send_message(
                    user_id,
                    f"📢 *Объявление HR-отдела*\n\n{message.text}",
                    parse_mode="Markdown"
                )
                sent += 1
            except:
                pass
    
    await state.finish()
    await message.answer(f"✅ Рассылка отправлена {sent} сотрудникам.", reply_markup=get_admin_keyboard())

# ===================== АДМИН: ВОПРОСЫ =====================
@dp.message_handler(state=AdminStates.waiting_for_question_add)
async def process_add_question(message: types.Message, state: FSMContext):
    db.add_survey_question(message.text)
    await state.finish()
    await message.answer("✅ Вопрос добавлен!", reply_markup=get_admin_keyboard())

@dp.message_handler(state=AdminStates.waiting_for_question_edit)
async def process_edit_question(message: types.Message, state: FSMContext):
    try:
        question_id = int(message.text.strip())
        question = db.get_question_by_id(question_id)
        if not question:
            await message.answer("❌ Вопрос не найден.")
            return
        
        await state.update_data(edit_id=question_id)
        await message.answer(
            f"✏️ *Редактирование #{question_id}*\n\n"
            f"Текущий текст: {question[1]}\n\n"
            "Введите новый текст вопроса:",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_question_edit_save.set()
    except:
        await message.answer("❌ Введите число (ID вопроса).")

@dp.message_handler(state=AdminStates.waiting_for_question_edit_save)
async def process_edit_question_save(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        question_id = data.get('edit_id')
        
        db.update_question(question_id, message.text, "Лояльность")
        await state.finish()
        await message.answer("✅ Вопрос обновлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message_handler(state=AdminStates.waiting_for_question_delete)
async def process_delete_question(message: types.Message, state: FSMContext):
    try:
        question_id = int(message.text.strip())
        if not db.get_question_by_id(question_id):
            await message.answer("❌ Вопрос не найден.")
            return
        
        db.delete_question(question_id)
        await state.finish()
        await message.answer(f"✅ Вопрос #{question_id} удален.", reply_markup=get_admin_keyboard())
    except:
        await message.answer("❌ Введите число (ID вопроса).")

# ===================== АДМИН: НАЗНАЧЕНИЕ =====================
@dp.message_handler(state=AdminStates.waiting_for_admin_add)
async def process_assign_admin(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        employee = db.get_employee(user_id)
        
        if not employee:
            await message.answer("❌ Пользователь не найден.")
            return
        
        db.set_admin(user_id, True)
        await state.finish()
        await message.answer(f"✅ {employee[1]} назначен администратором!", reply_markup=get_admin_keyboard())
        
        try:
            await bot.send_message(
                user_id,
                "🔑 Вам назначены права администратора!\n"
                "Теперь вам доступна админ-панель."
            )
        except:
            pass
    except:
        await message.answer("❌ Введите корректный ID (число).")

# ===================== ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД =====================
@dp.message_handler()
async def unknown_command(message: types.Message):
    user_id = message.from_user.id
    if db.is_registered(user_id):
        await message.answer(
            "❓ Неизвестная команда.\n\n"
            "Используйте кнопки меню для навигации.",
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        await message.answer(
            "👋 Для начала работы отправьте команду /start"
        )

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("🚀 Запуск HR-бота для Pulse-опроса...")
    print("=" * 50)
    
    try:
        # Инициализация вопросов
        init_survey_questions()
        
        print(f"✅ Бот запущен успешно!")
        print(f"👤 Администраторы: {ADMINS}")
        print(f"📊 Всего вопросов: {db.count_questions()}")
        print(f"🕵️ Все ответы анонимны!")
        print("=" * 50)
        print("💬 Бот готов к работе...")
        
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        sys.exit(1)
