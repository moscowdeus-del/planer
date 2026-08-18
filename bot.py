#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HR-бот для СПА-салона
Работает на BotHost и других хостингах
"""

import sqlite3
import random
import time
import json
import logging
from datetime import datetime
import os
import sys

# ===================== УСТАНОВКА ЗАВИСИМОСТЕЙ =====================
try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HR-бот для СПА-салона
Работает на BotHost и других хостингах
"""

import sqlite3
import random
import time
import json
import logging
from datetime import datetime
import os
import sys

# ===================== УСТАНОВКА ЗАВИСИМОСТЕЙ =====================
try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
except ImportError:
    print("Установка aiogram...")
    os.system("pip install aiogram==2.25.1")
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"  # ЗАМЕНИТЕ НА ВАШ ТОКЕН
ADMINS = [1024761707]  # ЗАМЕНИТЕ НА ВАШ TELEGRAM ID

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ===================== СОСТОЯНИЯ =====================
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_department = State()
    waiting_for_position = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_edit_save = State()  # ДОБАВЛЕНО!
    waiting_for_question_delete = State()
    waiting_for_admin_add = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                department TEXT,
                position TEXT,
                registered_at TEXT,
                is_admin INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                best_score REAL DEFAULT 0,
                best_time INTEGER DEFAULT 999999
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_answer TEXT,
                category TEXT DEFAULT 'СПА',
                difficulty INTEGER DEFAULT 1
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                total_questions INTEGER,
                correct_answers INTEGER,
                score REAL,
                passed INTEGER,
                category TEXT,
                time_spent INTEGER,
                attempt_number INTEGER
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_quizzes (
                user_id INTEGER PRIMARY KEY,
                questions TEXT,
                current_index INTEGER,
                correct_count INTEGER,
                total_asked INTEGER,
                category TEXT,
                start_time INTEGER,
                question_start_time INTEGER
            )
        ''')
        self.conn.commit()
    
    # ---- Сотрудники ----
    def register_employee(self, user_id, full_name, department, position):
        self.cursor.execute('''
            INSERT OR REPLACE INTO employees (user_id, full_name, department, position, registered_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, full_name, department, position, datetime.now().isoformat()))
        self.conn.commit()
    
    def is_admin(self, user_id):
        self.cursor.execute('SELECT is_admin FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result is not None and result[0] == 1
    
    def get_employee(self, user_id):
        self.cursor.execute('SELECT * FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()
    
    def get_all_employees(self):
        self.cursor.execute('SELECT user_id, full_name, department, position, total_attempts, best_score, best_time FROM employees ORDER BY full_name')
        return self.cursor.fetchall()
    
    def set_admin(self, user_id, is_admin=True):
        self.cursor.execute('UPDATE employees SET is_admin = ? WHERE user_id = ?', (1 if is_admin else 0, user_id))
        self.conn.commit()
    
    def update_stats(self, user_id, score, time_spent):
        self.cursor.execute('SELECT total_attempts, best_score, best_time FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            attempts = result[0] + 1
            best_score = max(result[1] or 0, score)
            best_time = min(result[2] or 999999, time_spent)
            self.cursor.execute('''
                UPDATE employees SET total_attempts = ?, best_score = ?, best_time = ?
                WHERE user_id = ?
            ''', (attempts, best_score, best_time, user_id))
            self.conn.commit()
    
    # ---- Вопросы ----
    def add_question(self, question_text, options, correct_answer, category="СПА", difficulty=1):
        self.cursor.execute('''
            INSERT INTO questions (question_text, option_a, option_b, option_c, option_d, correct_answer, category, difficulty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (question_text, options[0], options[1], options[2], options[3], correct_answer, category, difficulty))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_all_questions(self):
        self.cursor.execute('SELECT * FROM questions ORDER BY id')
        return self.cursor.fetchall()
    
    def get_question_by_id(self, question_id):
        self.cursor.execute('SELECT * FROM questions WHERE id = ?', (question_id,))
        return self.cursor.fetchone()
    
    def update_question(self, question_id, question_text, options, correct_answer, category, difficulty):
        self.cursor.execute('''
            UPDATE questions SET question_text = ?, option_a = ?, option_b = ?, option_c = ?, option_d = ?,
                correct_answer = ?, category = ?, difficulty = ?
            WHERE id = ?
        ''', (question_text, options[0], options[1], options[2], options[3], correct_answer, category, difficulty, question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('DELETE FROM questions WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def count_questions(self):
        self.cursor.execute('SELECT COUNT(*) FROM questions')
        return self.cursor.fetchone()[0]
    
    # ---- Результаты ----
    def save_result(self, user_id, total, correct, category, time_spent):
        score = (correct / total) * 100 if total > 0 else 0
        passed = 1 if score >= 70 else 0
        
        self.cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE user_id = ?', (user_id,))
        attempt_number = self.cursor.fetchone()[0] + 1
        
        self.cursor.execute('''
            INSERT INTO quiz_results (user_id, date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), total, correct, score, passed, category, time_spent, attempt_number))
        self.conn.commit()
        
        self.update_stats(user_id, score, time_spent)
        return score, passed, attempt_number
    
    def get_user_results(self, user_id, limit=20):
        self.cursor.execute('''
            SELECT date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number
            FROM quiz_results WHERE user_id = ? ORDER BY date DESC LIMIT ?
        ''', (user_id, limit))
        return self.cursor.fetchall()
    
    def get_leaderboard(self, limit=20):
        self.cursor.execute('''
            SELECT e.user_id, e.full_name, e.department, e.total_attempts, e.best_score, e.best_time,
                   COUNT(r.id) as attempts, AVG(r.score) as avg_score,
                   SUM(CASE WHEN r.passed = 1 THEN 1 ELSE 0 END) as passed_count
            FROM employees e
            LEFT JOIN quiz_results r ON e.user_id = r.user_id
            WHERE e.total_attempts > 0
            GROUP BY e.user_id
            ORDER BY e.total_attempts ASC, e.best_time ASC
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_admin_stats(self):
        self.cursor.execute('''
            SELECT COUNT(DISTINCT user_id), COUNT(*), AVG(score), SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END),
                   AVG(time_spent), MIN(time_spent)
            FROM quiz_results
        ''')
        return self.cursor.fetchone()
    
    # ---- Активные викторины ----
    def save_active_quiz(self, user_id, question_ids, current_index, correct_count, total_asked, category, start_time, question_start_time):
        self.cursor.execute('''
            INSERT OR REPLACE INTO active_quizzes (user_id, questions, current_index, correct_count, total_asked, category, start_time, question_start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, json.dumps(question_ids), current_index, correct_count, total_asked, category, start_time, question_start_time))
        self.conn.commit()
    
    def get_active_quiz(self, user_id):
        self.cursor.execute('SELECT questions, current_index, correct_count, total_asked, category, start_time, question_start_time FROM active_quizzes WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return json.loads(result[0]), result[1], result[2], result[3], result[4], result[5], result[6]
        return None, 0, 0, 0, None, None, None
    
    def clear_active_quiz(self, user_id):
        self.cursor.execute('DELETE FROM active_quizzes WHERE user_id = ?', (user_id,))
        self.conn.commit()

# ===================== ИНИЦИАЛИЗАЦИЯ БД =====================
db = Database()

# ===================== 100 ВОПРОСОВ ПО СПА =====================
def init_questions():
    if db.count_questions() > 0:
        return
    
    questions_data = [
        ("Что такое СПА-процедура?", ["Комплекс оздоровительных процедур", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой массаж используется в СПА?", ["Ароматерапевтический", "Спортивный", "Классический", "Лечебный"], "A"),
        ("Что такое гидротерапия?", ["Лечение водой", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какая температура для гидромассажа?", ["37-40°C", "20-25°C", "45-50°C", "30-35°C"], "A"),
        ("Что такое талассотерапия?", ["Лечение морем", "Лечение травами", "Массаж", "Ароматерапия"], "A"),
        ("Для чего используется скраб в СПА?", ["Отшелушивание", "Увлажнение", "Питание", "Защита"], "A"),
        ("Что такое обертывание в СПА?", ["Нанесение масок с пленкой", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой эффект дает шоколадное обертывание?", ["Антицеллюлитный", "Омоложение", "Увлажнение", "Питание"], "A"),
        ("Что такое стоун-терапия?", ["Массаж камнями", "Массаж палками", "Массаж руками", "Массаж водой"], "A"),
        ("Какие масла используются в ароматерапии?", ["Эфирные", "Растительные", "Минеральные", "Синтетические"], "A"),
        ("Какой массаж считается расслабляющим?", ["Релаксирующий", "Спортивный", "Классический", "Лечебный"], "A"),
        ("Что такое баночный массаж?", ["Вакуумный массаж", "Ручной массаж", "Камневый массаж", "Водный массаж"], "A"),
        ("Какой массаж помогает при целлюлите?", ["Антицеллюлитный", "Релаксирующий", "Спортивный", "Точечный"], "A"),
        ("Что такое лимфодренажный массаж?", ["Улучшение лимфотока", "Расслабление", "Омоложение", "Лечение"], "A"),
        ("Что такое шиацу?", ["Точечный массаж", "Китайский массаж", "Тайский массаж", "Шведский массаж"], "A"),
        ("Какое обертывание помогает похудеть?", ["Водорослевое", "Шоколадное", "Грязевое", "Медовое"], "A"),
        ("Что такое горячее обертывание?", ["Обертывание с подогревом", "Холодное", "Сухое", "Влажное"], "A"),
        ("Что такое альгинатная маска?", ["Маска на основе водорослей", "Глиняная", "Шоколадная", "Фруктовая"], "A"),
        ("Какая маска увлажняет кожу?", ["Гидрогелевая", "Глиняная", "Грязевая", "Шоколадная"], "A"),
        ("Что такое ритуал 'Хаммам'?", ["Турецкая парная", "Финская сауна", "Японская баня", "Русская баня"], "A"),
        ("Что такое 'Кедровая бочка'?", ["Парная из кедра", "Массаж", "Обертывание", "Пилинг"], "A"),
        ("Что такое пилинг в СПА?", ["Отшелушивание кожи", "Увлажнение", "Питание", "Защита"], "A"),
        ("Для чего используется сыворотка?", ["Интенсивный уход", "Очищение", "Тонизирование", "Защита"], "A"),
        ("Что такое коллагеновая маска?", ["Маска для омоложения", "Увлажнения", "Очищения", "Питания"], "A"),
        ("Что такое микротоковая терапия?", ["Аппаратная косметология", "Массаж", "Пилинг", "Инъекции"], "A"),
        ("Что такое RF-лифтинг?", ["Радиочастотный лифтинг", "Лазерный", "Ультразвуковой", "Инъекционный"], "A"),
        ("Какое масло успокаивает нервную систему?", ["Лаванда", "Мята", "Лимон", "Розмарин"], "A"),
        ("Какое масло бодрит и тонизирует?", ["Мята", "Лаванда", "Роза", "Сандал"], "A"),
        ("Что такое диффузор?", ["Устройство для распыления масел", "Массажер", "Крем", "Лосьон"], "A"),
        ("Что такое душ Шарко?", ["Лечебный душ", "Контрастный", "Циркулярный", "Игольчатый"], "A"),
        ("Что такое контрастный душ?", ["Чередование горячей и холодной воды", "С солью", "С маслами", "С грязью"], "A"),
        ("Что такое гидромассажная ванна?", ["Ванна с водным массажем", "Обычная", "Грязевая", "Соляная"], "A"),
        ("Что такое криотерапия?", ["Лечение холодом", "Лечение теплом", "Лечение водой", "Лечение грязью"], "A"),
        ("Что такое озонотерапия?", ["Лечение озоном", "Лечение кислородом", "Лечение водой", "Лечение грязью"], "A"),
        ("Что такое анти-стресс программа?", ["Комплекс релаксации", "Похудения", "Омоложения", "Питания"], "A"),
        ("Что такое детокс-программа?", ["Очищение организма", "Питание", "Массаж", "Пилинг"], "A"),
        ("Что такое иглорефлексотерапия?", ["Лечение иглами", "Массаж", "Пилинг", "Инъекции"], "A"),
        ("Что такое мануальная терапия?", ["Лечение руками", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Что такое флоатинг?", ["Плавание в соляной камере", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое соляная комната?", ["Галотерапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое фитобочка?", ["Парная с травами", "Сауна", "Хаммам", "Офуро"], "A"),
        ("Что такое парафинотерапия?", ["Лечение парафином", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое брашинг?", ["Чистка щетками", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое альготерапия?", ["Лечение водорослями", "Грязью", "Травами", "Водой"], "A"),
        ("Что такое фитотерапия?", ["Лечение травами", "Водой", "Грязью", "Маслами"], "A"),
        ("Что такое глинолечение?", ["Лечение глиной", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое пелоидотерапия?", ["Лечение грязями", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое лазеротерапия?", ["Лечение лазером", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое магнитотерапия?", ["Лечение магнитным полем", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое ультразвук в СПА?", ["Ультразвуковая терапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое инфракрасная сауна?", ["Сауна с ИК-излучением", "Обычная", "Хаммам", "Офуро"], "A"),
        ("Что такое йога в СПА?", ["Йога в СПА-центре", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое медитация в СПА?", ["Медитация", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-питание?", ["Здоровое питание", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-капсула?", ["Косметическая капсула", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой массаж делают при остеохондрозе?", ["Лечебный", "Релаксирующий", "Спортивный", "Точечный"], "A"),
        ("Что такое вакуумная терапия?", ["Лечение вакуумом", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое прессотерапия?", ["Лечение давлением", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое дарсонваль?", ["Аппаратная косметология", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое биоревитализация?", ["Инъекции гиалуроновой кислоты", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое мезотерапия?", ["Инъекции витаминов", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое плазмолифтинг?", ["Инъекции плазмы", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое ботулинотерапия?", ["Инъекции ботокса", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое нитевой лифтинг?", ["Лифтинг нитями", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое контурная пластика?", ["Инъекции филлеров", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое офуро?", ["Японская баня", "Турецкая", "Финская", "Русская"], "A"),
        ("Что такое римская баня?", ["Парная с горячим паром", "Сауна", "Хаммам", "Ледяная"], "A"),
        ("Что такое снежная комната?", ["Комната с искусственным снегом", "Холодильная", "Парная", "Сауна"], "A"),
        ("Что такое СПА-маникюр?", ["Маникюр с СПА-процедурами", "Обычный", "Наращивание", "Педикюр"], "A"),
        ("Что такое СПА-педикюр?", ["Педикюр с СПА-процедурами", "Обычный", "Наращивание", "Маникюр"], "A"),
        ("Что такое кнеип-терапия?", ["Водная терапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое миофасциальный массаж?", ["Массаж фасций", "Массаж мышц", "Массаж связок", "Массаж суставов"], "A"),
        ("Какое масло используют при головной боли?", ["Мята", "Лаванда", "Роза", "Иланг-иланг"], "A"),
        ("Какое масло используют для релаксации?", ["Иланг-иланг", "Мята", "Лимон", "Розмарин"], "A"),
        ("Что такое ванна с морской солью?", ["Расслабляющая ванна", "Тонизирующая", "Лечебная", "Все варианты"], "D"),
        ("Какая температура в криокамере?", ["-150°C", "-60°C", "-100°C", "-200°C"], "A"),
        ("Что такое СПА-коктейль?", ["Напиток с витаминами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое эко-СПА?", ["СПА с натуральными продуктами", "Синтетический", "Химический", "Алкогольный"], "A"),
        ("Что такое фитнес-СПА?", ["СПА с фитнесом", "Просто СПА", "Массаж", "Пилинг"], "A"),
        ("Что такое остеопатия?", ["Лечение костей", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Какой массаж делают в перчатках?", ["Тайский", "Классический", "Спортивный", "Шведский"], "A"),
        ("Что такое тайский массаж?", ["Массаж с растяжкой", "Классический", "Спортивный", "Точечный"], "A"),
        ("Что такое шведский массаж?", ["Классический массаж", "Спортивный", "Тайский", "Точечный"], "A"),
        ("Что такое точечный массаж?", ["Массаж на точках", "Классический", "Спортивный", "Тайский"], "A"),
        ("Что такое детский массаж?", ["Массаж для детей", "Классический", "Спортивный", "Лечебный"], "A"),
        ("Что такое спортивный массаж?", ["Массаж для спортсменов", "Классический", "Релаксирующий", "Лечебный"], "A"),
        ("Что такое лечебный массаж?", ["Массаж для лечения", "Классический", "Релаксирующий", "Спортивный"], "A"),
        ("Что такое рефлексотерапия?", ["Лечение на точках", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Что такое апитерапия?", ["Лечение пчелами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое гирудотерапия?", ["Лечение пиявками", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое фиточай в СПА?", ["Чай с травами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-релакс?", ["Комплекс расслабления", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-оздоровление?", ["Комплекс оздоровления", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-красота?", ["Комплекс красоты", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-молодость?", ["Комплекс омоложения", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-гармония?", ["Комплекс гармонии", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какая вода используется в гидротерапии?", ["Минеральная", "Водопроводная", "Морская", "Дистиллированная"], "A"),
        ("Что такое сухая сауна?", ["Сауна с сухим паром", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое влажная сауна?", ["Сауна с влажным паром", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое финская сауна?", ["Сухая сауна", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое русская баня?", ["Влажная баня", "Хаммам", "Офуро", "Финская сауна"], "A"),
        ("Что такое японская баня?", ["Офуро", "Хаммам", "Сауна", "Русская баня"], "A"),
        ("Что такое турецкая баня?", ["Хаммам", "Офуро", "Сауна", "Русская баня"], "A")
    ]
    
    for q in questions_data:
        db.add_question(q[0], q[1], q[2], "СПА", 1)
    
    print(f"✅ Добавлено {len(questions_data)} вопросов по СПА-тематике")

# ===================== КЛАВИАТУРЫ =====================
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📝 Пройти викторину"))
    keyboard.add(KeyboardButton("📊 Мой рейтинг"))
    keyboard.add(KeyboardButton("🏆 Топ сотрудников"))
    
    if db.is_admin(user_id):
        keyboard.add(KeyboardButton("⚙️ Админ-панель"))
    
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📢 Сделать рассылку"))
    keyboard.add(KeyboardButton("➕ Добавить вопрос"))
    keyboard.add(KeyboardButton("✏️ Редактировать вопрос"))
    keyboard.add(KeyboardButton("❌ Удалить вопрос"))
    keyboard.add(KeyboardButton("👥 Все сотрудники"))
    keyboard.add(KeyboardButton("📊 Статистика"))
    keyboard.add(KeyboardButton("👑 Назначить админа"))
    keyboard.add(KeyboardButton("🔙 Назад в меню"))
    return keyboard

def get_question_keyboard(question_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    letters = ["A", "B", "C", "D"]
    for letter in letters:
        keyboard.insert(InlineKeyboardButton(letter, callback_data=f"answer_{letter}_{question_id}"))
    return keyboard

# ===================== ОБРАБОТЧИКИ =====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    employee = db.get_employee(user_id)
    
    if not employee:
        await message.answer(
            "👋 *Добро пожаловать в HR-бот для СПА-салона!*\n\n"
            "Здесь вы можете:\n"
            "✅ Пройти профессиональную викторину по СПА-тематике\n"
            "✅ Узнать свой рейтинг\n"
            "✅ Посмотреть топ сотрудников\n\n"
            "Для начала работы зарегистрируйтесь:",
            parse_mode="Markdown"
        )
        await message.answer("Введите ваше *полное имя* (ФИО):", parse_mode="Markdown")
        await RegistrationStates.waiting_for_name.set()
    else:
        await message.answer(
            f"👋 С возвращением, *{employee[1]}*!\n\n"
            f"📊 Попыток: {employee[5]}\n"
            f"🏆 Лучший результат: {employee[6]:.1f}%\n"
            f"⏱️ Лучшее время: {employee[7]} сек.\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )

# ===================== РЕГИСТРАЦИЯ =====================
@dp.message_handler(state=RegistrationStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Введите ваш *отдел* (например: СПА-зона, Массаж, Косметология):", parse_mode="Markdown")
    await RegistrationStates.waiting_for_department.set()

@dp.message_handler(state=RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await message.answer("Введите вашу *должность*:")
    await RegistrationStates.waiting_for_position.set()

@dp.message_handler(state=RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    
    db.register_employee(user_id, data['full_name'], data['department'], message.text)
    
    await state.finish()
    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"Имя: {data['full_name']}\n"
        f"Отдел: {data['department']}\n"
        f"Должность: {message.text}\n\n"
        f"Теперь вы можете пройти викторину!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

# ===================== ОСНОВНЫЕ КОМАНДЫ =====================
@dp.message_handler(lambda message: message.text in ["📝 Пройти викторину", "📊 Мой рейтинг", "🏆 Топ сотрудников", "⚙️ Админ-панель"])
async def handle_menu_buttons(message: types.Message):
    user_id = message.from_user.id
    
    if message.text == "📝 Пройти викторину":
        await start_quiz(message, user_id)
    elif message.text == "📊 Мой рейтинг":
        await show_user_results(message, user_id)
    elif message.text == "🏆 Топ сотрудников":
        await show_leaderboard(message)
    elif message.text == "⚙️ Админ-панель":
        if db.is_admin(user_id):
            await message.answer("⚙️ *Админ-панель*\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        else:
            await message.answer("⛔ У вас нет прав администратора.")

# ===================== ВИКТОРИНА =====================
async def start_quiz(message: types.Message, user_id):
    if db.count_questions() == 0:
        await message.answer("❌ Вопросы еще не загружены. Обратитесь к администратору.")
        return
    
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if questions and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_quiz"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="restart_quiz")
        )
        await message.answer("⏳ У вас есть незавершенная викторина.", reply_markup=keyboard)
        return
    
    all_questions = db.get_all_questions()
    selected = random.sample(all_questions, min(10, len(all_questions)))
    question_ids = [q[0] for q in selected]
    
    current_time = int(time.time())
    db.save_active_quiz(user_id, question_ids, 0, 0, 0, "СПА", current_time, current_time)
    
    await send_question(message, user_id, 0)

async def send_question(message: types.Message, user_id, index):
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions or index >= len(questions):
        await finish_quiz(message, user_id)
        return
    
    question_id = questions[index]
    question = db.get_question_by_id(question_id)
    
    if not question:
        await message.answer("❌ Ошибка загрузки вопроса.")
        return
    
    db.save_active_quiz(user_id, questions, index, correct_count, total_asked, category, start_time, int(time.time()))
    
    question_text = question[1]
    options = [question[2], question[3], question[4], question[5]]
    letters = ["A", "B", "C", "D"]
    
    text = f"📝 *Вопрос {index + 1} из {len(questions)}*\n\n"
    text += f"*{question_text}*\n\n"
    
    for i, option in enumerate(options):
        text += f"{letters[i]}) {option}\n"
    
    text += f"\n📂 Категория: {question[6]}"
    
    keyboard = get_question_keyboard(question_id)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('answer_'))
async def handle_answer(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    selected = data[1]
    question_id = int(data[2])
    
    question = db.get_question_by_id(question_id)
    if not question:
        await callback_query.answer("❌ Ошибка загрузки вопроса")
        return
    
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions:
        await callback_query.answer("❌ Викторина не найдена")
        return
    
    correct = question[6]
    is_correct = selected == correct
    
    if is_correct:
        correct_count += 1
    
    total_asked += 1
    current_index += 1
    
    db.save_active_quiz(user_id, questions, current_index, correct_count, total_asked, category, start_time, int(time.time()))
    
    await callback_query.answer()
    
    if is_correct:
        await callback_query.message.edit_text(
            callback_query.message.text + "\n\n✅ *Правильно!* 🎉",
            parse_mode="Markdown"
        )
    else:
        await callback_query.message.edit_text(
            callback_query.message.text + f"\n\n❌ *Неправильно!*\nПравильный ответ: {correct}",
            parse_mode="Markdown"
        )
    
    import asyncio
    await asyncio.sleep(1.5)
    await send_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'continue_quiz')
async def continue_quiz(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await send_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'restart_quiz')
async def restart_quiz(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    db.clear_active_quiz(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await start_quiz(callback_query.message, user_id)

async def finish_quiz(message: types.Message, user_id):
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions or total_asked == 0:
        await message.answer("❌ Викторина не была начата.")
        return
    
    time_spent = int(time.time()) - start_time
    score, passed, attempt_number = db.save_result(user_id, total_asked, correct_count, category, time_spent)
    db.clear_active_quiz(user_id)
    
    minutes = time_spent // 60
    seconds = time_spent % 60
    time_str = f"{minutes} мин. {seconds} сек." if minutes > 0 else f"{seconds} сек."
    
    result_text = f"🏁 *Результаты викторины*\n\n"
    result_text += f"📊 Правильных: {correct_count} из {total_asked}\n"
    result_text += f"📈 Результат: {score:.1f}%\n"
    result_text += f"⏱️ Время: {time_str}\n"
    result_text += f"🔄 Попытка №{attempt_number}\n\n"
    
    if passed:
        result_text += "✅ *ЗАЧЕТ!* Поздравляем! 🎉\n"
    else:
        result_text += "❌ *НЕЗАЧЕТ!*\nРекомендуем повторить материал."
    
    employee = db.get_employee(user_id)
    if employee:
        result_text += f"\n📊 Всего попыток: {employee[5]}"
        result_text += f"\n🏆 Лучший результат: {employee[6]:.1f}%"
        result_text += f"\n⏱️ Лучшее время: {employee[7]} сек." if employee[7] > 0 and employee[7] < 999999 else ""
    
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

# ===================== РЕЙТИНГИ =====================
async def show_user_results(message: types.Message, user_id):
    results = db.get_user_results(user_id)
    employee = db.get_employee(user_id)
    
    if not results:
        await message.answer("📊 У вас пока нет результатов. Пройдите викторину!")
        return
    
    text = f"📊 *История результатов*"
    text += f" для *{employee[1]}*\n\n" if employee else "\n\n"
    
    for i, result in enumerate(results, 1):
        date = datetime.fromisoformat(result[0]).strftime("%d.%m.%Y %H:%M")
        minutes = result[6] // 60
        seconds = result[6] % 60
        time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
        passed = "✅" if result[4] else "❌"
        text += f"#{result[7]}: {date} | {result[1]} вопр. | {result[2]} прав. | {result[3]:.1f}% | ⏱️{time_str} {passed}\n"
    
    avg_score = sum(r[3] for r in results) / len(results)
    best_score = max(r[3] for r in results)
    best_time = min(r[6] for r in results)
    passed_count = sum(1 for r in results if r[4])
    
    text += f"\n📈 *Статистика:*\n"
    text += f"📊 Средний: {avg_score:.1f}%\n"
    text += f"🏆 Лучший: {best_score:.1f}%\n"
    text += f"⏱️ Лучшее время: {best_time} сек.\n"
    text += f"✅ Зачетов: {passed_count} из {len(results)}"
    
    await message.answer(text, parse_mode="Markdown")

async def show_leaderboard(message: types.Message):
    leaderboard = db.get_leaderboard()
    
    if not leaderboard:
        await message.answer("🏆 Пока нет данных для рейтинга.")
        return
    
    text = "🏆 *Топ сотрудников*\n*(Меньше попыток и времени — лучше)*\n\n"
    
    for i, row in enumerate(leaderboard, 1):
        user_id, name, dept, total_attempts, best_score, best_time, attempts, avg_score, passed_count = row
        
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"{i}. "
        
        text += f"{medal}*{name}*\n"
        text += f"   📊 {dept}\n"
        text += f"   🔄 Попыток: {total_attempts}\n"
        text += f"   🏆 Лучший: {best_score:.1f}%\n"
        text += f"   ⏱️ Лучшее время: {best_time} сек.\n"
        text += f"   ✅ Зачетов: {passed_count}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# ===================== АДМИН-ПАНЕЛЬ =====================
@dp.message_handler(lambda message: message.text == "📢 Сделать рассылку")
async def broadcast_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    await message.answer("📢 Введите текст для рассылки всем сотрудникам:")
    await AdminStates.waiting_for_broadcast.set()

@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    employees = db.get_all_employees()
    sent = 0
    
    for user_id, name, dept, pos, attempts, score, time_best in employees:
        try:
            await bot.send_message(user_id, f"📢 *Объявление*\n\n{message.text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    
    await state.finish()
    await message.answer(f"✅ Рассылка отправлена {sent} сотрудникам.", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "➕ Добавить вопрос")
async def add_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    await message.answer(
        "📝 *Добавление вопроса*\n\n"
        "Формат: `Текст | A | B | C | D | Правильный ответ | Категория | Сложность`\n\n"
        "Пример: `Что такое СПА? | Комплекс процедур | Массаж | Пилинг | Ингаляция | A | СПА | 1`",
        parse_mode="Markdown"
    )
    await AdminStates.waiting_for_question_add.set()

@dp.message_handler(state=AdminStates.waiting_for_question_add)
async def process_add_question(message: types.Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 8:
            await message.answer("❌ Нужно 7 разделителей '|'")
            return
        
        db.add_question(parts[0], parts[1:5], parts[5].upper(), parts[6] if parts[6] else "СПА", int(parts[7]) if parts[7].isdigit() else 1)
        await state.finish()
        await message.answer("✅ Вопрос добавлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message_handler(lambda message: message.text == "✏️ Редактировать вопрос")
async def edit_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    questions = db.get_all_questions()
    if not questions:
        await message.answer("❌ Вопросов нет.")
        return
    
    text = "✏️ *Выберите вопрос для редактирования*\n\n"
    for q in questions[:20]:
        text += f"ID: {q[0]}. {q[1][:40]}...\n"
    
    text += "\nВведите ID вопроса:"
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_question_edit.set()

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
            f"Текущий: {question[1]}\n\n"
            "Введите новые данные в том же формате:\n"
            "`Текст | A | B | C | D | Правильный ответ | Категория | Сложность`",
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
        parts = [p.strip() for p in message.text.split('|')]
        
        if len(parts) != 8:
            await message.answer("❌ Неверный формат. Нужно 7 разделителей '|'")
            return
        
        db.update_question(question_id, parts[0], parts[1:5], parts[5].upper(), parts[6], int(parts[7]))
        await state.finish()
        await message.answer("✅ Вопрос обновлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message_handler(lambda message: message.text == "❌ Удалить вопрос")
async def delete_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    questions = db.get_all_questions()
    if not questions:
        await message.answer("❌ Вопросов нет.")
        return
    
    text = "❌ *Удаление вопроса*\n\n"
    for q in questions[:20]:
        text += f"ID: {q[0]}. {q[1][:40]}...\n"
    
    text += "\nВведите ID вопроса:"
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_question_delete.set()

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

@dp.message_handler(lambda message: message.text == "👥 Все сотрудники")
async def list_employees(message: types.Message):
    if not db.is_admin(message.from_user.id):
        return
    
    employees = db.get_all_employees()
    if not employees:
        await message.answer("👥 Сотрудников пока нет.")
        return
    
    text = "👥 *Список сотрудников*\n\n"
    for user_id, name, dept, pos, attempts, best_score, best_time in employees:
        text += f"👤 *{name}*\n"
        text += f"   📊 {dept} | {pos}\n"
        text += f"   🔄 {attempts} попыток\n"
        text += f"   🏆 {best_score:.1f}% | ⏱️ {best_time} сек.\n\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not db.is_admin(message.from_user.id):
        return
    
    stats = db.get_admin_stats()
    
    text = "📊 *Статистика системы*\n\n"
    text += f"👥 Сотрудников: {stats[0] or 0}\n"
    text += f"📝 Попыток: {stats[1] or 0}\n"
    text += f"📈 Средний балл: {stats[2] or 0:.1f}%\n"
    text += f"✅ Зачетов: {stats[3] or 0}\n"
    text += f"⏱️ Среднее время: {stats[4] or 0:.0f} сек.\n"
    text += f"⚡ Лучшее время: {stats[5] or 0} сек."
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "👑 Назначить админа")
async def assign_admin_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    employees = db.get_all_employees()
    if not employees:
        await message.answer("❌ Нет сотрудников.")
        return
    
    text = "👑 *Назначение администратора*\n\nВведите ID пользователя:\n\n"
    for user_id, name, dept, pos, attempts, score, time_best in employees:
        is_admin = db.is_admin(user_id)
        status = "✅ Админ" if is_admin else "👤 Сотрудник"
        text += f"ID: `{user_id}` | {name} | {status}\n"
    
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_admin_add.set()

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
    except:
        await message.answer("❌ Введите корректный ID (число).")

@dp.message_handler(lambda message: message.text == "🔙 Назад в меню")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    await message.answer("🔙 Возврат в главное меню", reply_markup=get_main_keyboard(user_id))

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("🚀 Запуск HR-бота для СПА-салона...")
    
    try:
        init_questions()
        print(f"✅ Бот запущен!")
        print(f"👤 Администраторы: {ADMINS}")
        print(f"📊 Всего вопросов: {db.count_questions()}")
        print("💬 Бот готов к работе...")
        
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        sys.exit(1)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
except ImportError:
    print("Установка aiogram...")
    os.system("pip install aiogram==2.25.1")
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.middlewares.logging import LoggingMiddleware
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
    from aiogram.utils import executor
    from aiogram.dispatcher import FSMContext
    from aiogram.dispatcher.filters.state import State, StatesGroup
    from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"  # ЗАМЕНИТЕ НА ВАШ ТОКЕН
ADMINS = [1024761707]  # ЗАМЕНИТЕ НА ВАШ TELEGRAM ID

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ===================== СОСТОЯНИЯ =====================
class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_department = State()
    waiting_for_position = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_delete = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                department TEXT,
                position TEXT,
                registered_at TEXT,
                is_admin INTEGER DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                best_score REAL DEFAULT 0,
                best_time INTEGER DEFAULT 999999
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_answer TEXT,
                category TEXT DEFAULT 'СПА',
                difficulty INTEGER DEFAULT 1
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                total_questions INTEGER,
                correct_answers INTEGER,
                score REAL,
                passed INTEGER,
                category TEXT,
                time_spent INTEGER,
                attempt_number INTEGER
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS active_quizzes (
                user_id INTEGER PRIMARY KEY,
                questions TEXT,
                current_index INTEGER,
                correct_count INTEGER,
                total_asked INTEGER,
                category TEXT,
                start_time INTEGER,
                question_start_time INTEGER
            )
        ''')
        self.conn.commit()
    
    # ---- Сотрудники ----
    def register_employee(self, user_id, full_name, department, position):
        self.cursor.execute('''
            INSERT OR REPLACE INTO employees (user_id, full_name, department, position, registered_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, full_name, department, position, datetime.now().isoformat()))
        self.conn.commit()
    
    def is_admin(self, user_id):
        self.cursor.execute('SELECT is_admin FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        return result is not None and result[0] == 1
    
    def get_employee(self, user_id):
        self.cursor.execute('SELECT * FROM employees WHERE user_id = ?', (user_id,))
        return self.cursor.fetchone()
    
    def get_all_employees(self):
        self.cursor.execute('SELECT user_id, full_name, department, position, total_attempts, best_score, best_time FROM employees ORDER BY full_name')
        return self.cursor.fetchall()
    
    def set_admin(self, user_id, is_admin=True):
        self.cursor.execute('UPDATE employees SET is_admin = ? WHERE user_id = ?', (1 if is_admin else 0, user_id))
        self.conn.commit()
    
    def update_stats(self, user_id, score, time_spent):
        self.cursor.execute('SELECT total_attempts, best_score, best_time FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            attempts = result[0] + 1
            best_score = max(result[1] or 0, score)
            best_time = min(result[2] or 999999, time_spent)
            self.cursor.execute('''
                UPDATE employees SET total_attempts = ?, best_score = ?, best_time = ?
                WHERE user_id = ?
            ''', (attempts, best_score, best_time, user_id))
            self.conn.commit()
    
    # ---- Вопросы ----
    def add_question(self, question_text, options, correct_answer, category="СПА", difficulty=1):
        self.cursor.execute('''
            INSERT INTO questions (question_text, option_a, option_b, option_c, option_d, correct_answer, category, difficulty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (question_text, options[0], options[1], options[2], options[3], correct_answer, category, difficulty))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_all_questions(self):
        self.cursor.execute('SELECT * FROM questions ORDER BY id')
        return self.cursor.fetchall()
    
    def get_question_by_id(self, question_id):
        self.cursor.execute('SELECT * FROM questions WHERE id = ?', (question_id,))
        return self.cursor.fetchone()
    
    def update_question(self, question_id, question_text, options, correct_answer, category, difficulty):
        self.cursor.execute('''
            UPDATE questions SET question_text = ?, option_a = ?, option_b = ?, option_c = ?, option_d = ?,
                correct_answer = ?, category = ?, difficulty = ?
            WHERE id = ?
        ''', (question_text, options[0], options[1], options[2], options[3], correct_answer, category, difficulty, question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('DELETE FROM questions WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def count_questions(self):
        self.cursor.execute('SELECT COUNT(*) FROM questions')
        return self.cursor.fetchone()[0]
    
    # ---- Результаты ----
    def save_result(self, user_id, total, correct, category, time_spent):
        score = (correct / total) * 100 if total > 0 else 0
        passed = 1 if score >= 70 else 0
        
        self.cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE user_id = ?', (user_id,))
        attempt_number = self.cursor.fetchone()[0] + 1
        
        self.cursor.execute('''
            INSERT INTO quiz_results (user_id, date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), total, correct, score, passed, category, time_spent, attempt_number))
        self.conn.commit()
        
        self.update_stats(user_id, score, time_spent)
        return score, passed, attempt_number
    
    def get_user_results(self, user_id, limit=20):
        self.cursor.execute('''
            SELECT date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number
            FROM quiz_results WHERE user_id = ? ORDER BY date DESC LIMIT ?
        ''', (user_id, limit))
        return self.cursor.fetchall()
    
    def get_leaderboard(self, limit=20):
        self.cursor.execute('''
            SELECT e.user_id, e.full_name, e.department, e.total_attempts, e.best_score, e.best_time,
                   COUNT(r.id) as attempts, AVG(r.score) as avg_score,
                   SUM(CASE WHEN r.passed = 1 THEN 1 ELSE 0 END) as passed_count
            FROM employees e
            LEFT JOIN quiz_results r ON e.user_id = r.user_id
            WHERE e.total_attempts > 0
            GROUP BY e.user_id
            ORDER BY e.total_attempts ASC, e.best_time ASC
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_admin_stats(self):
        self.cursor.execute('''
            SELECT COUNT(DISTINCT user_id), COUNT(*), AVG(score), SUM(CASE WHEN passed=1 THEN 1 ELSE 0 END),
                   AVG(time_spent), MIN(time_spent)
            FROM quiz_results
        ''')
        return self.cursor.fetchone()
    
    # ---- Активные викторины ----
    def save_active_quiz(self, user_id, question_ids, current_index, correct_count, total_asked, category, start_time, question_start_time):
        self.cursor.execute('''
            INSERT OR REPLACE INTO active_quizzes (user_id, questions, current_index, correct_count, total_asked, category, start_time, question_start_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, json.dumps(question_ids), current_index, correct_count, total_asked, category, start_time, question_start_time))
        self.conn.commit()
    
    def get_active_quiz(self, user_id):
        self.cursor.execute('SELECT questions, current_index, correct_count, total_asked, category, start_time, question_start_time FROM active_quizzes WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        if result:
            return json.loads(result[0]), result[1], result[2], result[3], result[4], result[5], result[6]
        return None, 0, 0, 0, None, None, None
    
    def clear_active_quiz(self, user_id):
        self.cursor.execute('DELETE FROM active_quizzes WHERE user_id = ?', (user_id,))
        self.conn.commit()

# ===================== ИНИЦИАЛИЗАЦИЯ БД =====================
db = Database()

# ===================== 100 ВОПРОСОВ ПО СПА =====================
def init_questions():
    if db.count_questions() > 0:
        return
    
    questions_data = [
        ("Что такое СПА-процедура?", ["Комплекс оздоровительных процедур", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой массаж используется в СПА?", ["Ароматерапевтический", "Спортивный", "Классический", "Лечебный"], "A"),
        ("Что такое гидротерапия?", ["Лечение водой", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какая температура для гидромассажа?", ["37-40°C", "20-25°C", "45-50°C", "30-35°C"], "A"),
        ("Что такое талассотерапия?", ["Лечение морем", "Лечение травами", "Массаж", "Ароматерапия"], "A"),
        ("Для чего используется скраб в СПА?", ["Отшелушивание", "Увлажнение", "Питание", "Защита"], "A"),
        ("Что такое обертывание в СПА?", ["Нанесение масок с пленкой", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой эффект дает шоколадное обертывание?", ["Антицеллюлитный", "Омоложение", "Увлажнение", "Питание"], "A"),
        ("Что такое стоун-терапия?", ["Массаж камнями", "Массаж палками", "Массаж руками", "Массаж водой"], "A"),
        ("Какие масла используются в ароматерапии?", ["Эфирные", "Растительные", "Минеральные", "Синтетические"], "A"),
        ("Какой массаж считается расслабляющим?", ["Релаксирующий", "Спортивный", "Классический", "Лечебный"], "A"),
        ("Что такое баночный массаж?", ["Вакуумный массаж", "Ручной массаж", "Камневый массаж", "Водный массаж"], "A"),
        ("Какой массаж помогает при целлюлите?", ["Антицеллюлитный", "Релаксирующий", "Спортивный", "Точечный"], "A"),
        ("Что такое лимфодренажный массаж?", ["Улучшение лимфотока", "Расслабление", "Омоложение", "Лечение"], "A"),
        ("Что такое шиацу?", ["Точечный массаж", "Китайский массаж", "Тайский массаж", "Шведский массаж"], "A"),
        ("Какое обертывание помогает похудеть?", ["Водорослевое", "Шоколадное", "Грязевое", "Медовое"], "A"),
        ("Что такое горячее обертывание?", ["Обертывание с подогревом", "Холодное", "Сухое", "Влажное"], "A"),
        ("Что такое альгинатная маска?", ["Маска на основе водорослей", "Глиняная", "Шоколадная", "Фруктовая"], "A"),
        ("Какая маска увлажняет кожу?", ["Гидрогелевая", "Глиняная", "Грязевая", "Шоколадная"], "A"),
        ("Что такое ритуал 'Хаммам'?", ["Турецкая парная", "Финская сауна", "Японская баня", "Русская баня"], "A"),
        ("Что такое 'Кедровая бочка'?", ["Парная из кедра", "Массаж", "Обертывание", "Пилинг"], "A"),
        ("Что такое пилинг в СПА?", ["Отшелушивание кожи", "Увлажнение", "Питание", "Защита"], "A"),
        ("Для чего используется сыворотка?", ["Интенсивный уход", "Очищение", "Тонизирование", "Защита"], "A"),
        ("Что такое коллагеновая маска?", ["Маска для омоложения", "Увлажнения", "Очищения", "Питания"], "A"),
        ("Что такое микротоковая терапия?", ["Аппаратная косметология", "Массаж", "Пилинг", "Инъекции"], "A"),
        ("Что такое RF-лифтинг?", ["Радиочастотный лифтинг", "Лазерный", "Ультразвуковой", "Инъекционный"], "A"),
        ("Какое масло успокаивает нервную систему?", ["Лаванда", "Мята", "Лимон", "Розмарин"], "A"),
        ("Какое масло бодрит и тонизирует?", ["Мята", "Лаванда", "Роза", "Сандал"], "A"),
        ("Что такое диффузор?", ["Устройство для распыления масел", "Массажер", "Крем", "Лосьон"], "A"),
        ("Что такое душ Шарко?", ["Лечебный душ", "Контрастный", "Циркулярный", "Игольчатый"], "A"),
        ("Что такое контрастный душ?", ["Чередование горячей и холодной воды", "С солью", "С маслами", "С грязью"], "A"),
        ("Что такое гидромассажная ванна?", ["Ванна с водным массажем", "Обычная", "Грязевая", "Соляная"], "A"),
        ("Что такое криотерапия?", ["Лечение холодом", "Лечение теплом", "Лечение водой", "Лечение грязью"], "A"),
        ("Что такое озонотерапия?", ["Лечение озоном", "Лечение кислородом", "Лечение водой", "Лечение грязью"], "A"),
        ("Что такое анти-стресс программа?", ["Комплекс релаксации", "Похудения", "Омоложения", "Питания"], "A"),
        ("Что такое детокс-программа?", ["Очищение организма", "Питание", "Массаж", "Пилинг"], "A"),
        ("Что такое иглорефлексотерапия?", ["Лечение иглами", "Массаж", "Пилинг", "Инъекции"], "A"),
        ("Что такое мануальная терапия?", ["Лечение руками", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Что такое флоатинг?", ["Плавание в соляной камере", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое соляная комната?", ["Галотерапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое фитобочка?", ["Парная с травами", "Сауна", "Хаммам", "Офуро"], "A"),
        ("Что такое парафинотерапия?", ["Лечение парафином", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое брашинг?", ["Чистка щетками", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое альготерапия?", ["Лечение водорослями", "Грязью", "Травами", "Водой"], "A"),
        ("Что такое фитотерапия?", ["Лечение травами", "Водой", "Грязью", "Маслами"], "A"),
        ("Что такое глинолечение?", ["Лечение глиной", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое пелоидотерапия?", ["Лечение грязями", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое лазеротерапия?", ["Лечение лазером", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое магнитотерапия?", ["Лечение магнитным полем", "Водой", "Травами", "Маслами"], "A"),
        ("Что такое ультразвук в СПА?", ["Ультразвуковая терапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое инфракрасная сауна?", ["Сауна с ИК-излучением", "Обычная", "Хаммам", "Офуро"], "A"),
        ("Что такое йога в СПА?", ["Йога в СПА-центре", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое медитация в СПА?", ["Медитация", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-питание?", ["Здоровое питание", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-капсула?", ["Косметическая капсула", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какой массаж делают при остеохондрозе?", ["Лечебный", "Релаксирующий", "Спортивный", "Точечный"], "A"),
        ("Что такое вакуумная терапия?", ["Лечение вакуумом", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое прессотерапия?", ["Лечение давлением", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое дарсонваль?", ["Аппаратная косметология", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое биоревитализация?", ["Инъекции гиалуроновой кислоты", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое мезотерапия?", ["Инъекции витаминов", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое плазмолифтинг?", ["Инъекции плазмы", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое ботулинотерапия?", ["Инъекции ботокса", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое нитевой лифтинг?", ["Лифтинг нитями", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое контурная пластика?", ["Инъекции филлеров", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое офуро?", ["Японская баня", "Турецкая", "Финская", "Русская"], "A"),
        ("Что такое римская баня?", ["Парная с горячим паром", "Сауна", "Хаммам", "Ледяная"], "A"),
        ("Что такое снежная комната?", ["Комната с искусственным снегом", "Холодильная", "Парная", "Сауна"], "A"),
        ("Что такое СПА-маникюр?", ["Маникюр с СПА-процедурами", "Обычный", "Наращивание", "Педикюр"], "A"),
        ("Что такое СПА-педикюр?", ["Педикюр с СПА-процедурами", "Обычный", "Наращивание", "Маникюр"], "A"),
        ("Что такое кнеип-терапия?", ["Водная терапия", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое миофасциальный массаж?", ["Массаж фасций", "Массаж мышц", "Массаж связок", "Массаж суставов"], "A"),
        ("Какое масло используют при головной боли?", ["Мята", "Лаванда", "Роза", "Иланг-иланг"], "A"),
        ("Какое масло используют для релаксации?", ["Иланг-иланг", "Мята", "Лимон", "Розмарин"], "A"),
        ("Что такое ванна с морской солью?", ["Расслабляющая ванна", "Тонизирующая", "Лечебная", "Все варианты"], "D"),
        ("Какая температура в криокамере?", ["-150°C", "-60°C", "-100°C", "-200°C"], "A"),
        ("Что такое СПА-коктейль?", ["Напиток с витаминами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое эко-СПА?", ["СПА с натуральными продуктами", "Синтетический", "Химический", "Алкогольный"], "A"),
        ("Что такое фитнес-СПА?", ["СПА с фитнесом", "Просто СПА", "Массаж", "Пилинг"], "A"),
        ("Что такое остеопатия?", ["Лечение костей", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Какой массаж делают в перчатках?", ["Тайский", "Классический", "Спортивный", "Шведский"], "A"),
        ("Что такое тайский массаж?", ["Массаж с растяжкой", "Классический", "Спортивный", "Точечный"], "A"),
        ("Что такое шведский массаж?", ["Классический массаж", "Спортивный", "Тайский", "Точечный"], "A"),
        ("Что такое точечный массаж?", ["Массаж на точках", "Классический", "Спортивный", "Тайский"], "A"),
        ("Что такое детский массаж?", ["Массаж для детей", "Классический", "Спортивный", "Лечебный"], "A"),
        ("Что такое спортивный массаж?", ["Массаж для спортсменов", "Классический", "Релаксирующий", "Лечебный"], "A"),
        ("Что такое лечебный массаж?", ["Массаж для лечения", "Классический", "Релаксирующий", "Спортивный"], "A"),
        ("Что такое рефлексотерапия?", ["Лечение на точках", "Массаж", "Гимнастика", "Лечение водой"], "A"),
        ("Что такое апитерапия?", ["Лечение пчелами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое гирудотерапия?", ["Лечение пиявками", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое фиточай в СПА?", ["Чай с травами", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-релакс?", ["Комплекс расслабления", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-оздоровление?", ["Комплекс оздоровления", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-красота?", ["Комплекс красоты", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-молодость?", ["Комплекс омоложения", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Что такое СПА-гармония?", ["Комплекс гармонии", "Массаж", "Пилинг", "Ингаляция"], "A"),
        ("Какая вода используется в гидротерапии?", ["Минеральная", "Водопроводная", "Морская", "Дистиллированная"], "A"),
        ("Что такое сухая сауна?", ["Сауна с сухим паром", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое влажная сауна?", ["Сауна с влажным паром", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое финская сауна?", ["Сухая сауна", "Хаммам", "Офуро", "Русская баня"], "A"),
        ("Что такое русская баня?", ["Влажная баня", "Хаммам", "Офуро", "Финская сауна"], "A"),
        ("Что такое японская баня?", ["Офуро", "Хаммам", "Сауна", "Русская баня"], "A"),
        ("Что такое турецкая баня?", ["Хаммам", "Офуро", "Сауна", "Русская баня"], "A")
    ]
    
    for q in questions_data:
        db.add_question(q[0], q[1], q[2], "СПА", 1)
    
    print(f"✅ Добавлено {len(questions_data)} вопросов по СПА-тематике")

# ===================== КЛАВИАТУРЫ =====================
def get_main_keyboard(user_id):
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📝 Пройти викторину"))
    keyboard.add(KeyboardButton("📊 Мой рейтинг"))
    keyboard.add(KeyboardButton("🏆 Топ сотрудников"))
    
    if db.is_admin(user_id):
        keyboard.add(KeyboardButton("⚙️ Админ-панель"))
    
    return keyboard

def get_admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📢 Сделать рассылку"))
    keyboard.add(KeyboardButton("➕ Добавить вопрос"))
    keyboard.add(KeyboardButton("✏️ Редактировать вопрос"))
    keyboard.add(KeyboardButton("❌ Удалить вопрос"))
    keyboard.add(KeyboardButton("👥 Все сотрудники"))
    keyboard.add(KeyboardButton("📊 Статистика"))
    keyboard.add(KeyboardButton("👑 Назначить админа"))
    keyboard.add(KeyboardButton("🔙 Назад в меню"))
    return keyboard

def get_question_keyboard(question_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    letters = ["A", "B", "C", "D"]
    for letter in letters:
        keyboard.insert(InlineKeyboardButton(letter, callback_data=f"answer_{letter}_{question_id}"))
    return keyboard

# ===================== ОБРАБОТЧИКИ =====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    employee = db.get_employee(user_id)
    
    if not employee:
        await message.answer(
            "👋 *Добро пожаловать в HR-бот для СПА-салона!*\n\n"
            "Здесь вы можете:\n"
            "✅ Пройти профессиональную викторину по СПА-тематике\n"
            "✅ Узнать свой рейтинг\n"
            "✅ Посмотреть топ сотрудников\n\n"
            "Для начала работы зарегистрируйтесь:",
            parse_mode="Markdown"
        )
        await message.answer("Введите ваше *полное имя* (ФИО):", parse_mode="Markdown")
        await RegistrationStates.waiting_for_name.set()
    else:
        await message.answer(
            f"👋 С возвращением, *{employee[1]}*!\n\n"
            f"📊 Попыток: {employee[5]}\n"
            f"🏆 Лучший результат: {employee[6]:.1f}%\n"
            f"⏱️ Лучшее время: {employee[7]} сек.\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )

# ===================== РЕГИСТРАЦИЯ =====================
@dp.message_handler(state=RegistrationStates.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Введите ваш *отдел* (например: СПА-зона, Массаж, Косметология):", parse_mode="Markdown")
    await RegistrationStates.waiting_for_department.set()

@dp.message_handler(state=RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await message.answer("Введите вашу *должность*:")
    await RegistrationStates.waiting_for_position.set()

@dp.message_handler(state=RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    
    db.register_employee(user_id, data['full_name'], data['department'], message.text)
    
    await state.finish()
    await message.answer(
        f"✅ *Регистрация завершена!*\n\n"
        f"Имя: {data['full_name']}\n"
        f"Отдел: {data['department']}\n"
        f"Должность: {message.text}\n\n"
        f"Теперь вы можете пройти викторину!",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )

# ===================== ОСНОВНЫЕ КОМАНДЫ =====================
@dp.message_handler(lambda message: message.text in ["📝 Пройти викторину", "📊 Мой рейтинг", "🏆 Топ сотрудников", "⚙️ Админ-панель"])
async def handle_menu_buttons(message: types.Message):
    user_id = message.from_user.id
    
    if message.text == "📝 Пройти викторину":
        await start_quiz(message, user_id)
    elif message.text == "📊 Мой рейтинг":
        await show_user_results(message, user_id)
    elif message.text == "🏆 Топ сотрудников":
        await show_leaderboard(message)
    elif message.text == "⚙️ Админ-панель":
        if db.is_admin(user_id):
            await message.answer("⚙️ *Админ-панель*\n\nВыберите действие:", parse_mode="Markdown", reply_markup=get_admin_keyboard())
        else:
            await message.answer("⛔ У вас нет прав администратора.")

# ===================== ВИКТОРИНА =====================
async def start_quiz(message: types.Message, user_id):
    if db.count_questions() == 0:
        await message.answer("❌ Вопросы еще не загружены. Обратитесь к администратору.")
        return
    
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if questions and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_quiz"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="restart_quiz")
        )
        await message.answer("⏳ У вас есть незавершенная викторина.", reply_markup=keyboard)
        return
    
    all_questions = db.get_all_questions()
    selected = random.sample(all_questions, min(10, len(all_questions)))
    question_ids = [q[0] for q in selected]
    
    current_time = int(time.time())
    db.save_active_quiz(user_id, question_ids, 0, 0, 0, "СПА", current_time, current_time)
    
    await send_question(message, user_id, 0)

async def send_question(message: types.Message, user_id, index):
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions or index >= len(questions):
        await finish_quiz(message, user_id)
        return
    
    question_id = questions[index]
    question = db.get_question_by_id(question_id)
    
    if not question:
        await message.answer("❌ Ошибка загрузки вопроса.")
        return
    
    db.save_active_quiz(user_id, questions, index, correct_count, total_asked, category, start_time, int(time.time()))
    
    question_text = question[1]
    options = [question[2], question[3], question[4], question[5]]
    letters = ["A", "B", "C", "D"]
    
    text = f"📝 *Вопрос {index + 1} из {len(questions)}*\n\n"
    text += f"*{question_text}*\n\n"
    
    for i, option in enumerate(options):
        text += f"{letters[i]}) {option}\n"
    
    text += f"\n📂 Категория: {question[6]}"
    
    keyboard = get_question_keyboard(question_id)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('answer_'))
async def handle_answer(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split('_')
    selected = data[1]
    question_id = int(data[2])
    
    question = db.get_question_by_id(question_id)
    if not question:
        await callback_query.answer("❌ Ошибка загрузки вопроса")
        return
    
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions:
        await callback_query.answer("❌ Викторина не найдена")
        return
    
    correct = question[6]
    is_correct = selected == correct
    
    if is_correct:
        correct_count += 1
    
    total_asked += 1
    current_index += 1
    
    db.save_active_quiz(user_id, questions, current_index, correct_count, total_asked, category, start_time, int(time.time()))
    
    await callback_query.answer()
    
    if is_correct:
        await callback_query.message.edit_text(
            callback_query.message.text + "\n\n✅ *Правильно!* 🎉",
            parse_mode="Markdown"
        )
    else:
        await callback_query.message.edit_text(
            callback_query.message.text + f"\n\n❌ *Неправильно!*\nПравильный ответ: {correct}",
            parse_mode="Markdown"
        )
    
    import asyncio
    await asyncio.sleep(1.5)
    await send_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'continue_quiz')
async def continue_quiz(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await send_question(callback_query.message, user_id, current_index)

@dp.callback_query_handler(lambda c: c.data == 'restart_quiz')
async def restart_quiz(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    db.clear_active_quiz(user_id)
    
    await callback_query.answer()
    await callback_query.message.delete()
    await start_quiz(callback_query.message, user_id)

async def finish_quiz(message: types.Message, user_id):
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions or total_asked == 0:
        await message.answer("❌ Викторина не была начата.")
        return
    
    time_spent = int(time.time()) - start_time
    score, passed, attempt_number = db.save_result(user_id, total_asked, correct_count, category, time_spent)
    db.clear_active_quiz(user_id)
    
    minutes = time_spent // 60
    seconds = time_spent % 60
    time_str = f"{minutes} мин. {seconds} сек." if minutes > 0 else f"{seconds} сек."
    
    result_text = f"🏁 *Результаты викторины*\n\n"
    result_text += f"📊 Правильных: {correct_count} из {total_asked}\n"
    result_text += f"📈 Результат: {score:.1f}%\n"
    result_text += f"⏱️ Время: {time_str}\n"
    result_text += f"🔄 Попытка №{attempt_number}\n\n"
    
    if passed:
        result_text += "✅ *ЗАЧЕТ!* Поздравляем! 🎉\n"
    else:
        result_text += "❌ *НЕЗАЧЕТ!*\nРекомендуем повторить материал."
    
    employee = db.get_employee(user_id)
    if employee:
        result_text += f"\n📊 Всего попыток: {employee[5]}"
        result_text += f"\n🏆 Лучший результат: {employee[6]:.1f}%"
        result_text += f"\n⏱️ Лучшее время: {employee[7]} сек." if employee[7] > 0 and employee[7] < 999999 else ""
    
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

# ===================== РЕЙТИНГИ =====================
async def show_user_results(message: types.Message, user_id):
    results = db.get_user_results(user_id)
    employee = db.get_employee(user_id)
    
    if not results:
        await message.answer("📊 У вас пока нет результатов. Пройдите викторину!")
        return
    
    text = f"📊 *История результатов*"
    text += f" для *{employee[1]}*\n\n" if employee else "\n\n"
    
    for i, result in enumerate(results, 1):
        date = datetime.fromisoformat(result[0]).strftime("%d.%m.%Y %H:%M")
        minutes = result[6] // 60
        seconds = result[6] % 60
        time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
        passed = "✅" if result[4] else "❌"
        text += f"#{result[7]}: {date} | {result[1]} вопр. | {result[2]} прав. | {result[3]:.1f}% | ⏱️{time_str} {passed}\n"
    
    avg_score = sum(r[3] for r in results) / len(results)
    best_score = max(r[3] for r in results)
    best_time = min(r[6] for r in results)
    passed_count = sum(1 for r in results if r[4])
    
    text += f"\n📈 *Статистика:*\n"
    text += f"📊 Средний: {avg_score:.1f}%\n"
    text += f"🏆 Лучший: {best_score:.1f}%\n"
    text += f"⏱️ Лучшее время: {best_time} сек.\n"
    text += f"✅ Зачетов: {passed_count} из {len(results)}"
    
    await message.answer(text, parse_mode="Markdown")

async def show_leaderboard(message: types.Message):
    leaderboard = db.get_leaderboard()
    
    if not leaderboard:
        await message.answer("🏆 Пока нет данных для рейтинга.")
        return
    
    text = "🏆 *Топ сотрудников*\n*(Меньше попыток и времени — лучше)*\n\n"
    
    for i, row in enumerate(leaderboard, 1):
        user_id, name, dept, total_attempts, best_score, best_time, attempts, avg_score, passed_count = row
        
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else f"{i}. "
        
        text += f"{medal}*{name}*\n"
        text += f"   📊 {dept}\n"
        text += f"   🔄 Попыток: {total_attempts}\n"
        text += f"   🏆 Лучший: {best_score:.1f}%\n"
        text += f"   ⏱️ Лучшее время: {best_time} сек.\n"
        text += f"   ✅ Зачетов: {passed_count}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# ===================== АДМИН-ПАНЕЛЬ =====================
@dp.message_handler(lambda message: message.text == "📢 Сделать рассылку")
async def broadcast_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    await message.answer("📢 Введите текст для рассылки всем сотрудникам:")
    await AdminStates.waiting_for_broadcast.set()

@dp.message_handler(state=AdminStates.waiting_for_broadcast)
async def process_broadcast(message: types.Message, state: FSMContext):
    employees = db.get_all_employees()
    sent = 0
    
    for user_id, name, dept, pos, attempts, score, time_best in employees:
        try:
            await bot.send_message(user_id, f"📢 *Объявление*\n\n{message.text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    
    await state.finish()
    await message.answer(f"✅ Рассылка отправлена {sent} сотрудникам.", reply_markup=get_admin_keyboard())

@dp.message_handler(lambda message: message.text == "➕ Добавить вопрос")
async def add_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    await message.answer(
        "📝 *Добавление вопроса*\n\n"
        "Формат: `Текст | A | B | C | D | Правильный ответ | Категория | Сложность`\n\n"
        "Пример: `Что такое СПА? | Комплекс процедур | Массаж | Пилинг | Ингаляция | A | СПА | 1`",
        parse_mode="Markdown"
    )
    await AdminStates.waiting_for_question_add.set()

@dp.message_handler(state=AdminStates.waiting_for_question_add)
async def process_add_question(message: types.Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 8:
            await message.answer("❌ Нужно 7 разделителей '|'")
            return
        
        db.add_question(parts[0], parts[1:5], parts[5].upper(), parts[6] if parts[6] else "СПА", int(parts[7]) if parts[7].isdigit() else 1)
        await state.finish()
        await message.answer("✅ Вопрос добавлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message_handler(lambda message: message.text == "✏️ Редактировать вопрос")
async def edit_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    questions = db.get_all_questions()
    if not questions:
        await message.answer("❌ Вопросов нет.")
        return
    
    text = "✏️ *Выберите вопрос для редактирования*\n\n"
    for q in questions[:20]:
        text += f"ID: {q[0]}. {q[1][:40]}...\n"
    
    text += "\nВведите ID вопроса:"
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_question_edit.set()

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
            f"Текущий: {question[1]}\n\n"
            "Введите новые данные в том же формате:",
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
        parts = [p.strip() for p in message.text.split('|')]
        
        if len(parts) != 8:
            await message.answer("❌ Неверный формат.")
            return
        
        db.update_question(question_id, parts[0], parts[1:5], parts[5].upper(), parts[6], int(parts[7]))
        await state.finish()
        await message.answer("✅ Вопрос обновлен!", reply_markup=get_admin_keyboard())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.message_handler(lambda message: message.text == "❌ Удалить вопрос")
async def delete_question_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    questions = db.get_all_questions()
    if not questions:
        await message.answer("❌ Вопросов нет.")
        return
    
    text = "❌ *Удаление вопроса*\n\n"
    for q in questions[:20]:
        text += f"ID: {q[0]}. {q[1][:40]}...\n"
    
    text += "\nВведите ID вопроса:"
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_question_delete.set()

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

@dp.message_handler(lambda message: message.text == "👥 Все сотрудники")
async def list_employees(message: types.Message):
    if not db.is_admin(message.from_user.id):
        return
    
    employees = db.get_all_employees()
    if not employees:
        await message.answer("👥 Сотрудников пока нет.")
        return
    
    text = "👥 *Список сотрудников*\n\n"
    for user_id, name, dept, pos, attempts, best_score, best_time in employees:
        text += f"👤 *{name}*\n"
        text += f"   📊 {dept} | {pos}\n"
        text += f"   🔄 {attempts} попыток\n"
        text += f"   🏆 {best_score:.1f}% | ⏱️ {best_time} сек.\n\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not db.is_admin(message.from_user.id):
        return
    
    stats = db.get_admin_stats()
    
    text = "📊 *Статистика системы*\n\n"
    text += f"👥 Сотрудников: {stats[0] or 0}\n"
    text += f"📝 Попыток: {stats[1] or 0}\n"
    text += f"📈 Средний балл: {stats[2] or 0:.1f}%\n"
    text += f"✅ Зачетов: {stats[3] or 0}\n"
    text += f"⏱️ Среднее время: {stats[4] or 0:.0f} сек.\n"
    text += f"⚡ Лучшее время: {stats[5] or 0} сек."
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "👑 Назначить админа")
async def assign_admin_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    employees = db.get_all_employees()
    if not employees:
        await message.answer("❌ Нет сотрудников.")
        return
    
    text = "👑 *Назначение администратора*\n\nВведите ID пользователя:\n\n"
    for user_id, name, dept, pos, attempts, score, time_best in employees:
        is_admin = db.is_admin(user_id)
        status = "✅ Админ" if is_admin else "👤 Сотрудник"
        text += f"ID: `{user_id}` | {name} | {status}\n"
    
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_admin_add.set()

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
    except:
        await message.answer("❌ Введите корректный ID (число).")

@dp.message_handler(lambda message: message.text == "🔙 Назад в меню")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    await message.answer("🔙 Возврат в главное меню", reply_markup=get_main_keyboard(user_id))

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    print("🚀 Запуск HR-бота для СПА-салона...")
    
    try:
        init_questions()
        print(f"✅ Бот запущен!")
        print(f"👤 Администраторы: {ADMINS}")
        print(f"📊 Всего вопросов: {db.count_questions()}")
        print("💬 Бот готов к работе...")
        
        executor.start_polling(dp, skip_updates=True)
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")
        sys.exit(1)
