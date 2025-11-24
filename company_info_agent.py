# company_info_agent.py
"""
Агент для сбора полной информации о компании через GigaChat.
Проверяет наличие: отрасли, средней выручки и численности компании.
"""

import os
import uuid
import json
import logging
import requests
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompanyInfoAgent:
    """
    Агент для сбора информации о компании через GigaChat.
    
    Проверяет полноту ответа по трем критериям:
    - Понимание отрасли
    - Понимание средней выручки
    - Численность компании
    
    Если информации не хватает - задает уточняющие вопросы.
    """
    
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
        
        # История диалога для контекста
        self.dialog_history: List[Dict[str, str]] = []
        
        # Максимальное количество попыток уточнения
        self.max_clarification_attempts = 3
        
        logger.info("CompanyInfoAgent инициализирован")
    
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
    
    def _call_gigachat(self, messages: List[Dict[str, str]], 
                       temperature: float = 0.7, 
                       max_tokens: int = 2000) -> str:
        """
        Вызов GigaChat API.
        
        Args:
            messages: История сообщений в формате [{"role": "user", "content": "..."}]
            temperature: Температура генерации (0.0-1.0)
            max_tokens: Максимальное количество токенов в ответе
            
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
        
        try:
            response = requests.post(
                self.api_url, 
                headers=headers, 
                json=payload, 
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
    
    def _create_analysis_prompt(self) -> str:
        """
        Создание промпта для анализа полноты информации о компании.
        
        Returns:
            str: Промпт для GigaChat
        """
        return """Ты - аналитик, который собирает базовую информацию о компании.

Проанализируй ответ пользователя и определи, есть ли хотя бы общее понимание по трем параметрам:

1. **Отрасль** - чем занимается компания (IT, торговля, производство и т.д.)
2. **Выручка** - примерный размер компании по обороту (можно приблизительно: малый/средний/крупный бизнес, или в цифрах)
3. **Численность** - сколько примерно людей (можно диапазон: 1-10, 10-50, 50-100, более 100 и т.д.)

ПРАВИЛА:
- Принимай даже приблизительную информацию
- Если есть информация обо всех трёх параметрах в любом виде - complete = true
- Если чего-то явно не хватает - complete = false и задай короткий вопрос

Ответь СТРОГО в одном из двух форматов JSON:

ВАРИАНТ 1 - ВСЯ ИНФОРМАЦИЯ ЕСТЬ (complete = true):
{
  "complete": true,
  "found_info": {
    "industry": "отрасль",
    "revenue": "выручка/масштаб",
    "staff_count": "численность"
  }
}

ВАРИАНТ 2 - ЧЕГО-ТО НЕ ХВАТАЕТ (complete = false):
{
  "complete": false,
  "clarification_question": "Короткий вопрос для уточнения недостающей информации"
}

Примеры:

Пользователь: "Небольшая IT компания, человек 20, выручка миллионов 50"
→ {"complete": true, "found_info": {"industry": "IT", "revenue": "50 млн", "staff_count": "20 человек"}}

Пользователь: "Торгуем продуктами"
→ {"complete": false, "clarification_question": "Какая примерно выручка и сколько сотрудников?"}

Пользователь: "Производство, крупная компания"
→ {"complete": false, "clarification_question": "Сколько примерно сотрудников и какая выручка?"}

Анализируй последний ответ пользователя в контексте всего диалога."""
    
    def _parse_analysis_result(self, response: str) -> Optional[Dict]:
        """
        Парсинг JSON-ответа от GigaChat.
        
        Args:
            response: Ответ от GigaChat
            
        Returns:
            Dict или None в случае ошибки парсинга
        """
        try:
            # Пытаемся найти JSON в ответе
            start_idx = response.find('{')
            end_idx = response.rfind('}')
            
            if start_idx == -1 or end_idx == -1:
                logger.error("JSON не найден в ответе")
                return None
            
            json_str = response[start_idx:end_idx + 1]
            result = json.loads(json_str)
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            logger.error(f"Ответ: {response}")
            return None
    
    def _build_messages_with_history(self, user_message: str) -> List[Dict[str, str]]:
        """
        Формирование списка сообщений с учетом истории диалога.
        
        Args:
            user_message: Новое сообщение пользователя
            
        Returns:
            List[Dict]: Список сообщений для API
        """
        messages = [
            {"role": "system", "content": self._create_analysis_prompt()}
        ]
        
        # Добавляем историю диалога
        for msg in self.dialog_history:
            messages.append(msg)
        
        # Добавляем новое сообщение
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def collect_company_info(self, initial_message: str) -> Tuple[bool, Dict, str]:
        """
        Основной метод для сбора информации о компании.
        
        Запускает цикл уточняющих вопросов, пока не будет собрана вся информация
        или не достигнут лимит попыток.
        
        Args:
            initial_message: Первое сообщение пользователя
            
        Returns:
            Tuple[bool, Dict, str]: 
                - Флаг успешности (True если вся информация собрана)
                - Словарь с собранной информацией
                - Финальное сообщение (вопрос или подтверждение)
        """
        logger.info(f"Начало сбора информации. Исходное сообщение: {initial_message}")
        
        # Очищаем историю
        self.dialog_history = []
        
        current_message = initial_message
        attempts = 0
        
        while attempts < self.max_clarification_attempts:
            attempts += 1
            logger.info(f"Попытка {attempts}/{self.max_clarification_attempts}")
            
            # Формируем сообщения с историей
            messages = self._build_messages_with_history(current_message)
            
            # Добавляем сообщение в историю
            self.dialog_history.append({"role": "user", "content": current_message})
            
            # Получаем ответ от GigaChat
            response = self._call_gigachat(messages)
            
            # Добавляем ответ в историю
            self.dialog_history.append({"role": "assistant", "content": response})
            
            # Парсим результат
            analysis = self._parse_analysis_result(response)
            
            if not analysis:
                error_msg = "Извините, произошла ошибка при анализе вашего ответа. Попробуйте еще раз."
                return False, {}, error_msg
            
            # Проверяем полноту информации
            if analysis.get('complete', False):
                logger.info("Вся информация собрана успешно")
                
                success_msg = self._format_success_message(analysis['found_info'])
                return True, analysis['found_info'], success_msg
            
            # Информация неполная - задаем уточняющий вопрос
            clarification_question = analysis.get('clarification_question', '')
            
            if not clarification_question:
                clarification_question = "Пожалуйста, предоставьте недостающую информацию."
            
            logger.info(f"Информация неполная. Недостающие поля: {analysis.get('missing_fields')}")
            
            # Возвращаем вопрос для уточнения
            # В реальном использовании здесь должен быть ввод от пользователя
            return False, analysis.get('found_info', {}), clarification_question
        
        # Достигнут лимит попыток
        logger.warning(f"Достигнут лимит попыток ({self.max_clarification_attempts})")
        return False, {}, "К сожалению, не удалось собрать всю необходимую информацию."
    
    def continue_dialog(self, user_response: str) -> Tuple[bool, Dict, str]:
        """
        Продолжение диалога с новым ответом пользователя.
        
        Args:
            user_response: Ответ пользователя на уточняющий вопрос
            
        Returns:
            Tuple[bool, Dict, str]: 
                - Флаг успешности
                - Словарь с информацией
                - Сообщение (вопрос или подтверждение)
        """
        logger.info(f"Продолжение диалога с ответом: {user_response}")
        
        # Формируем сообщения с полной историей
        messages = self._build_messages_with_history(user_response)
        
        # Добавляем в историю
        self.dialog_history.append({"role": "user", "content": user_response})
        
        # Получаем ответ
        response = self._call_gigachat(messages)
        self.dialog_history.append({"role": "assistant", "content": response})
        
        # Парсим
        analysis = self._parse_analysis_result(response)
        
        if not analysis:
            return False, {}, "Извините, произошла ошибка при анализе."
        
        # Проверяем полноту
        if analysis.get('complete', False):
            logger.info("Вся информация собрана")
            success_msg = self._format_success_message(analysis['found_info'])
            return True, analysis['found_info'], success_msg
        
        # Еще не вся информация
        clarification_question = analysis.get('clarification_question', 
                                              "Пожалуйста, уточните недостающую информацию.")
        
        return False, analysis.get('found_info', {}), clarification_question
    
    def _format_success_message(self, info: Dict) -> str:
        """
        Форматирование успешного сообщения с собранной информацией.
        
        Args:
            info: Словарь с информацией о компании
            
        Returns:
            str: Отформатированное сообщение
        """
        msg = "✅ Отлично! Я получил всю необходимую информацию:\n\n"
        msg += f"🏢 Отрасль: {info.get('industry', 'Не указано')}\n"
        msg += f"💰 Выручка: {info.get('revenue', 'Не указано')}\n"
        msg += f"👥 Численность: {info.get('staff_count', 'Не указано')}\n"
        msg += "\nСпасибо за предоставленную информацию!"
        
        return msg
    
    def reset_dialog(self):
        """Сброс истории диалога."""
        self.dialog_history = []
        logger.info("История диалога очищена")


# === Пример использования ===

def example_usage():
    """Пример использования агента в интерактивном режиме."""
    
    # Создаем агента
    agent = CompanyInfoAgent()
    
    print("=" * 60)
    print("АГЕНТ СБОРА ИНФОРМАЦИИ О КОМПАНИИ")
    print("=" * 60)
    print("\nОпишите вашу компанию (отрасль, выручку, численность):")
    print("Для выхода введите 'выход'\n")
    
    # Получаем первое сообщение
    initial_input = input("Вы: ").strip()
    
    if initial_input.lower() in ['выход', 'exit', 'quit']:
        return
    
    # Первый анализ
    complete, info, message = agent.collect_company_info(initial_input)
    
    print(f"\nАгент: {message}\n")
    
    # Цикл уточняющих вопросов
    while not complete:
        user_input = input("Вы: ").strip()
        
        if user_input.lower() in ['выход', 'exit', 'quit']:
            break
        
        complete, info, message = agent.continue_dialog(user_input)
        print(f"\nАгент: {message}\n")
    
    if complete:
        print("\n" + "=" * 60)
        print("ИНФОРМАЦИЯ СОБРАНА УСПЕШНО!")
        print("=" * 60)
        print(f"\nСобранные данные:")
        print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    # Отключаем предупреждения о SSL
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    example_usage()

