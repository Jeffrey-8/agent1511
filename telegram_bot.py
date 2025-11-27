import os
import logging
import urllib3
import sqlite3
import json
import uuid
import asyncio
from datetime import datetime
from typing import List, Optional
from telegram import Update
from telegram.error import TimedOut, NetworkError, RetryAfter
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

from company_info_agent import CompanyInfoAgent
from revenue_extractor_agent import RevenueExtractorAgent
from calculation_params_agent import CalculationParamsAgent
from okved_agent import OkvedAgent
from analytics_engine import calculate_potential_full_pipeline
from results_formatter import format_calculation_results, format_filters_summary

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


# Максимальная длина сообщения Telegram (4096 символов)
MAX_MESSAGE_LENGTH = 4096


async def safe_send_message(update: Update, text: str, parse_mode: str = None, max_retries: int = 3):
    """
    Безопасная отправка сообщения с обработкой ошибок сети и разбиением на части.
    
    Args:
        update: Объект Update от Telegram
        text: Текст сообщения
        parse_mode: Режим парсинга (Markdown, HTML и т.д.)
        max_retries: Максимальное количество попыток при ошибке сети
    """
    if not text or not text.strip():
        return
    
    # Разбиваем длинные сообщения на части
    if len(text) > MAX_MESSAGE_LENGTH:
        # Разбиваем по строкам, стараясь не разрывать структуру
        parts = []
        current_part = ""
        
        for line in text.split('\n'):
            if len(current_part) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                if current_part:
                    parts.append(current_part)
                    current_part = line + '\n'
                else:
                    # Если одна строка слишком длинная, разбиваем её
                    while len(line) > MAX_MESSAGE_LENGTH:
                        parts.append(line[:MAX_MESSAGE_LENGTH])
                        line = line[MAX_MESSAGE_LENGTH:]
                    current_part = line + '\n'
            else:
                current_part += line + '\n'
        
        if current_part:
            parts.append(current_part)
    else:
        parts = [text]
    
    # Отправляем каждую часть с retry логикой
    for part_num, part in enumerate(parts, 1):
        for attempt in range(max_retries):
            try:
                if len(parts) > 1:
                    # Добавляем индикатор части для многочастных сообщений
                    part_with_header = f"📄 Часть {part_num}/{len(parts)}\n\n{part}"
                    if len(part_with_header) > MAX_MESSAGE_LENGTH:
                        part_with_header = part
                else:
                    part_with_header = part
                
                await update.message.reply_text(
                    part_with_header,
                    parse_mode=parse_mode
                )
                break  # Успешно отправлено
                
            except RetryAfter as e:
                # Telegram просит подождать
                wait_time = e.retry_after
                logger.warning(f"Rate limit, ждем {wait_time} секунд...")
                await asyncio.sleep(wait_time)
                continue
                
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # Экспоненциальная задержка: 2, 4, 6 секунд
                    logger.warning(f"Ошибка сети при отправке сообщения (попытка {attempt + 1}/{max_retries}): {e}. Повтор через {wait_time} сек...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Не удалось отправить сообщение после {max_retries} попыток: {e}")
                    # Пытаемся отправить упрощенное сообщение об ошибке
                    try:
                        await update.message.reply_text(
                            "⚠️ Произошла ошибка при отправке результатов. "
                            "Попробуйте запросить расчет еще раз."
                        )
                    except:
                        pass  # Если и это не получилось, просто логируем
                    
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке сообщения: {e}", exc_info=True)
                if attempt == max_retries - 1:
                    try:
                        await update.message.reply_text(
                            "⚠️ Произошла ошибка при отправке сообщения."
                        )
                    except:
                        pass
                break
        
        # Небольшая задержка между частями, чтобы не перегружать API
        if part_num < len(parts):
            await asyncio.sleep(0.5)


# Приветственное сообщение
START_MESSAGE = (
    "Привет! Я бот для расчета потенциала партнерской программы.\n\n"
    "Я помогу вам:\n"
    "1️⃣ Собрать информацию о компании (отрасль, выручка, численность)\n"
    "2️⃣ Собрать параметры для расчета (средние чеки, Кприб, доля владения, тип продукта)\n"
    "3️⃣ Рассчитать потенциал по сегментам и каналам\n\n"
    "💡 **Совет:** Если хотите рассчитать по всему рынку без фильтров, "
    "используйте команду /no_filters или напишите 'весь рынок' / 'без фильтров'\n\n"
    "📖 Используйте /help для получения справки\n\n"
    "Начнем! Расскажите о вашей компании в свободной форме."
)


# Глобальный словарь для хранения агентов пользователей
user_agents = {}
calculation_params_agents = {}

# Агент для извлечения категории выручки
revenue_agent = None

# Агент для определения ОКВЭД кодов
okved_agent = None

# База данных
DB_NAME = 'data_storage.db'


def get_revenue_agent() -> RevenueExtractorAgent:
    """Получить или создать агента для извлечения выручки."""
    global revenue_agent
    if revenue_agent is None:
        revenue_agent = RevenueExtractorAgent()
        logger.info("Создан агент извлечения категории выручки")
    return revenue_agent


def get_okved_agent() -> OkvedAgent:
    """Получить или создать агента для определения ОКВЭД кодов."""
    global okved_agent
    if okved_agent is None:
        okved_agent = OkvedAgent()
        logger.info("Создан агент определения ОКВЭД кодов")
    return okved_agent


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


def collect_user_responses_from_agent(agent) -> str:
    """
    Собирает весь диалог из истории агента (вопросы бота + ответы пользователя).
    
    Args:
        agent: Экземпляр CompanyInfoAgent или CalculationParamsAgent
        
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


def collect_full_dialog(user_id: int) -> str:
    """
    Собирает полный диалог из обоих агентов (компания + параметры расчета).
    
    Args:
        user_id: ID пользователя
        
    Returns:
        str: Полный диалог
    """
    dialog_parts = []
    
    if user_id in user_agents:
        company_dialog = collect_user_responses_from_agent(user_agents[user_id])
        if company_dialog:
            dialog_parts.append("=== Информация о компании ===")
            dialog_parts.append(company_dialog)
    
    if user_id in calculation_params_agents:
        calc_dialog = collect_user_responses_from_agent(calculation_params_agents[user_id])
        if calc_dialog:
            dialog_parts.append("\n=== Параметры расчета ===")
            dialog_parts.append(calc_dialog)
    
    return "\n".join(dialog_parts)


def get_user_agent(user_id: int) -> CompanyInfoAgent:
    """Получить или создать агента для пользователя."""
    if user_id not in user_agents:
        user_agents[user_id] = CompanyInfoAgent()
        logger.info(f"Создан новый агент для пользователя {user_id}")
    return user_agents[user_id]


def get_calculation_params_agent(user_id: int) -> CalculationParamsAgent:
    """Получить или создать агента для сбора параметров расчета."""
    if user_id not in calculation_params_agents:
        calculation_params_agents[user_id] = CalculationParamsAgent()
        logger.info(f"Создан новый агент параметров расчета для пользователя {user_id}")
    return calculation_params_agents[user_id]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Сбрасываем агентов для пользователя (новый диалог)
    if user_id in user_agents:
        user_agents[user_id].reset_dialog()
        logger.info(f"Сброшен агент для пользователя {user_id}")
    if user_id in calculation_params_agents:
        calculation_params_agents[user_id].reset_dialog()
        logger.info(f"Сброшен агент параметров расчета для пользователя {user_id}")
    
    # Инициализируем состояние диалога
    context.user_data['dialog_started'] = False
    context.user_data['company_info_collected'] = False
    context.user_data['calculation_params_collected'] = False
    context.user_data['no_filters'] = False
    context.user_data['waiting_company_confirmation'] = False
    context.user_data['waiting_params_confirmation'] = False
    
    await update.message.reply_text(START_MESSAGE)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help - справка о боте"""
    help_text = (
        "🤖 **Я бот для расчета потенциала партнерской программы**\n\n"
        "**Что я умею:**\n"
        "1️⃣ Собираю информацию о компании (отрасль, выручка, численность)\n"
        "2️⃣ Автоматически определяю ОКВЭД коды по отрасли\n"
        "3️⃣ Собираю параметры для расчета (средние чеки, Кприб, доля владения, тип продукта)\n"
        "4️⃣ Фильтрую данные из базы по вашим критериям\n"
        "5️⃣ Рассчитываю потенциал по сегментам и каналам продаж\n"
        "6️⃣ Показываю детальные результаты с оценкой рынка\n\n"
        "**Доступные команды:**\n"
        "• /start - начать новый диалог\n"
        "• /reset - сбросить текущий диалог\n"
        "• /no_filters - расчет по всему рынку без фильтров\n"
        "• /help - эта справка\n\n"
        "**Как начать:**\n"
        "Просто напишите о вашей компании, например:\n"
        "\"IT компания, 50 человек, выручка 100 млн\"\n\n"
        "**Режим без фильтров:**\n"
        "Используйте команду /no_filters или напишите \"весь рынок\" / \"без фильтров\" "
        "для расчета по всем данным без ограничений.\n\n"
        "Готов помочь! Начните с описания вашей компании."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')


def check_about_bot_question(message: str) -> bool:
    """
    Проверка, спрашивает ли пользователь о боте.
    
    Args:
        message: Сообщение пользователя
        
    Returns:
        bool: True если пользователь спрашивает о боте
    """
    about_keywords = [
        'что ты',
        'кто ты',
        'расскажи о себе',
        'расскажи о боте',
        'что умеешь',
        'что можешь',
        'как работает',
        'помощь',
        'help',
        'справка',
        'команды',
        'функции',
        'возможности',
        'что делаешь',
        'для чего'
    ]
    
    message_lower = message.lower().strip()
    
    # Проверяем, начинается ли сообщение с вопроса о боте
    if any(message_lower.startswith(keyword) or keyword in message_lower for keyword in about_keywords):
        return True
    
    # Проверяем вопросы
    if message_lower.endswith('?') and any(keyword in message_lower for keyword in ['ты', 'бот', 'умеешь', 'можешь']):
        return True
    
    return False


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /reset - сброс диалога"""
    user_id = update.effective_user.id
    
    if user_id in user_agents:
        user_agents[user_id].reset_dialog()
        logger.info(f"Диалог сброшен для пользователя {user_id}")
    if user_id in calculation_params_agents:
        calculation_params_agents[user_id].reset_dialog()
        logger.info(f"Диалог параметров расчета сброшен для пользователя {user_id}")
    
    context.user_data['dialog_started'] = False
    context.user_data['company_info_collected'] = False
    context.user_data['calculation_params_collected'] = False
    context.user_data['no_filters'] = False
    
    await update.message.reply_text(
        "Диалог сброшен! Можете начать заново.\n\n"
        "Расскажите о вашей компании."
    )


async def no_filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /no_filters - расчет без фильтров (весь рынок)"""
    user_id = update.effective_user.id
    
    # Устанавливаем флаг "без фильтров"
    context.user_data['no_filters'] = True
    context.user_data['company_info_collected'] = True  # Пропускаем сбор информации о компании
    context.user_data['company_info'] = {}  # Пустая информация
    context.user_data['okved_codes'] = []  # Без ОКВЭД кодов
    
    await update.message.reply_text(
        "✅ Режим расчета без фильтров активирован!\n\n"
        "Расчет будет выполнен по всему рынку (без фильтрации по отрасли, выручке, штату, ТБ).\n\n"
        "Теперь мне нужны параметры для расчета потенциала:\n"
        "• Средний чек в сегменте ММБ (руб.)\n"
        "• Средний чек в других сегментах (руб.)\n"
        "• Кприб (%)\n"
        "• Доля владения (%)\n"
        "• Тип продукта (Коробка/Кастом)\n"
        "• Территориальный банк (опционально)\n\n"
        "Опишите эти параметры в свободной форме."
    )


def check_no_filters_request(message: str) -> bool:
    """
    Проверка, просит ли пользователь расчет без фильтров.
    
    Args:
        message: Сообщение пользователя
        
    Returns:
        bool: True если пользователь просит расчет без фильтров
    """
    no_filters_keywords = [
        'без фильтров',
        'весь рынок',
        'все данные',
        'вся база',
        'не фильтровать',
        'без ограничений',
        'полный рынок',
        'все отрасли',
        'любая отрасль'
    ]
    
    message_lower = message.lower()
    return any(keyword in message_lower for keyword in no_filters_keywords)


def build_filters_from_company_info(
    company_info: dict, 
    revenue_category: str = None,
    okved_codes: List[str] = None
) -> dict:
    """
    Построение фильтров для БД на основе собранной информации о компании.
    
    Args:
        company_info: Словарь с информацией о компании
        revenue_category: Категория выручки из справочника
        okved_codes: Список ОКВЭД кодов
        
    Returns:
        dict: Словарь фильтров для БД
    """
    filters = {
        "industries": [],
        "revenue": [],
        "staff": [],
        "tb": []
    }
    
    # ОКВЭД коды
    if okved_codes:
        filters["industries"] = okved_codes
    
    # Выручка
    if revenue_category:
        filters["revenue"] = [revenue_category]
    
    # Штат - нужно преобразовать текстовое описание в категорию
    staff_count = company_info.get('staff_count', '')
    if staff_count:
        staff_category = map_staff_to_category(staff_count)
        if staff_category:
            filters["staff"] = [staff_category]
    
    return filters


def format_company_info_summary(company_info: dict, okved_codes: List[str] = None, revenue_category: str = None) -> str:
    """
    Форматирование сводки информации о компании для подтверждения.
    
    Args:
        company_info: Словарь с информацией о компании
        okved_codes: Список ОКВЭД кодов
        revenue_category: Категория выручки
        
    Returns:
        str: Отформатированная сводка
    """
    output = []
    output.append("📋 **Собранная информация о компании:**\n")
    
    industry = company_info.get('industry', 'не указано')
    output.append(f"🏢 Отрасль: {industry}")
    
    if okved_codes:
        codes_text = ', '.join(okved_codes)
        output.append(f"📊 ОКВЭД коды: {codes_text}")
    else:
        output.append("📊 ОКВЭД коды: не определены")
    
    revenue = company_info.get('revenue', 'не указано')
    output.append(f"💰 Выручка: {revenue}")
    
    if revenue_category:
        output.append(f"📈 Категория выручки: {revenue_category}")
    
    staff_count = company_info.get('staff_count', 'не указано')
    output.append(f"👥 Численность: {staff_count}")
    
    return "\n".join(output)


def format_calculation_params_summary(calculation_params: dict) -> str:
    """
    Форматирование сводки параметров расчета для подтверждения.
    
    Args:
        calculation_params: Словарь с параметрами расчета
        
    Returns:
        str: Отформатированная сводка
    """
    output = []
    output.append("⚙️ **Собранные параметры расчета:**\n")
    
    output.append(f"💰 Средний чек ММБ: {calculation_params.get('avg_amount_mmb', 0):,.0f} руб.")
    output.append(f"💰 Средний чек другие сегменты: {calculation_params.get('avg_amount_other', 0):,.0f} руб.")
    output.append(f"📊 Кприб: {calculation_params.get('k', 0)}%")
    output.append(f"📈 Доля владения: {calculation_params.get('own_share', 0)}%")
    output.append(f"📦 Тип продукта: {calculation_params.get('product_type', 'не указано')}")
    
    if calculation_params.get('tb'):
        output.append(f"🏢 Территориальный банк: {calculation_params.get('tb')}")
    else:
        output.append("🏢 Территориальный банк: не указано (все регионы)")
    
    return "\n".join(output)


def check_confirmation(message: str) -> Optional[bool]:
    """
    Проверка, подтверждает ли пользователь или отклоняет.
    
    Args:
        message: Сообщение пользователя
        
    Returns:
        Optional[bool]: True если подтверждение, False если отклонение, None если неопределенно
    """
    message_lower = message.lower().strip()
    
    # Подтверждение
    confirm_keywords = ['да', 'yes', 'ок', 'ok', 'правильно', 'верно', 'все верно', 'все правильно', 'подтверждаю', 'согласен']
    if any(keyword in message_lower for keyword in confirm_keywords):
        return True
    
    # Отклонение
    reject_keywords = ['нет', 'no', 'не', 'неправильно', 'неверно', 'изменить', 'изменю', 'поменять', 'исправить']
    if any(keyword in message_lower for keyword in reject_keywords):
        return False
    
    return None


def map_staff_to_category(staff_text: str) -> str:
    """
    Преобразование текстового описания численности в категорию из справочника.
    
    Args:
        staff_text: Текстовое описание (например, "20 человек", "50-100")
        
    Returns:
        str: Категория из справочника или None
    """
    from reference_data import STAFF_CATEGORIES
    
    staff_text = staff_text.lower().strip()
    
    # Пытаемся извлечь число
    import re
    numbers = re.findall(r'\d+', staff_text)
    
    if not numbers:
        # Если нет чисел, пытаемся сопоставить по ключевым словам
        if any(word in staff_text for word in ['1', 'один', 'one']):
            return "1 чел."
        elif any(word in staff_text for word in ['2-5', '2 до 5', 'несколько']):
            return "2-5 чел."
        elif any(word in staff_text for word in ['6-30', '6 до 30', 'маленьк']):
            return "6-30 чел."
        elif any(word in staff_text for word in ['31-100', '31 до 100', 'средн']):
            return "31-100 чел."
        elif any(word in staff_text for word in ['более 100', 'больше 100', 'крупн']):
            return "Более 100 чел."
        return None
    
    # Если есть числа, определяем категорию
    max_num = max(int(n) for n in numbers)
    
    if max_num == 1:
        return "1 чел."
    elif 2 <= max_num <= 5:
        return "2-5 чел."
    elif 6 <= max_num <= 30:
        return "6-30 чел."
    elif 31 <= max_num <= 100:
        return "31-100 чел."
    else:
        return "Более 100 чел."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    logger.info(f"Получено сообщение от пользователя {user_id}: {user_message}")
    
    try:
        # Проверяем, не спрашивает ли пользователь о боте
        if check_about_bot_question(user_message):
            await help_command(update, context)
            return
        
        company_info_collected = context.user_data.get('company_info_collected', False)
        calculation_params_collected = context.user_data.get('calculation_params_collected', False)
        waiting_company_confirmation = context.user_data.get('waiting_company_confirmation', False)
        waiting_params_confirmation = context.user_data.get('waiting_params_confirmation', False)
        
        # Проверяем, не просит ли пользователь расчет без фильтров
        no_filters_requested = check_no_filters_request(user_message)
        if no_filters_requested and not company_info_collected:
            context.user_data['no_filters'] = True
            context.user_data['company_info_collected'] = True
            context.user_data['company_info'] = {}
            context.user_data['okved_codes'] = []
            
            await update.message.reply_text(
                "✅ Понял! Выполню расчет по всему рынку без фильтров.\n\n"
                "Теперь мне нужны параметры для расчета потенциала:\n"
                "• Средний чек в сегменте ММБ (руб.)\n"
                "• Средний чек в других сегментах (руб.)\n"
                "• Кприб (%)\n"
                "• Доля владения (%)\n"
                "• Тип продукта (Коробка/Кастом)\n"
                "• Территориальный банк (опционально)\n\n"
                "Опишите эти параметры в свободной форме."
            )
            return
        
        # Обработка подтверждения информации о компании (проверяем ПЕРЕД сбором информации)
        if waiting_company_confirmation:
            confirmation = check_confirmation(user_message)
            
            if confirmation is True:
                # Подтверждено - переходим к сбору параметров
                context.user_data['company_info_collected'] = True
                context.user_data['waiting_company_confirmation'] = False
                
                await update.message.reply_text(
                    "✅ Отлично! Информация подтверждена.\n\n"
                    "Теперь мне нужны параметры для расчета потенциала:\n"
                    "• Средний чек в сегменте ММБ (руб.)\n"
                    "• Средний чек в других сегментах (руб.)\n"
                    "• Кприб (%)\n"
                    "• Доля владения (%)\n"
                    "• Тип продукта (Коробка/Кастом)\n"
                    "• Территориальный банк (опционально)\n\n"
                    "Опишите эти параметры в свободной форме."
                )
                return
            elif confirmation is False:
                # Отклонено - возвращаемся к редактированию
                context.user_data['waiting_company_confirmation'] = False
                context.user_data['company_info'] = {}
                context.user_data['okved_codes'] = []
                context.user_data['dialog_started'] = False
                
                # Сбрасываем агента
                if user_id in user_agents:
                    user_agents[user_id].reset_dialog()
                
                await update.message.reply_text(
                    "Хорошо, давайте исправим информацию о компании.\n\n"
                    "Расскажите о вашей компании заново:\n"
                    "• Отрасль деятельности\n"
                    "• Примерная выручка\n"
                    "• Численность сотрудников"
                )
                return
            else:
                # Неопределенный ответ
                await update.message.reply_text(
                    "Пожалуйста, ответьте 'да' если все правильно, или 'нет' если хотите что-то изменить."
                )
                return
        
        # Этап 1: Сбор информации о компании
        if not company_info_collected:
            agent = get_user_agent(user_id)
            dialog_started = context.user_data.get('dialog_started', False)
            
            if not dialog_started:
                context.user_data['dialog_started'] = True
                complete, info, message = agent.collect_company_info(user_message)
            else:
                complete, info, message = agent.continue_dialog(user_message)
            
            await update.message.reply_text(message)
            
            # Если информация не собрана полностью, ждем следующего ответа пользователя
            if not complete:
                return
            
            if complete:
                logger.info(f"Информация о компании собрана для пользователя {user_id}: {info}")
                context.user_data['company_info'] = info
                context.user_data['dialog_started'] = False
                
                # Определяем ОКВЭД коды по отрасли (если не установлен флаг no_filters)
                if not context.user_data.get('no_filters', False):
                    industry = info.get('industry', '')
                    okved_codes = []
                    
                    if industry:
                        try:
                            await update.message.reply_text(
                                f"🔍 Определяю ОКВЭД коды для отрасли: {industry}..."
                            )
                            
                            okved_agent = get_okved_agent()
                            okved_codes = okved_agent.get_okved_codes(industry)
                            
                            logger.info(f"Результат поиска ОКВЭД для '{industry}': {len(okved_codes) if okved_codes else 0} кодов")
                            
                            if okved_codes:
                                context.user_data['okved_codes'] = okved_codes
                                codes_text = ', '.join(okved_codes)
                                await update.message.reply_text(
                                    f"✅ Найдены ОКВЭД коды: {codes_text}"
                                )
                            else:
                                # Сохраняем пустой список, чтобы не использовать старые значения
                                context.user_data['okved_codes'] = []
                                await update.message.reply_text(
                                    "⚠️ Не удалось определить ОКВЭД коды для данной отрасли. "
                                    "Расчет будет выполнен без фильтрации по отраслям."
                                )
                        except Exception as e:
                            logger.error(f"Ошибка при определении ОКВЭД кодов: {e}", exc_info=True)
                            # Сохраняем пустой список при ошибке
                            context.user_data['okved_codes'] = []
                            await update.message.reply_text(
                                "⚠️ Произошла ошибка при определении ОКВЭД кодов. "
                                "Продолжаю без фильтрации по отраслям."
                            )
                else:
                    context.user_data['okved_codes'] = []
                
                # Извлекаем категорию выручки для показа в сводке
                revenue_category = None
                try:
                    dialog = collect_user_responses_from_agent(agent)
                    if dialog:
                        rev_agent = get_revenue_agent()
                        revenue_category = rev_agent.extract_revenue_category(dialog)
                except Exception as e:
                    logger.error(f"Ошибка при извлечении категории выручки: {e}", exc_info=True)
                    # Продолжаем без категории выручки
                
                # Показываем сводку и просим подтверждение
                okved_codes = context.user_data.get('okved_codes', [])
                summary = format_company_info_summary(info, okved_codes, revenue_category)
                
                await update.message.reply_text(
                    summary + "\n\n"
                    "❓ **Все правильно?** (да/нет)\n"
                    "Если хотите что-то изменить, напишите 'нет' или 'изменить'."
                )
                
                context.user_data['waiting_company_confirmation'] = True
                return
        
        # Обработка подтверждения параметров расчета (проверяем ПЕРЕД сбором параметров)
        if waiting_params_confirmation:
            confirmation = check_confirmation(user_message)
            
            if confirmation is True:
                # Подтверждено - запускаем расчет
                context.user_data['calculation_params_collected'] = True
                context.user_data['waiting_params_confirmation'] = False
                
                await update.message.reply_text("⏳ Выполняю расчет потенциала...")
                
                try:
                    # Получаем сохраненные данные
                    company_info = context.user_data.get('company_info', {})
                    calculation_params = context.user_data.get('calculation_params', {})
                    okved_codes = context.user_data.get('okved_codes', [])
                    no_filters = context.user_data.get('no_filters', False)
                    
                    # Строим фильтры
                    if no_filters:
                        # Режим без фильтров - пустые фильтры (весь рынок)
                        filters = {
                            "industries": [],
                            "revenue": [],
                            "staff": [],
                            "tb": []
                        }
                        # Только ТБ можно указать, если пользователь хочет
                        if calculation_params.get('tb'):
                            filters['tb'] = [calculation_params['tb']]
                    else:
                        # Обычный режим - строим фильтры из собранной информации
                        # Извлекаем категорию выручки из полного диалога
                        full_dialog = collect_full_dialog(user_id)
                        rev_agent = get_revenue_agent()
                        revenue_category = rev_agent.extract_revenue_category(full_dialog) if full_dialog else None
                        
                        # Строим фильтры (включая ОКВЭД коды)
                        filters = build_filters_from_company_info(
                            company_info, 
                            revenue_category,
                            okved_codes
                        )
                        
                        # Добавляем ТБ из параметров расчета, если указан
                        if calculation_params.get('tb'):
                            filters['tb'] = [calculation_params['tb']]
                    
                    # Запускаем расчет
                    results = calculate_potential_full_pipeline(
                        db_name=DB_NAME,
                        filters=filters,
                        avg_amount_mmb=calculation_params.get('avg_amount_mmb', 0),
                        avg_amount_other=calculation_params.get('avg_amount_other', 0),
                        k=calculation_params.get('k', 0),
                        own_share=calculation_params.get('own_share', 0),
                        product_type=calculation_params.get('product_type', 'Коробка'),
                    )
                    
                    # Форматируем и выводим результаты
                    results_text = format_calculation_results(results)
                    filters_summary = format_filters_summary(filters, calculation_params, no_filters)
                    
                    # Используем безопасную отправку с обработкой ошибок
                    await safe_send_message(update, filters_summary, parse_mode='Markdown')
                    await safe_send_message(update, results_text, parse_mode='Markdown')
                    
                    # Сохраняем в БД
                    if no_filters:
                        full_dialog = "Режим расчета без фильтров (весь рынок)"
                        revenue_category_for_save = None
                    else:
                        full_dialog = collect_full_dialog(user_id)
                        revenue_category_for_save = revenue_category
                    
                    save_chat_session(user_id, full_dialog, company_info, revenue_category_for_save)
                    
                    await update.message.reply_text(
                        "\n✅ Расчет завершен!\n\n"
                        "Чтобы начать новый расчет, используйте /reset или /start"
                    )
                    
                except Exception as e:
                    logger.error(f"Ошибка при расчете: {e}", exc_info=True)
                    await update.message.reply_text(
                        f"❌ Произошла ошибка при расчете: {str(e)}\n\n"
                        "Попробуйте еще раз или используйте /reset для сброса."
                    )
            elif confirmation is False:
                # Отклонено - возвращаемся к редактированию
                context.user_data['waiting_params_confirmation'] = False
                context.user_data['calculation_params'] = {}
                context.user_data['calc_dialog_started'] = False
                
                # Сбрасываем агента параметров
                if user_id in calculation_params_agents:
                    calculation_params_agents[user_id].reset_dialog()
                
                await update.message.reply_text(
                    "Хорошо, давайте исправим параметры расчета.\n\n"
                    "Опишите параметры заново:\n"
                    "• Средний чек в сегменте ММБ (руб.)\n"
                    "• Средний чек в других сегментах (руб.)\n"
                    "• Кприб (%)\n"
                    "• Доля владения (%)\n"
                    "• Тип продукта (Коробка/Кастом)\n"
                    "• Территориальный банк (опционально)"
                )
            else:
                # Неопределенный ответ
                await update.message.reply_text(
                    "Пожалуйста, ответьте 'да' если все правильно, или 'нет' если хотите что-то изменить."
                )
            return
        
        # Этап 2: Сбор параметров расчета
        elif not calculation_params_collected:
            calc_agent = get_calculation_params_agent(user_id)
            dialog_started = context.user_data.get('calc_dialog_started', False)
            
            if not dialog_started:
                context.user_data['calc_dialog_started'] = True
                complete, params, message = calc_agent.collect_calculation_params(user_message)
            else:
                complete, params, message = calc_agent.continue_dialog(user_message)
            
            await update.message.reply_text(message)
            
            # Если параметры не собраны полностью, ждем следующего ответа пользователя
            if not complete:
                return
            
            if complete:
                logger.info(f"Параметры расчета собраны для пользователя {user_id}: {params}")
                context.user_data['calculation_params'] = params
                context.user_data['calc_dialog_started'] = False
                
                # Показываем сводку и просим подтверждение
                summary = format_calculation_params_summary(params)
                
                await update.message.reply_text(
                    summary + "\n\n"
                    "❓ **Все правильно?** (да/нет)\n"
                    "Если хотите что-то изменить, напишите 'нет' или 'изменить'."
                )
                
                context.user_data['waiting_params_confirmation'] = True
                return
    
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего сообщения. "
            "Попробуйте еще раз или используйте /reset для сброса диалога."
        )


async def post_init(application: Application) -> None:
    """Пост-инициализация приложения"""
    await application.bot.initialize()


def main():
    """Запуск бота"""
    logger.info("Запуск телеграм бота...")
    
    # Создаём приложение
    application = Application.builder().token(TOKEN).post_init(post_init).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("no_filters", no_filters_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    logger.info("Бот запущен и готов к работе...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()