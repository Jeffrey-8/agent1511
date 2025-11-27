# okved_agent.py
"""
Агент для определения ОКВЭД кодов по названию отрасли.
Использует GigaChat для умного сопоставления названия отрасли с кодами ОКВЭД из БД.
"""

import os
import uuid
import json
import logging
import sqlite3
import requests
from typing import List, Optional, Dict, Tuple
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OkvedAgent:
    """
    Агент для определения ОКВЭД кодов по названию отрасли.
    
    Работает в два этапа:
    1. Поиск в БД по ключевым словам
    2. Использование GigaChat для выбора наиболее подходящих кодов
    """
    
    def __init__(self, db_name='data_storage.db'):
        """Инициализация агента."""
        self.db_name = db_name
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
        
        logger.info("OkvedAgent инициализирован")
    
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
                       temperature: float = 0.3, 
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
            
            logger.info(f"Получен ответ от GigaChat: {content[:100]}...")
            return content
            
        except Exception as e:
            logger.error(f"Ошибка при вызове GigaChat API: {e}")
            raise
    
    def _expand_industry_synonyms(self, industry_name: str) -> List[str]:
        """
        Расширение названия отрасли синонимами для улучшения поиска.
        
        Args:
            industry_name: Название отрасли
            
        Returns:
            List[str]: Список вариантов для поиска
        """
        industry_lower = industry_name.lower().strip()
        synonyms = [industry_name]  # Оригинальное название
        
        # Маппинг общих терминов на более конкретные
        general_terms = {
            'промышленность': ['производство', 'изготовление', 'выпуск'],
            'торговля': ['розничная торговля', 'оптовая торговля', 'продажа'],
            'it': ['разработка программного обеспечения', 'программирование', 'информационные технологии'],
            'услуги': ['оказание услуг', 'сервис'],
            'строительство': ['строительные работы', 'возведение'],
            'транспорт': ['перевозка', 'транспортировка'],
            'образование': ['обучение', 'преподавание'],
            'медицина': ['здравоохранение', 'медицинские услуги'],
        }
        
        # Добавляем синонимы для общих терминов
        for general_term, specific_terms in general_terms.items():
            if general_term in industry_lower:
                synonyms.extend(specific_terms)
                break
        
        return synonyms
    
    def search_okved_in_db(self, industry_name: str, limit: int = 20) -> List[Dict[str, str]]:
        """
        Поиск ОКВЭД кодов в БД по названию отрасли.
        
        Args:
            industry_name: Название отрасли
            limit: Максимальное количество результатов
            
        Returns:
            List[Dict]: Список словарей с code и name
        """
        if not os.path.exists(self.db_name):
            logger.warning(f"База данных {self.db_name} не найдена")
            return []
        
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            
            # Расширяем поисковые запросы синонимами
            search_terms = self._expand_industry_synonyms(industry_name)
            logger.info(f"Поиск ОКВЭД для '{industry_name}' с вариантами: {search_terms}")
            
            # Разбиваем все варианты на ключевые слова
            all_keywords = set()
            for term in search_terms:
                keywords = term.lower().split()
                for keyword in keywords:
                    if len(keyword) > 2:  # Игнорируем слишком короткие слова
                        all_keywords.add(keyword)
            
            # Формируем SQL запрос с поиском по ключевым словам
            # Для кириллицы делаем поиск с учетом обоих вариантов регистра
            conditions = []
            params = []
            
            for keyword in all_keywords:
                # Добавляем поиск с маленькой и заглавной буквы
                keyword_lower = keyword.lower()
                keyword_title = keyword_lower.capitalize()
                conditions.append("(name LIKE ? OR name LIKE ?)")
                params.append(f"%{keyword_lower}%")
                params.append(f"%{keyword_title}%")
            
            if not conditions:
                # Если нет ключевых слов, ищем по всему названию
                industry_lower = industry_name.lower()
                industry_title = industry_lower.capitalize()
                conditions.append("(name LIKE ? OR name LIKE ?)")
                params.append(f"%{industry_lower}%")
                params.append(f"%{industry_title}%")
            
            # Добавляем параметры для сортировки (приоритет точному совпадению)
            industry_lower = industry_name.lower()
            industry_title = industry_lower.capitalize()
            params.append(f"%{industry_lower}%")
            params.append(f"%{industry_title}%")
            
            query = f"""
                SELECT DISTINCT code, name 
                FROM okved 
                WHERE {' OR '.join(conditions)}
                ORDER BY 
                    CASE 
                        WHEN name LIKE ? OR name LIKE ? THEN 1
                        ELSE 2
                    END
                LIMIT {limit}
            """
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            conn.close()
            
            okved_list = [{"code": row[0], "name": row[1]} for row in results]
            logger.info(f"Найдено {len(okved_list)} ОКВЭД кодов для '{industry_name}': {[item['code'] for item in okved_list[:5]]}")
            
            return okved_list
            
        except Exception as e:
            logger.error(f"Ошибка при поиске в БД: {e}", exc_info=True)
            return []
    
    def select_relevant_okved_codes(
        self, 
        industry_name: str, 
        okved_candidates: List[Dict[str, str]]
    ) -> List[str]:
        """
        Использование GigaChat для выбора наиболее подходящих ОКВЭД кодов.
        
        Args:
            industry_name: Название отрасли от пользователя
            okved_candidates: Список кандидатов из БД
            
        Returns:
            List[str]: Список выбранных ОКВЭД кодов
        """
        if not okved_candidates:
            logger.warning("Нет кандидатов для выбора")
            return []
        
        # Формируем список кандидатов для промпта
        candidates_text = "\n".join([
            f"{idx + 1}. Код: {item['code']}, Название: {item['name']}"
            for idx, item in enumerate(okved_candidates)
        ])
        
        prompt = f"""Ты - эксперт по классификации видов экономической деятельности (ОКВЭД).

Пользователь указал отрасль: "{industry_name}"

Ниже представлен список ОКВЭД кодов, найденных в справочнике:

{candidates_text}

Твоя задача: выбрать наиболее подходящие ОКВЭД коды для указанной отрасли.

ПРАВИЛА:
1. Выбирай коды, которые точно соответствуют отрасли
2. Можно выбрать несколько кодов, если отрасль широкая
3. Предпочитай более конкретные коды (с большим количеством точек) более общим
4. Если отрасль очень общая (например, "IT"), можно выбрать несколько связанных кодов
5. Если ничего не подходит - верни пустой список

Ответь СТРОГО в формате JSON:
{{
  "selected_codes": ["код1", "код2", ...],
  "reasoning": "краткое объяснение выбора"
}}

Примеры:

Отрасль: "Разработка программного обеспечения"
→ {{"selected_codes": ["62.01", "62.02"], "reasoning": "Выбраны коды, связанные с разработкой ПО"}}

Отрасль: "Торговля продуктами"
→ {{"selected_codes": ["47.11", "47.19"], "reasoning": "Выбраны коды розничной торговли продуктами"}}

Отрасль: "Производство мебели"
→ {{"selected_codes": ["31.01"], "reasoning": "Выбран код производства мебели"}}

Выбери коды для отрасли: "{industry_name}"
"""
        
        try:
            messages = [
                {"role": "user", "content": prompt}
            ]
            
            try:
                response = self._call_gigachat(messages, temperature=0.3)
            except Exception as e:
                logger.error(f"Ошибка при вызове GigaChat API: {e}", exc_info=True)
                # В случае ошибки API возвращаем первые 3 кандидата
                logger.info("Используем первые 3 кандидата из БД из-за ошибки API")
                return [item['code'] for item in okved_candidates[:3]]
            
            # Парсим JSON ответ
            result = self._parse_response(response)
            
            if result and 'selected_codes' in result:
                selected_codes = result['selected_codes']
                # Проверяем, что коды валидны
                if isinstance(selected_codes, list) and selected_codes:
                    # Фильтруем только те коды, которые есть в кандидатах
                    valid_codes = [code for code in selected_codes if any(c['code'] == code for c in okved_candidates)]
                    if valid_codes:
                        logger.info(f"Выбрано {len(valid_codes)} ОКВЭД кодов: {valid_codes}")
                        return valid_codes
                    else:
                        logger.warning("Выбранные коды не найдены в кандидатах")
                else:
                    logger.warning("selected_codes не является непустым списком")
            else:
                logger.warning("Не удалось извлечь коды из ответа")
            
            # Fallback: возвращаем первые 3 кандидата
            logger.info("Используем первые 3 кандидата из БД как fallback")
            return [item['code'] for item in okved_candidates[:3]]
                
        except Exception as e:
            logger.error(f"Неожиданная ошибка при выборе кодов: {e}", exc_info=True)
            # В случае ошибки возвращаем первые 3 кандидата
            return [item['code'] for item in okved_candidates[:3]]
    
    def _parse_response(self, response: str) -> Optional[Dict]:
        """Парсинг JSON-ответа от GigaChat с улучшенной обработкой ошибок."""
        if not response or not response.strip():
            logger.error("Пустой ответ от GigaChat")
            return None
        
        try:
            start_idx = response.find('{')
            end_idx = response.rfind('}')
            
            if start_idx == -1 or end_idx == -1:
                logger.warning(f"JSON не найден в ответе. Ответ: {response[:200]}")
                # Пытаемся найти JSON в обратном порядке
                last_open = response.rfind('{')
                if last_open != -1:
                    potential_json = response[last_open:]
                    try:
                        result = json.loads(potential_json)
                        logger.info("Найден JSON в конце ответа")
                        return result
                    except:
                        pass
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
    
    def determine_industry(self, company_or_industry: str) -> str:
        """
        Определение отрасли через GigaChat на основе названия компании или общего описания.
        
        Args:
            company_or_industry: Название компании или отрасли
            
        Returns:
            str: Определенная отрасль для поиска ОКВЭД
        """
        logger.info(f"Определение отрасли для: {company_or_industry}")
        
        prompt = f"""Ты - эксперт по классификации видов экономической деятельности.

Пользователь указал: "{company_or_industry}"

Твоя задача: определить, к какой отрасли/виду экономической деятельности это относится.

ПРАВИЛА:
1. Если это название компании или организации - определи её основную отрасль
2. Если это уже отрасль - уточни или оставь как есть
3. Используй конкретные термины, которые могут быть в справочнике ОКВЭД
4. Для учебных заведений указывай конкретный тип (например: "высшее образование", "среднее профессиональное образование")
5. Для институтов учитывай их специализацию (авиационный → авиация, медицинский → медицина)

Примеры:
"Московский авиационный институт" → "высшее образование в области авиации и авиастроения"
"Сбербанк" → "банковская деятельность"
"Магнит" → "розничная торговля продуктами"
"IT компания по разработке ПО" → "разработка программного обеспечения"
"Завод по производству мебели" → "производство мебели"

Ответь СТРОГО в формате JSON:
{{
  "industry": "название отрасли",
  "keywords": ["ключевое", "слово", "для", "поиска"],
  "reasoning": "краткое объяснение"
}}

Определи отрасль для: "{company_or_industry}"
"""
        
        try:
            messages = [{"role": "user", "content": prompt}]
            
            try:
                response = self._call_gigachat(messages, temperature=0.3)
            except Exception as e:
                logger.error(f"Ошибка при вызове GigaChat для определения отрасли: {e}")
                # В случае ошибки возвращаем исходное значение
                return company_or_industry
            
            # Парсим JSON ответ
            result = self._parse_response(response)
            
            if result and 'industry' in result:
                industry = result['industry']
                keywords = result.get('keywords', [])
                reasoning = result.get('reasoning', '')
                
                logger.info(f"Определена отрасль: {industry}")
                logger.info(f"Ключевые слова: {keywords}")
                logger.info(f"Объяснение: {reasoning}")
                
                # Если есть ключевые слова, объединяем их с отраслью для лучшего поиска
                if keywords:
                    enhanced_industry = f"{industry} {' '.join(keywords)}"
                    return enhanced_industry
                
                return industry
            else:
                logger.warning("Не удалось определить отрасль, используем исходное значение")
                return company_or_industry
                
        except Exception as e:
            logger.error(f"Ошибка при определении отрасли: {e}", exc_info=True)
            return company_or_industry
    
    def get_okved_codes(self, industry_name: str) -> List[str]:
        """
        Основной метод для получения ОКВЭД кодов по названию отрасли или компании.
        
        Args:
            industry_name: Название отрасли или компании (например, "IT", "Сбербанк", "Московский авиационный институт")
            
        Returns:
            List[str]: Список ОКВЭД кодов
        """
        logger.info(f"Поиск ОКВЭД кодов для: {industry_name}")
        
        # Этап 1: Определяем отрасль через GigaChat
        determined_industry = self.determine_industry(industry_name)
        logger.info(f"Определенная отрасль для поиска: {determined_industry}")
        
        # Этап 2: Поиск в БД по определенной отрасли
        candidates = self.search_okved_in_db(determined_industry, limit=30)
        
        if not candidates:
            logger.warning(f"Не найдено кандидатов для отрасли: {determined_industry}")
            return []
        
        logger.info(f"Найдено {len(candidates)} кандидатов, выбираю наиболее подходящие через GigaChat")
        
        # Этап 3: Выбор наиболее подходящих через GigaChat
        selected_codes = self.select_relevant_okved_codes(determined_industry, candidates)
        
        if selected_codes:
            logger.info(f"Выбрано {len(selected_codes)} ОКВЭД кодов: {selected_codes}")
        else:
            logger.warning(f"GigaChat не выбрал коды для отрасли: {determined_industry}")
        
        return selected_codes


# === Пример использования ===

def example_usage():
    """Пример использования агента."""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    agent = OkvedAgent()
    
    test_cases = [
        "Московский авиационный институт",
        "Сбербанк",
        "IT",
        "Разработка программного обеспечения",
        "Торговля продуктами",
        "Производство мебели",
        "Консалтинг"
    ]
    
    print("\n" + "=" * 80)
    print("ТЕСТИРОВАНИЕ OKVED AGENT")
    print("=" * 80)
    
    for test_input in test_cases:
        print(f"\n--- Вход: {test_input} ---")
        codes = agent.get_okved_codes(test_input)
        if codes:
            print(f"✓ Найдено кодов: {len(codes)}")
            for code in codes:
                print(f"  • {code}")
        else:
            print("✗ Коды не найдены")
        print("-" * 80)


if __name__ == "__main__":
    example_usage()

