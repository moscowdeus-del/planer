#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Планировщик задач с напоминаниями (3, 2, 1 день) и расширенными функциями
- Автоматические напоминания о дедлайнах
- Статистика выполнения
- Экспорт задач
- Архив выполненных задач
- Ежедневный отчёт
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMIN_ID = 1024761707

# ===================== API КЛЮЧИ =====================
OPENWEATHER_API_KEY = "190a44f2866cdf55936786fe537f190d"
WEATHERAPI_KEY = "015e8df355d64902bf965948261808"

# ===================== БАЗА ДАННЫХ =====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('tasks.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
    
    def _create_tables(self):
        # Задачи
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
                reminder_sent_3d INTEGER DEFAULT 0,
                reminder_sent_2d INTEGER DEFAULT 0,
                reminder_sent_1d INTEGER DEFAULT 0,
                completed_at TEXT
            )
        ''')
        
        # Категории
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                color TEXT DEFAULT '#007AFF'
            )
        ''')
        
        # Настройки
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # История напоминаний
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS reminder_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                days_before INTEGER,
                sent_at TEXT
            )
        ''')
        self.conn.commit()
        
        # Категории по умолчанию
        default_categories = ['Работа', 'Личное', 'Учёба', 'Здоровье', 'Финансы', 'Развлечения', 'Проекты']
        for cat in default_categories:
            self.cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (cat,))
        self.conn.commit()
        
        self.cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('city', 'Москва'))
        self.conn.commit()
    
    def add_task(self, title, description="", category="Работа", priority="Средний", due_date=None):
        self.cursor.execute('''
            INSERT INTO tasks (title, description, category, priority, due_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, description, category, priority, due_date, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_tasks(self, status="active", limit=None):
        if limit:
            self.cursor.execute('''
                SELECT id, title, description, category, priority, due_date,
                       reminder_sent_3d, reminder_sent_2d, reminder_sent_1d
                FROM tasks WHERE status = ? ORDER BY due_date, priority DESC LIMIT ?
            ''', (status, limit))
        else:
            self.cursor.execute('''
                SELECT id, title, description, category, priority, due_date,
                       reminder_sent_3d, reminder_sent_2d, reminder_sent_1d
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
        if status == 'completed':
            self.cursor.execute('UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?', 
                               (status, datetime.now().isoformat(), task_id))
        else:
            self.cursor.execute('UPDATE tasks SET status = ? WHERE id = ?', (status, task_id))
        self.conn.commit()
    
    def delete_task(self, task_id):
        self.cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        self.conn.commit()
    
    def get_categories(self):
        self.cursor.execute('SELECT name FROM categories ORDER BY name')
        return [row[0] for row in self.cursor.fetchall()]
    
    def get_stats(self):
        # Активные
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active"')
        active = self.cursor.fetchone()[0]
        
        # Выполненные
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "completed"')
        completed = self.cursor.fetchone()[0]
        
        # Просроченные
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active" AND due_date < ?', (today,))
        overdue = self.cursor.fetchone()[0]
        
        # По категориям
        self.cursor.execute('''
            SELECT category, COUNT(*) FROM tasks WHERE status = "active" 
            GROUP BY category ORDER BY COUNT(*) DESC
        ''')
        by_category = self.cursor.fetchall()
        
        return active, completed, overdue, by_category
    
    def get_overdue_tasks(self):
        today = datetime.now().strftime('%Y-%m-%d')
        self.cursor.execute('''
            SELECT id, title, due_date FROM tasks 
            WHERE status = "active" AND due_date < ?
            ORDER BY due_date
        ''', (today,))
        return self.cursor.fetchall()
    
    def get_tasks_due_soon(self, days):
        today = datetime.now().strftime('%Y-%m-%d')
        future = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        self.cursor.execute('''
            SELECT id, title, due_date, category, priority,
                   reminder_sent_3d, reminder_sent_2d, reminder_sent_1d
            FROM tasks 
            WHERE status = "active" AND due_date BETWEEN ? AND ?
            ORDER BY due_date
        ''', (today, future))
        return self.cursor.fetchall()
    
    def mark_reminder_sent(self, task_id, days_before):
        field = f'reminder_sent_{days_before}d'
        self.cursor.execute(f'UPDATE tasks SET {field} = 1 WHERE id = ?', (task_id,))
        self.conn.commit()
        
        # Логируем
        self.cursor.execute('''
            INSERT INTO reminder_log (task_id, days_before, sent_at)
            VALUES (?, ?, ?)
        ''', (task_id, days_before, datetime.now().isoformat()))
        self.conn.commit()
    
    def reset_reminder_flags(self, task_id):
        self.cursor.execute('''
            UPDATE tasks SET reminder_sent_3d = 0, reminder_sent_2d = 0, reminder_sent_1d = 0
            WHERE id = ?
        ''', (task_id,))
        self.conn.commit()
    
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
    result = get_weather_weatherapi(city)
    if result:
        return result
    
    result = get_weather_openweather(city)
    if result:
        return result
    
    return "❌ Не удалось получить погоду. Проверьте API ключи."

def get_city_by_ip():
    try:
        response = requests.get('https://ipapi.co/json/', timeout=10)
        data = response.json()
        return data.get('city', 'Москва')
    except:
        return 'Москва'

# ===================== ФОНОВЫЕ НАПОМИНАНИЯ =====================
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Проверка задач и отправка напоминаний"""
    try:
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        # Проверяем задачи с дедлайнами на 3, 2, 1 день
        reminders_config = [
            (3, 'reminder_sent_3d', 'через 3 дня'),
            (2, 'reminder_sent_2d', 'через 2 дня'),
            (1, 'reminder_sent_1d', 'завтра')
        ]
        
        for days, field, label in reminders_config:
            target_date = (now + timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Ищем задачи с этой датой
            db.cursor.execute(f'''
                SELECT id, title, due_date, category, priority
                FROM tasks 
                WHERE status = "active" 
                  AND due_date = ? 
                  AND {field} = 0
            ''', (target_date,))
            
            tasks = db.cursor.fetchall()
            
            for task in tasks:
                task_id, title, due_date, category, priority = task
                
                # Отправляем напоминание
                priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
                
                message = f"⏰ *Напоминание!*\n\n"
                message += f"📌 *{title}*\n"
                message += f"📂 Категория: {category}\n"
                message += f"{priority_emoji} Приоритет: {priority}\n"
                message += f"📅 Дедлайн: {due_date}\n"
                message += f"⏳ Осталось: {label}\n\n"
                message += "_Не забудьте выполнить задачу!_"
                
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=message,
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Выполнено", callback_data=f'done_{task_id}')],
                            [InlineKeyboardButton("📝 Просмотр", callback_data=f'task_{task_id}')]
                        ])
                    )
                    
                    # Отмечаем, что напоминание отправлено
                    db.mark_reminder_sent(task_id, days)
                    logger.info(f"Напоминание отправлено для задачи #{task_id} ({days} дней)")
                    
                except Exception as e:
                    logger.error(f"Ошибка отправки напоминания: {e}")
        
        # Проверяем просроченные задачи
        db.cursor.execute('''
            SELECT id, title, due_date FROM tasks 
            WHERE status = "active" AND due_date < ?
        ''', (today,))
        overdue = db.cursor.fetchall()
        
        if overdue:
            message = "⚠️ *Просроченные задачи!*\n\n"
            for task in overdue[:10]:
                task_id, title, due_date = task
                message += f"• {title} (дедлайн: {due_date})\n"
            
            message += f"\n_Всего просроченных: {len(overdue)}_"
            
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о просрочке: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка в check_reminders: {e}")

# ===================== КЛАВИАТУРЫ =====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Мои дела", callback_data='list_tasks')],
        [InlineKeyboardButton("➕ Добавить дело", callback_data='add_task_start')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🗂 Категории", callback_data='categories')],
        [InlineKeyboardButton("🌤 Погода", callback_data='weather')],
        [InlineKeyboardButton("📅 Календарь", callback_data='calendar')],
        [InlineKeyboardButton("📦 Экспорт", callback_data='export_tasks')],
        [InlineKeyboardButton("📊 Отчёт за неделю", callback_data='weekly_report')],
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
        "• Создавать задачи с категориями и приоритетами\n"
        "• Автоматические напоминания за 3, 2, 1 день\n"
        "• Статистика выполнения\n"
        "• Экспорт задач в CSV\n"
        "• Еженедельный отчёт\n"
        "• Погода в вашем городе\n"
        "• Календарь с задачами\n\n"
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
        tasks = db.get_tasks('active')
        if not tasks:
            await query.edit_message_text(
                "📭 *Нет активных задач*\n\n"
                "Нажмите '➕ Добавить дело' чтобы создать задачу.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Добавить дело", callback_data='add_task_start')],
                    [InlineKeyboardButton("🗂 Архив", callback_data='archived_tasks')],
                    [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
                ]),
                parse_mode='Markdown'
            )
            return
        
        text = "📋 *Ваши задачи:*\n\n"
        today = datetime.now().strftime('%Y-%m-%d')
        overdue_count = 0
        
        for task in tasks:
            task_id, title, desc, category, priority, due_date, r3, r2, r1 = task
            priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
            
            # Проверка просрочки
            is_overdue = due_date and due_date < today
            overdue_emoji = "⏰" if is_overdue else ""
            if is_overdue:
                overdue_count += 1
            
            due = f" (до {due_date})" if due_date else ""
            text += f"{priority_emoji} *{title}* {overdue_emoji}{due}\n"
            text += f"   📂 {category}\n"
            if desc:
                text += f"   📝 {desc[:50]}\n"
            text += "\n"
        
        if overdue_count > 0:
            text += f"⚠️ *{overdue_count} просроченных задач!*\n\n"
        
        text += "\n_Выберите задачу для управления:_"
        
        keyboard = []
        for task in tasks[:10]:
            task_id = task[0]
            keyboard.append([InlineKeyboardButton(f"• {task[1][:30]}", callback_data=f'task_{task_id}')])
        keyboard.append([InlineKeyboardButton("🗂 Архив", callback_data='archived_tasks')])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')])
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data == 'archived_tasks':
        tasks = db.get_tasks('completed', limit=20)
        if not tasks:
            await query.edit_message_text(
                "📭 *Архив пуст*",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data='list_tasks')]
                ]),
                parse_mode='Markdown'
            )
            return
        
        text = "📦 *Выполненные задачи:*\n\n"
        for task in tasks[:20]:
            task_id, title, desc, category, priority, due_date, r3, r2, r1 = task
            due = f" (до {due_date})" if due_date else ""
            text += f"✅ *{title}*{due}\n"
            text += f"   📂 {category}\n\n"
        
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
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
            text += f"📅 Дедлайн: {task[5]}\n"
        if task[2]:
            text += f"📝 {task[2]}\n"
        text += f"📌 Статус: {'✅ Выполнено' if task[6] == 'completed' else '🔄 В процессе'}"
        
        # Показываем статус напоминаний
        text += f"\n\n⏰ Напоминания:\n"
        text += f"{'✅' if task[7] else '⏳'} За 3 дня\n"
        text += f"{'✅' if task[8] else '⏳'} За 2 дня\n"
        text += f"{'✅' if task[9] else '⏳'} За 1 день"
        
        await query.edit_message_text(text, reply_markup=task_actions_keyboard(task_id), parse_mode='Markdown')
    
    elif data.startswith('done_'):
        task_id = int(data.split('_')[1])
        db.update_task_status(task_id, 'completed')
        await query.edit_message_text(
            "✅ *Задача выполнена!* Отлично! 🎉\n\n"
            "Продолжайте в том же духе!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку задач", callback_data='list_tasks')],
                [InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]
            ]),
            parse_mode='Markdown'
        )
    
    elif data.startswith('delete_'):
        task_id = int(data.split('_')[1])
        db.delete_task(task_id)
        await query.edit_message_text(
            "🗑 Задача удалена.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 К списку задач", callback_data='list_tasks')],
                [InlineKeyboardButton("🔙 В меню", callback_data='back_to_menu')]
            ])
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
            "📂 *Категории*\n\n"
            "Выберите категорию для просмотра задач:",
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
        active, completed, overdue, by_category = db.get_stats()
        
        text = "📊 *Статистика задач*\n\n"
        text += f"🔄 Активных: {active}\n"
        text += f"✅ Выполнено: {completed}\n"
        text += f"⚠️ Просрочено: {overdue}\n"
        text += f"📊 Всего: {active + completed}\n\n"
        
        if by_category:
            text += "*По категориям:*\n"
            for cat, count in by_category:
                text += f"📂 {cat}: {count} задач\n"
        else:
            text += "Нет задач в категориях"
        
        # Процент выполнения
        total = active + completed
        if total > 0:
            completion_rate = (completed / total) * 100
            text += f"\n📈 *Выполнение:* {completion_rate:.1f}%"
        
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
        
        tasks = db.get_tasks('active')
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
    
    elif data == 'export_tasks':
        tasks = db.get_tasks('active')
        if not tasks:
            await query.edit_message_text("📭 Нет задач для экспорта.", reply_markup=main_menu())
            return
        
        # Формируем CSV
        csv_text = "ID,Название,Категория,Приоритет,Дедлайн,Статус\n"
        for task in tasks:
            csv_text += f"{task[0]},{task[1]},{task[3]},{task[4]},{task[5] or 'Нет'},Активна\n"
        
        # Отправляем файл
        await query.edit_message_text(
            "📦 *Экспорт задач*\n\n"
            "Нажмите на файл ниже чтобы скачать:",
            parse_mode='Markdown'
        )
        
        # Создаем файл и отправляем
        import io
        file = io.StringIO(csv_text)
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=file.getvalue().encode('utf-8'),
            filename=f'tasks_export_{datetime.now().strftime("%Y%m%d")}.csv',
            caption="📋 Список задач"
        )
    
    elif data == 'weekly_report':
        today = datetime.now().strftime('%Y-%m-%d')
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Получаем задачи за неделю
        db.cursor.execute('''
            SELECT status, COUNT(*) FROM tasks 
            WHERE due_date BETWEEN ? AND ? OR created_at BETWEEN ? AND ?
            GROUP BY status
        ''', (week_ago, today, week_ago, today))
        weekly_stats = db.cursor.fetchall()
        
        text = "📊 *Отчёт за неделю*\n"
        text += f"📅 {week_ago} - {today}\n\n"
        
        total = 0
        completed = 0
        for status, count in weekly_stats:
            total += count
            if status == 'completed':
                completed = count
                text += f"✅ Выполнено: {count}\n"
            else:
                text += f"🔄 Активных: {count}\n"
        
        text += f"\n📊 Всего задач: {total}\n"
        if total > 0:
            text += f"📈 Прогресс: {(completed/total)*100:.1f}%"
        
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == 'settings':
        keyboard = [
            [InlineKeyboardButton("🌍 Сменить город", callback_data='change_city')],
            [InlineKeyboardButton("🗑 Очистить все задачи", callback_data='clear_all')],
            [InlineKeyboardButton("📋 Просмотр архива", callback_data='archived_tasks')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
        ]
        await query.edit_message_text(
            "⚙️ *Настройки*\n\n"
            "Выберите действие:",
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
        text += "📋 Мои дела — список активных задач\n"
        text += "➕ Добавить дело — создать задачу\n"
        text += "📊 Статистика — общая статистика\n"
        text += "🗂 Категории — задачи по категориям\n"
        text += "🌤 Погода — погода в вашем городе\n"
        text += "📅 Календарь — задачи по датам\n"
        text += "📦 Экспорт — выгрузка задач в CSV\n"
        text += "📊 Отчёт за неделю — еженедельная статистика\n\n"
        text += "⏰ *Автоматические напоминания:*\n"
        text += "• За 3 дня до дедлайна\n"
        text += "• За 2 дня до дедлайна\n"
        text += "• За 1 день до дедлайна\n\n"
        text += "🔐 Бот доступен только администратору."
        
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    elif data == 'noop':
        pass

async def show_calendar(query, year, month):
    await query.edit_message_text(
        "📅 *Календарь*\n\nВыберите дату для просмотра задач:",
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
            [InlineKeyboardButton("🔴 Высокий", callback_data=f'priority_high_{title}_{date_str}')],
            [InlineKeyboardButton("🟡 Средний", callback_data=f'priority_medium_{title}_{date_str}')],
            [InlineKeyboardButton("🟢 Низкий", callback_data=f'priority_low_{title}_{date_str}')]
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
        
        # Спрашиваем дедлайн
        await query.edit_message_text(
            f"✏️ *{context.user_data.get('task_title', '')}*\n\n"
            f"📂 Категория: {category}\n\n"
            "📅 Введите дату дедлайна (в формате ДД.ММ.ГГГГ) или отправьте '-' чтобы пропустить:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_date_manual'
    
    elif data.startswith('priority_'):
        # Извлекаем приоритет, название и дату
        parts = data.split('_')
        priority_key = parts[1]
        priority_map = {
            'high': 'Высокий',
            'medium': 'Средний',
            'low': 'Низкий'
        }
        priority = priority_map.get(priority_key, 'Средний')
        
        # Если данные переданы через callback
        if len(parts) > 2:
            title = parts[2]
            date_str = parts[3] if len(parts) > 3 else None
        else:
            title = context.user_data.get('task_title', 'Без названия')
            date_str = context.user_data.get('task_date', None)
        
        category = context.user_data.get('task_category', 'Работа')
        
        # Парсим дату если есть
        due_date = None
        if date_str:
            try:
                # Если формат ДД.ММ.ГГГГ
                if '.' in date_str:
                    dt = datetime.strptime(date_str, '%d.%m.%Y')
                    due_date = dt.strftime('%Y-%m-%d')
                else:
                    due_date = date_str
            except:
                due_date = None
        
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
            f"🔵 Приоритет: {priority}\n\n"
            "⏰ Напоминания будут отправлены за 3, 2 и 1 день до дедлайна.",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        )

# ===================== ОБРАБОТКА РУЧНОГО ВВОДА ДЕДЛАЙНА =====================
async def handle_task_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
    
    text = update.message.text
    step = context.user_data.get('step')
    
    if step == 'add_task_date_manual':
        if text == '-':
            date_str = None
        else:
            try:
                # Парсим дату
                dt = datetime.strptime(text, '%d.%m.%Y')
                date_str = dt.strftime('%Y-%m-%d')
            except:
                await update.message.reply_text(
                    "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ или '-' для пропуска."
                )
                return
        
        title = context.user_data.get('task_title', 'Без названия')
        category = context.user_data.get('task_category', 'Работа')
        
        # Показываем выбор приоритета
        keyboard = [
            [InlineKeyboardButton("🔴 Высокий", callback_data=f'priority_high')],
            [InlineKeyboardButton("🟡 Средний", callback_data=f'priority_medium')],
            [InlineKeyboardButton("🟢 Низкий", callback_data=f'priority_low')]
        ]
        
        context.user_data['task_date'] = date_str
        date_text = f" до {text}" if text != '-' and text else " без дедлайна"
        
        await update.message.reply_text(
            f"✏️ *{title}*\n\n"
            f"📅 Дедлайн: {date_text}\n\n"
            "Выберите приоритет:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_priority'

# ===================== ОСНОВНАЯ ФУНКЦИЯ =====================
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(add_task_callback, pattern='^(set_cat_|priority_)'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_task_date))
    
    # Настраиваем фоновый планировщик для напоминаний
    job_queue = app.job_queue
    if job_queue:
        # Проверяем напоминания каждые 30 минут
        job_queue.run_repeating(check_reminders, interval=1800, first=10)
        logger.info("✅ Планировщик напоминаний запущен (каждые 30 минут)")
    
    print("=" * 60)
    print("🤖 Бот-планировщик с напоминаниями запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("📋 Функции: Задачи, Календарь, Погода, Статистика")
    print("⏰ Напоминания: за 3, 2 и 1 день до дедлайна")
    print("=" * 60)
    
    app.run_polling()

if __name__ == "__main__":
    main()
