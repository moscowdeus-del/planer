#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Планировщик задач с напоминаниями (3, 2, 1 день) - ИСПРАВЛЕННАЯ ВЕРСИЯ
Единый обработчик для всех callback и сообщений
"""

import sqlite3
import json
import logging
import io
import csv
from datetime import datetime, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMIN_ID = 1024761707

# ===================== API КЛЮЧИ =====================
OPENWEATHER_API_KEY = "190a44f2866cdf55936786fe537f190d"

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
                reminder_sent_3d INTEGER DEFAULT 0,
                reminder_sent_2d INTEGER DEFAULT 0,
                reminder_sent_1d INTEGER DEFAULT 0,
                completed_at TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        self.conn.commit()
        
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
    
    def get_tasks(self, status="active"):
        self.cursor.execute('''
            SELECT id, title, description, category, priority, due_date,
                   reminder_sent_3d, reminder_sent_2d, reminder_sent_1d
            FROM tasks WHERE status = ? ORDER BY due_date NULLS LAST, priority DESC
        ''', (status,))
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
    
    def add_category(self, name):
        self.cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (name,))
        self.conn.commit()
    
    def get_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active"')
        active = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "completed"')
        completed = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT COUNT(*) FROM tasks WHERE status = "active" AND due_date < date("now")')
        overdue = self.cursor.fetchone()[0]
        
        self.cursor.execute('''
            SELECT category, COUNT(*) FROM tasks WHERE status = "active" 
            GROUP BY category ORDER BY COUNT(*) DESC
        ''')
        by_category = self.cursor.fetchall()
        
        return active, completed, overdue, by_category
    
    def get_overdue_tasks(self):
        self.cursor.execute('''
            SELECT id, title, due_date FROM tasks 
            WHERE status = "active" AND due_date < date("now")
            ORDER BY due_date
        ''')
        return self.cursor.fetchall()
    
    def get_tasks_by_date(self, date_str):
        self.cursor.execute('''
            SELECT id, title, category, priority FROM tasks 
            WHERE status = "active" AND due_date = ?
            ORDER BY priority DESC
        ''', (date_str,))
        return self.cursor.fetchall()
    
    def mark_reminder_sent(self, task_id, days_before):
        field = f'reminder_sent_{days_before}d'
        self.cursor.execute(f'UPDATE tasks SET {field} = 1 WHERE id = ?', (task_id,))
        self.conn.commit()
    
    def get_tasks_for_reminder(self, days_before):
        target_date = (datetime.now() + timedelta(days=days_before)).strftime('%Y-%m-%d')
        field = f'reminder_sent_{days_before}d'
        self.cursor.execute(f'''
            SELECT id, title, due_date, category, priority
            FROM tasks 
            WHERE status = "active" AND due_date = ? AND {field} = 0
        ''', (target_date,))
        return self.cursor.fetchall()
    
    def get_setting(self, key):
        self.cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def set_setting(self, key, value):
        self.cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        self.conn.commit()

db = Database()

# ===================== ПОГОДА =====================
def get_weather(city):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('cod') != 200:
            return f"❌ Город '{city}' не найден"
        
        temp = data['main']['temp']
        feels_like = data['main']['feels_like']
        humidity = data['main']['humidity']
        pressure = data['main']['pressure']
        wind = data['wind']['speed']
        description = data['weather'][0]['description']
        
        return (f"🌤 *Погода в {city}*\n\n"
                f"🌡 Температура: {temp:.1f}°C (ощущается {feels_like:.1f}°C)\n"
                f"💧 Влажность: {humidity}%\n"
                f"📊 Давление: {pressure} мм рт. ст.\n"
                f"🌬 Ветер: {wind} м/с\n"
                f"📝 {description.capitalize()}")
    except Exception as e:
        return f"❌ Ошибка получения погоды: {str(e)}"

def get_city_by_ip():
    try:
        response = requests.get('https://ipapi.co/json/', timeout=10)
        return response.json().get('city', 'Москва')
    except:
        return 'Москва'

# ===================== ФОНОВЫЕ НАПОМИНАНИЯ =====================
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        for days in [3, 2, 1]:
            tasks = db.get_tasks_for_reminder(days)
            for task in tasks:
                task_id, title, due_date, category, priority = task
                priority_emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
                days_words = {3: 'через 3 дня', 2: 'через 2 дня', 1: 'завтра'}
                
                message = (f"⏰ *Напоминание!*\n\n"
                          f"📌 *{title}*\n"
                          f"📂 Категория: {category}\n"
                          f"{priority_emoji} Приоритет: {priority}\n"
                          f"📅 Дедлайн: {due_date}\n"
                          f"⏳ Осталось: {days_words[days]}")
                
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{task_id}")],
                        [InlineKeyboardButton("📝 Просмотр", callback_data=f"view:{task_id}")]
                    ])
                )
                db.mark_reminder_sent(task_id, days)
                logger.info(f"Напоминание отправлено для задачи #{task_id} ({days} дней)")
        
        # Просроченные задачи
        overdue = db.get_overdue_tasks()
        if overdue:
            msg = "⚠️ *Просроченные задачи!*\n\n"
            for task in overdue[:10]:
                msg += f"• {task[1]} (дедлайн: {task[2]})\n"
            await context.bot.send_message(chat_id=ADMIN_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в check_reminders: {e}")

# ===================== КЛАВИАТУРЫ =====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Мои дела", callback_data="list")],
        [InlineKeyboardButton("➕ Добавить дело", callback_data="add_start")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🗂 Категории", callback_data="categories")],
        [InlineKeyboardButton("🌤 Погода", callback_data="weather")],
        [InlineKeyboardButton("📅 Календарь", callback_data="calendar")],
        [InlineKeyboardButton("📦 Экспорт", callback_data="export")],
        [InlineKeyboardButton("📊 Отчёт за неделю", callback_data="weekly")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def categories_keyboard():
    keyboard = []
    for cat in db.get_categories():
        keyboard.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f"cat:{cat}")])
    keyboard.append([InlineKeyboardButton("➕ Новая категория", callback_data="add_category")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

def task_list_keyboard(tasks):
    keyboard = []
    for task in tasks[:10]:
        task_id = task[0]
        title = task[1][:30]
        keyboard.append([InlineKeyboardButton(f"• {title}", callback_data=f"view:{task_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

def task_actions_keyboard(task_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Выполнено", callback_data=f"done:{task_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete:{task_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="list")]
    ])

def priority_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Высокий", callback_data="priority:high")],
        [InlineKeyboardButton("🟡 Средний", callback_data="priority:medium")],
        [InlineKeyboardButton("🟢 Низкий", callback_data="priority:low")]
    ])

def calendar_keyboard(year, month):
    import calendar
    keyboard = []
    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    keyboard.append([InlineKeyboardButton(f"📅 {month_names[month-1]} {year}", callback_data="noop")])
    
    week_days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    row = []
    for day in week_days:
        row.append(InlineKeyboardButton(day, callback_data="noop"))
    keyboard.append(row)
    
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="noop"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(str(day), callback_data=f"caldate:{date_str}"))
        keyboard.append(row)
    
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data=f"cal:{prev_year}:{prev_month}"),
        InlineKeyboardButton("Сегодня", callback_data=f"cal:{year}:{month}"),
        InlineKeyboardButton("▶️", callback_data=f"cal:{next_year}:{next_month}")
    ])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="menu")])
    return InlineKeyboardMarkup(keyboard)

# ===================== ГЛАВНЫЙ ОБРАБОТЧИК =====================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    parts = data.split(':')
    action = parts[0]
    
    # ---- Навигация ----
    if action == "menu":
        await query.edit_message_text("🤖 *Планировщик задач*\n\nВыберите действие:", 
                                     reply_markup=main_menu(), parse_mode='Markdown')
    
    elif action == "list":
        tasks = db.get_tasks('active')
        if not tasks:
            await query.edit_message_text("📭 *Нет активных задач*", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="menu")]]),
                parse_mode='Markdown')
            return
        text = "📋 *Ваши задачи:*\n\n"
        today = datetime.now().strftime('%Y-%m-%d')
        for task in tasks:
            task_id, title, desc, category, priority, due_date, r3, r2, r1 = task
            emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
            overdue = " ⏰" if due_date and due_date < today else ""
            due = f" (до {due_date})" if due_date else ""
            text += f"{emoji} *{title}*{overdue}{due}\n   📂 {category}\n"
        await query.edit_message_text(text, reply_markup=task_list_keyboard(tasks), parse_mode='Markdown')
    
    elif action == "view":
        task_id = int(parts[1])
        task = db.get_task_by_id(task_id)
        if not task:
            await query.edit_message_text("❌ Задача не найдена.", reply_markup=main_menu())
            return
        text = (f"📌 *{task[1]}*\n\n"
                f"📂 Категория: {task[3]}\n"
                f"🔵 Приоритет: {task[4]}\n"
                f"📅 Дедлайн: {task[5] or 'Не указан'}\n"
                f"📝 {task[2] or 'Нет описания'}\n"
                f"📌 Статус: {'✅ Выполнено' if task[6] == 'completed' else '🔄 В процессе'}\n\n"
                f"⏰ Напоминания:\n"
                f"{'✅' if task[7] else '⏳'} За 3 дня\n"
                f"{'✅' if task[8] else '⏳'} За 2 дня\n"
                f"{'✅' if task[9] else '⏳'} За 1 день")
        await query.edit_message_text(text, reply_markup=task_actions_keyboard(task_id), parse_mode='Markdown')
    
    elif action == "done":
        task_id = int(parts[1])
        db.update_task_status(task_id, 'completed')
        await query.edit_message_text("✅ *Задача выполнена!* 🎉", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="list")]]),
            parse_mode='Markdown')
    
    elif action == "delete":
        task_id = int(parts[1])
        db.delete_task(task_id)
        await query.edit_message_text("🗑 Задача удалена.", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="list")]]))
    
    # ---- Категории ----
    elif action == "categories":
        await query.edit_message_text("📂 *Категории*", reply_markup=categories_keyboard(), parse_mode='Markdown')
    
    elif action == "cat":
        category = parts[1]
        tasks = db.get_tasks('active')
        filtered = [t for t in tasks if t[3] == category]
        if not filtered:
            await query.edit_message_text(f"📭 В категории '{category}' нет задач.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="categories")]]))
            return
        text = f"📂 *{category}*\n\n"
        for task in filtered:
            emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(task[4], "🟡")
            due = f" (до {task[5]})" if task[5] else ""
            text += f"{emoji} {task[1]}{due}\n"
        await query.edit_message_text(text, reply_markup=task_list_keyboard(filtered), parse_mode='Markdown')
    
    elif action == "add_category":
        await query.edit_message_text("✏️ Введите название новой категории:")
        context.user_data['step'] = 'add_category'
    
    # ---- Добавление задачи ----
    elif action == "add_start":
        await query.edit_message_text("✏️ Введите название задачи:")
        context.user_data['step'] = 'add_title'
    
    elif action == "setcat":
        category = parts[1]
        context.user_data['task_category'] = category
        await query.edit_message_text("📅 Введите дату дедлайна (ДД.ММ.ГГГГ) или '-' для пропуска:")
        context.user_data['step'] = 'add_date'
    
    elif action == "priority":
        priority_map = {'high': 'Высокий', 'medium': 'Средний', 'low': 'Низкий'}
        priority = priority_map.get(parts[1], 'Средний')
        
        title = context.user_data.get('task_title', 'Без названия')
        category = context.user_data.get('task_category', 'Работа')
        due_date = context.user_data.get('task_due_date')
        
        db.add_task(title, "", category, priority, due_date)
        
        context.user_data.clear()
        
        emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(priority, "🟡")
        date_text = f" (до {due_date})" if due_date else ""
        await query.edit_message_text(
            f"✅ *Задача добавлена!*\n\n{emoji} *{title}*{date_text}\n📂 Категория: {category}\n🔵 Приоритет: {priority}",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        )
    
    # ---- Календарь ----
    elif action == "calendar":
        now = datetime.now()
        await query.edit_message_text("📅 *Календарь*\n\nВыберите дату:", 
            reply_markup=calendar_keyboard(now.year, now.month), parse_mode='Markdown')
    
    elif action == "cal":
        year = int(parts[1])
        month = int(parts[2])
        await query.edit_message_text("📅 *Календарь*", 
            reply_markup=calendar_keyboard(year, month), parse_mode='Markdown')
    
    elif action == "caldate":
        date_str = parts[1]
        tasks = db.get_tasks_by_date(date_str)
        if not tasks:
            await query.edit_message_text(f"📅 Нет задач на {date_str}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="calendar")]]))
            return
        text = f"📅 *Задачи на {date_str}:*\n\n"
        for task in tasks:
            emoji = {"Высокий": "🔴", "Средний": "🟡", "Низкий": "🟢"}.get(task[3], "🟡")
            text += f"{emoji} {task[1]}\n"
        await query.edit_message_text(text, 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="calendar")]]),
            parse_mode='Markdown')
    
    # ---- Статистика ----
    elif action == "stats":
        active, completed, overdue, by_category = db.get_stats()
        text = f"📊 *Статистика*\n\n🔄 Активных: {active}\n✅ Выполнено: {completed}\n⚠️ Просрочено: {overdue}\n📊 Всего: {active + completed}\n\n"
        if by_category:
            text += "*По категориям:*\n"
            for cat, count in by_category:
                text += f"📂 {cat}: {count}\n"
        total = active + completed
        if total > 0:
            text += f"\n📈 Выполнение: {(completed/total)*100:.1f}%"
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    # ---- Погода ----
    elif action == "weather":
        city = db.get_setting('city') or 'Москва'
        await query.edit_message_text(get_weather(city), 
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="weather")],
                [InlineKeyboardButton("🌍 Сменить город", callback_data="change_city")],
                [InlineKeyboardButton("🔙 Назад", callback_data="menu")]
            ]),
            parse_mode='Markdown')
    
    elif action == "change_city":
        await query.edit_message_text("🌍 Введите название города:")
        context.user_data['step'] = 'change_city'
    
    # ---- Экспорт ----
    elif action == "export":
        tasks = db.get_tasks('active')
        if not tasks:
            await query.edit_message_text("📭 Нет задач для экспорта.", reply_markup=main_menu())
            return
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Название', 'Категория', 'Приоритет', 'Дедлайн'])
        for task in tasks:
            writer.writerow([task[0], task[1], task[3], task[4], task[5] or 'Нет'])
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=output.getvalue().encode('utf-8'),
            filename=f'tasks_{datetime.now().strftime("%Y%m%d")}.csv'
        )
        await query.edit_message_text("📦 Файл экспорта отправлен!", reply_markup=main_menu())
    
    # ---- Отчёт за неделю ----
    elif action == "weekly":
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')
        db.cursor.execute('''
            SELECT status, COUNT(*) FROM tasks 
            WHERE date(created_at) BETWEEN ? AND ? OR date(due_date) BETWEEN ? AND ?
            GROUP BY status
        ''', (week_ago, today, week_ago, today))
        weekly = db.cursor.fetchall()
        text = f"📊 *Отчёт за неделю*\n📅 {week_ago} - {today}\n\n"
        total = 0
        completed = 0
        for status, count in weekly:
            total += count
            if status == 'completed':
                completed = count
                text += f"✅ Выполнено: {count}\n"
            else:
                text += f"🔄 Активных: {count}\n"
        if total > 0:
            text += f"\n📈 Прогресс: {(completed/total)*100:.1f}%"
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode='Markdown')
    
    # ---- Настройки ----
    elif action == "settings":
        await query.edit_message_text("⚙️ *Настройки*", 
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌍 Сменить город", callback_data="change_city")],
                [InlineKeyboardButton("🗑 Очистить всё", callback_data="clear_confirm")],
                [InlineKeyboardButton("🔙 Назад", callback_data="menu")]
            ]),
            parse_mode='Markdown')
    
    elif action == "clear_confirm":
        await query.edit_message_text("⚠️ *Удалить все задачи?*",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да", callback_data="clear_yes")],
                [InlineKeyboardButton("❌ Нет", callback_data="settings")]
            ]),
            parse_mode='Markdown')
    
    elif action == "clear_yes":
        db.cursor.execute('DELETE FROM tasks')
        db.conn.commit()
        await query.edit_message_text("🗑 Все задачи удалены.", reply_markup=main_menu())
    
    # ---- Помощь ----
    elif action == "help":
        await query.edit_message_text(
            "❓ *Помощь*\n\n"
            "📋 Мои дела — список задач\n"
            "➕ Добавить дело — создать задачу\n"
            "📊 Статистика — общая статистика\n"
            "🗂 Категории — задачи по категориям\n"
            "🌤 Погода — погода\n"
            "📅 Календарь — задачи по датам\n"
            "📦 Экспорт — выгрузка CSV\n"
            "📊 Отчёт за неделю — еженедельная статистика\n\n"
            "⏰ *Напоминания:* за 3, 2 и 1 день до дедлайна",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        )
    
    elif action == "noop":
        pass

# ===================== ОБРАБОТКА СООБЩЕНИЙ =====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return
    
    text = update.message.text
    step = context.user_data.get('step')
    
    # ---- Добавление категории ----
    if step == 'add_category':
        db.add_category(text)
        context.user_data['step'] = None
        await update.message.reply_text(f"✅ Категория '{text}' добавлена!", reply_markup=main_menu())
        return
    
    # ---- Смена города ----
    if step == 'change_city':
        db.set_setting('city', text)
        context.user_data['step'] = None
        await update.message.reply_text(f"🌍 Город изменён на {text}", reply_markup=main_menu())
        return
    
    # ---- Добавление задачи: название ----
    if step == 'add_title':
        context.user_data['task_title'] = text
        # Показываем категории
        keyboard = []
        for cat in db.get_categories():
            keyboard.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f"setcat:{cat}")])
        keyboard.append([InlineKeyboardButton("➕ Новая категория", callback_data="add_category")])
        keyboard.append([InlineKeyboardButton("🔙 Отмена", callback_data="menu")])
        await update.message.reply_text(f"✏️ *{text}*\n\nВыберите категорию:", 
                                       reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    # ---- Добавление задачи: дата ----
    if step == 'add_date':
        if text == '-':
            context.user_data['task_due_date'] = None
        else:
            try:
                dt = datetime.strptime(text, '%d.%m.%Y')
                context.user_data['task_due_date'] = dt.strftime('%Y-%m-%d')
            except:
                await update.message.reply_text("❌ Неверный формат. Используйте ДД.ММ.ГГГГ или '-'")
                return
        await update.message.reply_text("Выберите приоритет:", reply_markup=priority_keyboard())
        context.user_data['step'] = 'add_priority'
        return

# ===================== ЗАПУСК =====================
async def post_init(app: Application):
    # Запускаем проверку напоминаний каждые 30 минут
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_reminders, interval=1800, first=10)
        logger.info("✅ Планировщик напоминаний запущен")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", 
        lambda u, c: u.message.reply_text(
            "🤖 *Планировщик задач*\n\nВыберите действие:",
            reply_markup=main_menu(),
            parse_mode='Markdown'
        ) if u.effective_user.id == ADMIN_ID else u.message.reply_text("⛔ Доступ запрещен.")))
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.post_init = post_init
    
    print("=" * 60)
    print("🤖 Бот-планировщик с напоминаниями запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("⏰ Напоминания: за 3, 2 и 1 день до дедлайна")
    print("=" * 60)
    
    app.run_polling()

if __name__ == "__main__":
    main()
