import os
import logging
import urllib3
import sqlite3
import json
import uuid
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

from company_info_agent import CompanyInfoAgent
from revenue_extractor_agent import RevenueExtractorAgent

# Отключаем предупреждения SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Загружаем переменные из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("Не найден TELEGRAM_BOT_TOKEN в переменных окружения!")


# Приветственное сообщение
START_MESSAGE = (
    "Привет! Я агент для сбора информации о компании.\n\n"
    "Расскажите о вашей компании, и я помогу собрать всю необходимую информацию:\n"
    "• Отрасль деятельности\n"
    "• Примерная выручка\n"
    "• Численность сотрудников\n\n"
    "Просто опишите свою компанию в свободной форме!"
)


# Глобальный словарь для хранения агентов пользователей
user_agents = {}

# Агент для извлечения категории выручки
revenue_agent = None

# База данных
DB_NAME = 'data_storage.db'


def get_revenue_agent() -> RevenueExtractorAgent:
    """Получить или создать агента для извлечения выручки."""
    global revenue_agent
    if revenue_agent is None:
        revenue_agent = RevenueExtractorAgent()
        logger.info("Создан агент извлечения категории выручки")
    return revenue_agent


def save_chat_session(chat_id: int, dialog: str, company_info: dict, revenue_category: str = None):
    """
    Сохранение диалога пользователя в базу данных.
    
    Args:
        chat_id: ID чата в Telegram
        dialog: Полный диалог (вопросы бота + ответы пользователя)
        company_info: Информация о компании в формате dict
        revenue_category: Категория выручки (опционально)
    """
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Генерируем уникальный session_id
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Сохраняем в БД
        cursor.execute('''
            INSERT INTO chat_sessions 
            (chat_id, session_id, user_response, company_info, revenue_category, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            chat_id,
            session_id,
            dialog,
            json.dumps(company_info, ensure_ascii=False),
            revenue_category,
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Диалог сохранен в БД: chat_id={chat_id}, session_id={session_id}, revenue={revenue_category}")
        return session_id
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении в БД: {e}", exc_info=True)
        return None


def collect_user_responses_from_agent(agent: CompanyInfoAgent) -> str:
    """
    Собирает весь диалог из истории агента (вопросы бота + ответы пользователя).
    
    Args:
        agent: Экземпляр CompanyInfoAgent
        
    Returns:
        str: Полный диалог в читаемом формате
    """
    dialog_lines = []
    
    for msg in agent.dialog_history:
        role = msg.get('role', '')
        content = msg.get('content', '').strip()
        
        if not content:
            continue
        
        if role == 'user':
            dialog_lines.append(f"Пользователь: {content}")
        elif role == 'assistant':
            # Извлекаем только вопрос из ответа бота (clarification_question из JSON)
            # Если это JSON-ответ, пытаемся извлечь вопрос
            try:
                # Ищем JSON в ответе
                start_idx = content.find('{')
                end_idx = content.rfind('}')
                
                if start_idx != -1 and end_idx != -1:
                    json_str = content[start_idx:end_idx + 1]
                    data = json.loads(json_str)
                    
                    # Если есть clarification_question - используем его
                    if 'clarification_question' in data and data['clarification_question']:
                        dialog_lines.append(f"Бот: {data['clarification_question']}")
                    # Иначе сохраняем весь контент (может быть системное сообщение)
                    else:
                        # Пропускаем системные JSON-ответы без вопроса
                        pass
                else:
                    # Если это не JSON, а обычный текст - сохраняем как есть
                    dialog_lines.append(f"Бот: {content}")
            except (json.JSONDecodeError, ValueError):
                # Если не удалось распарсить - сохраняем как обычный текст
                dialog_lines.append(f"Бот: {content}")
    
    # Объединяем диалог через перенос строки
    full_dialog = '\n'.join(dialog_lines)
    
    logger.info(f"Собран диалог из {len(dialog_lines)} реплик")
    return full_dialog


def get_user_agent(user_id: int) -> CompanyInfoAgent:
    """Получить или создать агента для пользователя."""
    if user_id not in user_agents:
        user_agents[user_id] = CompanyInfoAgent()
        logger.info(f"Создан новый агент для пользователя {user_id}")
    return user_agents[user_id]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Сбрасываем агента для пользователя (новый диалог)
    if user_id in user_agents:
        user_agents[user_id].reset_dialog()
        logger.info(f"Сброшен агент для пользователя {user_id}")
    
    # Инициализируем состояние диалога
    context.user_data['dialog_started'] = False
    
    await update.message.reply_text(START_MESSAGE)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /reset - сброс диалога"""
    user_id = update.effective_user.id
    
    if user_id in user_agents:
        user_agents[user_id].reset_dialog()
        logger.info(f"Диалог сброшен для пользователя {user_id}")
    
    context.user_data['dialog_started'] = False
    
    await update.message.reply_text(
        "Диалог сброшен! Можете начать заново.\n\n"
        "Расскажите о вашей компании."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")
    
    try:
        # Получаем агента для пользователя
        agent = get_user_agent(user_id)
        
        # Проверяем, первое ли это сообщение в диалоге
        dialog_started = context.user_data.get('dialog_started', False)
        
        if not dialog_started:
            # Первое сообщение - запускаем collect_company_info
            context.user_data['dialog_started'] = True
            complete, info, message = agent.collect_company_info(user_message)
        else:
            # Продолжение диалога - используем continue_dialog
            complete, info, message = agent.continue_dialog(user_message)
        
        # Отправляем ответ пользователю
        await update.message.reply_text(message)
        
        # Если информация собрана полностью - сохраняем в БД и сбрасываем диалог
        if complete:
            logger.info(f"Информация собрана для пользователя {user_id}: {info}")
            
            # Собираем весь диалог из истории
            dialog = collect_user_responses_from_agent(agent)
            
            # Извлекаем категорию выручки из диалога
            try:
                rev_agent = get_revenue_agent()
                revenue_category = rev_agent.extract_revenue_category(dialog)
                logger.info(f"Категория выручки: {revenue_category}")
            except Exception as e:
                logger.error(f"Ошибка при извлечении категории выручки: {e}")
                revenue_category = None
            
            # Сохраняем в БД
            session_id = save_chat_session(user_id, dialog, info, revenue_category)
            
            if session_id:
                logger.info(f"Данные сохранены в БД: session_id={session_id}")
            
            # Сбрасываем состояние
            context.user_data['dialog_started'] = False
            
            # Дополнительное сообщение с категорией выручки
            extra_msg = "\nЧтобы начать новый опрос, просто напишите о другой компании или используйте /reset"
            
            if revenue_category:
                extra_msg = f"\n📊 Определена категория выручки: {revenue_category}" + extra_msg
            
            await update.message.reply_text(extra_msg)
    
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего сообщения. "
            "Попробуйте еще раз или используйте /reset для сброса диалога."
        )


def main():
    """Запуск бота"""
    logger.info("Запуск телеграм бота...")
    
    # Создаём приложение
    application = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    logger.info("Бот запущен и готов к работе...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
