import sqlite3
import random
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
import logging
import json

# ===================== КОНФИГУРАЦИЯ =====================
BOT_TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"  # Замените на ваш токен
ADMINS = [1024761707]  # Замените на ваш Telegram ID

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(level=logging.INFO)
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ===================== СОСТОЯНИЯ FSM =====================
class QuizStates(StatesGroup):
    waiting_for_start = State()
    answering = State()
    waiting_for_result = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_question_add = State()
    waiting_for_question_edit = State()
    waiting_for_question_delete = State()
    waiting_for_admin_add = State()
    waiting_for_admin_remove = State()

class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_department = State()
    waiting_for_position = State()

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('hr_bot.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        # Таблица сотрудников
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS employees (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                department TEXT,
                position TEXT,
                registered_at TEXT,
                is_admin BOOLEAN DEFAULT 0,
                total_attempts INTEGER DEFAULT 0,
                best_score REAL DEFAULT 0,
                best_time INTEGER DEFAULT 0
            )
        ''')
        
        # Таблица вопросов
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_answer TEXT,
                category TEXT,
                difficulty INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица результатов с временем
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                total_questions INTEGER,
                correct_answers INTEGER,
                score REAL,
                passed BOOLEAN,
                category TEXT,
                time_spent INTEGER,  -- время в секундах
                attempt_number INTEGER
            )
        ''')
        
        # Таблица активных викторин
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
    
    # ----- Работа с сотрудниками -----
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
        self.cursor.execute('UPDATE employees SET is_admin = ? WHERE user_id = ?', (is_admin, user_id))
        self.conn.commit()
    
    def update_employee_stats(self, user_id, score, time_spent):
        self.cursor.execute('SELECT total_attempts, best_score, best_time FROM employees WHERE user_id = ?', (user_id,))
        result = self.cursor.fetchone()
        
        if result:
            attempts = result[0] + 1
            best_score = max(result[1], score) if result[1] else score
            best_time = min(result[2], time_spent) if result[2] and result[2] > 0 else time_spent
            
            self.cursor.execute('''
                UPDATE employees 
                SET total_attempts = ?, best_score = ?, best_time = ?
                WHERE user_id = ?
            ''', (attempts, best_score, best_time, user_id))
            self.conn.commit()
    
    # ----- Работа с вопросами -----
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
            UPDATE questions 
            SET question_text = ?, option_a = ?, option_b = ?, option_c = ?, option_d = ?, 
                correct_answer = ?, category = ?, difficulty = ?
            WHERE id = ?
        ''', (question_text, options[0], options[1], options[2], options[3], correct_answer, category, difficulty, question_id))
        self.conn.commit()
    
    def delete_question(self, question_id):
        self.cursor.execute('DELETE FROM questions WHERE id = ?', (question_id,))
        self.conn.commit()
    
    def get_questions_by_category(self, category):
        self.cursor.execute('SELECT * FROM questions WHERE category = ? ORDER BY RANDOM()', (category,))
        return self.cursor.fetchall()
    
    def get_all_categories(self):
        self.cursor.execute('SELECT DISTINCT category FROM questions')
        return [row[0] for row in self.cursor.fetchall()]
    
    def count_questions(self):
        self.cursor.execute('SELECT COUNT(*) FROM questions')
        return self.cursor.fetchone()[0]
    
    # ----- Работа с результатами -----
    def save_result(self, user_id, total, correct, category, time_spent):
        score = (correct / total) * 100 if total > 0 else 0
        passed = score >= 70
        
        # Получаем номер попытки
        self.cursor.execute('SELECT COUNT(*) FROM quiz_results WHERE user_id = ?', (user_id,))
        attempt_number = self.cursor.fetchone()[0] + 1
        
        self.cursor.execute('''
            INSERT INTO quiz_results (user_id, date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, datetime.now().isoformat(), total, correct, score, passed, category, time_spent, attempt_number))
        self.conn.commit()
        
        # Обновляем статистику сотрудника
        self.update_employee_stats(user_id, score, time_spent)
        
        return score, passed, attempt_number
    
    def get_user_results(self, user_id, limit=20):
        self.cursor.execute('''
            SELECT date, total_questions, correct_answers, score, passed, category, time_spent, attempt_number 
            FROM quiz_results 
            WHERE user_id = ? 
            ORDER BY date DESC 
            LIMIT ?
        ''', (user_id, limit))
        return self.cursor.fetchall()
    
    def get_leaderboard(self, limit=20):
        """Рейтинг: сначала по количеству попыток (меньше лучше), потом по времени (меньше лучше)"""
        self.cursor.execute('''
            SELECT 
                e.user_id,
                e.full_name, 
                e.department,
                e.total_attempts,
                e.best_score,
                e.best_time,
                COUNT(r.id) as attempts,
                AVG(r.score) as avg_score,
                MIN(r.time_spent) as min_time,
                SUM(CASE WHEN r.passed = 1 THEN 1 ELSE 0 END) as passed_count,
                (
                    SELECT MIN(attempt_number) 
                    FROM quiz_results 
                    WHERE user_id = e.user_id AND passed = 1
                ) as passed_attempt
            FROM employees e
            LEFT JOIN quiz_results r ON e.user_id = r.user_id
            WHERE e.total_attempts > 0
            GROUP BY e.user_id
            ORDER BY 
                e.total_attempts ASC,  -- меньше попыток - лучше
                e.best_time ASC         -- меньше время - лучше
            LIMIT ?
        ''', (limit,))
        return self.cursor.fetchall()
    
    def get_admin_stats(self):
        """Полная статистика для админа"""
        # Общая статистика
        self.cursor.execute('''
            SELECT 
                COUNT(DISTINCT user_id) as total_users,
                COUNT(*) as total_attempts,
                AVG(score) as avg_score,
                SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed_count,
                AVG(time_spent) as avg_time,
                MIN(time_spent) as best_time
            FROM quiz_results
        ''')
        general = self.cursor.fetchone()
        
        # Лучший сотрудник по попыткам
        self.cursor.execute('''
            SELECT e.full_name, e.total_attempts, e.best_time
            FROM employees e
            WHERE e.total_attempts > 0
            ORDER BY e.total_attempts ASC, e.best_time ASC
            LIMIT 1
        ''')
        best_attempts = self.cursor.fetchone()
        
        # Лучший сотрудник по времени
        self.cursor.execute('''
            SELECT e.full_name, e.best_time, e.total_attempts
            FROM employees e
            WHERE e.best_time > 0
            ORDER BY e.best_time ASC
            LIMIT 1
        ''')
        best_time = self.cursor.fetchone()
        
        return general, best_attempts, best_time
    
    # ----- Работа с активными викторинами -----
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

# ===================== БАЗА ДАННЫХ (СОЗДАЕМ ОБЪЕКТ) =====================
db = Database()

# ===================== 100 ВОПРОСОВ ПО СПА-ТЕМАТИКЕ =====================
def init_questions():
    # Проверяем, есть ли уже вопросы
    if db.count_questions() > 0:
        return
    
    questions = [
        # СПА-процедуры
        ("Что такое СПА-процедура?", ["Косметическая процедура", "Комплекс оздоровительных процедур", "Массаж", "Пилинг"], "B", "СПА", 2),
        ("Какой вид массажа используется в СПА?", ["Спортивный", "Классический", "Ароматерапевтический", "Лечебный"], "C", "СПА", 1),
        ("Что такое гидротерапия?", ["Лечение водой", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Какая температура воды для гидромассажа?", ["20-25°C", "30-35°C", "37-40°C", "45-50°C"], "C", "СПА", 2),
        ("Что такое талассотерапия?", ["Лечение морем", "Лечение травами", "Массаж", "Ароматерапия"], "A", "СПА", 3),
        ("Для чего используется скраб в СПА?", ["Увлажнение", "Отшелушивание", "Питание", "Защита"], "B", "СПА", 1),
        ("Что такое обертывание в СПА?", ["Массаж", "Нанесение масок с пленкой", "Пилинг", "Ингаляция"], "B", "СПА", 2),
        ("Какой эффект дает шоколадное обертывание?", ["Омоложение", "Увлажнение", "Антицеллюлитный", "Все варианты"], "D", "СПА", 2),
        ("Что такое стоун-терапия?", ["Массаж камнями", "Массаж палками", "Массаж руками", "Массаж водой"], "A", "СПА", 2),
        ("Какие масла используются в ароматерапии?", ["Эфирные", "Растительные", "Минеральные", "Синтетические"], "A", "СПА", 1),
        
        # Виды массажа
        ("Какой массаж считается расслабляющим?", ["Спортивный", "Классический", "Релаксирующий", "Лечебный"], "C", "СПА", 1),
        ("Что такое баночный массаж?", ["Массаж вакуумными банками", "Массаж руками", "Массаж камнями", "Массаж водой"], "A", "СПА", 2),
        ("Какой массаж помогает при целлюлите?", ["Релаксирующий", "Антицеллюлитный", "Спортивный", "Точечный"], "B", "СПА", 2),
        ("Что такое лимфодренажный массаж?", ["Улучшение лимфотока", "Расслабление", "Омоложение", "Лечение"], "A", "СПА", 2),
        ("Какой массаж выполняется в перчатках?", ["Спортивный", "Классический", "Тайский", "Шведский"], "C", "СПА", 2),
        ("Что такое шиацу?", ["Японский точечный массаж", "Китайский массаж", "Тайский массаж", "Шведский массаж"], "A", "СПА", 3),
        ("Какой массаж делают бамбуковыми палками?", ["Тайский", "Китайский", "Японский", "Вьетнамский"], "A", "СПА", 3),
        ("Что такое миофасциальный массаж?", ["Массаж фасций", "Массаж мышц", "Массаж связок", "Массаж суставов"], "A", "СПА", 3),
        
        # СПА-обертывания
        ("Какое обертывание помогает похудеть?", ["Шоколадное", "Водорослевое", "Грязевое", "Все варианты"], "D", "СПА", 2),
        ("Что такое горячее обертывание?", ["Обертывание с подогревом", "Обертывание без подогрева", "Массаж", "Пилинг"], "A", "СПА", 2),
        ("Для чего нужна грязевая маска?", ["Очищение", "Питание", "Лечение", "Все варианты"], "D", "СПА", 2),
        ("Что такое альгинатная маска?", ["Маска на основе водорослей", "Глиняная маска", "Шоколадная маска", "Фруктовая маска"], "A", "СПА", 2),
        ("Какая маска увлажняет кожу?", ["Глиняная", "Гидрогелевая", "Грязевая", "Шоколадная"], "B", "СПА", 1),
        
        # СПА-ритуалы
        ("Что такое ритуал 'Хаммам'?", ["Турецкая парная", "Финская сауна", "Японская баня", "Русская баня"], "A", "СПА", 2),
        ("Что такое ритуал 'Римская баня'?", ["Парная с горячим паром", "Сауна", "Хаммам", "Ледяная баня"], "A", "СПА", 2),
        ("Что такое ритуал 'Японская баня'?", ["Офуро", "Сауна", "Хаммам", "Русская баня"], "A", "СПА", 3),
        ("Что такое 'Кедровая бочка'?", ["Парная из кедра", "Массаж", "Обертывание", "Пилинг"], "A", "СПА", 2),
        ("Что такое 'Снежная комната'?", ["Комната с искусственным снегом", "Холодильная комната", "Парная", "Сауна"], "A", "СПА", 3),
        
        # Косметология в СПА
        ("Что такое пилинг в СПА?", ["Отшелушивание кожи", "Увлажнение", "Питание", "Защита"], "A", "СПА", 1),
        ("Для чего используется сыворотка?", ["Интенсивный уход", "Очищение", "Тонизирование", "Защита"], "A", "СПА", 1),
        ("Что такое коллагеновая маска?", ["Маска для омоложения", "Маска для увлажнения", "Маска для очищения", "Маска для питания"], "A", "СПА", 2),
        ("Какой крем используют после СПА-процедур?", ["Успокаивающий", "Очищающий", "Тонизирующий", "Питательный"], "A", "СПА", 1),
        ("Что такое микротоковая терапия?", ["Аппаратная косметология", "Массаж", "Пилинг", "Инъекции"], "A", "СПА", 3),
        ("Что такое ультразвуковая чистка лица?", ["Аппаратная чистка", "Ручная чистка", "Химическая чистка", "Лазерная чистка"], "A", "СПА", 3),
        ("Что такое RF-лифтинг?", ["Радиочастотный лифтинг", "Лазерный лифтинг", "Ультразвуковой лифтинг", "Инъекционный лифтинг"], "A", "СПА", 3),
        
        # Ароматерапия
        ("Какое масло успокаивает нервную систему?", ["Лаванда", "Мята", "Лимон", "Розмарин"], "A", "СПА", 1),
        ("Какое масло бодрит и тонизирует?", ["Мята", "Лаванда", "Роза", "Сандал"], "A", "СПА", 1),
        ("Какое масло используют при головной боли?", ["Мята", "Лаванда", "Роза", "Иланг-иланг"], "A", "СПА", 2),
        ("Что такое диффузор?", ["Устройство для распыления масел", "Массажный инструмент", "Крем", "Лосьон"], "A", "СПА", 1),
        ("Какое масло используют для релаксации?", ["Иланг-иланг", "Мята", "Лимон", "Розмарин"], "A", "СПА", 2),
        
        # Водные процедуры
        ("Что такое душ Шарко?", ["Лечебный душ", "Контрастный душ", "Циркулярный душ", "Игольчатый душ"], "A", "СПА", 2),
        ("Что такое контрастный душ?", ["Чередование горячей и холодной воды", "Душ с солью", "Душ с маслами", "Душ с грязью"], "A", "СПА", 1),
        ("Что такое ванна с морской солью?", ["Расслабляющая ванна", "Тонизирующая ванна", "Лечебная ванна", "Все варианты"], "D", "СПА", 1),
        ("Что такое гидромассажная ванна?", ["Ванна с водным массажем", "Обычная ванна", "Грязевая ванна", "Соляная ванна"], "A", "СПА", 2),
        ("Что такое кнеип-терапия?", ["Водная терапия", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        
        # Озонотерапия и криотерапия
        ("Что такое криотерапия?", ["Лечение холодом", "Лечение теплом", "Лечение водой", "Лечение грязью"], "A", "СПА", 2),
        ("Какая температура в криокамере?", ["-60°C", "-100°C", "-150°C", "-200°C"], "C", "СПА", 3),
        ("Что такое озонотерапия?", ["Лечение озоном", "Лечение кислородом", "Лечение водой", "Лечение грязью"], "A", "СПА", 3),
        ("Для чего используется криотерапия?", ["Омоложение", "Лечение целлюлита", "Укрепление иммунитета", "Все варианты"], "D", "СПА", 2),
        
        # СПА-программы
        ("Что такое анти-стресс программа?", ["Комплекс релаксации", "Комплекс похудения", "Комплекс омоложения", "Комплекс питания"], "A", "СПА", 1),
        ("Что такое детокс-программа?", ["Очищение организма", "Питание", "Массаж", "Пилинг"], "A", "СПА", 2),
        ("Что такое эко-СПА?", ["СПА с натуральными продуктами", "СПА с синтетикой", "СПА с химией", "СПА с алкоголем"], "A", "СПА", 2),
        
        # Медицинские процедуры
        ("Что такое иглорефлексотерапия?", ["Лечение иглами", "Массаж", "Пилинг", "Инъекции"], "A", "СПА", 3),
        ("Что такое мануальная терапия?", ["Лечение руками", "Массаж", "Гимнастика", "Лечение водой"], "A", "СПА", 3),
        ("Что такое остеопатия?", ["Лечение костей", "Массаж", "Гимнастика", "Лечение водой"], "A", "СПА", 3),
        
        # Дополнительные вопросы для набора 100
        ("Какое масло используют для массажа?", ["Растительное", "Эфирное", "Минеральное", "Синтетическое"], "A", "СПА", 1),
        ("Что такое флоатинг?", ["Плавание в соляной камере", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое соляная комната?", ["Галотерапия", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое фитобочка?", ["Парная с травами", "Сауна", "Хаммам", "Офуро"], "A", "СПА", 2),
        ("Что такое чайная церемония в СПА?", ["Дегустация чая", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое СПА-маникюр?", ["Маникюр с СПА-процедурами", "Обычный маникюр", "Наращивание", "Педикюр"], "A", "СПА", 1),
        ("Что такое СПА-педикюр?", ["Педикюр с СПА-процедурами", "Обычный педикюр", "Наращивание", "Маникюр"], "A", "СПА", 1),
        ("Что такое парафинотерапия?", ["Лечение парафином", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое брашинг?", ["Чистка щетками", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое альготерапия?", ["Лечение водорослями", "Лечение грязью", "Лечение травами", "Лечение водой"], "A", "СПА", 3),
        ("Что такое фитотерапия?", ["Лечение травами", "Лечение водой", "Лечение грязью", "Лечение маслами"], "A", "СПА", 2),
        ("Что такое глинолечение?", ["Лечение глиной", "Лечение водой", "Лечение травами", "Лечение маслами"], "A", "СПА", 2),
        ("Что такое пелоидотерапия?", ["Лечение грязями", "Лечение водой", "Лечение травами", "Лечение маслами"], "A", "СПА", 3),
        ("Что такое лазеротерапия?", ["Лечение лазером", "Лечение водой", "Лечение травами", "Лечение маслами"], "A", "СПА", 3),
        ("Что такое магнитотерапия?", ["Лечение магнитным полем", "Лечение водой", "Лечение травами", "Лечение маслами"], "A", "СПА", 3),
        ("Что такое ультразвук в СПА?", ["Ультразвуковая терапия", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое инфракрасная сауна?", ["Сауна с ИК-излучением", "Обычная сауна", "Хаммам", "Офуро"], "A", "СПА", 2),
        ("Что такое фитнес-СПА?", ["СПА с фитнесом", "Просто СПА", "Массаж", "Пилинг"], "A", "СПА", 2),
        ("Что такое йога в СПА?", ["Йога в СПА-центре", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое медитация в СПА?", ["Медитация", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое СПА-питание?", ["Здоровое питание", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое СПА-коктейль?", ["Напиток с витаминами", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое СПА-капсула?", ["Косметическая капсула", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        
        # Еще вопросы
        ("Какой массаж делают при остеохондрозе?", ["Лечебный", "Релаксирующий", "Спортивный", "Точечный"], "A", "СПА", 2),
        ("Что такое вакуумная терапия?", ["Лечение вакуумом", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое прессотерапия?", ["Лечение давлением", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое дарсонваль?", ["Аппаратная косметология", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое биоревитализация?", ["Инъекции гиалуроновой кислоты", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое мезотерапия?", ["Инъекции витаминов", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 2),
        ("Что такое плазмолифтинг?", ["Инъекции плазмы", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое ботулинотерапия?", ["Инъекции ботокса", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое нитевой лифтинг?", ["Лифтинг нитями", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
        ("Что такое контурная пластика?", ["Инъекции филлеров", "Массаж", "Пилинг", "Ингаляция"], "A", "СПА", 3),
    ]
    
    for question in questions:
        db.add_question(question[0], question[1], question[2], question[3], question[4])
    
    print(f"✅ Добавлено {len(questions)} вопросов по СПА-тематике")

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
    keyboard.add(
        InlineKeyboardButton("A", callback_data=f"answer_A_{question_id}"),
        InlineKeyboardButton("B", callback_data=f"answer_B_{question_id}")
    )
    keyboard.add(
        InlineKeyboardButton("C", callback_data=f"answer_C_{question_id}"),
        InlineKeyboardButton("D", callback_data=f"answer_D_{question_id}")
    )
    return keyboard

# ===================== ОБРАБОТЧИКИ КОМАНД =====================
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    user_id = message.from_user.id
    employee = db.get_employee(user_id)
    
    if not employee:
        await message.answer(
            "👋 *Добро пожаловать в HR-бот для контроля сотрудников СПА-салона!*\n\n"
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

# ===================== ОСНОВНОЕ МЕНЮ =====================
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
    # Проверяем, есть ли вопросы
    if db.count_questions() == 0:
        await message.answer("❌ Вопросы еще не загружены. Обратитесь к администратору.")
        return
    
    # Проверяем, есть ли активная викторина
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if questions and current_index > 0 and current_index < len(questions):
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("✅ Продолжить", callback_data="continue_quiz"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="restart_quiz")
        )
        await message.answer("⏳ У вас есть незавершенная викторина.", reply_markup=keyboard)
        return
    
    # Получаем 10 случайных вопросов
    all_questions = db.get_all_questions()
    selected = random.sample(all_questions, min(10, len(all_questions)))
    question_ids = [q[0] for q in selected]
    
    # Сохраняем время начала
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
    
    # Сохраняем время начала вопроса
    db.save_active_quiz(user_id, questions, index, correct_count, total_asked, category, start_time, int(time.time()))
    
    question_text = question[1]
    options = [question[2], question[3], question[4], question[5]]
    letters = ["A", "B", "C", "D"]
    
    text = f"📝 *Вопрос {index + 1} из {len(questions)}*\n\n"
    text += f"*{question_text}*\n\n"
    
    for i, option in enumerate(options):
        text += f"{letters[i]}) {option}\n"
    
    text += f"\n📂 Категория: {question[6]} | ⭐ Сложность: {question[7]}"
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    for i, letter in enumerate(letters):
        keyboard.add(InlineKeyboardButton(letter, callback_data=f"answer_{letter}_{question_id}"))
    
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
    
    # Получаем активную викторину
    questions, current_index, correct_count, total_asked, category, start_time, question_start_time = db.get_active_quiz(user_id)
    
    if not questions:
        await callback_query.answer("❌ Викторина не найдена")
        return
    
    # Проверяем ответ
    correct = question[6]
    is_correct = selected == correct
    
    if is_correct:
        correct_count += 1
    
    total_asked += 1
    current_index += 1
    
    # Сохраняем прогресс
    db.save_active_quiz(user_id, questions, current_index, correct_count, total_asked, category, start_time, int(time.time()))
    
    # Показываем результат
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
    
    # Отправляем следующий вопрос через 1.5 секунды
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
    
    # Вычисляем затраченное время
    time_spent = int(time.time()) - start_time
    
    # Сохраняем результат
    score, passed, attempt_number = db.save_result(user_id, total_asked, correct_count, category, time_spent)
    db.clear_active_quiz(user_id)
    
    # Форматируем время
    minutes = time_spent // 60
    seconds = time_spent % 60
    time_str = f"{minutes} мин. {seconds} сек." if minutes > 0 else f"{seconds} сек."
    
    result_text = f"🏁 *Результаты викторины*\n\n"
    result_text += f"📊 Правильных ответов: {correct_count} из {total_asked}\n"
    result_text += f"📈 Результат: {score:.1f}%\n"
    result_text += f"⏱️ Затраченное время: {time_str}\n"
    result_text += f"🔄 Попытка №{attempt_number}\n\n"
    
    if passed:
        result_text += "✅ *ЗАЧЕТ!* Поздравляем! 🎉\n"
    else:
        result_text += "❌ *НЕЗАЧЕТ!*\n"
        result_text += "Рекомендуем повторить материал и попробовать снова."
    
    # Показываем прогресс
    employee = db.get_employee(user_id)
    if employee:
        result_text += f"\n📊 Всего попыток: {employee[5]}\n"
        result_text += f"🏆 Лучший результат: {employee[6]:.1f}%\n"
        result_text += f"⏱️ Лучшее время: {employee[7]} сек." if employee[7] > 0 else ""
    
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

# ===================== РЕЙТИНГИ =====================
async def show_user_results(message: types.Message, user_id):
    results = db.get_user_results(user_id)
    employee = db.get_employee(user_id)
    
    if not results:
        await message.answer("📊 У вас пока нет результатов. Пройдите викторину!")
        return
    
    text = f"📊 *История результатов*"
    if employee:
        text += f" для *{employee[1]}*\n\n"
    else:
        text += "\n\n"
    
    for i, result in enumerate(results, 1):
        date = datetime.fromisoformat(result[0]).strftime("%d.%m.%Y %H:%M")
        minutes = result[6] // 60
        seconds = result[6] % 60
        time_str = f"{minutes}м {seconds}с" if minutes > 0 else f"{seconds}с"
        passed = "✅" if result[4] else "❌"
        text += f"#{result[7]}: {date} | {result[1]} вопр. | {result[2]} прав. | {result[3]:.1f}% | ⏱️{time_str} {passed}\n"
    
    # Статистика
    avg_score = sum(r[3] for r in results) / len(results)
    best_score = max(r[3] for r in results)
    best_time = min(r[6] for r in results)
    passed_count = sum(1 for r in results if r[4])
    
    text += "\n📈 *Общая статистика:*\n"
    text += f"📊 Средний результат: {avg_score:.1f}%\n"
    text += f"🏆 Лучший результат: {best_score:.1f}%\n"
    text += f"⏱️ Лучшее время: {best_time} сек.\n"
    text += f"✅ Зачетов: {passed_count} из {len(results)}"
    
    await message.answer(text, parse_mode="Markdown")

async def show_leaderboard(message: types.Message):
    leaderboard = db.get_leaderboard()
    
    if not leaderboard:
        await message.answer("🏆 Пока нет данных для рейтинга.")
        return
    
    text = "🏆 *Топ сотрудников*\n"
    text += "*(Учитывается: меньше попыток → лучше, меньше время → лучше)*\n\n"
    
    for i, row in enumerate(leaderboard, 1):
        user_id, name, dept, total_attempts, best_score, best_time, attempts, avg_score, min_time, passed_count, passed_attempt = row
        
        medal = "🥇 " if i == 1 else "🥈 " if i == 2 else "🥉 " if i == 3 else ""
        
        text += f"{medal}{i}. *{name}*\n"
        text += f"   📊 Отдел: {dept}\n"
        text += f"   🔄 Попыток: {total_attempts}\n"
        text += f"   🏆 Лучший балл: {best_score:.1f}%\n"
        text += f"   ⏱️ Лучшее время: {best_time} сек.\n"
        text += f"   ✅ Зачетов: {passed_count}\n"
        if passed_attempt:
            text += f"   🎯 Зачет с {passed_attempt} попытки\n"
        text += "\n"
    
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
            await bot.send_message(
                user_id,
                f"📢 *Объявление от HR-администратора*\n\n{message.text}",
                parse_mode="Markdown"
            )
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
        "📝 *Добавление нового вопроса*\n\n"
        "Введите вопрос в формате:\n"
        "`Текст вопроса | A | B | C | D | Правильный ответ | Категория | Сложность (1-3)`\n\n"
        "Пример:\n"
        "`Что такое СПА? | Комплекс процедур | Массаж | Пилинг | Ингаляция | A | СПА | 1`",
        parse_mode="Markdown"
    )
    await AdminStates.waiting_for_question_add.set()

@dp.message_handler(state=AdminStates.waiting_for_question_add)
async def process_add_question(message: types.Message, state: FSMContext):
    try:
        parts = [p.strip() for p in message.text.split('|')]
        if len(parts) != 8:
            await message.answer("❌ Неверный формат. Нужно 7 разделителей '|'")
            return
        
        question_text = parts[0]
        options = parts[1:5]
        correct_answer = parts[5].upper()
        category = parts[6] if parts[6] else "СПА"
        difficulty = int(parts[7]) if parts[7].isdigit() else 1
        
        db.add_question(question_text, options, correct_answer, category, difficulty)
        
        await state.finish()
        await message.answer("✅ Вопрос успешно добавлен!", reply_markup=get_admin_keyboard())
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
            f"✏️ *Редактирование вопроса #{question_id}*\n\n"
            f"Текущий текст: {question[1]}\n\n"
            "Введите новые данные в формате:\n"
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
    
    text = "❌ *Выберите вопрос для удаления*\n\n"
    for q in questions[:20]:
        text += f"ID: {q[0]}. {q[1][:40]}...\n"
    
    text += "\nВведите ID вопроса:"
    await message.answer(text, parse_mode="Markdown")
    await AdminStates.waiting_for_question_delete.set()

@dp.message_handler(state=AdminStates.waiting_for_question_delete)
async def process_delete_question(message: types.Message, state: FSMContext):
    try:
        question_id = int(message.text.strip())
        question = db.get_question_by_id(question_id)
        
        if not question:
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
        text += f"   📊 Отдел: {dept}\n"
        text += f"   💼 Должность: {pos}\n"
        text += f"   🔄 Попыток: {attempts}\n"
        text += f"   🏆 Лучший: {best_score:.1f}%\n"
        text += f"   ⏱️ Лучшее время: {best_time} сек.\n\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "📊 Статистика")
async def admin_stats(message: types.Message):
    if not db.is_admin(message.from_user.id):
        return
    
    general, best_attempts, best_time = db.get_admin_stats()
    
    text = "📊 *Статистика системы*\n\n"
    text += f"👥 Всего сотрудников: {general[0] or 0}\n"
    text += f"📝 Всего попыток: {general[1] or 0}\n"
    text += f"📈 Средний балл: {general[2] or 0:.1f}%\n"
    text += f"✅ Зачетов: {general[3] or 0}\n"
    text += f"⏱️ Среднее время: {general[4] or 0:.0f} сек.\n"
    text += f"⚡ Лучшее время: {general[5] or 0} сек.\n\n"
    
    if best_attempts:
        text += f"🏆 *Лучший по попыткам:*\n"
        text += f"   {best_attempts[0]} - {best_attempts[1]} попыток\n\n"
    
    if best_time:
        text += f"⏱️ *Лучший по времени:*\n"
        text += f"   {best_time[0]} - {best_time[1]} сек."
    
    await message.answer(text, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "👑 Назначить админа")
async def assign_admin_command(message: types.Message, state: FSMContext):
    if not db.is_admin(message.from_user.id):
        return
    
    employees = db.get_all_employees()
    if not employees:
        await message.answer("❌ Нет зарегистрированных сотрудников.")
        return
    
    text = "👑 *Назначение администратора*\n\n"
    text += "Введите ID пользователя, которому хотите дать права администратора:\n\n"
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
        await message.answer(f"✅ Пользователь {employee[1]} назначен администратором!", reply_markup=get_admin_keyboard())
    except:
        await message.answer("❌ Введите корректный ID (число).")

@dp.message_handler(lambda message: message.text == "🔙 Назад в меню")
async def back_to_menu(message: types.Message):
    user_id = message.from_user.id
    await message.answer("🔙 Возврат в главное меню", reply_markup=get_main_keyboard(user_id))

# ===================== ЗАПУСК БОТА =====================
if __name__ == "__main__":
    print("🚀 Запуск HR-бота для СПА-салона...")
    
    # Инициализируем вопросы
    init_questions()
    
    print(f"✅ Бот запущен!")
    print(f"👤 Администраторы: {ADMINS}")
    print(f"📊 Всего вопросов: {db.count_questions()}")
    print("💬 Бот готов к работе...")
    
    executor.start_polling(dp, skip_updates=True)
