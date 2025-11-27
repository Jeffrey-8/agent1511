# calculation_params_agent.py
"""
Агент для сбора параметров расчета потенциала.
Собирает: avg_amount_mmb, avg_amount_other, k, own_share, product_type, tb (опционально)
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


class CalculationParamsAgent:
    """
    Агент для сбора параметров расчета потенциала.
    
    Собирает:
    - avg_amount_mmb: средний чек в ММБ, руб.
    - avg_amount_other: средний чек в других сегментах, руб.
    - k: Кприб, % (0-100)
    - own_share: доля владения, % (0-100)
    - product_type: тип продукта (Коробка/Кастом)
    - tb: территориальный банк (опционально)
    """
    
    def __init__(self):
        """Инициализация агента с параметрами из окружения."""
        self.auth_token = os.getenv('GIGACHAT_AUTH')
        self.token_url = os.getenv('GIGACHAT_TOKEN_URL')
        self.api_url = os.getenv('GIGACHAT_API_URL')
        self.scope = os.getenv('GIGACHAT_SCOPE')
        self.model = os.getenv('GIGACHAT_MODEL')
        
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
        
        self.dialog_history: List[Dict[str, str]] = []
        self.max_clarification_attempts = 5
        
        logger.info("CalculationParamsAgent инициализирован")
    
    def _get_access_token(self) -> str:
        """Получение access token от GigaChat."""
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
        """Вызов GigaChat API."""
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
            
            logger.info(f"Получен ответ от GigaChat (длина: {len(content)}): {content[:200]}...")
            return content
            
        except Exception as e:
            logger.error(f"Ошибка при вызове GigaChat API: {e}")
            raise
    
    def _create_analysis_prompt(self) -> str:
        """Создание промпта для анализа параметров расчета."""
        return """Ты - аналитик, который собирает параметры для расчета потенциала партнерской программы.

Тебе нужно собрать следующие параметры:

1. **avg_amount_mmb** - средний чек в сегменте ММБ, в рублях (число)
2. **avg_amount_other** - средний чек в других сегментах, в рублях (число)
3. **k** - Кприб, процент (от 0 до 100)
4. **own_share** - доля владения, процент (от 0 до 100)
5. **product_type** - тип продукта: "Коробка" или "Кастом"
6. **tb** - территориальный банк (опционально, можно пропустить): ЦА, ББ, ВВБ, ДВБ, МБ, ПБ, СЗБ, СибБ, СРБ, УБ, ЦЧБ, ЮЗБ

ПРАВИЛА:
- Если параметр не указан - complete = false и задай вопрос
- Для avg_amount_mmb и avg_amount_other принимай числа (можно в млн, переведи в рубли)
- Для k и own_share принимай проценты (0-100)
- product_type должен быть строго "Коробка" или "Кастом"
- tb можно пропустить (если не указан - не спрашивай)

Ответь СТРОГО в одном из двух форматов JSON:

ВАРИАНТ 1 - ВСЯ ИНФОРМАЦИЯ ЕСТЬ (complete = true):
{
  "complete": true,
  "found_info": {
    "avg_amount_mmb": число в рублях,
    "avg_amount_other": число в рублях,
    "k": число от 0 до 100,
    "own_share": число от 0 до 100,
    "product_type": "Коробка" или "Кастом",
    "tb": "ЦА" или null (опционально)
  }
}

ВАРИАНТ 2 - ЧЕГО-ТО НЕ ХВАТАЕТ (complete = false):
{
  "complete": false,
  "clarification_question": "Короткий вопрос для уточнения недостающей информации",
  "missing_fields": ["список", "недостающих", "полей"]
}

Примеры:

Пользователь: "Средний чек ММБ 50000, в других сегментах 30000, кприб 10%, доля владения 50%, продукт коробка"
→ {"complete": true, "found_info": {"avg_amount_mmb": 50000, "avg_amount_other": 30000, "k": 10, "own_share": 50, "product_type": "Коробка", "tb": null}}

Пользователь: "Чек 50 тысяч"
→ {"complete": false, "clarification_question": "Уточните: средний чек в ММБ и в других сегментах отдельно, Кприб (%), долю владения (%), тип продукта (Коробка/Кастом)", "missing_fields": ["avg_amount_other", "k", "own_share", "product_type"]}

Анализируй последний ответ пользователя в контексте всего диалога."""
    
    def _parse_analysis_result(self, response: str) -> Optional[Dict]:
        """Парсинг JSON-ответа от GigaChat с улучшенной обработкой ошибок."""
        if not response or not response.strip():
            logger.error("Пустой ответ от GigaChat")
            return None
        
        try:
            start_idx = response.find('{')
            end_idx = response.rfind('}')
            
            if start_idx == -1 or end_idx == -1:
                logger.warning(f"JSON не найден в ответе. Полный ответ: {response}")
                # Пытаемся найти JSON в обратном порядке
                last_open = response.rfind('{')
                if last_open != -1:
                    potential_json = response[last_open:]
                    try:
                        result = json.loads(potential_json)
                        logger.info("Найден JSON в конце ответа")
                        return result
                    except Exception as e:
                        logger.warning(f"Не удалось распарсить потенциальный JSON: {e}")
                        pass
                logger.error(f"Не удалось найти валидный JSON в ответе. Ответ: {response}")
                return None
            
            json_str = response[start_idx:end_idx + 1]
            result = json.loads(json_str)
            
            # Проверяем структуру
            if not isinstance(result, dict):
                logger.error(f"Результат не является словарем: {type(result)}")
                return None
            
            return result
            
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {e}")
            logger.error(f"Ответ (первые 500 символов): {response[:500]}")
            
            # Пытаемся исправить частые ошибки
            try:
                cleaned = response.strip()
                start_idx = cleaned.find('{')
                end_idx = cleaned.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = cleaned[start_idx:end_idx + 1]
                    result = json.loads(json_str)
                    logger.info("JSON успешно распарсен после очистки")
                    return result
            except:
                pass
            
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при парсинге: {e}", exc_info=True)
            return None
    
    def _build_messages_with_history(self, user_message: str) -> List[Dict[str, str]]:
        """Формирование списка сообщений с учетом истории диалога."""
        messages = [
            {"role": "system", "content": self._create_analysis_prompt()}
        ]
        
        for msg in self.dialog_history:
            messages.append(msg)
        
        messages.append({"role": "user", "content": user_message})
        
        return messages
    
    def collect_calculation_params(self, initial_message: str) -> Tuple[bool, Dict, str]:
        """
        Основной метод для сбора параметров расчета.
        
        Анализирует одно сообщение пользователя. Если параметров недостаточно,
        возвращает вопрос для уточнения и ждет следующего ответа (который будет
        обработан через continue_dialog).
        
        Args:
            initial_message: Первое сообщение пользователя
            
        Returns:
            Tuple[bool, Dict, str]: 
                - Флаг успешности (True если все параметры собраны)
                - Словарь с собранными параметрами
                - Финальное сообщение (вопрос или подтверждение)
        """
        logger.info(f"Начало сбора параметров расчета. Исходное сообщение: {initial_message}")
        
        # Очищаем историю при первом сообщении
        self.dialog_history = []
        
        # Формируем сообщения с историей
        messages = self._build_messages_with_history(initial_message)
        
        # Добавляем сообщение в историю
        self.dialog_history.append({"role": "user", "content": initial_message})
        
        # Получаем ответ от GigaChat
        try:
            response = self._call_gigachat(messages)
        except Exception as e:
            logger.error(f"Ошибка при вызове GigaChat API: {e}", exc_info=True)
            error_msg = (
                "Извините, произошла техническая ошибка при обращении к сервису анализа. "
                "Попробуйте еще раз через несколько секунд."
            )
            return False, {}, error_msg
        
        # Добавляем ответ в историю
        self.dialog_history.append({"role": "assistant", "content": response})
        
        # Парсим результат
        analysis = self._parse_analysis_result(response)
        
        if not analysis:
            error_msg = (
                "Извините, не удалось обработать ответ системы анализа. "
                "Попробуйте переформулировать ваш ответ или повторить попытку."
            )
            return False, {}, error_msg
        
        # Проверяем полноту параметров
        if analysis.get('complete', False):
            logger.info("Все параметры собраны успешно")
            
            found_info = analysis.get('found_info', {})
            # Нормализуем данные
            normalized_info = self._normalize_params(found_info)
            
            success_msg = self._format_success_message(normalized_info)
            return True, normalized_info, success_msg
        
        # Параметры неполные - задаем уточняющий вопрос
        clarification_question = analysis.get('clarification_question', 
                                             'Пожалуйста, предоставьте недостающую информацию.')
        
        logger.info(f"Параметры неполные. Недостающие поля: {analysis.get('missing_fields', [])}")
        
        # Возвращаем вопрос для уточнения - следующий ответ пользователя будет обработан через continue_dialog
        return False, analysis.get('found_info', {}), clarification_question
    
    def continue_dialog(self, user_response: str) -> Tuple[bool, Dict, str]:
        """Продолжение диалога с новым ответом пользователя."""
        logger.info(f"Продолжение диалога с ответом: {user_response}")
        
        messages = self._build_messages_with_history(user_response)
        self.dialog_history.append({"role": "user", "content": user_response})
        
        try:
            response = self._call_gigachat(messages)
        except Exception as e:
            logger.error(f"Ошибка при вызове GigaChat API: {e}", exc_info=True)
            return False, {}, (
                "Извините, произошла техническая ошибка при обращении к сервису анализа. "
                "Попробуйте еще раз через несколько секунд."
            )
        
        self.dialog_history.append({"role": "assistant", "content": response})
        
        analysis = self._parse_analysis_result(response)
        
        if not analysis:
            return False, {}, (
                "Извините, не удалось обработать ответ системы анализа. "
                "Попробуйте переформулировать ваш ответ."
            )
        
        if analysis.get('complete', False):
            logger.info("Все параметры собраны")
            found_info = analysis.get('found_info', {})
            normalized_info = self._normalize_params(found_info)
            success_msg = self._format_success_message(normalized_info)
            return True, normalized_info, success_msg
        
        clarification_question = analysis.get('clarification_question', 
                                             "Пожалуйста, уточните недостающую информацию.")
        
        return False, analysis.get('found_info', {}), clarification_question
    
    def _normalize_params(self, params: Dict) -> Dict:
        """Нормализация параметров (преобразование типов, проверка диапазонов)."""
        normalized = {}
        
        # avg_amount_mmb
        if 'avg_amount_mmb' in params:
            val = params['avg_amount_mmb']
            if isinstance(val, str):
                val = val.replace(' ', '').replace(',', '.')
                if 'млн' in val.lower() or 'млн.' in val.lower():
                    val = float(val.replace('млн', '').replace('млн.', '').strip()) * 1_000_000
                else:
                    val = float(val)
            normalized['avg_amount_mmb'] = float(val)
        
        # avg_amount_other
        if 'avg_amount_other' in params:
            val = params['avg_amount_other']
            if isinstance(val, str):
                val = val.replace(' ', '').replace(',', '.')
                if 'млн' in val.lower() or 'млн.' in val.lower():
                    val = float(val.replace('млн', '').replace('млн.', '').strip()) * 1_000_000
                else:
                    val = float(val)
            normalized['avg_amount_other'] = float(val)
        
        # k
        if 'k' in params:
            val = params['k']
            if isinstance(val, str):
                val = val.replace('%', '').replace(' ', '').strip()
            normalized['k'] = float(val)
        
        # own_share
        if 'own_share' in params:
            val = params['own_share']
            if isinstance(val, str):
                val = val.replace('%', '').replace(' ', '').strip()
            normalized['own_share'] = float(val)
        
        # product_type
        if 'product_type' in params:
            val = str(params['product_type']).strip()
            if val.lower() in ['коробка', 'box']:
                normalized['product_type'] = 'Коробка'
            elif val.lower() in ['кастом', 'custom', 'каст']:
                normalized['product_type'] = 'Кастом'
            else:
                normalized['product_type'] = val
        
        # tb (опционально)
        if 'tb' in params and params['tb']:
            normalized['tb'] = str(params['tb']).strip()
        else:
            normalized['tb'] = None
        
        return normalized
    
    def _format_success_message(self, info: Dict) -> str:
        """Форматирование успешного сообщения с собранными параметрами."""
        msg = "✅ Отлично! Я получил все параметры для расчета:\n\n"
        msg += f"💰 Средний чек ММБ: {info.get('avg_amount_mmb', 0):,.0f} руб.\n"
        msg += f"💰 Средний чек другие сегменты: {info.get('avg_amount_other', 0):,.0f} руб.\n"
        msg += f"📊 Кприб: {info.get('k', 0)}%\n"
        msg += f"📈 Доля владения: {info.get('own_share', 0)}%\n"
        msg += f"📦 Тип продукта: {info.get('product_type', 'не указано')}\n"
        if info.get('tb'):
            msg += f"🏢 Территориальный банк: {info.get('tb')}\n"
        msg += "\nЗапускаю расчет потенциала..."
        
        return msg
    
    def reset_dialog(self):
        """Сброс истории диалога."""
        self.dialog_history = []
        logger.info("История диалога очищена")

