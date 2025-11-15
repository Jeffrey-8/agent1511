# import os
# import logging
# import json
# import re
# from typing import Dict, List, Optional, Any
#
# import requests
# from langgraph.graph import StateGraph, END
# from pydantic import BaseModel
# from gigachat import GigaChat
# from analytics_engine import calculate_potential_full_pipeline
#
# # Настройка логирования
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)
#
#
# # Модели для структурированного ответа от LLM
# class FilterParameters(BaseModel):
#     industries: List[str] = []
#     revenue: List[str] = []
#     staff: List[str] = []
#     tb: List[str] = []
#     product_type: str = "Коробка"
#     mmb_dolya: Optional[float] = None
#     mmb_kpr: Optional[float] = None
#     other_dolya: Optional[float] = None
#     other_kpr: Optional[float] = None
#
#
# class AgentState(BaseModel):
#     user_input: str
#     extracted_parameters: Optional[FilterParameters] = None
#     confirmed_parameters: Optional[FilterParameters] = None
#     calculation_results: Optional[Dict] = None
#     missing_parameters: List[str] = []
#     reasoning: List[str] = []
#
#
# AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
# # --- Конфигурация GigaChat ---
# GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
# GIGACHAT_MODEL = "GigaChat-2-Max"
# RQ_UID = "884a110b-feca-430f-bb5e-57d3d06b2ee9"
# AUTHORIZATION = "Basic ZDZmMDBiY2EtNTViYi00NTg0LWJkNDAtZjdlNGUzMTY3YjczOmQ2YTUzMmZhLTdmNjMtNDI4NS1hN2NlLTAzZmZiMWU4YmNjYg=="
#
#
# # --- Утилиты для работы с LLM ---
# def get_giga_access_token():
#     payload = {'scope': GIGACHAT_SCOPE}
#     headers = {
#         'Content-Type': 'application/x-www-form-urlencoded',
#         'Accept': 'application/json',
#         'RqUID': RQ_UID,
#         'Authorization': AUTHORIZATION
#     }
#     response = requests.post(AUTH_URL, headers=headers, data=payload, verify=False)
#     return response.json().get('access_token')
#
#
# def clean_llm_response(content: str) -> str:
#     """Очистка ответа от LLM от лишнего текста и извлечение JSON"""
#     # Удаляем markdown коды
#     content = re.sub(r'```json\s*', '', content)
#     content = re.sub(r'```\s*', '', content)
#
#     # Ищем JSON паттерн
#     json_match = re.search(r'\{.*\}', content, re.DOTALL)
#     if json_match:
#         return json_match.group().strip()
#     return content.strip()
#
#
# class PotentialCalculationAgent:
#     def __init__(self):
#         token = get_giga_access_token()
#         self.llm = GigaChat(
#             access_token=token,
#             scope=GIGACHAT_SCOPE,
#             verify_ssl_certs=False
#         )
#         # Путь к данным (должен совпадать с тем, что ты используешь для CSV)
#         self.data_directory = "./resources/csv"
#
#     # =======================
#     #     EXTRACT BLOCK
#     # =======================
#
#     def extract_industries(self, user_input: str) -> List[str]:
#         """Извлечение отраслей из запроса пользователя"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Определи отрасли бизнеса из запроса и верни соответствующие коды ОКВЭД в формате XX.X.
#
# Справочник отраслей:
# - IT, программирование, разработка, софт → "62.0", "63.1"
# - Розничная торговля, магазины, ритейл → "47.1", "47.2"
# - Производство, заводы, фабрики → "10.1", "10.8", "11.0", "13.0"
# - Строительство, ремонт, строительные работы → "41.0", "42.0", "43.0"
# - Финансы, банки, страхование, инвестиции → "64.1", "64.9", "65.0"
# - Транспорт, логистика, грузоперевозки → "49.0", "50.0", "51.0", "52.0"
# - Здравоохранение, медицина, больницы → "86.0"
# - Образование, университеты, школы → "85.0"
# - Гостиницы, рестораны, общепит → "55.0", "56.0"
# - Недвижимость, аренда → "68.0"
# - Консалтинг, юридические услуги → "69.0", "70.0"
#
# Верни ТОЛЬКО JSON объект с ключом "industries" и массивом кодов ОКВЭД.
# Если отрасли не найдены, верни: {{"industries": []}}
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][industries] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return data.get("industries", [])
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении отраслей: {e}")
#             return []
#
#     def extract_revenue_categories(self, user_input: str) -> List[str]:
#         """Извлечение категорий выручки"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Найди упоминания о выручке и сопоставь с категориями.
#
# Справочник выручки:
# - "Менее 1 млн.р."
# - "1-10 млн.р."
# - "10-120 млн.р."
# - "120-800 млн.р."
# - "Более 800 млн.р."
#
# Правила сопоставления:
# - "выручка 5 млн" → "1-10 млн.р."
# - "выручка 50 млн" → "10-120 млн.р."
# - "оборот 100-500 млн" → ["10-120 млн.р."]
# - "доход менее 1 млн" → "Менее 1 млн.р."
# - "более 1 млрд" → "Более 800 млн.р."
#
# Верни ТОЛЬКО JSON объект: {{"revenue": [...]}}.
# Если не смог определить категорию — верни {{"revenue": []}}.
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][revenue] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return data.get("revenue", [])
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении выручки: {e}")
#             return []
#
#     def extract_staff_categories(self, user_input: str) -> List[str]:
#         """Извлечение категорий штата"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Найди упоминания о количестве сотрудников и сопоставь с категориями.
#
# Справочник штата:
# - 1 человек → "1 чел."
# - 2-5 человек → "2-5 чел."
# - 6-30 человек → "6-30 чел."
# - 31-100 человек → "31-100 чел."
# - более 100 человек → "Более 100 чел."
#
# Правила сопоставления:
# - "15 человек" → "6-30 чел."
# - "штат 50 человек" → "31-100 чел."
# - "2 сотрудника" → "2-5 чел."
# - "более 200 человек" → "Более 100 чел."
# - "малый бизнес" → "6-30 чел.", "31-100 чел." (верни обе категории)
#
# Верни ТОЛЬКО JSON объект: {{"staff": [...]}}.
# Если в запросе нет упоминания о кол-ве сотрудников — верни {{"staff": []}}.
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][staff] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return data.get("staff", [])
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении штата: {e}")
#             return []
#
#     def extract_territorial_banks(self, user_input: str) -> List[str]:
#         """Извлечение территориальных банков"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Найди упоминания о регионах или территориальных банках.
#
# Справочник ТБ (используй ТОЛЬКО эти коды):
# - "ЦА" (Центральный)
# - "ББ" (Байкальский)
# - "ВВБ" (Волго-Вятский)
# - "ДВБ" (Дальневосточный)
# - "МБ" (Московский)
# - "ПБ" (Поволжский)
# - "СЗБ" (Северо-Западный)
# - "СибБ" (Сибирский)
# - "СРБ" (Северо-Кавказский)
# - "УБ" (Уральский)
# - "ЦЧБ" (Центрально-Черноземный)
# - "ЮЗБ" (Юго-Западный)
#
# Примеры сопоставления:
# - "Москва", "Московская область" → "МБ"
# - "Урал", "Екатеринбург", "Челябинск" → "УБ"
# - "Сибирь", "Новосибирск", "Красноярск" → "СибБ"
# - "Санкт-Петербург", "Ленинградская область" → "СЗБ"
#
# Верни ТОЛЬКО JSON объект: {{"tb": [...]}}.
# Если регион определить нельзя — верни {{"tb": []}}.
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][tb] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return data.get("tb", [])
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении ТБ: {e}")
#             return []
#
#     def extract_product_type(self, user_input: str) -> str:
#         """Извлечение типа продукта"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Определи тип продукта - "Коробка" или "Кастом".
#
# Правила:
# - По умолчанию: "Коробка".
# - Используй "Кастом" только если явно указано: "кастом", "кастомный", "индивидуальный", "персональный".
#
# Верни ТОЛЬКО JSON: {{"product_type": "Коробка"}} или {{"product_type": "Кастом"}}.
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][product_type] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return data.get("product_type", "Коробка")
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении типа продукта: {e}")
#             return "Коробка"
#
#     def extract_calculation_parameters(self, user_input: str) -> Dict[str, float]:
#         """Извлечение параметров расчета (доли и Кприб)"""
#         prompt = f"""
# Запрос пользователя: "{user_input}"
#
# Задача: Найди числовые параметры для расчета.
#
# Параметры (используй значения по умолчанию, если не указано):
# - mmb_dolya: доля владения для ММБ (по умолчанию 6.0)
# - mmb_kpr: Кприб для ММБ (по умолчанию 15.0)
# - other_dolya: доля владения для других сегментов (по умолчанию 10.0)
# - other_kpr: Кприб для других сегментов (по умолчанию 20.0)
#
# Верни ТОЛЬКО JSON:
# {{
#   "mmb_dolya": 6.0,
#   "mmb_kpr": 15.0,
#   "other_dolya": 10.0,
#   "other_kpr": 20.0
# }}
# """
#         try:
#             response = self.llm.chat(prompt)
#             logger.info(f"[LLM][calc_params] raw: {response.choices[0].message.content}")
#             content = clean_llm_response(response.choices[0].message.content)
#             data = json.loads(content)
#             return {
#                 "mmb_dolya": data.get("mmb_dolya", 6.0),
#                 "mmb_kpr": data.get("mmb_kpr", 15.0),
#                 "other_dolya": data.get("other_dolya", 10.0),
#                 "other_kpr": data.get("other_kpr", 20.0),
#             }
#         except Exception as e:
#             logger.error(f"Ошибка при извлечении параметров расчета: {e}")
#             return {
#                 "mmb_dolya": 6.0,
#                 "mmb_kpr": 15.0,
#                 "other_dolya": 10.0,
#                 "other_kpr": 20.0,
#             }
#
#     # =======================
#     #   GRAPH NODE METHODS
#     # =======================
#
#     def extract_parameters(self, state: AgentState) -> AgentState:
#         """Извлечение параметров из пользовательского запроса поэтапно"""
#         logger.info("🔍 Извлекаю параметры из запроса пользователя...")
#
#         user_input = state.user_input
#         reasoning_steps = []
#
#         try:
#             industries = self.extract_industries(user_input)
#             reasoning_steps.append(f"Извлечены отрасли: {industries}")
#
#             revenue = self.extract_revenue_categories(user_input)
#             reasoning_steps.append(f"Извлечены категории выручки: {revenue}")
#
#             staff = self.extract_staff_categories(user_input)
#             reasoning_steps.append(f"Извлечены категории штата: {staff}")
#
#             tb = self.extract_territorial_banks(user_input)
#             reasoning_steps.append(f"Извлечены тербанки: {tb}")
#
#             product_type = self.extract_product_type(user_input)
#             reasoning_steps.append(f"Определен тип продукта: {product_type}")
#
#             calc_params = self.extract_calculation_parameters(user_input)
#             reasoning_steps.append(f"Параметры расчета (доля/Кприб): {calc_params}")
#
#             state.extracted_parameters = FilterParameters(
#                 industries=industries,
#                 revenue=revenue,
#                 staff=staff,
#                 tb=tb,
#                 product_type=product_type,
#                 **calc_params,
#             )
#
#             state.reasoning.extend(reasoning_steps)
#             logger.info("✅ Параметры успешно извлечены")
#
#         except Exception as e:
#             error_msg = f"Ошибка при извлечении параметров: {e}"
#             logger.error(error_msg)
#             state.reasoning.append(error_msg)
#             state.extracted_parameters = FilterParameters()
#
#         return state
#
#     def validate_parameters(self, state: AgentState) -> AgentState:
#         """Валидация извлеченных параметров"""
#         logger.info("✅ Проверяю корректность извлеченных параметров...")
#
#         if not state.extracted_parameters:
#             state.missing_parameters = ["Все параметры"]
#             return state
#
#         missing = []
#         params = state.extracted_parameters
#
#         if not params.product_type:
#             missing.append("product_type")
#         if params.mmb_dolya is None:
#             missing.append("mmb_dolya")
#         if params.mmb_kpr is None:
#             missing.append("mmb_kpr")
#         if params.other_dolya is None:
#             missing.append("other_dolya")
#         if params.other_kpr is None:
#             missing.append("other_kpr")
#
#         state.missing_parameters = missing
#
#         reasoning = (
#             f"Проверка параметров: отсутствуют {missing}" if missing else "Все параметры присутствуют"
#         )
#         logger.info(reasoning)
#         state.reasoning.append(reasoning)
#
#         return state
#
#     def request_missing_parameters(self, state: AgentState) -> AgentState:
#         """Запрос недостающих параметров у пользователя через консоль"""
#         if state.missing_parameters:
#             logger.info("❌ Требуются дополнительные параметры:")
#
#             params_dict = state.extracted_parameters.dict() if state.extracted_parameters else {}
#
#             for param in state.missing_parameters:
#                 if param == "product_type":
#                     print("\n🎯 Выберите тип продукта:")
#                     print("1. Коробка")
#                     print("2. Кастом")
#                     choice = input("Введите номер (1 или 2): ").strip()
#                     if choice == "2":
#                         params_dict["product_type"] = "Кастом"
#                     else:
#                         params_dict["product_type"] = "Коробка"
#
#                 elif param == "mmb_dolya":
#                     print(f"\n📊 Введите долю владения для ММБ (текущее: {params_dict.get('mmb_dolya', 'не задано')}):")
#                     try:
#                         value = float(input("Доля владения ММБ (%): ").strip())
#                         params_dict["mmb_dolya"] = value
#                     except Exception:
#                         params_dict["mmb_dolya"] = 6.0
#                         print("Использую значение по умолчанию: 6.0")
#
#                 elif param == "mmb_kpr":
#                     print(f"\n💰 Введите Кприб для ММБ (текущее: {params_dict.get('mmb_kpr', 'не задано')}):")
#                     try:
#                         value = float(input("Кприб ММБ (%): ").strip())
#                         params_dict["mmb_kpr"] = value
#                     except Exception:
#                         params_dict["mmb_kpr"] = 15.0
#                         print("Использую значение по умолчанию: 15.0")
#
#                 elif param == "other_dolya":
#                     print(
#                         f"\n📊 Введите долю владения для других сегментов (текущее: {params_dict.get('other_dolya', 'не задано')}):"
#                     )
#                     try:
#                         value = float(input("Доля владения других сегментов (%): ").strip())
#                         params_dict["other_dolya"] = value
#                     except Exception:
#                         params_dict["other_dolya"] = 10.0
#                         print("Использую значение по умолчанию: 10.0")
#
#                 elif param == "other_kpr":
#                     print(
#                         f"\n💰 Введите Кприб для других сегментов (текущее: {params_dict.get('other_kpr', 'не задано')}):"
#                     )
#                     try:
#                         value = float(input("Кприб других сегментов (%): ").strip())
#                         params_dict["other_kpr"] = value
#                     except Exception:
#                         params_dict["other_kpr"] = 20.0
#                         print("Использую значение по умолчанию: 20.0")
#
#             state.extracted_parameters = FilterParameters(**params_dict)
#             state.missing_parameters = []
#
#             logger.info("✅ Параметры получены от пользователя")
#
#         return state
#
#     def confirm_parameters(self, state: AgentState) -> AgentState:
#         """Подтверждение параметров пользователем"""
#         logger.info("📋 Подтверждение параметров расчета...")
#
#         if state.extracted_parameters:
#             params = state.extracted_parameters.dict()
#
#             print("\n" + "=" * 50)
#             print("📋 ПАРАМЕТРЫ ДЛЯ РАСЧЕТА:")
#             print("=" * 50)
#
#             print(f"\n🏭 Отрасли (ОКВЭД): {params['industries'] or 'Все отрасли'}")
#             print(f"💰 Выручка: {params['revenue'] or 'Все категории'}")
#             print(f"👥 Штат: {params['staff'] or 'Все категории'}")
#             print(f"🏙️ Тербанки: {params['tb'] or 'Все регионы'}")
#             print(f"🎯 Тип продукта: {params['product_type']}")
#             print(f"📊 Доля владения ММБ: {params['mmb_dolya']}%")
#             print(f"💰 Кприб ММБ: {params['mmb_kpr']}%")
#             print(f"📊 Доля владения других: {params['other_dolya']}%")
#             print(f"💰 Кприб других: {params['other_kpr']}%")
#
#             print("\nПодтверждаете расчет с этими параметрами?")
#             confirmation = input("Введите 'да' для подтверждения или 'нет' для отмены: ").strip().lower()
#
#             if confirmation == 'да':
#                 state.confirmed_parameters = state.extracted_parameters
#                 reasoning = "Пользователь подтвердил параметры"
#                 logger.info(reasoning)
#                 state.reasoning.append(reasoning)
#             else:
#                 reasoning = "Пользователь отменил расчет"
#                 logger.info(reasoning)
#                 state.reasoning.append(reasoning)
#
#         return state
#
#     def calculate_potential(self, state: AgentState) -> AgentState:
#         """Выполнение расчета потенциала (НОВАЯ ЛОГИКА ПОД НОВЫЙ analytics_engine)"""
#         logger.info("🧮 Запускаю расчет потенциала...")
#
#         if not state.confirmed_parameters:
#             state.reasoning.append("Ошибка: нет подтвержденных параметров для расчета")
#             return state
#
#         try:
#             params = state.confirmed_parameters
#
#             # 1. Фильтры для пайплайна
#             filters = {
#                 "industries": params.industries,
#                 "revenue": params.revenue,
#                 "staff": params.staff,
#                 "tb": params.tb,
#             }
#
#             # 2. Параметры сегментов для нового analytics_engine:
#             #    segment_params: { "Сегмент": {"dolya": float, "kpr": float}, ... }
#             mmb_dolya = params.mmb_dolya or 6.0
#             mmb_kpr = params.mmb_kpr or 15.0
#             other_dolya = params.other_dolya or 10.0
#             other_kpr = params.other_kpr or 20.0
#
#             segment_params: Dict[str, Dict[str, float]] = {}
#
#             # ММБ — отдельные параметры
#             segment_params["ММБ"] = {"dolya": mmb_dolya, "kpr": mmb_kpr}
#
#             # Остальные сегменты (KeyClients, КСБ, СКМ, РГС) — общие параметры other_*
#             for seg in ["KeyClients", "КСБ", "СКМ", "РГС"]:
#                 segment_params[seg] = {"dolya": other_dolya, "kpr": other_kpr}
#
#             logger.info(f"segment_params для расчета: {segment_params}")
#
#             # 3. Запуск нового пайплайна
#             results = calculate_potential_full_pipeline(
#                 data_directory=self.data_directory,
#                 filters=filters,
#                 segment_params=segment_params,
#                 product_type=params.product_type or "Коробка",
#             )
#
#             state.calculation_results = results
#             reasoning = (
#                 f"Расчет завершен: {len(results['potential_results'])} результатов, "
#                 f"{results['filtered_records_count']} записей после фильтрации"
#             )
#             logger.info(reasoning)
#             state.reasoning.append(reasoning)
#
#         except Exception as e:
#             error_msg = f"Ошибка при расчете: {e}"
#             logger.error(error_msg)
#             state.reasoning.append(error_msg)
#
#         return state
#
#     # =======================
#     #   WORKFLOW & UI
#     # =======================
#
#     def create_workflow(self) -> StateGraph:
#         """Создание графа workflow"""
#         workflow = StateGraph(AgentState)
#
#         workflow.add_node("extract_parameters", self.extract_parameters)
#         workflow.add_node("validate_parameters", self.validate_parameters)
#         workflow.add_node("request_missing_parameters", self.request_missing_parameters)
#         workflow.add_node("confirm_parameters", self.confirm_parameters)
#         workflow.add_node("calculate_potential", self.calculate_potential)
#
#         workflow.set_entry_point("extract_parameters")
#         workflow.add_edge("extract_parameters", "validate_parameters")
#
#         workflow.add_conditional_edges(
#             "validate_parameters",
#             lambda state: "request_missing_parameters" if state.missing_parameters else "confirm_parameters",
#         )
#
#         workflow.add_edge("request_missing_parameters", "confirm_parameters")
#         workflow.add_edge("confirm_parameters", "calculate_potential")
#         workflow.add_edge("calculate_potential", END)
#
#         return workflow
#
#     def run_interactive(self):
#         """Интерактивный запуск агента с вводом от пользователя"""
#         print("🤖 AI Агент расчета потенциала")
#         print("=" * 50)
#         print("Примеры запросов:")
#         print("- 'Рассчитай потенциал для IT компаний с выручкой 100-500 млн в Москве'")
#         print("- 'Проанализируй розничную торговлю, малый бизнес, продукт Коробка'")
#         print("- 'Потенциал для строительных компаний в ТБ Урала'")
#         print("=" * 50)
#
#         user_query = input("\n📝 Введите ваш запрос: ").strip()
#
#         if not user_query:
#             print("❌ Запрос не может быть пустым")
#             return
#
#         print("\n🔄 Обрабатываю запрос...")
#         print("-" * 50)
#
#         workflow = self.create_workflow()
#         app = workflow.compile()
#
#         initial_state = AgentState(user_input=user_query)
#         final_state = app.invoke(initial_state)
#
#         self._display_results(final_state)
#
#     def _display_results(self, final_state: Dict[str, Any]):
#         """Отображение результатов расчета в человеко-читаемом виде (без таблиц)"""
#         print("\n" + "=" * 50)
#         print("📊 РЕЗУЛЬТАТЫ РАСЧЕТА")
#         print("=" * 50)
#
#         # 1. Ход рассуждений
#         reasoning_list = final_state.get("reasoning", [])
#
#         print("\n🔍 Ход рассуждений агента:")
#         if reasoning_list:
#             for i, reasoning in enumerate(reasoning_list, 1):
#                 print(f"{i}. {reasoning}")
#         else:
#             print("- (нет записанных шагов)")
#
#         results = final_state.get("calculation_results")
#         if not results:
#             print("\n❌ Расчет не выполнен из-за ошибок")
#             return
#
#         segment_metrics = results.get("segment_metrics", {})
#         potential_results = results.get("potential_results", [])
#         filtered_count = results.get("filtered_records_count", 0)
#
#         # 2. Шаг 1: аналитика по сегментам
#         print("\n" + "-" * 50)
#         print("📌 Шаг 1. Аналитика по сегментам")
#         print("-" * 50)
#
#         if not segment_metrics:
#             print("Нет сегментов после фильтрации.")
#         else:
#             for segment, metrics in segment_metrics.items():
#                 # "Неизвестно" можно пропустить, если не нужно
#                 if segment == "Неизвестно":
#                     continue
#
#                 print(f"\n🔹 Сегмент: {segment}")
#                 print(f"  • Рынок: {metrics.get('Рынок', 0):,.0f}")
#                 print(f"  • Активные клиенты: {metrics.get('Активные клиенты Банка', 0):,.0f}")
#                 print(f"  • Спящие и не клиенты: {metrics.get('Спящие клиенты и не клиенты Банка', 0):,.0f}")
#                 print(f"  • Средняя выручка: {metrics.get('Средняя выручка, млн. р.', 0):.3f} млн ₽")
#                 print(f"  • Среднее число сотрудников: {metrics.get('Среднее кол-во сотрудников', 0)}")
#                 avg_check = metrics.get("avg_check")
#                 if avg_check is not None:
#                     print(f"  • Средний чек (оценка): {avg_check:,.0f} ₽")
#
#         # 3. Шаг 2: расчёт потенциала по каналам
#         print("\n" + "-" * 50)
#         print("📌 Шаг 2. Расчет потенциала по каналам")
#         print("-" * 50)
#
#         if not potential_results:
#             print("Нет результатов по каналам.")
#             print(f"\n📊 Обработано записей после фильтров: {filtered_count}")
#             return
#
#         successful_results = [r for r in potential_results if r.get("Решение") == "да"]
#         failed_results = [r for r in potential_results if r.get("Решение") != "да"]
#
#         # 3.1 Каналы с решением "да"
#         print("\n✅ Каналы, где продажа возможна (Решение = 'да'):")
#
#         if not successful_results:
#             print("  • Нет каналов с решением 'да'.")
#         else:
#             total_potential = 0.0
#             for r in successful_results:
#                 seg = r.get("Сегмент")
#                 ch_name = r.get("Канал")
#                 calc_clients = r.get("calc_clients", 0)
#                 potential_amount = r.get("potential_amount", 0.0)
#                 rate_ab = r.get("rate_ab", 0.0)
#                 amount_ab = r.get("amount_ab", 0.0)
#                 amount_chkd = r.get("amount_chkd", 0.0)
#                 revenue_val = r.get("revenue", 0.0)
#                 total = r.get("total_potential", 0.0)
#                 total_potential += total
#
#                 # средний чек достаём из сегментных метрик
#                 avg_check = None
#                 if seg in segment_metrics:
#                     avg_check = segment_metrics[seg].get("avg_check")
#
#                 print(f"\n🔹 Канал: {ch_name}")
#                 print(f"  • Сегмент: {seg}")
#                 print(f"  • Клиентов в сегменте: {calc_clients:,.0f}")
#                 if avg_check is not None:
#                     print(f"  • Средний чек сегмента: {avg_check:,.0f} ₽")
#                 print(f"  • Потенциал (с учетом утилизации): {potential_amount:.3f} млн ₽")
#                 print(f"  • Ставка AB: {rate_ab:.1f}%")
#                 print(f"  • Сумма AB: {amount_ab:.3f} млн ₽")
#                 print(f"  • ЧКД: {amount_chkd:.3f} млн ₽")
#                 print(f"  • Прибыль: {revenue_val:.3f} млн ₽")
#                 print(f"  🏆 Итоговый потенциал по каналу: {total:.3f} млн ₽")
#
#             print(f"\n💰 Суммарный потенциал по каналам с решением 'да': {total_potential:.3f} млн ₽")
#
#         # 3.2 Каналы с решением "нет"
#         print("\n❌ Каналы, где продажа НЕ рекомендуется (Решение ≠ 'да'):")
#
#         if not failed_results:
#             print("  • Таких каналов нет.")
#         else:
#             for r in failed_results:
#                 seg = r.get("Сегмент")
#                 ch_name = r.get("Канал")
#                 calc_clients = r.get("calc_clients", 0)
#                 reason = r.get("Пояснение", "без пояснения")
#                 print(f"\n🔹 Канал: {ch_name}")
#                 print(f"  • Сегмент: {seg}")
#                 print(f"  • Клиентов в сегменте: {calc_clients:,.0f}")
#                 print(f"  • Причина отказа: {reason}")
#
#         # 4. Служебная информация
#         print(f"\n📊 Обработано записей после фильтров: {filtered_count}")
#         print("\n" + "=" * 50 + "\n")
#
#
# def main():
#     try:
#         agent = PotentialCalculationAgent()
#         agent.run_interactive()
#     except KeyboardInterrupt:
#         print("\n\n❌ Программа прервана пользователем")
#     except Exception as e:
#         print(f"\n❌ Произошла ошибка: {e}")
#
#
# if __name__ == "__main__":
#     main()
