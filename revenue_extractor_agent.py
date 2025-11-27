# revenue_extractor_agent.py
"""
Агент для извлечения категории выручки из диалога с пользователем.
Использует GigaChat API для анализа текста и определения категории выручки.
"""

import os
import uuid
import json
import logging
import requests
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RevenueExtractorAgent:
    """
    Агент для извлечения категории выручки из диалога.
    
    Анализирует полный диалог и определяет категорию выручки компании
    согласно справочнику категорий.
    
    Использует жесткий словарь с уникальными кодами (888XXX) для надежного 
    извлечения категорий. Это защищает от ошибок LLM при формулировках - 
    модель возвращает только код, который затем извлекается регулярным выражением.
    
    Коды категорий:
        888001 → "Менее 1 млн.р."
        888002 → "1-10 млн.р."
        888003 → "10-120 млн.р."
        888004 → "120-800 млн.р."
        888005 → "Более 800 млн.р."
    """
    
    # Жесткий словарик: индекс -> категория выручки
    # Используются уникальные коды для защиты от ошибок LLM
    REVENUE_CATEGORIES = {
        '888001': 'Менее 1 млн.р.',
        '888002': '1-10 млн.р.',
        '888003': '10-120 млн.р.',
        '888004': '120-800 млн.р.',
        '888005': 'Более 800 млн.р.'
    }
    
    def __init__(self):
        """Инициализация агента с параметрами из окружения."""
        # Получаем credentials из environment
        self.auth_token = os.getenv('GIGACHAT_AUTH')
        self.token_url = os.getenv('GIGACHAT_TOKEN_URL')
        self.api_url = os.getenv('GIGACHAT_API_URL')
        self.scope = os.getenv('GIGACHAT_SCOPE')
        self.model = os.getenv('GIGACHAT_MODEL')
        
        # Проверяем наличие всех обязательных переменных
        if not self.auth_token:
            raise ValueError("GIGACHAT_AUTH не найден в переменных окружения!")
        if not self.token_url:
            raise ValueError("GIGACHAT_TOKEN_URL не найден в переменных окружения!")
        if not self.api_url:
            raise ValueError("GIGACHAT_API_URL не найден в переменных окружения!")
        if not self.scope:
            raise ValueError("GIGACHAT_SCOPE не найден в переменных окружения!")
        if not self.model:
            raise ValueError("GIGACHAT_MODEL не найден в переменных окружения!")
        
        logger.info("RevenueExtractorAgent инициализирован")
    
    @classmethod
    def get_all_categories(cls) -> dict:
        """
        Получить все категории выручки.
        
        Returns:
            dict: Словарь {код: категория}
        """
        return cls.REVENUE_CATEGORIES.copy()
    
    @classmethod
    def get_category_by_code(cls, code: str) -> Optional[str]:
        """
        Получить категорию по коду.
        
        Args:
            code: Код категории (например, "888003")
            
        Returns:
            Optional[str]: Название категории или None
        """
        return cls.REVENUE_CATEGORIES.get(code)
    
    def _get_access_token(self) -> str:
        """
        Получение access token от GigaChat.
        
        Returns:
            str: Access token
        """
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {self.auth_token}'
        }
        
        data = f'scope={self.scope}'
        
        try:
            response = requests.post(
                self.token_url, 
                headers=headers, 
                data=data, 
                verify=False
            )
            response.raise_for_status()
            
            token_json = response.json()
            if 'access_token' not in token_json:
                raise Exception(f"Ошибка получения токена: {token_json}")
            
            logger.info("Access token успешно получен")
            return token_json['access_token']
            
        except Exception as e:
            logger.error(f"Ошибка при получении токена: {e}")
            raise
    
    def _call_gigachat(self, messages: list, 
                       temperature: float = 0.3, 
                       max_tokens: int = 500) -> str:
        """
        Вызов GigaChat API.
        
        Args:
            messages: История сообщений
            temperature: Температура генерации (низкая для точности)
            max_tokens: Максимальное количество токенов
            
        Returns:
            str: Ответ от GigaChat
        """
        token = self._get_access_token()
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {token}'
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        # Отключаем предупреждения SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # Создаем адаптер с расширенными настройками SSL
        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context
        
        class SSLAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                context = create_urllib3_context()
                context.check_hostname = False
                context.verify_mode = 0  # ssl.CERT_NONE
                kwargs['ssl_context'] = context
                return super().init_poolmanager(*args, **kwargs)
        
        session = requests.Session()
        session.mount('https://', SSLAdapter())
        
        try:
            response = session.post(
                self.api_url, 
                headers=headers, 
                json=payload, 
                timeout=30,
                verify=False
            )
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            logger.info(f"Получен ответ от GigaChat: {content[:100]}...")
            return content
            
        except Exception as e:
            logger.error(f"Ошибка при вызове GigaChat API: {e}")
            raise
    
    def _create_extraction_prompt(self, dialog: str) -> str:
        """
        Создание промпта для извлечения категории выручки.
        
        Args:
            dialog: Полный диалог пользователя с ботом
            
        Returns:
            str: Промпт для GigaChat
        """
        return f"""Ты - аналитик, который извлекает информацию о выручке компании из диалога.

Твоя задача: найти упоминания о выручке, обороте или доходе компании и сопоставить их с категориями из справочника.

Справочник категорий выручки (код → категория):
- 888001 → "Менее 1 млн.р."
- 888002 → "1-10 млн.р."
- 888003 → "10-120 млн.р."
- 888004 → "120-800 млн.р."
- 888005 → "Более 800 млн.р."

Правила сопоставления:
- "выручка 5 млн" → 888002 (1-10 млн.р.)
- "выручка 50 млн" → 888003 (10-120 млн.р.)
- "выручка 150 млн" → 888004 (120-800 млн.р.)
- "оборот 500 млн" → 888004 (120-800 млн.р.)
- "доход менее 1 млн" → 888001 (Менее 1 млн.р.)
- "более 1 млрд" или "1000 млн" → 888005 (Более 800 млн.р.)
- "небольшая компания" без конкретной суммы → null
- если выручка в диапазоне (например "100-500 млн"), выбери категорию по верхней границе

Диалог:
{dialog}

ВАЖНО: В ответе укажи ТОЛЬКО КОД категории (888001-888005) или null.

Ответь СТРОГО в формате:
{{
  "revenue_code": "888XXX или null"
}}

Примеры ответов:

Диалог: "Пользователь: У нас выручка 100 млн в год"
→ {{"revenue_code": "888003"}}

Диалог: "Пользователь: Оборот около 500 млн"
→ {{"revenue_code": "888004"}}

Диалог: "Пользователь: Небольшая компания"
→ {{"revenue_code": null}}

Диалог: "Пользователь: Выручка больше миллиарда"
→ {{"revenue_code": "888005"}}

Диалог: "Пользователь: Выручка 5 млн"
→ {{"revenue_code": "888002"}}

Анализируй ВЕСЬ диалог и ищи любые упоминания цифр, связанных с выручкой, оборотом или доходом.
В ответе используй ТОЛЬКО коды из справочника (888001, 888002, 888003, 888004, 888005)."""
    
    def extract_revenue_category(self, dialog: str) -> Optional[str]:
        """
        Извлечение категории выручки из диалога.
        
        Args:
            dialog: Полный текст диалога (вопросы бота + ответы пользователя)
            
        Returns:
            Optional[str]: Категория выручки или None, если не удалось определить
        """
        logger.info(f"Начало извлечения категории выручки из диалога")
        
        try:
            # Формируем промпт
            prompt = self._create_extraction_prompt(dialog)
            
            # Вызываем GigaChat
            messages = [
                {"role": "user", "content": prompt}
            ]
            
            response = self._call_gigachat(messages, temperature=0.3)
            
            # Парсим JSON-ответ
            revenue_category = self._parse_response(response)
            
            logger.info(f"Извлеченная категория выручки: {revenue_category}")
            return revenue_category
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении категории выручки: {e}", exc_info=True)
            return None
    
    def _parse_response(self, response: str) -> Optional[str]:
        """
        Парсинг ответа от GigaChat с использованием регулярных выражений.
        Ищет код категории (888XXX) и возвращает соответствующую категорию.
        
        Args:
            response: Ответ от GigaChat
            
        Returns:
            Optional[str]: Категория выручки или None
        """
        import re
        
        try:
            # Сначала пробуем найти код через регулярку во всем ответе
            # Ищем паттерн 888001-888005
            code_pattern = r'888(00[1-5])'
            match = re.search(code_pattern, response)
            
            if match:
                revenue_code = match.group(0)  # Полный код, например "888003"
                logger.info(f"Найден код выручки через регулярку: {revenue_code}")
                
                # Получаем категорию из словаря
                if revenue_code in self.REVENUE_CATEGORIES:
                    category = self.REVENUE_CATEGORIES[revenue_code]
                    logger.info(f"Код {revenue_code} -> категория '{category}'")
                    return category
                else:
                    logger.warning(f"Код {revenue_code} не найден в словаре")
                    return None
            
            # Если регулярка не нашла, пробуем через JSON (fallback)
            logger.info("Код не найден регуляркой, пробуем через JSON")
            
            start_idx = response.find('{')
            end_idx = response.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = response[start_idx:end_idx + 1]
                data = json.loads(json_str)
                
                revenue_code = data.get('revenue_code')
                
                if revenue_code and revenue_code != "null":
                    # Убираем возможные кавычки и пробелы
                    revenue_code = str(revenue_code).strip().strip('"').strip("'")
                    
                    if revenue_code in self.REVENUE_CATEGORIES:
                        category = self.REVENUE_CATEGORIES[revenue_code]
                        logger.info(f"Из JSON: код {revenue_code} -> категория '{category}'")
                        return category
                    else:
                        logger.warning(f"Код из JSON '{revenue_code}' не найден в словаре")
                        return None
            
            # Ничего не нашли
            logger.warning("Ни регулярка, ни JSON не дали результата")
            return None
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            logger.error(f"Ответ: {response}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при парсинге: {e}")
            return None


# === Пример использования ===

def example_usage():
    """Пример использования агента."""
    
    # Создаем агента
    agent = RevenueExtractorAgent()
    
    print("\n" + "=" * 80)
    print("СПРАВОЧНИК КАТЕГОРИЙ ВЫРУЧКИ")
    print("=" * 80)
    for code, category in agent.REVENUE_CATEGORIES.items():
        print(f"  {code} → {category}")
    print("=" * 80)
    
    # Тестовые диалоги
    test_dialogs = [
        ("Около 100 млн в год", "Пользователь: Мы IT компания\nБот: Какая примерно выручка?\nПользователь: Около 100 млн в год"),
        ("Больше миллиарда", "Пользователь: Торговая компания, 50 сотрудников\nБот: Какая выручка?\nПользователь: Больше миллиарда"),
        ("Нет информации о выручке", "Пользователь: Небольшая производственная компания\nБот: Сколько сотрудников?\nПользователь: Человек 20"),
        ("5 млн рублей в год", "Пользователь: Оборот примерно 5 млн рублей в год, 10 человек в штате"),
        ("Менее миллиона", "Пользователь: У нас стартап\nБот: Какая выручка?\nПользователь: Менее миллиона пока"),
        ("500 млн", "Пользователь: Средняя компания\nБот: Выручка?\nПользователь: Около 500 миллионов")
    ]
    
    print("\n" + "=" * 80)
    print("ТЕСТИРОВАНИЕ АГЕНТА ИЗВЛЕЧЕНИЯ КАТЕГОРИИ ВЫРУЧКИ")
    print("=" * 80)
    
    for i, (desc, dialog) in enumerate(test_dialogs, 1):
        print(f"\n--- Тест {i}: {desc} ---")
        print(f"Диалог:\n{dialog}\n")
        
        category = agent.extract_revenue_category(dialog)
        
        if category:
            # Находим код категории
            code = None
            for c, cat in agent.REVENUE_CATEGORIES.items():
                if cat == category:
                    code = c
                    break
            print(f"✓ Категория выручки: {category} (код: {code})")
        else:
            print("✗ Категория выручки не определена")
        
        print("-" * 80)


if __name__ == "__main__":
    # Отключаем предупреждения о SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    example_usage()

