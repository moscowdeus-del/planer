import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8811262187:AAEssO3CfPRKIXJW1Qh3Nxj-je-yKTBJLnc"
ADMIN_ID = "1024761707"

# Временное хранилище
user_data = {}

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📋 Мои дела", callback_data='list')],
        [InlineKeyboardButton("➕ Добавить дело", callback_data='add')],
        [InlineKeyboardButton("📊 Статистика", callback_data='stats')]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return
    
    await update.message.reply_text(
        "🤖 *Планировщик задач*\n\nВыберите действие:",
        reply_markup=main_menu(),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'list':
        tasks = user_data.get('tasks', [])
        if not tasks:
            await query.edit_message_text("📭 Нет задач")
        else:
            text = "📋 *Ваши задачи:*\n\n"
            for i, task in enumerate(tasks, 1):
                text += f"{i}. {task}\n"
            await query.edit_message_text(text, parse_mode='Markdown')
    
    elif query.data == 'add':
        await query.edit_message_text("✏️ Введите название задачи:")
        context.user_data['step'] = 'add_task'
    
    elif query.data == 'stats':
        tasks = user_data.get('tasks', [])
        await query.edit_message_text(f"📊 Всего задач: {len(tasks)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        return
    
    if context.user_data.get('step') == 'add_task':
        task = update.message.text
        if 'tasks' not in user_data:
            user_data['tasks'] = []
        user_data['tasks'].append(task)
        context.user_data['step'] = None
        await update.message.reply_text(f"✅ Задача \"{task}\" добавлена!", reply_markup=main_menu())

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()