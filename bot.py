#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Планировщик задач с погодой (OpenWeatherMap + WeatherAPI)
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMIN_ID = 1024761707

# ===================== ВАШИ API КЛЮЧИ =====================
OPENWEATHER_API_KEY = "190a44f2866cdf55936786fe537f190d"
WEATHERAPI_KEY = "015e8df355d64902bf965948261808"  # Полный ключ!

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('tasks.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                category TEXT DEFAULT 'Работа',
                priority TEXT DEFAULT 'Средний',
                due_date TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                reminder_time TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                color TEXT DEFAULT '#007AFF'
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        self.conn.commit()
        
        default_categories = ['Работа', 'Личное', 'Учёба', 'Здоровье', 'Финансы', 'Развлечения']
        for cat in default_categories:
            self.cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (cat,))
        self.conn.commit()
        
        self.cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('city', 'Москва'))
        self.conn.commit()
    
    def add_task(self, title, description="", category="Работа", priority="Средний", due_date=None, reminder_time=None):
        self.cursor.execute('''
            INSERT INTO tasks (title, description, category, priority, due_date, created_at, reminder_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (title, description, category, priority, due_date, datetime.now().isoformat(), reminder_time))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_tasks(self, status="active"):
        self.cursor.execute('''
            SELECT id, title, description, category, priority, due_date, reminder_time
            FROM tasks WHERE status = ? ORDER BY due_date, priority DESC
        ''', (status,))
        return self.cursor.fetchall()
    
    def get_tasks_by_category(self, category, status="active"):
        self.cursor.execute('''
            SELECT id, title, description, priority, due_date
            FROM tasks WHERE category = ? AND status = ?
            ORDER BY due_date
        ''', (category, status))
        return self.cursor.fetchall()
    
    def get_task_by_id(self, task_id):
        self.cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        return self.cursor.fetchone()
    
    def update_task_status(self, task_id, status):
        self.cursor.execute('UPDATE tasks SET status = ? WHERE id = ?', (status, task_id))
        self.conn.commit()
    
    def delete_task(self, task_id):
        self.cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        self.conn.commit()
    
    def get_categories(self):
        self.cursor.execute('SELECT name FROM categories ORDER BY name')
        return [row[0] for row in self.cursor.fetchall()]
    
    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active"')
        active = self.cursor.fetchone()[0]
        
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "completed"')
        completed = self.cursor.fetchone()[0]
        
        self.cursor.execute('''
            SELECT category, COUNT(*) FROM tasks WHERE status = "active" 
            GROUP BY category ORDER BY COUNT(*) DESC
        ''')
        by_category = self.cursor.fetchall()
        
        return active, completed, by_category
    
    def get_setting(self, key):
        self.cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def set_setting(self, key, value):
        self.cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

db = Database()

# ===================== ПОГОДА =====================
def get_weather_openweather(city):
    """Погода через OpenWeatherMap"""
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('cod') != 200:
            return None
        
        temp = data['main']['temp']
        feels_like = data['main']['feels_like']
        humidity = data['main']['humidity']
        pressure = data['main']['pressure']
        wind = data['wind']['speed']
        description = data['weather'][0]['description']
        
        text = f"🌤 *Погода в {city}*\n\n"
        text += f"🌡 Температура: {temp:.1f}°C (ощущается {feels_like:.1f}°C)\n"
        text += f"💧 Влажность: {humidity}%\n"
        text += f"📊 Давление: {pressure} мм рт. ст.\n"
        text += f"🌬 Ветер: {wind} м/с\n"
        text += f"📝 {description.capitalize()}"
        
        return text
    except Exception as e:
        logger.error(f"OpenWeather error: {e}")
        return None

def get_weather_weatherapi(city):
    """Погода через WeatherAPI"""
    if not WEATHERAPI_KEY or len(WEATHERAPI_KEY) < 20:
        return None
    
    try:
        url = f"https://api.weatherapi.com/v1/current.json?key={WEATHERAPI_KEY}&q={city}&lang=ru"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if 'error' in data:
            return None
        
        current = data['current']
        location = data['location']
        
        text = f"🌤 *Погода в {location['name']}*\n\n"
        text += f"🌡 Температура: {current['temp_c']:.1f}°C (ощущается {current['feelslike_c']:.1f}°C)\n"
        text += f"☁️ {current['condition']['text']}\n"
        text += f"💧 Влажность: {current['humidity']}%\n"
        text += f"🌬 Ветер: {current['wind_kph']} км/ч\n"
        text += f"📊 Давление: {current['pressure_mb']} мбар"
        
        return text
    except Exception as e:
        logger.error(f"WeatherAPI error: {e}")
        return None

def get_weather(city):
    """Получение погоды из доступных API"""
    # Пробуем WeatherAPI
    result = get_weather_weatherapi(city)
    if result:
        return result
    
    # Пробуем OpenWeatherMap
    result = get_weather_openweather(city)
    if result:
        return result
    
    return "❌ Не удалось получить погоду. Проверьте API ключи."

def get_city_by_ip():
    """Автоопределение города по IP"""
    try:
        response = requests.get('https://ipapi.co/json/', timeout=10)
        data = response.json()
        city = data.get('city', 'Москва')
        return city
    except:
        return 'Москва'

# ===================== КЛАВИАТУРЫ =====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Мои дела", callback_data='list_tasks')],
        [InlineKeyboardButton("➕ Добавить дело", callback_data='add_task_start')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🗂 Категории", callback_data='categories')],
        [InlineKeyboardButton("🌤 Погода", callback_data='weather')],
        [InlineKeyboardButton("📅 Календарь", callback_data='calendar')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='settings')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    return InlineKeyboardMarkup(keyboard)

def task_actions_keyboard(task_id):
    keyboard = [
        [InlineKeyboardButton("✅ Выполнено", callback_data=f'done_{task_id}')],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f'delete_{task_id}')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back_to_list')]
    ]
    return InlineKeyboardMarkup(keyboard)

def categories_keyboard():
    categories = db.get_categories()
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f'cat_{cat}')])
    keyboard.append([InlineKeyboardButton("➕ Добавить категорию", callback_data='add_category')])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')])
    return InlineKeyboardMarkup(keyboard)

def priority_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔴 Высокий", callback_data='priority_high')],
        [InlineKeyboardButton("🟡 Средний", callback_data='priority_medium')],
        [InlineKeyboardButton("🟢 Низкий", callback_data='priority_low')]
    ]
    return InlineKeyboardMarkup(keyboard)

def calendar_keyboard(year, month):
    import calendar
    keyboard = []
    
    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    
    keyboard.append([InlineKeyboardButton(f"📅 {month_names[month-1]} {year}", callback_data='noop')])
    
    week_days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    row = []
    for day in week_days:
        row.append(InlineKeyboardButton(day, callback_data='noop'))
    keyboard.append(row)
    
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data='noop'))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(str(day), callback_data=f'date_{date_str}'))
        keyboard.append(row)
    
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f'calendar_{prev_year}_{prev_month}'),
        InlineKeyboardButton("Сегодня", callback_data='calendar_today'),
        InlineKeyboardButton("▶️", callback_data=f'calendar_{next_year}_{next_month}')
    ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')])
    
    return InlineKeyboardMarkup(keyboard)

# ===================== ОБРАБОТЧИКИ =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return
    
    city = get_city_by_ip()
    db.set_setting('city', city)
    
    await update.message.reply_text(
        f"🤖 *Планировщик задач*\n\n"
        f"📍 Город: {city}\n\n"
        "📋 *Что я умею:*\n"
        "• Создавать задачи\n"
        "• Показывать погоду\n"
        "• Вести статистику\n"
        "• Работать с календарём\n\n"
        "Выберите действие:",
        reply_markup=main_menu(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    
    if data == 'back_to_menu':
        await query.edit_message_text(
            "🤖 *Планировщик задач*\n\nВыберите действие:",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        )
    
    elif data == 'list_tasks':
        tasks = db.get_tasks()
        if not tasks:
            await query.edit_message_text(
                "📭 *Нет активных задач*\n\n"
                "Нажмите '➕ Добавить дело' чтобы создать задачу.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Добавить дело", callback_data='add_task_start')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
                ]),
                parse_mode='Markdown'
            )
            return
        
        text = "📋 *Ваши задачи:*\n\n"
        for task in tasks:
            task_id, title, desc, category, priority, due_date, reminder = task
            priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
            due = f" (до {due_date})" if due_date else ""
            text += f"{priority_emoji} *{title}*{due}\n"
            text += f"   📂 {category}\n"
            if desc:
                text += f"   📝 {desc[:50]}\n"
            text += "\n"
        
        text += "\n_Выберите задачу для управления:_"
        
        keyboard = []
        for task in tasks[:10]:
            task_id = task[0]
            keyboard.append([InlineKeyboardButton(f"• {task[1][:30]}", callback_data=f'task_{task_id}')])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data.startswith('task_'):
        task_id = int(data.split('_')[1])
        task = db.get_task_by_id(task_id)
        if not task:
            await query.edit_message_text("❌ Задача не найдена.", reply_markup=main_menu())
            return
        
        text = f"📌 *{task[1]}*\n\n"
        text += f"📂 Категория: {task[3]}\n"
        text += f"🔵 Приоритет: {task[4]}\n"
        if task[5]:
            text += f"📅 Срок: {task[5]}\n"
        if task[6]:
            text += f"⏰ Напоминание: {task[6]}\n"
        if task[2]:
            text += f"📝 {task[2]}\n"
        text += f"📌 Статус: {'✅ Выполнено' if task[7] == 'completed' else '🔄 В процессе'}"
        
        await query.edit_message_text(text, reply_markup=task_actions_keyboard(task_id), parse_mode='Markdown')
    
    elif data.startswith('done_'):
        task_id = int(data.split('_')[1])
        db.update_task_status(task_id, 'completed')
        await query.edit_message_text(
            "✅ Задача выполнена! 🎉",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]])
        )
    
    elif data.startswith('delete_'):
        task_id = int(data.split('_')[1])
        db.delete_task(task_id)
        await query.edit_message_text(
            "🗑 Задача удалена.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]])
        )
    
    elif data == 'add_task_start':
        await query.edit_message_text(
            "✏️ *Добавление задачи*\n\n"
            "Введите название задачи:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_title'
    
    elif data == 'categories':
        await query.edit_message_text(
            "📂 *Категории*\n\nВыберите категорию:",
            reply_markup=categories_keyboard(),
            parse_mode='Markdown'
        )
    
    elif data.startswith('cat_'):
        category = data.replace('cat_', '')
        tasks = db.get_tasks_by_category(category)
        if not tasks:
            await query.edit_message_text(
                f"📭 В категории '{category}' нет задач.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data='categories')],
                    [InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]
                ])
            )
            return
        
        text = f"📂 *{category}*\n\n"
        for task in tasks:
            task_id, title, desc, priority, due_date = task
            priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
            due = f" (до {due_date})" if due_date else ""
            text += f"{priority_emoji} {title}{due}\n"
        
        text += "\n_Выберите задачу:_"
        keyboard = []
        for task in tasks[:10]:
            keyboard.append([InlineKeyboardButton(f"• {task[1][:30]}", callback_data=f'task_{task[0]}')])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='categories')])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'add_category':
        await query.edit_message_text(
            "✏️ Введите название новой категории:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_category'
    
    elif data == 'stats':
        active, completed, by_category = db.get_stats()
        
        text = "📊 *Статистика задач*\n\n"
        text += f"🔄 Активных: {active}\n"
        text += f"✅ Выполнено: {completed}\n"
        text += f"📊 Всего: {active + completed}\n\n"
        
        if by_category:
            text += "*По категориям:*\n"
            for cat, count in by_category:
                text += f"📂 {cat}: {count} задач\n"
        else:
            text += "Нет задач в категориях"
        
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == 'weather':
        city = db.get_setting('city') or 'Москва'
        weather_text = get_weather(city)
        await query.edit_message_text(
            weather_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data='weather')],
                [InlineKeyboardButton("🌍 Сменить город", callback_data='change_city')],
                [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
            ]),
            parse_mode='Markdown'
        )
    
    elif data == 'change_city':
        await query.edit_message_text(
            "🌍 *Смена города*\n\nВведите название города:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'change_city'
    
    elif data.startswith('calendar'):
        if data == 'calendar_today':
            now = datetime.now()
            await show_calendar(query, now.year, now.month)
        elif data == 'calendar':
            now = datetime.now()
            await show_calendar(query, now.year, now.month)
        elif data.startswith('calendar_'):
            parts = data.split('_')
            year = int(parts[1])
            month = int(parts[2])
            await show_calendar(query, year, month)
    
    elif data.startswith('date_'):
        date_str = data.replace('date_', '')
        context.user_data['selected_date'] = date_str
        
        tasks = db.get_tasks()
        tasks_on_date = [t for t in tasks if t[5] == date_str]
        
        if tasks_on_date:
            text = f"📅 *Задачи на {date_str}:*\n\n"
            for task in tasks_on_date:
                text += f"• {task[1]}\n"
        else:
            text = f"📅 Нет задач на {date_str}"
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить на эту дату", callback_data=f'add_date_{date_str}')],
            [InlineKeyboardButton("🔙 Назад", callback_data='calendar')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data.startswith('add_date_'):
        date_str = data.replace('add_date_', '')
        context.user_data['selected_date'] = date_str
        await query.edit_message_text(
            f"✏️ Введите название задачи на {date_str}:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_date'
    
    elif data == 'settings':
        keyboard = [
            [InlineKeyboardButton("🌍 Сменить город", callback_data='change_city')],
            [InlineKeyboardButton("🗑 Очистить все задачи", callback_data='clear_all')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
        ]
        await query.edit_message_text(
            "⚙️ *Настройки*\n\nВыберите действие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'clear_all':
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить всё", callback_data='confirm_clear')],
            [InlineKeyboardButton("❌ Нет, отмена", callback_data='settings')]
        ]
        await query.edit_message_text(
            "⚠️ *ВНИМАНИЕ!*\n\n"
            "Вы уверены, что хотите удалить ВСЕ задачи?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'confirm_clear':
        db.cursor.execute('DELETE FROM tasks')
        db.conn.commit()
        await query.edit_message_text(
            "🗑 Все задачи удалены.",
            reply_markup=main_menu()
        )
    
    elif data == 'help':
        text = "❓ *Помощь*\n\n"
        text += "🤖 *Что я умею:*\n"
        text += "📋 Мои дела — список задач\n"
        text += "➕ Добавить дело — создать задачу\n"
        text += "📊 Статистика — общая статистика\n"
        text += "🗂 Категории — задачи по категориям\n"
        text += "🌤 Погода — погода в вашем городе\n"
        text += "📅 Календарь — задачи по датам\n\n"
        text += "🔐 Бот доступен только администратору."
        
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == 'noop':
        pass

async def show_calendar(query, year, month):
    await query.edit_message_text(
        "📅 *Календарь*\n\nВыберите дату:",
        reply_markup=calendar_keyboard(year, month),
        parse_mode='Markdown'
    )

# ===================== ОБРАБОТКА СООБЩЕНИЙ =====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return
    
    text = update.message.text
    step = context.user_data.get('step')
    
    if step == 'add_task_title':
        context.user_data['task_title'] = text
        
        categories = db.get_categories()
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f'set_cat_{cat}')])
        keyboard.append([InlineKeyboardButton("➕ Новая категория", callback_data='add_category')])
        keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data='back_to_menu')])
        
        await update.message.reply_text(
            f"✏️ *{text}*\n\nВыберите категорию:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_category'
    
    elif step == 'add_category':
        db.cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (text,))
        db.conn.commit()
        context.user_data['step'] = None
        await update.message.reply_text(
            f"✅ Категория '{text}' добавлена!",
            reply_markup=main_menu()
        )
    
    elif step == 'change_city':
        context.user_data['step'] = None
        db.set_setting('city', text)
        await update.message.reply_text(
            f"🌍 Город изменён на {text}",
            reply_markup=main_menu()
        )
    
    elif step == 'add_task_date':
        title = text
        date_str = context.user_data.get('selected_date', datetime.now().strftime('%Y-%m-%d'))
        
        keyboard = [
            [InlineKeyboardButton("🔴 Высокий", callback_data=f'set_priority_high_{title}_{date_str}')],
            [InlineKeyboardButton("🟡 Средний", callback_data=f'set_priority_medium_{title}_{date_str}')],
            [InlineKeyboardButton("🟢 Низкий", callback_data=f'set_priority_low_{title}_{date_str}')]
        ]
        
        await update.message.reply_text(
            f"✏️ *{title}*\n\n📅 Дата: {date_str}\n\nВыберите приоритет:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_priority'
        context.user_data['task_title'] = title
        context.user_data['task_date'] = date_str

# ===================== КОЛБЭКИ ДЛЯ ДОБАВЛЕНИЯ ЗАДАЧ =====================
async def add_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    
    if data.startswith('set_cat_'):
        category = data.replace('set_cat_', '')
        context.user_data['task_category'] = category
        
        keyboard = [
            [InlineKeyboardButton("🔴 Высокий", callback_data='priority_high')],
            [InlineKeyboardButton("🟡 Средний", callback_data='priority_medium')],
            [InlineKeyboardButton("🟢 Низкий", callback_data='priority_low')]
        ]
        
        await query.edit_message_text(
            f"✏️ *{context.user_data.get('task_title', '')}*\n\n"
            f"📂 Категория: {category}\n\n"
            "Выберите приоритет:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_priority'
    
    elif data.startswith('priority_'):
        priority_map = {
            'priority_high': 'Высокий',
            'priority_medium': 'Средний',
            'priority_low': 'Низкий'
        }
        priority = priority_map.get(data, 'Средний')
        
        title = context.user_data.get('task_title', 'Без названия')
        category = context.user_data.get('task_category', 'Работа')
        due_date = context.user_data.get('task_date', None)
        
        db.add_task(title, "", category, priority, due_date)
        
        context.user_data['step'] = None
        context.user_data['task_title'] = None
        context.user_data['task_category'] = None
        context.user_data['task_date'] = None
        
        priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
        date_text = f" (до {due_date})" if due_date else ""
        
        await query.edit_message_text(
            f"✅ *Задача добавлена!*\n\n"
            f"{priority_emoji} *{title}*{date_text}\n"
            f"📂 Категория: {category}\n"
            f"🔵 Приоритет: {priority}",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        )

# ===================== ЗАПУСК =====================
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(add_task_callback, pattern='^(set_cat_|priority_)'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🤖 Бот-планировщик запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("🌤 OpenWeatherMap ключ: " + ("✅" if OPENWEATHER_API_KEY else "❌"))
    print("🌤 WeatherAPI ключ: " + ("✅" if WEATHERAPI_KEY and len(WEATHERAPI_KEY) > 20 else "❌"))
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
