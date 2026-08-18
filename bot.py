#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HR-бот для анонимных Pulse-опросов
- Анонимные тесты: Лояльность, Выгорание, Вовлеченность, Стресс
- Топ сотрудников по отделам (анонимно)
- Полная админ-панель
"""

import sqlite3
import random
import time
import json
import logging
from datetime import datetime, timedelta
import os
import sys
import hashlib

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
ADMINS = [1024761707]

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ===================== СОСТОЯНИЯ =====================
class RegistrationStates(StatesGroup):
    waiting_for_position = State()
    waiting_for_experience = State()
    waiting_for_department = State()

class SurveyStates(StatesGroup):
    answering = State()
    waiting_for_test_type = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_edit_save = State()
    waiting_for_question_delete = State()
    waiting_for_admin_add = State()
    waiting_for_test_add = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._create_indexes()
    
    def _create_tables(self):
        # Сотрудники (анонимные данные)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                position TEXT,
                department TEXT,
                experience TEXT,
                registered_at TEXT
            )
        ''')
        
        # Администраторы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT
            )
        ''')
        
        # Вопросы по тестам
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_type TEXT,
                question_text TEXT,
                options TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        ''')
        
        # Результаты тестов (ОДНА ЗАПИСЬ НА СОТРУДНИКА)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_type TEXT,
                position TEXT,
                department TEXT,
                experience TEXT,
                answers_json TEXT,
                score REAL,
                level TEXT,
                date TEXT,
                hash_id TEXT
            )
        ''')
        
        # Участники (факт участия)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_participants (
                user_id INTEGER PRIMARY KEY,
                last_test_date TEXT,
                test_type TEXT
            )
        ''')
        
        # Активные тесты
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_tests (
                user_id INTEGER PRIMARY KEY,
                test_type TEXT,
                questions TEXT,
                current_index INTEGER,
                answers TEXT
            )
        ''')
        self.conn.commit()
    
    def _create_indexes(self):
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_type ON test_results(test_type)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_date ON test_results(date)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_dept ON test_results(department)')
        self.conn.commit()
    
    # ---- Сотрудники ----
    def register_employee(self, user_id, position, department, experience):
        self.cursor.execute('''
            INSERT OR REPLACE INTO employees (user_id, position, department, experience, registered_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, position, department, experience, datetime.now().isoformat()))
        self.conn.commit()
    
    def is_registered(self, user_id):
        self.cursor.execute('SELECT user_id FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_employee(self, user_id):
        self.cursor.execute('SELECT position, department, experience FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()
    
    def get_all_employees(self):
        self.cursor.execute('SELECT user_id, position, department, experience FROM employees')
        return self.cursor.fetchall()
    
    # ---- Админы ----
    def is_admin(self, user_id):
        self.cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def add_admin(self, user_id):
        self.cursor.execute('INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)', 
                           (user_id, datetime.now().isoformat()))
        self.conn.commit()
    
    def remove_admin(self, user_id):
        self.cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def get_all_admins(self):
        self.cursor.execute('SELECT user_id FROM admins')
        return [row[0] for row in self.cursor.fetchall()]
    
    # ---- Вопросы ----
    def add_question(self, test_type, question_text, options):
        self.cursor.execute('''
            INSERT INTO test_questions (test_type, question_text, options, created_at)
            VALUES (?, ?, ?, ?)
        ''', (test_type, question_text, json.dumps(options), datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_questions_by_type(self, test_type):
        self.cursor.execute('SELECT * FROM test_questions WHERE test_type = ? AND is_active = 1 ORDER BY RANDOM()', (test_type,))
        return self.cursor.fetchall()
    
    def get_all_questions(self):
        self.cursor.execute('SELECT * FROM test_questions WHERE is_active = 1 ORDER BY test_type, id')
        return self.cursor.fetchall()
    
    def get_question_by_id(self, question_id):
        self.cursor.execute('SELECT * FROM test_questions WHERE id = ? AND is_active = 1', (question_id,))
        return self.cursor.fetchone()
    
    def update_question(self, question_id, question_text, options):
        self.cursor.execute('UPDATE test_questions SET question_text = ?, options = ? WHERE id = ?', 
                           (question_text, json.dumps(options), question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('UPDATE test_questions SET is_active = 0 WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def count_questions_by_type(self, test_type):
        self.cursor.execute('SELECT COUNT(*) FROM test_questions WHERE test_type = ? AND is_active = 1', (test_type,))
        return self.cursor.fetchone()[0]
    
    def get_test_types(self):
        self.cursor.execute('SELECT DISTINCT test_type FROM test_questions WHERE is_active = 1')
        return [row[0] for row in self.cursor.fetchall()]
    
    # ---- Результаты тестов ----
    def save_test_result(self, test_type, position, department, experience, answers_dict, score, level):
        hash_id = hashlib.md5(f"{position}{department}{experience}{datetime.now().timestamp()}".encode()).hexdigest()[:8]
        
        self.cursor.execute('''
            INSERT INTO test_results (test_type, position, department, experience, answers_json, score, level, date, hash_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (test_type, position, department, experience, json.dumps(answers_dict), score, level, datetime.now().isoformat(), hash_id))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def mark_participant(self, user_id, test_type):
        self.cursor.execute('''
            INSERT OR REPLACE INTO test_participants (user_id, last_test_date, test_type)
            VALUES (?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), test_type))
        self.conn.commit()
    
    def has_participated(self, user_id, test_type=None):
        if test_type:
            self.cursor.execute('SELECT user_id FROM test_participants WHERE user_id = ? AND test_type = ?', (user_id, test_type))
        else:
            self.cursor.execute('SELECT user_id FROM test_participants WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_test_stats(self, test_type=None):
        """Полная статистика для админа"""
        if test_type:
            where = f"WHERE test_type = '{test_type}'"
        else:
            where = ""
        
        # Общая статистика
        self.cursor.execute(f'''
            SELECT 
                COUNT(*) as total_participants,
                AVG(score) as avg_score,
                MIN(score) as min_score,
                MAX(score) as max_score,
                COUNT(DISTINCT department) as dept_count,
                COUNT(DISTINCT position) as pos_count
            FROM test_results
            {where}
        ''')
        general = self.cursor.fetchone()
        
        # Уровни
        self.cursor.execute(f'''
            SELECT level, COUNT(*) as count, AVG(score) as avg_score
            FROM test_results
            {where}
            GROUP BY level
            ORDER BY avg_score DESC
        ''')
        levels = self.cursor.fetchall()
        
        # По отделам
        self.cursor.execute(f'''
            SELECT department, COUNT(*) as count, AVG(score) as avg_score
            FROM test_results
            {where}
            GROUP BY department
            ORDER BY avg_score DESC
        ''')
        by_department = self.cursor.fetchall()
        
        # По должностям
        self.cursor.execute(f'''
            SELECT position, COUNT(*) as count, AVG(score) as avg_score
            FROM test_results
            {where}
            GROUP BY position
            ORDER BY avg_score DESC
            LIMIT 15
        ''')
        by_position = self.cursor.fetchall()
        
        # По стажу
        self.cursor.execute(f'''
            SELECT experience, COUNT(*) as count, AVG(score) as avg_score
            FROM test_results
            {where}
            GROUP BY experience
            ORDER BY experience
        ''')
        by_experience = self.cursor.fetchall()
        
        # TOP сотрудников (анонимно)
        self.cursor.execute(f'''
            SELECT position, department, experience, score, level, date
            FROM test_results
            {where}
            ORDER BY score DESC
            LIMIT 10
        ''')
        top = self.cursor.fetchall()
        
        return general, levels, by_department, by_position, by_experience, top
    
    # ---- Активные тесты ----
    def save_active_test(self, user_id, test_type, question_ids, current_index, answers):
        self.cursor.execute('''
            INSERT OR REPLACE INTO active_tests (user_id, test_type, questions, current_index, answers)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, test_type, json.dumps(question_ids), current_index, json.dumps(answers)))
        self.conn.commit()
    
    def get_active_test(self, user_id):
        self.cursor.execute('SELECT test_type, questions, current_index, answers FROM active_tests WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0], json.loads(result[1]), result[2], json.loads(result[3])
        return None, None, 0, None
    
    def clear_active_test(self, user_id):
        self.cursor.execute('DELETE FROM active_tests WHERE user_id = ?', (user_id,))
        self.conn.commit()

# ===================== БАЗА ДАННЫХ =====================
db = Database()

# ===================== ТЕСТЫ =====================
def init_tests():
    """Инициализация тестов"""
    test_types = ['Лояльность', 'Выгорание', 'Вовлеченность', 'Стресс']
    
    for test_type in test_types:
        if db.count_questions_by_type(test_type) > 0:
            continue
    
    questions = {
        'Лояльность': [
            ("Насколько вы удовлетворены своей работой?", ["1 - Совсем нет", "5 - Частично", "10 - Полностью"]),
            ("Как вы оцениваете руководство?", ["1 - Плохо", "5 - Нормально", "10 - Отлично"]),
            ("Гордитесь ли вы работой в компании?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
            ("Рекомендуете ли вы компанию друзьям?", ["1 - Нет", "5 - Возможно", "10 - Да"]),
            ("Как вы оцениваете атмосферу в коллективе?", ["1 - Плохая", "5 - Нормальная", "10 - Отличная"]),
        ],
        'Выгорание': [
            ("Чувствуете ли вы эмоциональное истощение?", ["1 - Никогда", "5 - Иногда", "10 - Постоянно"]),
            ("Потеряли ли вы интерес к работе?", ["1 - Нет", "5 - Частично", "10 - Да"]),
            ("Чувствуете ли вы цинизм к работе?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
            ("Чувствуете ли вы снижение продуктивности?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
            ("Чувствуете ли вы перегрузку?", ["1 - Нет", "5 - Иногда", "10 - Постоянно"]),
        ],
        'Вовлеченность': [
            ("Насколько вы вовлечены в работу?", ["1 - Совсем нет", "5 - Частично", "10 - Полностью"]),
            ("Готовы ли вы работать сверхурочно?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
            ("Участвуете ли вы в жизни компании?", ["1 - Нет", "5 - Иногда", "10 - Активно"]),
            ("Вносите ли вы идеи по улучшению?", ["1 - Никогда", "5 - Иногда", "10 - Постоянно"]),
            ("Чувствуете ли вы связь с целями компании?", ["1 - Нет", "5 - Частично", "10 - Да"]),
        ],
        'Стресс': [
            ("Как часто вы испытываете стресс на работе?", ["1 - Никогда", "5 - Иногда", "10 - Постоянно"]),
            ("Влияет ли стресс на качество работы?", ["1 - Нет", "5 - Частично", "10 - Сильно"]),
            ("Чувствуете ли вы напряжение в коллективе?", ["1 - Нет", "5 - Иногда", "10 - Постоянно"]),
            ("Можете ли вы расслабиться после работы?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
            ("Чувствуете ли вы поддержку руководства?", ["1 - Нет", "5 - Иногда", "10 - Да"]),
        ]
    }
    
    for test_type, q_list in questions.items():
        for q_text, options in q_list:
            db.add_question(test_type, q_text, options)
    
    logging.info(f"✅ Добавлены тесты: {', '.join(test_types)}")

# ===================== КЛАВИАТУРЫ =====================
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📝 Пройти тест"),
        KeyboardButton("📊 Моя статистика")
    )
    keyboard.add(
        KeyboardButton("🏆 Топ HR"),
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
        KeyboardButton("📊 Статистика"),
        KeyboardButton("👑 Назначить админа")
    )
    keyboard.add(
        KeyboardButton("🗑 Очистить БД"),
        KeyboardButton("🔙 Главное меню")
    )
    return keyboard

def get_test_type_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("❤️ Лояльность", callback_data="test_Лояльность"),
        InlineKeyboardButton("🔥 Выгорание", callback_data="test_Выгорание")
    )
    keyboard.add(
        InlineKeyboardButton("🚀 Вовлеченность", callback_data="test_Вовлеченность"),
        InlineKeyboardButton("😰 Стресс", callback_data="test_Стресс")
    )
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    return keyboard

def get_rating_keyboard(question_id, options):
    keyboard = InlineKeyboardMarkup(row_width=3)
    buttons = []
    for i, option in enumerate(options):
        emoji = "🔴" if i == 0 else "🟡" if i == 1 else "🟢"
        buttons.append(InlineKeyboardButton(f"{emoji} {option[:15]}", callback_data=f"rate_{i}_{question_id}"))
    
    for i in range(0, len(buttons), 3):
        keyboard.add(*buttons[i:i+3])
    
    return keyboard

# ===================== ОБРАБОТЧИКИ =====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    
    if not db.is_registered(user_id):
        await message.answer(
            "🌟 *Добро пожаловать в HR Pulse!*\n\n"
            "Здесь вы можете пройти анонимные тесты:\n"
            "❤️ Лояльность\n"
            "🔥 Выгорание\n"
            "🚀 Вовлеченность\n"
            "😰 Стресс\n\n"
            "📌 *Важно:*\n"
            "✅ Все ответы полностью анонимны\n"
            "✅ Данные видны только HR\n"
            "✅ Тесты занимают 2-3 минуты\n\n"
            "Для начала укажите вашу *должность*:",
            parse_mode="Markdown"
        )
        await RegistrationStates.waiting_for_position.set()
    else:
        await message.answer(
            "👋 *С возвращением!*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )

# ===================== РЕГИСТРАЦИЯ =====================
@dp.message_handler(state=RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await message.answer("🏢 Введите ваш *отдел*:", parse_mode="Markdown")
    await RegistrationStates.waiting_for_department.set()

@dp.message_handler(state=RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await message.answer(
        "📅 *Стаж работы в компании:*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add(
            KeyboardButton("Менее 3 месяцев"),
            KeyboardButton("3-6 месяцев"),
            KeyboardButton("6-12 месяцев"),
            KeyboardButton("1-2 года"),
            KeyboardButton("2-5 лет"),
            KeyboardButton("Более 5 лет")
        )
    )
    await RegistrationStates.waiting_for_experience.set()

@dp.message_handler(state=RegistrationStates.waiting_for_experience)
async def process_experience(message: types.Message, state: FSMContext):
    experience = message.text
    valid_options = ["Менее 3 месяцев", "3-6 месяцев", "6-12 месяцев", "1-2 года", "2-5 лет", "Более 5 лет"]
    
    if experience not in valid_options:
        await message.answer("❌ Пожалуйста, выберите вариант из списка:")
        return
    
    data = await state.get_data()
    
    db.register_employee(
        message.from_user.id,
        data.get('position'),
        data.get('department'),
        experience
    )
    
    await state.finish()
    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"📊 Должность: {data.get('position')}\n"
        f"🏢 Отдел: {data.get('department')}\n"
        f"📅 Стаж: {experience}\n\n"
        "Все данные анонимны! 🕵️\n"
        "Теперь вы можете пройти тесты.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ===================== ГЛАВНОЕ МЕНЮ =====================
@dp.message_handler(lambda message: message.text in ["📝 Пройти тест", "📊 Моя статистика", "🏆 Топ HR", "ℹ️ Помощь", "⚙️ Админ-панель"])
async def handle_menu(message: types.Message):
    user_id = message.from_user.id
    
    if message.text == "📝 Пройти тест":
        await message.answer(
            "📝 *Выберите тип теста:*",
            parse_mode="Markdown",
            reply_markup=get_test_type_keyboard()
        )
    
    elif message.text == "📊 Моя статистика":
        await show_user_stats(message, user_id)
    
    elif message.text == "🏆 Топ HR":
        await show_top_hr(message)
    
    elif message.text == "ℹ️ Помощь":
        await message.answer(
            "ℹ️ *Помощь*\n\n"
            "📝 *Пройти тест* - анонимные тесты:\n"
            "   ❤️ Лояльность\n"
            "   🔥 Выгорание\n"
            "   🚀 Вовлеченность\n"
            "   😰 Стресс\n\n"
            "📊 *Моя статистика* - ваши результаты\n"
            "🏆 *Топ HR* - лучшие сотрудники (анонимно)\n"
            "⚙️ *Админ-панель* - управление (только для HR)",
            parse_mode="Markdown"
        )
    
    elif message.text == "⚙️ Админ-панель":
        if db.is_admin(user_id):
            await message.answer(
                "⚙️ *Панель администратора*\n\n"
                "Управление анонимными тестами:",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer("⛔ У вас нет прав администратора.")

# ===================== ТЕСТЫ =====================
@dp.callback_query_handler(lambda c: c.data.startswith('test_'))
async def start_test(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    test_type = callback_query.data.replace('test_', '')
    
    await callback_query.answer()
    
    if not db.is_registered(user_id):
        await callback_query.message.answer("❌ Сначала зарегистрируйтесь через /start")
        return
    
    if db.count_questions_by_type(test_type) == 0:
        await callback_query.message.answer(f"❌ Вопросы для теста '{test_type}' не найдены.")
        return
    
    if db.has_participated(user_id, test_type):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("🔄 Пройти заново", callback_data=f"restart_test_{test_type}"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
        )
        await callback_query.message.answer(
            f"⚠️ *Вы уже проходили тест '{test_type}'*\n\n"
            "Хотите пройти заново?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    # Проверяем незавершенный тест
    active_type, questions, current_index, answers = db.get_active_test(user_id)
    
    if active_type and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_test"),
            InlineKeyboardButton("🔄 Начать заново", callback_data=f"restart_test_{test_type}"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
        )
        await callback_query.message.answer("⏳ У вас есть незавершенный тест.", reply_markup=keyboard)
        return
    
    # Начинаем новый тест
    all_questions = db.get_questions_by_type(test_type)
    question_ids = [q[0] for q in all_questions]
    
    await callback_query.message.answer(
        f"📝 *Тест: {test_type}*\n\n"
        f"Всего вопросов: {len(question_ids)}\n"
        "Оцените каждый вопрос по шкале.\n\n"
        "Все ответы анонимны! 🕵️",
        parse_mode="Markdown"
    )
    
    db.save_active_test(user_id, test_type, question_ids, 0, {})
    await send_test_question(callback_query.message, user_id, 0)

@dp.callback_query_handler(lambda c: c.data == 'continue_test')
async def continue_test(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    test_type, questions, current_index, answers = db.get_active_test(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await send_test_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data.startswith('restart_test_'))
async def restart_test(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    test_type = callback_query.data.replace('restart_test_', '')
    
    db.clear_active_test(user_id)
    await callback_query.answer()
    await callback_query.message.delete()
    
    # Удаляем старую запись участника
    db.cursor.execute('DELETE FROM test_participants WHERE user_id = ? AND test_type = ?', (user_id, test_type))
    db.conn.commit()
    
    await start_test(callback_query)

@dp.callback_query_handler(lambda c: c.data == 'back_to_menu')
async def back_to_menu_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await callback_query.answer()
    await callback_query.message.delete()
    await callback_query.message.answer(
        "🔙 Главное меню",
        reply_markup=get_main_keyboard(user_id)
    )

async def send_test_question(message: types.Message, user_id, index):
    test_type, questions, current_index, answers = db.get_active_test(user_id)
    
    if not questions or index >= len(questions):
        await finish_test(message, user_id)
        return
    
    question_id = questions[index]
    question = db.get_question_by_id(question_id)
    
    if not question:
        await message.answer("❌ Ошибка загрузки вопроса.")
        return
    
    options = json.loads(question[3])
    
    text = f"📝 *Вопрос {index + 1} из {len(questions)}*\n\n"
    text += f"*{question[2]}*\n\n"
    text += "Выберите вариант:"
    
    keyboard = get_rating_keyboard(question_id, options)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('rate_'))
async def handle_answer(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    rating = int(data[1])
    question_id = int(data[2])
    
    test_type, questions, current_index, answers = db.get_active_test(user_id)
    
    if not questions:
        await callback_query.answer("❌ Тест не найден")
        return
    
    answers[str(question_id)] = rating
    current_index += 1
    
    db.save_active_test(user_id, test_type, questions, current_index, answers)
    
    await callback_query.answer(f"✅ Ответ сохранен")
    
    if current_index >= len(questions):
        await finish_test(callback_query.message, user_id)
    else:
        await callback_query.message.delete()
        await send_test_question(callback_query.message, user_id, current_index)

async def finish_test(message: types.Message, user_id):
    test_type, questions, current_index, answers = db.get_active_test(user_id)
    
    if not answers:
        await message.answer("❌ Тест не был начат.")
        return
    
    employee = db.get_employee(user_id)
    position = employee[0] if employee else "Не указана"
    department = employee[1] if employee else "Не указан"
    experience = employee[2] if employee else "Не указан"
    
    # Считаем баллы (0-100)
    total_questions = len(answers)
    total_score = sum(answers.values())
    
    # Нормализуем: если ответы 0-2, то 0-100
    max_possible = total_questions * 2  # так как максимум 2
    score = (total_score / max_possible) * 100 if max_possible > 0 else 0
    score = round(score, 1)
    
    # Уровень
    if score >= 80:
        level = "🟢 Отлично"
    elif score >= 60:
        level = "🟡 Хорошо"
    elif score >= 40:
        level = "🟠 Средне"
    else:
        level = "🔴 Требуется внимание"
    
    # Сохраняем результат
    db.save_test_result(test_type, position, department, experience, answers, score, level)
    db.mark_participant(user_id, test_type)
    db.clear_active_test(user_id)
    
    await message.answer(
        f"✅ *Тест '{test_type}' завершен!*\n\n"
        f"📊 Ваш результат: {score:.1f}%\n"
        f"📈 Уровень: {level}\n\n"
        "Спасибо за участие! 🙌\n"
        "Все ответы анонимны! 🕵️",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

# ===================== СТАТИСТИКА =====================
async def show_user_stats(message: types.Message, user_id):
    results = db.cursor.execute('SELECT test_type, score, level, date FROM test_results WHERE position IN (SELECT position FROM employees WHERE user_id = ?) ORDER BY date DESC', (user_id,)).fetchall()
    
    if not results:
        await message.answer("📊 Вы еще не проходили тесты.")
        return
    
    text = "📊 *Моя статистика*\n\n"
    for test_type, score, level, date in results[:10]:
        d = datetime.fromisoformat(date).strftime("%d.%m %H:%M")
        text += f"📝 {test_type}: {score:.1f}% {level}\n"
        text += f"   🕐 {d}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

async def show_top_hr(message: types.Message):
    results = db.cursor.execute('''
        SELECT position, department, experience, score, level, date, test_type
        FROM test_results
        ORDER BY score DESC
        LIMIT 15
    ''').fetchall()
    
    if not results:
        await message.answer("🏆 Пока нет данных.")
        return
    
    text = "🏆 *Топ сотрудников (анонимно)*\n\n"
    
    for i, (position, department, experience, score, level, date, test_type) in enumerate(results, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {position}\n"
        text += f"   📊 {department} | {test_type}\n"
        text += f"   📈 {score:.1f}% {level}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# ===================== АДМИН-ПАНЕЛЬ =====================
@dp.message_handler(lambda message: message.text in [
    "📢 Рассылка", "➕ Добавить вопрос", "✏️ Редактировать вопрос",
    "❌ Удалить вопрос", "📊 Статистика", "👑 Назначить админа",
    "🗑 Очистить БД", "🔙 Главное меню"
])
async def handle_admin_buttons(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ Нет прав")
        return
    
    if message.text == "🔙 Главное меню":
        await message.answer("🔙 Возврат", reply_markup=get_main_keyboard(user_id))
    
    elif message.text == "📢 Рассылка":
        await message.answer("📢 Введите текст рассылки:")
        await AdminStates.waiting_for_broadcast.set()
    
    elif message.text == "➕ Добавить вопрос":
        await message.answer(
            "📝 *Добавление вопроса*\n\n"
            "Формат: `Тест | Вопрос | Вариант1 | Вариант2 | Вариант3`\n\n"
            "Пример: `Лояльность | Как вы оцениваете? | Плохо | Нормально | Отлично`",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_question_add.set()
    
    elif message.text == "✏️ Редактировать вопрос":
        questions = db.get_all_questions()
        if not questions:
            await message.answer("❌ Вопросов нет.")
            return
        
        text = "✏️ *Выберите вопрос*\n\n"
        for q in questions[:15]:
            text += f"ID: {q[0]}. [{q[1]}] {q[2][:40]}...\n"
        text += "\nВведите ID вопроса:"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_question_edit.set()
    
    elif message.text == "❌ Удалить вопрос":
        questions = db.get_all_questions()
        if not questions:
            await message.answer("❌ Вопросов нет.")
            return
        
        text = "❌ *Удаление вопроса*\n\n"
        for q in questions[:15]:
            text += f"ID: {q[0]}. {q[2][:40]}...\n"
        text += "\nВведите ID:"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_question_delete.set()
    
    elif message.text == "📊 Статистика":
        await show_admin_stats(message)
    
    elif message.text == "👑 Назначить админа":
        await message.answer(
            "👑 *Назначение администратора*\n\n"
            "Введите Telegram ID:\n\n"
            "Текущие админы:",
            parse_mode="Markdown"
        )
        admins = db.get_all_admins()
        text = ""
        for a in admins:
            text += f"🆔 `{a}`\n"
        await message.answer(text or "Нет админов", parse_mode="Markdown")
        await AdminStates.waiting_for_admin_add.set()
    
    elif message.text == "🗑 Очистить БД":
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ ДА, ОЧИСТИТЬ ВСЁ", callback_data="confirm_clear_db"),
            InlineKeyboardButton("❌ ОТМЕНА", callback_data="cancel_clear_db")
        )
        await message.answer(
            "⚠️ *Очистка базы данных*\n\n"
            "Будут удалены:\n"
            "✅ Все результаты тестов\n"
            "✅ Все участники\n\n"
            "❓ Вопросы останутся.\n\n"
            "Вы уверены?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

@dp.callback_query_handler(lambda c: c.data == 'confirm_clear_db')
async def confirm_clear_db(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if not db.is_admin(user_id):
        await callback_query.answer("⛔ Нет прав")
        return
    
    db.cursor.execute('DELETE FROM test_results')
    db.cursor.execute('DELETE FROM test_participants')
    db.cursor.execute('DELETE FROM sqlite_sequence')
    db.conn.commit()
    
    await callback_query.answer()
    await callback_query.message.edit_text(
        "✅ *База данных очищена!*",
        parse_mode="Markdown"
    )

@dp.callback_query_handler(lambda c: c.data == 'cancel_clear_db')
async def cancel_clear_db(callback_query: types.CallbackQuery):
    await callback_query.answer()
    await callback_query.message.edit_text("🔙 Операция отменена.")

# ===================== АДМИН: РАССЫЛКА =====================
@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    employees = db.get_all_employees()
    sent = 0
    
    for user_id, pos, dept, exp in employees:
        try:
            await bot.send_message(
                user_id,
                f"📢 *Объявление HR*\n\n{message.text}",
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
    try:
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 5:
            await message.answer("❌ Формат: `Тест | Вопрос | Вариант1 | Вариант2 | Вариант3`")
            return
        
        test_type = parts[0]
        question_text = parts[1]
        options = parts[2:5]
        
        db.add_question(test_type, question_text, options)
        await state.finish()
        await message.answer("✅ Вопрос добавлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

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
            f"Текущий: {question[2]}\n\n"
            "Введите новые данные в формате:\n"
            "`Тест | Вопрос | Вариант1 | Вариант2 | Вариант3`",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_question_edit_save.set()
    except:
        await message.answer("❌ Введите число (ID).")

@dp.message_handler(state=AdminStates.waiting_for_question_edit_save)
async def process_edit_question_save(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        question_id = data.get('edit_id')
        
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 5:
            await message.answer("❌ Неверный формат.")
            return
        
        db.update_question(question_id, parts[1], parts[2:5])
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
        await message.answer("❌ Введите число (ID).")

# ===================== АДМИН: СТАТИСТИКА =====================
async def show_admin_stats(message: types.Message):
    test_types = db.get_test_types()
    
    if not test_types:
        await message.answer("📊 Нет данных для статистики.")
        return
    
    text = "📊 *АНОНИМНАЯ СТАТИСТИКА*\n\n"
    
    for test_type in test_types:
        general, levels, by_dept, by_pos, by_exp, top = db.get_test_stats(test_type)
        
        text += f"📝 *{test_type}*\n"
        if general and general[0] > 0:
            text += f"👥 Участников: {general[0]}\n"
            text += f"📈 Средний: {general[1]:.1f}%\n"
            text += f"📉 Мин: {general[2]:.1f}%\n"
            text += f"📈 Макс: {general[3]:.1f}%\n"
        else:
            text += "Нет данных\n"
        text += "\n"
    
    await message.answer(text, parse_mode="Markdown")

# ===================== АДМИН: НАЗНАЧЕНИЕ =====================
@dp.message_handler(state=AdminStates.waiting_for_admin_add)
async def process_assign_admin(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        db.add_admin(user_id)
        await state.finish()
        await message.answer(f"✅ Пользователь {user_id} назначен админом!", reply_markup=get_admin_keyboard())
        
        try:
            await bot.send_message(user_id, "🔑 Вам назначены права администратора!")
        except:
            pass
    except:
        await message.answer("❌ Введите корректный ID.")

# ===================== КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ =====================
@dp.message_handler(commands=['admins'])
async def show_admins(message: types.Message):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ Нет доступа")
        return
    
    admins = db.get_all_admins()
    if not admins:
        await message.answer("👑 Список админов пуст.")
        return
    
    text = "👑 *Администраторы:*\n\n"
    for admin_id in admins:
        text += f"🆔 `{admin_id}`\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(commands=['addadmin'])
async def add_admin_command(message: types.Message):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ Нет доступа")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ /addadmin <TELEGRAM_ID>")
        return
    
    try:
        new_admin_id = int(args[1])
        db.add_admin(new_admin_id)
        await message.answer(f"✅ Пользователь `{new_admin_id}` назначен админом!", parse_mode="Markdown")
    except:
        await message.answer("❌ Введите корректный ID.")

@dp.message_handler(commands=['removeadmin'])
async def remove_admin_command(message: types.Message):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ Нет доступа")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ /removeadmin <TELEGRAM_ID>")
        return
    
    try:
        remove_id = int(args[1])
        if remove_id == user_id:
            await message.answer("❌ Нельзя удалить самого себя!")
            return
        
        db.remove_admin(remove_id)
        await message.answer(f"✅ Админ `{remove_id}` удален!", parse_mode="Markdown")
    except:
        await message.answer("❌ Введите корректный ID.")

@dp.message_handler(commands=['dbstatus'])
async def db_status_command(message: types.Message):
    user_id = message.from_user.id
    if not db.is_admin(user_id):
        await message.answer("⛔ Нет доступа")
        return
    
    db.cursor.execute('SELECT COUNT(*) FROM employees')
    employees = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT COUNT(*) FROM test_results')
    results = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT COUNT(*) FROM test_participants')
    participants = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT COUNT(*) FROM test_questions WHERE is_active = 1')
    questions = db.cursor.fetchone()[0]
    
    db.cursor.execute('SELECT COUNT(*) FROM admins')
    admins = db.cursor.fetchone()[0]
    
    text = "📊 *Состояние БД:*\n\n"
    text += f"👥 Сотрудников: {employees}\n"
    text += f"📝 Результатов: {results}\n"
    text += f"👤 Участников: {participants}\n"
    text += f"❓ Вопросов: {questions}\n"
    text += f"👑 Админов: {admins}\n"
    
    if admins > 0:
        admin_list = [str(a) for a in db.get_all_admins()]
        text += f"\n👑 Админы: `{', '.join(admin_list)}`"
    
    await message.answer(text, parse_mode="Markdown")

# ===================== ОБРАБОТКА НЕИЗВЕСТНЫХ =====================
@dp.message_handler()
async def unknown_command(message: types.Message):
    user_id = message.from_user.id
    if db.is_registered(user_id):
        await message.answer(
            "❓ Неизвестная команда.\n\n"
            "Используйте кнопки меню.",
            reply_markup=get_main_keyboard(user_id)
        )
    else:
        await message.answer("👋 Для начала отправьте /start")

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("🚀 Запуск HR Pulse бота...")
    print("=" * 50)
    
    try:
        for admin_id in ADMINS:
            db.add_admin(admin_id)
        
        init_tests()
        
        print(f"✅ Бот запущен!")
        print(f"👤 Админы: {ADMINS}")
        print(f"📊 Тесты: Лояльность, Выгорание, Вовлеченность, Стресс")
        print(f"🕵️ Все ответы анонимны!")
        print("=" * 50)
        print("💬 Бот готов...")
        
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
