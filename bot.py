#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HR-бот для анонимного Pulse-опроса
Сбор: должность и стаж (без имени)
Анонимная статистика для админа
"""

import sqlite3
import random
import time
import json
import logging
from datetime import datetime
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

class SurveyStates(StatesGroup):
    answering = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_edit_save = State()
    waiting_for_question_delete = State()
    waiting_for_admin_add = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        # Сотрудники (только анонимные данные!)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                position TEXT,
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
        
        # Вопросы для пульс-опроса
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            )
        ''')
        
        # АНОНИМНЫЕ ответы (без user_id!)
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                answer_score INTEGER,
                position TEXT,
                experience TEXT,
                date TEXT
            )
        ''')
        
        # Для отслеживания участия
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS survey_participants (
                user_id INTEGER PRIMARY KEY,
                last_survey_date TEXT
            )
        ''')
        
        # Активные опросы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_surveys (
                user_id INTEGER PRIMARY KEY,
                questions TEXT,
                current_index INTEGER,
                answers TEXT
            )
        ''')
        self.conn.commit()
    
    # ---- Сотрудники ----
    def register_employee(self, user_id, position, experience):
        self.cursor.execute('''
            INSERT OR REPLACE INTO employees (user_id, position, experience, registered_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, position, experience, datetime.now().isoformat()))
        self.conn.commit()
    
    def is_registered(self, user_id):
        self.cursor.execute('SELECT user_id FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_employee(self, user_id):
        self.cursor.execute('SELECT position, experience FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()
    
    # ---- Админы ----
    def is_admin(self, user_id):
        self.cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def add_admin(self, user_id):
        self.cursor.execute('INSERT OR IGNORE INTO admins (user_id, added_at) VALUES (?, ?)', 
                           (user_id, datetime.now().isoformat()))
        self.conn.commit()
    
    def get_all_admins(self):
        self.cursor.execute('SELECT user_id FROM admins')
        return [row[0] for row in self.cursor.fetchall()]
    
    # ---- Вопросы ----
    def add_question(self, question_text):
        self.cursor.execute('''
            INSERT INTO survey_questions (question_text, created_at)
            VALUES (?, ?)
        ''', (question_text, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_all_questions(self):
        self.cursor.execute('SELECT * FROM survey_questions WHERE is_active = 1 ORDER BY id')
        return self.cursor.fetchall()
    
    def get_question_by_id(self, question_id):
        self.cursor.execute('SELECT * FROM survey_questions WHERE id = ? AND is_active = 1', (question_id,))
        return self.cursor.fetchone()
    
    def update_question(self, question_id, question_text):
        self.cursor.execute('UPDATE survey_questions SET question_text = ? WHERE id = ?', 
                           (question_text, question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('UPDATE survey_questions SET is_active = 0 WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def count_questions(self):
        self.cursor.execute('SELECT COUNT(*) FROM survey_questions WHERE is_active = 1')
        return self.cursor.fetchone()[0]
    
    # ---- Анонимные ответы ----
    def save_anonymous_answer(self, question_id, answer_score, position, experience):
        self.cursor.execute('''
            INSERT INTO survey_answers (question_id, answer_score, position, experience, date)
            VALUES (?, ?, ?, ?, ?)
        ''', (question_id, answer_score, position, experience, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def mark_participant(self, user_id):
        self.cursor.execute('''
            INSERT OR REPLACE INTO survey_participants (user_id, last_survey_date)
            VALUES (?, ?)
        ''', (user_id, datetime.now().isoformat()))
        self.conn.commit()
    
    def has_participated(self, user_id):
        self.cursor.execute('SELECT user_id FROM survey_participants WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone() is not None
    
    def get_anonymous_stats(self):
        """Полная анонимная статистика для админа"""
        
        # Общая статистика
        self.cursor.execute('''
            SELECT 
                COUNT(*) as total_answers,
                AVG(answer_score) as avg_score,
                MIN(answer_score) as min_score,
                MAX(answer_score) as max_score,
                COUNT(DISTINCT position) as positions_count
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
        
        # По должностям
        self.cursor.execute('''
            SELECT position, COUNT(*) as count, AVG(answer_score) as avg_score
            FROM survey_answers
            GROUP BY position
            ORDER BY avg_score DESC
        ''')
        by_position = self.cursor.fetchall()
        
        # По стажу
        self.cursor.execute('''
            SELECT experience, COUNT(*) as count, AVG(answer_score) as avg_score
            FROM survey_answers
            GROUP BY experience
            ORDER BY experience
        ''')
        by_experience = self.cursor.fetchall()
        
        # eNPS (доля рекомендующих)
        self.cursor.execute('''
            SELECT 
                SUM(CASE WHEN answer_score >= 9 THEN 1 ELSE 0 END) as promoters,
                SUM(CASE WHEN answer_score <= 6 THEN 1 ELSE 0 END) as detractors,
                COUNT(*) as total
            FROM survey_answers
        ''')
        enps_data = self.cursor.fetchone()
        
        return general, distribution, by_position, by_experience, enps_data
    
    # ---- Активные опросы ----
    def save_active_survey(self, user_id, question_ids, current_index, answers):
        self.cursor.execute('''
            INSERT OR REPLACE INTO active_surveys (user_id, questions, current_index, answers)
            VALUES (?, ?, ?, ?)
        ''', (user_id, json.dumps(question_ids), current_index, json.dumps(answers)))
        self.conn.commit()
    
    def get_active_survey(self, user_id):
        self.cursor.execute('SELECT questions, current_index, answers FROM active_surveys WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return json.loads(result[0]), result[1], json.loads(result[2])
        return None, 0, None
    
    def clear_active_survey(self, user_id):
        self.cursor.execute('DELETE FROM active_surveys WHERE user_id = ?', (user_id,))
        self.conn.commit()

# ===================== БАЗА ДАННЫХ =====================
db = Database()

# ===================== ВОПРОСЫ ДЛЯ PULSE-ОПРОСА =====================
def init_survey_questions():
    if db.count_questions() > 0:
        return
    
    questions = [
        "Насколько вы удовлетворены своей работой в компании?",
        "Как вы оцениваете уровень поддержки со стороны руководства?",
        "Насколько вы чувствуете себя вовлеченным в жизнь компании?",
        "Как вы оцениваете возможности для профессионального роста?",
        "Насколько вы довольны уровнем заработной платы?",
        "Как вы оцениваете атмосферу в коллективе?",
        "Насколько вы довольны условиями труда?",
        "Как вы оцениваете баланс между работой и личной жизнью?",
        "Насколько вы гордитесь тем, что работаете в нашей компании?",
        "Порекомендовали бы вы нашу компанию как место работы друзьям?"
    ]
    
    for q in questions:
        db.add_question(q)
    
    logging.info(f"✅ Добавлено {len(questions)} вопросов для Pulse-опроса")

# ===================== КЛАВИАТУРЫ =====================
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("📝 Пройти опрос"),
        KeyboardButton("📊 Статистика")
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
        KeyboardButton("📊 Анонимная статистика"),
        KeyboardButton("👑 Назначить админа")
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

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
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
            "✅ Мы не спрашиваем ваше имя\n"
            "✅ Данные видны только HR-отделу\n"
            "✅ Опрос занимает 2-3 минуты\n\n"
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

# ===================== РЕГИСТРАЦИЯ (только должность и стаж) =====================
@dp.message_handler(state=RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await message.answer(
        "📅 *Сколько вы работаете в компании?*\n\n"
        "Выберите вариант:",
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
    position = data.get('position')
    
    db.register_employee(message.from_user.id, position, experience)
    
    await state.finish()
    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"📊 Должность: {position}\n"
        f"📅 Стаж: {experience}\n\n"
        "Все данные анонимны! 🕵️\n"
        "Теперь вы можете пройти опрос.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

# ===================== ГЛАВНОЕ МЕНЮ =====================
@dp.message_handler(lambda message: message.text in ["📝 Пройти опрос", "📊 Статистика", "⚙️ Админ-панель"])
async def handle_menu(message: types.Message):
    user_id = message.from_user.id
    
    if message.text == "📝 Пройти опрос":
        await start_survey(message, user_id)
    
    elif message.text == "📊 Статистика":
        await show_user_stats(message, user_id)
    
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

# ===================== ОПРОС =====================
async def start_survey(message: types.Message, user_id):
    if db.count_questions() == 0:
        await message.answer("❌ Вопросы для опроса еще не загружены.")
        return
    
    if db.has_participated(user_id):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("🔄 Пройти заново", callback_data="restart_survey"),
            InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu")
        )
        await message.answer(
            "⚠️ *Вы уже проходили опрос*\n\n"
            "Хотите пройти его заново?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return
    
    questions, current_index, answers = db.get_active_survey(user_id)
    
    if questions and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_survey"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="restart_survey"),
            InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu")
        )
        await message.answer("⏳ У вас есть незавершенный опрос.", reply_markup=keyboard)
        return
    
    all_questions = db.get_all_questions()
    
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
    db.save_active_survey(user_id, question_ids, 0, [])
    await send_question(message, user_id, 0)

async def send_question(message: types.Message, user_id, index):
    questions, current_index, answers = db.get_active_survey(user_id)
    
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
    
    questions, current_index, answers = db.get_active_survey(user_id)
    
    if not questions:
        await callback_query.answer("❌ Опрос не найден")
        return
    
    answers.append({
        'question_id': question_id,
        'rating': rating
    })
    
    current_index += 1
    db.save_active_survey(user_id, questions, current_index, answers)
    
    await callback_query.answer(f"✅ Оценка {rating} сохранена")
    
    if current_index >= len(questions):
        await finish_survey(callback_query.message, user_id)
    else:
        await callback_query.message.delete()
        await send_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'continue_survey')
async def continue_survey(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    questions, current_index, answers = db.get_active_survey(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await send_question(callback_query.message, user_id, current_index)

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
        "🔙 Возврат в главное меню",
        reply_markup=get_main_keyboard(user_id)
    )

async def finish_survey(message: types.Message, user_id):
    questions, current_index, answers = db.get_active_survey(user_id)
    
    if not answers:
        await message.answer("❌ Опрос не был начат.")
        return
    
    # Получаем данные сотрудника (анонимные)
    employee = db.get_employee(user_id)
    position = employee[0] if employee else "Не указана"
    experience = employee[1] if employee else "Не указан"
    
    # Сохраняем анонимные ответы
    for answer in answers:
        db.save_anonymous_answer(
            answer['question_id'],
            answer['rating'],
            position,
            experience
        )
    
    db.mark_participant(user_id)
    db.clear_active_survey(user_id)
    
    total_score = sum(a['rating'] for a in answers)
    avg_score = total_score / len(answers)
    
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
        "Спасибо за участие! 🙌\n"
        "Все ответы полностью анонимны! 🕵️",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

# ===================== СТАТИСТИКА ДЛЯ ПОЛЬЗОВАТЕЛЯ =====================
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
    "❌ Удалить вопрос", "📊 Анонимная статистика",
    "👑 Назначить админа", "🔙 Главное меню"
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
        questions = db.get_all_questions()
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
        questions = db.get_all_questions()
        if not questions:
            await message.answer("❌ Вопросов нет.")
            return
        
        text = "❌ *Удаление вопроса*\n\n"
        for q in questions[:15]:
            text += f"ID: {q[0]}. {q[1][:50]}...\n"
        text += "\nВведите ID вопроса для удаления:"
        await message.answer(text, parse_mode="Markdown")
        await AdminStates.waiting_for_question_delete.set()
    
    elif message.text == "📊 Анонимная статистика":
        general, distribution, by_position, by_experience, enps_data = db.get_anonymous_stats()
        
        text = "📊 *АНОНИМНАЯ СТАТИСТИКА PULSE-ОПРОСА*\n"
        text += "*Все данные анонимны*\n\n"
        
        if general:
            text += f"📝 Всего ответов: {general[0] or 0}\n"
            text += f"📈 Средний балл: {general[1] or 0:.1f}/10\n"
            text += f"📉 Минимальный балл: {general[2] or 0}\n"
            text += f"📈 Максимальный балл: {general[3] or 0}\n"
            text += f"👥 Должностей: {general[4] or 0}\n\n"
        
        # eNPS
        if enps_data:
            promoters = enps_data[0] or 0
            detractors = enps_data[1] or 0
            total = enps_data[2] or 0
            enps_score = round(((promoters - detractors) / total) * 100, 1) if total > 0 else 0
            
            text += f"📊 *eNPS (Лояльность):*\n"
            text += f"🌟 Промоутеры (9-10): {promoters}\n"
            text += f"😐 Нейтралы (7-8): {total - promoters - detractors}\n"
            text += f"🔴 Критики (0-6): {detractors}\n"
            text += f"📈 eNPS: {enps_score}\n\n"
        
        # Распределение оценок
        if distribution:
            text += "📊 *Распределение оценок:*\n"
            for score, count in distribution:
                bar = "█" * min(count, 20)
                text += f"{score} баллов: {bar} ({count})\n"
            text += "\n"
        
        # По должностям
        if by_position:
            text += "👔 *По должностям:*\n"
            for position, count, avg_score in by_position[:10]:
                text += f"📊 {position}: {avg_score:.1f}/10 ({count} чел.)\n"
            text += "\n"
        
        # По стажу
        if by_experience:
            text += "📅 *По стажу:*\n"
            for experience, count, avg_score in by_experience:
                text += f"📊 {experience}: {avg_score:.1f}/10 ({count} чел.)\n"
        
        await message.answer(text, parse_mode="Markdown")
    
    elif message.text == "👑 Назначить админа":
        await message.answer(
            "👑 *Назначение администратора*\n\n"
            "Введите Telegram ID пользователя:",
            parse_mode="Markdown"
        )
        await AdminStates.waiting_for_admin_add.set()

# ===================== АДМИН: РАССЫЛКА =====================
@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    # Получаем всех зарегистрированных пользователей
    db.cursor.execute('SELECT user_id FROM employees')
    users = db.cursor.fetchall()
    sent = 0
    
    for user_id in users:
        try:
            await bot.send_message(
                user_id[0],
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
    db.add_question(message.text)
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
        
        db.update_question(question_id, message.text)
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
        
        db.add_admin(user_id)
        await state.finish()
        await message.answer(f"✅ Пользователь {user_id} назначен администратором!", reply_markup=get_admin_keyboard())
        
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
        # Добавляем админов из списка
        for admin_id in ADMINS:
            db.add_admin(admin_id)
        
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
