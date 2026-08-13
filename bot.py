import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
DATA_FILE = "tasks_data.json"

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========
def load_data():
    """Загрузка данных из файла"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    return {}

def save_data(data):
    """Сохранение данных в файл"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_data(user_id: str):
    """Получение данных пользователя"""
    data = load_data()
    if user_id not in data:
        data[user_id] = {"tasks": [], "next_id": 1}
        save_data(data)
    return data[user_id]

def save_user_data(user_id: str, user_data):
    """Сохранение данных пользователя"""
    data = load_data()
    data[user_id] = user_data
    save_data(data)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def format_date(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "Без даты"
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return "Некорректная дата"

def get_priority_emoji(priority: str) -> str:
    emojis = {
        "critical": "🔥",
        "important": "⚠️",
        "normal": "🟢"
    }
    return emojis.get(priority, "🟢")

def get_section_emoji(section: str) -> str:
    emojis = {
        "work": "💼",
        "personal": "🏠",
        "ideas": "💡"
    }
    return emojis.get(section, "📌")

def get_section_name(section: str) -> str:
    names = {
        "work": "Работа",
        "personal": "Личное",
        "ideas": "Идеи"
    }
    return names.get(section, section)

# ========== КЛАВИАТУРЫ ==========
def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("💼 Работа", callback_data="section_work")],
        [InlineKeyboardButton("🏠 Личное", callback_data="section_personal")],
        [InlineKeyboardButton("💡 Идеи", callback_data="section_ideas")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
    ]
    return InlineKeyboardMarkup(keyboard)

def section_menu(section: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📋 Список задач", callback_data=f"list_{section}")],
        [InlineKeyboardButton("➕ Добавить задачу", callback_data=f"add_{section}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def task_actions(task_id: int, section: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Выполнено", callback_data=f"done_{task_id}"),
            InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_{task_id}")
        ],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"back_section_{section}")]
    ]
    if section == "ideas":
        keyboard.insert(0, [
            InlineKeyboardButton("💼 В работу", callback_data=f"to_work_{task_id}"),
            InlineKeyboardButton("🏠 В личное", callback_data=f"to_personal_{task_id}")
        ])
    return InlineKeyboardMarkup(keyboard)

def priority_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔥 Критично", callback_data="priority_critical"),
            InlineKeyboardButton("⚠️ Важно", callback_data="priority_important"),
            InlineKeyboardButton("🟢 Обычно", callback_data="priority_normal")
        ],
        [InlineKeyboardButton("🔙 Отмена", callback_data="cancel_priority")]
    ]
    return InlineKeyboardMarkup(keyboard)

def reminder_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("1 день", callback_data="remind_1"),
            InlineKeyboardButton("3 дня", callback_data="remind_3"),
            InlineKeyboardButton("7 дней", callback_data="remind_7")
        ],
        [
            InlineKeyboardButton("30 дней", callback_data="remind_30"),
            InlineKeyboardButton("❌ Не напоминать", callback_data="remind_none")
        ],
        [InlineKeyboardButton("🔙 Отмена", callback_data="cancel_reminder")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        await update.message.reply_text("⛔ Доступ запрещен.")
        return
    
    # Инициализация данных пользователя
    get_user_data(user_id)
    
    await update.message.reply_text(
        "🤖 *Планировщик задач v3.0*\n\n"
        "Выберите раздел для работы:\n\n"
        "💼 **Работа** — дедлайны, приоритеты, строгие напоминания\n"
        "🏠 **Личное** — покупки, быт, здоровье\n"
        "💡 **Идеи** — без дат, с возможностью напоминания",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = str(query.from_user.id)
    if user_id != str(ADMIN_ID):
        await query.edit_message_text("⛔ Доступ запрещен.")
        return
    
    data = query.data
    user_data = get_user_data(user_id)
    
    # Навигация
    if data == "back_main":
        await query.edit_message_text(
            "🤖 Главное меню\n\nВыберите раздел:",
            reply_markup=main_menu()
        )
        return
    
    if data.startswith("section_"):
        section = data.replace("section_", "")
        context.user_data["current_section"] = section
        await query.edit_message_text(
            f"{get_section_emoji(section)} *{get_section_name(section)}*\n\n"
            f"Выберите действие:",
            reply_markup=section_menu(section),
            parse_mode="Markdown"
        )
        return
    
    if data.startswith("back_section_"):
        section = data.replace("back_section_", "")
        context.user_data["current_section"] = section
        await query.edit_message_text(
            f"{get_section_emoji(section)} *{get_section_name(section)}*\n\n"
            f"Выберите действие:",
            reply_markup=section_menu(section),
            parse_mode="Markdown"
        )
        return
    
    # Список задач
    if data.startswith("list_"):
        section = data.replace("list_", "")
        tasks = [t for t in user_data["tasks"] if t["section"] == section and not t.get("done", False)]
        
        if not tasks:
            await query.edit_message_text(
                f"{get_section_emoji(section)} В разделе *{get_section_name(section)}* нет активных задач",
                parse_mode="Markdown",
                reply_markup=section_menu(section)
            )
            return
        
        text = f"{get_section_emoji(section)} *{get_section_name(section)}* — активные задачи:\n\n"
        for i, task in enumerate(tasks, 1):
            priority_emoji = get_priority_emoji(task.get("priority", "normal"))
            date_str = format_date(task.get("deadline"))
            
            is_overdue = False
            if task.get("deadline"):
                try:
                    deadline = datetime.fromisoformat(task["deadline"])
                    if deadline < datetime.now():
                        is_overdue = True
                except ValueError:
                    pass
            
            status = " ⏰ *ПРОСРОЧЕНО!*" if is_overdue else ""
            text += f"{i}. {priority_emoji} *{task['title']}*{status}\n"
            text += f"   📅 {date_str}\n"
            
            if task.get("reminder_days"):
                text += f"   🔔 Напомнить через {task['reminder_days']} дней\n"
        
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=section_menu(section)
        )
        return
    
    # Добавление задачи
    if data.startswith("add_"):
        section = data.replace("add_", "")
        context.user_data["add_section"] = section
        context.user_data["step"] = "waiting_task_title"
        
        await query.edit_message_text(
            f"✏️ Введите название задачи для раздела *{get_section_name(section)}*:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Отмена", callback_data=f"back_section_{section}")]
            ])
        )
        return
    
    # Приоритет
    if data.startswith("priority_"):
        priority = data.replace("priority_", "")
        context.user_data["task_priority"] = priority
        context.user_data["step"] = "waiting_deadline"
        
        await query.edit_message_text(
            "📅 Введите дату и время дедлайна в формате:\n"
            "`DD.MM.YYYY HH:MM`\n\n"
            "Например: `25.12.2026 18:00`\n"
            "Или нажмите «Пропустить»",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ Пропустить", callback_data="skip_deadline")],
                [InlineKeyboardButton("🔙 Отмена", callback_data="cancel_deadline")]
            ])
        )
        return
    
    if data == "skip_deadline":
        context.user_data["task_deadline"] = None
        await save_task_from_context(update, context, query)
        return
    
    if data == "cancel_deadline" or data == "cancel_priority" or data == "cancel_reminder":
        section = context.user_data.get("add_section", "work")
        context.user_data["step"] = None
        await query.edit_message_text(
            "❌ Добавление отменено",
            reply_markup=section_menu(section)
        )
        return
    
    # Напоминание для идей
    if data.startswith("remind_"):
        days = data.replace("remind_", "")
        if days == "none":
            context.user_data["reminder_days"] = None
        else:
            context.user_data["reminder_days"] = int(days)
        
        await save_task_from_context(update, context, query)
        return
    
    # Действия с задачей
    if data.startswith("done_"):
        task_id = int(data.replace("done_", ""))
        for task in user_data["tasks"]:
            if task["id"] == task_id:
                task["done"] = True
                task["done_at"] = datetime.now().isoformat()
                save_user_data(user_id, user_data)
                await query.edit_message_text(
                    f"✅ Задача *{task['title']}* выполнена!",
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )
                return
        await query.edit_message_text("❌ Задача не найдена")
        return
    
    if data.startswith("delete_"):
        task_id = int(data.replace("delete_", ""))
        user_data["tasks"] = [t for t in user_data["tasks"] if t["id"] != task_id]
        save_user_data(user_id, user_data)
        await query.edit_message_text("🗑 Задача удалена", reply_markup=main_menu())
        return
    
    if data.startswith("to_work_"):
        task_id = int(data.replace("to_work_", ""))
        for task in user_data["tasks"]:
            if task["id"] == task_id:
                task["section"] = "work"
                task["deadline"] = (datetime.now() + timedelta(days=3)).isoformat()
                save_user_data(user_id, user_data)
                await query.edit_message_text(
                    f"💼 Идея *{task['title']}* перенесена в Работу!\n"
                    f"Дедлайн установлен на {format_date(task['deadline'])}",
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )
                return
        await query.edit_message_text("❌ Задача не найдена")
        return
    
    if data.startswith("to_personal_"):
        task_id = int(data.replace("to_personal_", ""))
        for task in user_data["tasks"]:
            if task["id"] == task_id:
                task["section"] = "personal"
                save_user_data(user_id, user_data)
                await query.edit_message_text(
                    f"🏠 Идея *{task['title']}* перенесена в Личное",
                    parse_mode="Markdown",
                    reply_markup=main_menu()
                )
                return
        await query.edit_message_text("❌ Задача не найдена")
        return
    
    # Статистика
    if data == "stats":
        tasks = user_data["tasks"]
        total = len(tasks)
        done = len([t for t in tasks if t.get("done", False)])
        active = total - done
        
        work = len([t for t in tasks if t["section"] == "work" and not t.get("done", False)])
        personal = len([t for t in tasks if t["section"] == "personal" and not t.get("done", False)])
        ideas = len([t for t in tasks if t["section"] == "ideas" and not t.get("done", False)])
        
        overdue = len([
            t for t in tasks 
            if t["section"] == "work" 
            and not t.get("done", False) 
            and t.get("deadline") 
            and datetime.fromisoformat(t["deadline"]) < datetime.now()
        ])
        
        text = (
            "📊 *Статистика*\n\n"
            f"📌 Всего задач: {total}\n"
            f"✅ Выполнено: {done}\n"
            f"⏳ Активных: {active}\n\n"
            f"💼 Работа: {work} активных" + (f" (⚠️ {overdue} просрочено)" if overdue else "") + "\n"
            f"🏠 Личное: {personal} активных\n"
            f"💡 Идеи: {ideas} активных"
        )
        
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return
    
    # Поиск
    if data == "search":
        context.user_data["step"] = "searching"
        await query.edit_message_text(
            "🔍 Введите поисковый запрос\n\n"
            "Бот найдет задачи по всем разделам",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="back_main")]
            ])
        )
        return

async def save_task_from_context(update, context, query):
    """Сохранение задачи из контекста"""
    user_id = str(query.from_user.id)
    user_data = get_user_data(user_id)
    
    task = {
        "id": user_data["next_id"],
        "title": context.user_data.get("task_title"),
        "section": context.user_data.get("add_section"),
        "priority": context.user_data.get("task_priority", "normal"),
        "deadline": context.user_data.get("task_deadline"),
        "reminder_days": context.user_data.get("reminder_days"),
        "done": False,
        "created_at": datetime.now().isoformat()
    }
    
    user_data["tasks"].append(task)
    user_data["next_id"] += 1
    save_user_data(user_id, user_data)
    
    # Очищаем временные данные
    context.user_data["step"] = None
    context.user_data["task_title"] = None
    context.user_data["task_priority"] = None
    context.user_data["task_deadline"] = None
    context.user_data["reminder_days"] = None
    
    section = task["section"]
    await query.edit_message_text(
        f"✅ Задача *{task['title']}* добавлена в раздел *{get_section_name(section)}*!",
        parse_mode="Markdown",
        reply_markup=section_menu(section)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = str(update.effective_user.id)
    if user_id != str(ADMIN_ID):
        return
    
    text = update.message.text
    user_data = get_user_data(user_id)
    step = context.user_data.get("step")
    
    # Поиск
    if step == "searching":
        tasks = user_data["tasks"]
        results = [t for t in tasks if text.lower() in t["title"].lower() and not t.get("done", False)]
        
        if not results:
            await update.message.reply_text(
                "🔍 Ничего не найдено",
                reply_markup=main_menu()
            )
        else:
            text_response = f"🔍 Результаты поиска по запросу *{text}*:\n\n"
            for task in results[:10]:  # Ограничиваем 10 результатов
                section_emoji = get_section_emoji(task["section"])
                priority_emoji = get_priority_emoji(task.get("priority", "normal"))
                text_response += f"{section_emoji} {priority_emoji} *{task['title']}*\n"
                text_response += f"   Раздел: {get_section_name(task['section'])}\n"
            
            if len(results) > 10:
                text_response += f"\n...и еще {len(results) - 10} результатов"
            
            await update.message.reply_text(
                text_response,
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        
        context.user_data["step"] = None
        return
    
    # Добавление задачи
    if step == "waiting_task_title":
        context.user_data["task_title"] = text
        section = context.user_data.get("add_section")
        
        if section == "work":
            await update.message.reply_text(
                "🔥 Выберите приоритет задачи:",
                reply_markup=priority_keyboard()
            )
        elif section == "ideas":
            await update.message.reply_text(
                "💡 Отлично! Напомнить через сколько дней?\n"
                "(Идеи без напоминания будут просто храниться в списке)",
                reply_markup=reminder_keyboard()
            )
        else:  # personal
            context.user_data["task_deadline"] = None
            await save_task_from_message(update, context)
        return
    
    # Дедлайн
    if step == "waiting_deadline":
        try:
            dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
            context.user_data["task_deadline"] = dt.isoformat()
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат. Используйте `DD.MM.YYYY HH:MM`\n"
                "Например: `25.12.2026 18:00`",
                parse_mode="Markdown"
            )
            return
        
        await save_task_from_message(update, context)
        return

async def save_task_from_message(update, context):
    """Сохранение задачи из текстового сообщения"""
    user_id = str(update.effective_user.id)
    user_data = get_user_data(user_id)
    
    task = {
        "id": user_data["next_id"],
        "title": context.user_data.get("task_title"),
        "section": context.user_data.get("add_section"),
        "priority": context.user_data.get("task_priority", "normal"),
        "deadline": context.user_data.get("task_deadline"),
        "reminder_days": context.user_data.get("reminder_days"),
        "done": False,
        "created_at": datetime.now().isoformat()
    }
    
    user_data["tasks"].append(task)
    user_data["next_id"] += 1
    save_user_data(user_id, user_data)
    
    # Очищаем временные данные
    context.user_data["step"] = None
    context.user_data["task_title"] = None
    context.user_data["task_priority"] = None
    context.user_data["task_deadline"] = None
    context.user_data["reminder_days"] = None
    
    section = task["section"]
    await update.message.reply_text(
        f"✅ Задача *{task['title']}* добавлена в раздел *{get_section_name(section)}*!",
        parse_mode="Markdown",
        reply_markup=section_menu(section)
    )

# ========== ЕЖЕДНЕВНЫЙ ДАШБОРД ==========
def send_daily_dashboard():
    """Отправка ежедневного дашборда (запускается в фоне)"""
    import asyncio
    from telegram import Bot
    
    async def _send():
        bot = Bot(token=TOKEN)
        user_data = get_user_data(str(ADMIN_ID))
        tasks = user_data["tasks"]
        
        active = [t for t in tasks if not t.get("done", False)]
        work = [t for t in active if t["section"] == "work"]
        personal = [t for t in active if t["section"] == "personal"]
        ideas = [t for t in active if t["section"] == "ideas"]
        
        overdue = [
            t for t in work 
            if t.get("deadline") 
            and datetime.fromisoformat(t["deadline"]) < datetime.now()
        ]
        
        text = (
            "🌅 *Доброе утро! Ваш план на сегодня:*\n\n"
            f"💼 Работа: {len(work)} задач" + (f" (⚠️ {len(overdue)} просрочено)" if overdue else "") + "\n"
            f"🏠 Личное: {len(personal)} задач\n"
            f"💡 Идеи: {len(ideas)} ждут своего часа\n"
        )
        
        if overdue:
            text += "\n*⚠️ Просроченные задачи:*\n"
            for task in overdue[:3]:
                text += f"• {task['title']} (до {format_date(task['deadline'])})\n"
            if len(overdue) > 3:
                text += f"• ...и еще {len(overdue) - 3}\n"
        
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except Exception as e:
            logger.error(f"Ошибка отправки дашборда: {e}")
    
    asyncio.run(_send())

# ========== ЗАПУСК БОТА ==========
def main():
    """Запуск бота"""
    logger.info("Запуск бота...")
    
    app = Application.builder().token(TOKEN).build()
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Планировщик для дашборда (каждый день в 9:00)
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_daily_dashboard,
        CronTrigger(hour=9, minute=0),
        id="daily_dashboard"
    )
    scheduler.start()
    logger.info("Планировщик запущен")
    
    logger.info("✅ Бот готов к работе!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()