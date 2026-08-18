#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Планировщик задач с Яндекс API (погода, геокодер, поиск организаций)
"""

import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMIN_ID = 1024761707

# ===================== ЯНДЕКС API =====================
YANDEX_API_KEY = "7279c195-0ee9-4963-bcdc-92c563614bb8"
YANDEX_GEOCODER_URL = "https://geocode-maps.yandex.ru/1.x/"
YANDEX_WEATHER_URL = "https://api.weather.yandex.ru/v2/forecast"
YANDEX_SEARCH_URL = "https://search-maps.yandex.ru/v1/"
YANDEX_SUGGEST_URL = "https://suggest-maps.yandex.ru/v1/suggest"

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
        
        # Сохраняем город по умолчанию
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

# ===================== ЯНДЕКС API ФУНКЦИИ =====================

def geocode_address(address):
    """Получить координаты по адресу через Яндекс Геокодер"""
    try:
        params = {
            'apikey': YANDEX_API_KEY,
            'geocode': address,
            'format': 'json',
            'results': 1
        }
        response = requests.get(YANDEX_GEOCODER_URL, params=params, timeout=10)
        data = response.json()
        
        geo_objects = data.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])
        if not geo_objects:
            return None, None
        
        coords = geo_objects[0].get('GeoObject', {}).get('Point', {}).get('pos', '').split()
        if len(coords) == 2:
            lon, lat = coords[0], coords[1]
            return float(lat), float(lon)
        return None, None
    except Exception as e:
        logger.error(f"Geocode error: {e}")
        return None, None

def get_weather_by_city(city):
    """Получить погоду через Яндекс API"""
    try:
        # 1. Получаем координаты города
        lat, lon = geocode_address(city)
        if not lat or not lon:
            return f"❌ Город '{city}' не найден"
        
        # 2. Получаем погоду
        headers = {'X-Yandex-API-Key': YANDEX_API_KEY}
        params = {
            'lat': lat,
            'lon': lon,
            'lang': 'ru_RU',
            'limit': 1
        }
        
        response = requests.get(YANDEX_WEATHER_URL, headers=headers, params=params, timeout=10)
        data = response.json()
        
        if 'fact' not in data:
            return "❌ Ошибка получения погоды"
        
        fact = data['fact']
        forecast = data.get('forecasts', [{}])[0]
        
        temp = fact.get('temp', 0)
        feels_like = fact.get('feels_like', 0)
        humidity = fact.get('humidity', 0)
        wind_speed = fact.get('wind_speed', 0)
        pressure = fact.get('pressure_mm', 0)
        
        # Описание погоды
        condition_map = {
            'clear': '☀️ Ясно',
            'partly-cloudy': '⛅️ Малооблачно',
            'cloudy': '☁️ Облачно',
            'overcast': '☁️ Пасмурно',
            'drizzle': '🌧 Морось',
            'light-rain': '🌧 Небольшой дождь',
            'rain': '🌧 Дождь',
            'moderate-rain': '🌧 Умеренный дождь',
            'heavy-rain': '🌧 Сильный дождь',
            'continuous-heavy-rain': '🌧 Продолжительный дождь',
            'showers': '🌧 Ливень',
            'wet-snow': '🌨 Мокрый снег',
            'light-snow': '🌨 Небольшой снег',
            'snow': '🌨 Снег',
            'snow-showers': '🌨 Снегопад',
            'hail': '🌨 Град',
            'thunderstorm': '⛈ Гроза',
            'thunderstorm-with-rain': '⛈ Дождь с грозой',
            'thunderstorm-with-hail': '⛈ Град с грозой'
        }
        condition = condition_map.get(fact.get('condition', ''), fact.get('condition', 'Неизвестно'))
        
        # Восход/закат
        sunrise = forecast.get('sunrise', '')
        sunset = forecast.get('sunset', '')
        
        text = f"🌤 *Погода в {city}*\n\n"
        text += f"🌡 Температура: {temp}°C (ощущается {feels_like}°C)\n"
        text += f"☁️ {condition}\n"
        text += f"💧 Влажность: {humidity}%\n"
        text += f"🌬 Ветер: {wind_speed} м/с\n"
        text += f"📊 Давление: {pressure} мм рт. ст.\n"
        if sunrise and sunset:
            text += f"🌅 Рассвет: {sunrise}\n"
            text += f"🌇 Закат: {sunset}\n"
        
        return text
        
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return f"❌ Ошибка получения погоды: {str(e)}"

def search_organizations(query, lat=None, lon=None, city=None):
    """Поиск организаций через Яндекс API"""
    try:
        # Если указан город, получаем координаты
        if city and not lat:
            lat, lon = geocode_address(city)
        
        params = {
            'apikey': YANDEX_API_KEY,
            'text': query,
            'lang': 'ru_RU',
            'type': 'biz',
            'results': 10
        }
        
        if lat and lon:
            params['ll'] = f"{lon},{lat}"
            params['spn'] = '0.05,0.05'
        
        response = requests.get(YANDEX_SEARCH_URL, params=params, timeout=10)
        data = response.json()
        
        features = data.get('features', [])
        if not features:
            return "❌ Ничего не найдено"
        
        text = f"🔍 *Результаты поиска: {query}*\n\n"
        
        for i, feature in enumerate(features[:10], 1):
            props = feature.get('properties', {})
            name = props.get('name', 'Без названия')
            address = props.get('address', '')
            
            text += f"{i}. *{name}*\n"
            if address:
                text += f"   📍 {address}\n"
            text += "\n"
        
        return text
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"❌ Ошибка поиска: {str(e)}"

def get_address_suggestions(query):
    """Геосаджест (подсказки адресов)"""
    try:
        params = {
            'apikey': YANDEX_API_KEY,
            'text': query,
            'lang': 'ru_RU',
            'type': 'geo',
            'results': 5
        }
        
        response = requests.get(YANDEX_SUGGEST_URL, params=params, timeout=10)
        data = response.json()
        
        suggestions = data.get('suggestions', [])
        if not suggestions:
            return []
        
        return [s.get('displayText', '') for s in suggestions]
        
    except Exception as e:
        logger.error(f"Suggest error: {e}")
        return []

# ===================== КЛАВИАТУРЫ =====================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Мои дела", callback_data='list_tasks')],
        [InlineKeyboardButton("➕ Добавить дело", callback_data='add_task_start')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')],
        [InlineKeyboardButton("🗂 Категории", callback_data='categories')],
        [InlineKeyboardButton("🌤 Погода", callback_data='weather')],
        [InlineKeyboardButton("🔍 Поиск организаций", callback_data='search_orgs')],
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
    
    # Дни недели
    week_days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    row = []
    for day in week_days:
        row.append(InlineKeyboardButton(day, callback_data='noop'))
    keyboard.append(row)
    
    # Дни месяца
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
    
    # Навигация
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
    
    await update.message.reply_text(
        "🤖 *Планировщик задач с Яндекс API*\n\n"
        "📋 *Что я умею:*\n"
        "• Создавать задачи с категориями и приоритетами\n"
        "• Устанавливать сроки и напоминания\n"
        "• Показывать погоду через Яндекс API\n"
        "• Искать организации (магазины, аптеки, кафе)\n"
        "• Вести статистику задач\n"
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
            "✅ Задача выполнена! Отлично! 🎉",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]])
        )
    
    elif data.startswith('delete_'):
        task_id = int(data.split('_')[1])
        db.delete_task(task_id)
        await query.edit_message_text(
            "🗑 Задача удалена.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]])
        )
    
    elif data == 'back_to_list':
        await button_handler(update, context)
    
    elif data == 'add_task_start':
        await query.edit_message_text(
            "✏️ *Добавление задачи*\n\n"
            "Введите название задачи:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'add_task_title'
    
    elif data == 'categories':
        await query.edit_message_text(
            "📂 *Категории задач*\n\n"
            "Выберите категорию чтобы посмотреть задачи:",
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
    
    # ----- ПОГОДА (Яндекс) -----
    elif data == 'weather':
        city = db.get_setting('city') or 'Москва'
        weather_text = get_weather_by_city(city)
        await query.edit_message_text(
            weather_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data='weather')],
                [InlineKeyboardButton("🌍 Сменить город", callback_data='change_city')],
                [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
            ]),
            parse_mode='Markdown'
        )
    
    # ----- ПОИСК ОРГАНИЗАЦИЙ (Яндекс) -----
    elif data == 'search_orgs':
        await query.edit_message_text(
            "🔍 *Поиск организаций*\n\n"
            "Введите название организации или услуги:\n"
            "• Магазины\n"
            "• Аптеки\n"
            "• Кафе\n"
            "• Банки\n"
            "• и т.д.",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'search_orgs'
    
    elif data == 'change_city':
        await query.edit_message_text(
            "🌍 *Смена города*\n\n"
            "Введите название города:",
            parse_mode='Markdown'
        )
        context.user_data['step'] = 'change_city'
    
    # ----- КАЛЕНДАРЬ -----
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
    
    # ----- НАСТРОЙКИ -----
    elif data == 'settings':
        keyboard = [
            [InlineKeyboardButton("🌍 Сменить город", callback_data='change_city')],
            [InlineKeyboardButton("🗑 Очистить все задачи", callback_data='clear_all')],
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
        text += "📋 *Мои дела* — список всех активных задач\n"
        text += "➕ *Добавить дело* — создать новую задачу\n"
        text += "📊 *Статистика* — общая статистика задач\n"
        text += "🗂 *Категории* — задачи по категориям\n"
        text += "🌤 *Погода* — погода в вашем городе (Яндекс)\n"
        text += "🔍 *Поиск организаций* — поиск магазинов, кафе, аптек (Яндекс)\n"
        text += "📅 *Календарь* — просмотр задач по датам\n\n"
        text += "📝 *Как добавить задачу:*\n"
        text += "1. Нажмите '➕ Добавить дело'\n"
        text += "2. Введите название\n"
        text += "3. Выберите категорию\n"
        text += "4. Выберите приоритет\n"
        text += "5. Укажите срок (опционально)\n\n"
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
    
    # ---- Добавление задачи (шаг 1: название) ----
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
    
    # ---- Добавление категории ----
    elif step == 'add_category':
        db.cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (text,))
        db.conn.commit()
        context.user_data['step'] = None
        await update.message.reply_text(
            f"✅ Категория '{text}' добавлена!",
            reply_markup=main_menu()
        )
    
    # ---- Смена города ----
    elif step == 'change_city':
        context.user_data['step'] = None
        db.set_setting('city', text)
        await update.message.reply_text(
            f"🌍 Город изменён на {text}",
            reply_markup=main_menu()
        )
    
    # ---- Поиск организаций ----
    elif step == 'search_orgs':
        context.user_data['step'] = None
        city = db.get_setting('city') or 'Москва'
        result = search_organizations(text, city=city)
        await update.message.reply_text(
            result,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Новый поиск", callback_data='search_orgs')],
                [InlineKeyboardButton("🔙 Назад", callback_data='back_to_menu')]
            ])
        )
    
    # ---- Добавление задачи с датой ----
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
        
        task_id = db.add_task(title, "", category, priority, due_date)
        
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

# ===================== ОСНОВНАЯ ФУНКЦИЯ =====================
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(add_task_callback, pattern='^(set_cat_|priority_)'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("=" * 50)
    print("🤖 Бот-планировщик с Яндекс API запущен!")
    print(f"👤 Админ ID: {ADMIN_ID}")
    print("📋 Функции: Задачи, Календарь, Погода, Поиск организаций")
    print("=" * 50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
