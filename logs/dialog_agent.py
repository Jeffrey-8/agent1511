# # dialog_agent.py
# import json
# from dataclasses import dataclass, field
# from typing import Dict, Any, List, Optional
#
# from core_agent import CoreAnalyticsAgent
# from gigachat_client import GigaClient
#
#
# @dataclass
# class SessionState:
#     filters: Dict[str, List[str]] = field(default_factory=lambda: {
#         "industries": [],
#         "revenue": [],
#         "staff": [],
#         "tb": [],
#     })
#     segment_params: Dict[str, Dict[str, float]] = field(default_factory=lambda: {})
#     product_type: str = "Коробка"
#     last_results: Optional[Dict[str, Any]] = None
#     history: List[str] = field(default_factory=list)  # если захочешь хранить историю текстом
#
#
# class DialogAgent:
#     def __init__(self, data_directory: str):
#         self.state = SessionState()
#         self.core = CoreAnalyticsAgent(data_directory=data_directory)
#         self.llm = GigaClient()
#
#     # ==== 1. Классификация интента ====
#
#     def classify_intent(self, user_message: str) -> str:
#         """
#         Очень маленький промпт, чтобы не ломать GigaChat.
#         """
#         prompt = f"""
# <REASONING>
# Определи, что хочет пользователь. Варианты:
# - "set_filters" — задать или изменить фильтры (отрасль, выручка, штат, ТБ, продукт, доли/Kприб)
# - "show_filters" — спросить, какие сейчас фильтры
# - "run_calc" — посчитать/пересчитать потенциал
# - "reset_filters" — сбросить фильтры
# - "other" — всё остальное
# </REASONING>
# <ANSWER>
# Для фразы: "{user_message}"
# Ответь одним словом из списка: set_filters / show_filters / run_calc / reset_filters / other.
# </ANSWER>
# """
#         intent = self.llm.chat(prompt)
#         intent = intent.strip().lower()
#         if intent not in {"set_filters", "show_filters", "run_calc", "reset_filters", "other"}:
#             intent = "other"
#         return intent
#
#         # ==== 2. Обновление фильтров (используем "маленькие" промпты из агента) ====
#
#     def update_filters_from_message(self, user_message: str):
#             """
#             Использует те же промпты, что и в PotentialCalculationAgent:
#             - отрасли (industries)
#             - выручка (revenue)
#             - штат (staff)
#             - территориальные банки (tb)
#             - тип продукта (product_type)
#             - параметры расчёта (segment_params: доля и Кприб по сегментам)
#             """
#
#             # 1. Отрасли (industries) — определяем ОКВЭД, обрезаем к формату XX.X
#             prompt_industries = f"""
#             <REASONING>
#             Запрос пользователя: "{user_message}"
#
#             Твоя задача:
#             1) Определить предполагаемый вид деятельности организации.
#             2) Найти релевантные коды ОКВЭД 2.
#             3) Привести их к формату **класс.подкласс = XX.X**:
#                - только 4 символа: 2 цифры, точка, 1 цифра.
#                - например: "47.1", "56.3", "62.0", "10.2".
#
#             Правила:
#             - Если модель находит длинный код ("62.01", "56.10.1", "47.19.2") → привести к формату:
#                 "62.01" → "62.0"
#                 "56.10.1" → "56.1"
#                 "47.19.2" → "47.1"
#             - Если деятельность определить невозможно — вернуть пустой массив.
#
#             Верни строго JSON вида:
#             {{
#             "industries": ["56.1", "47.1"]
#             }}
#             или если не найдено:
#             {{
#             "industries": []
#             }}
#             </REASONING>
#             <ANSWER>
#             Ответь только JSON без пояснений.
#             </ANSWER>
#             """
#             try:
#                 ans = self.llm.chat(prompt_industries)
#                 data = json.loads(ans)
#                 industries_raw = data.get("industries", [])
#             except Exception:
#                 industries_raw = []
#
#             # пост-обработка: принудительно приводим к формату XX.X
#             industries = []
#             for code in industries_raw:
#                 # оставляем только цифры и точки
#                 clean = "".join(ch for ch in code if ch.isdigit() or ch == ".")
#                 parts = clean.split(".")
#                 if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
#                     # формируем XX.X
#                     industries.append(f"{parts[0]}.{parts[1][0]}")
#                 # если код слишком странный — пропускаем
#
#             if industries:
#                 industries = list(set(industries))  # убираем дубли
#                 self.state.filters["industries"] = industries
#
#             # 2. Выручка (revenue)
#             prompt_revenue = f"""
#     <REASONING>
#     Запрос пользователя: "{user_message}"
#
#     Задача: Найди упоминания о выручке и сопоставь с категориями.
#
#     Справочник выручки:
#     - "Менее 1 млн.р."
#     - "1-10 млн.р."
#     - "10-120 млн.р."
#     - "120-800 млн.р."
#     - "Более 800 млн.р."
#
#     Правила сопоставления:
#     - "выручка 5 млн" → "1-10 млн.р."
#     - "выручка 50 млн" → "10-120 млн.р."
#     - "оборот 100-500 млн" → ["10-120 млн.р."]
#     - "доход менее 1 млн" → "Менее 1 млн.р."
#     - "более 1 млрд" → "Более 800 млн.р."
#
#     Верни ТОЛЬКО JSON объект: {{ "revenue": [...] }}.
#     Если не смог определить категорию — верни {{ "revenue": [] }}.
#     </REASONING>
#     <ANSWER>
#     Ответь JSON-объектом.
#     </ANSWER>
#     """
#             try:
#                 ans = self.llm.chat(prompt_revenue)
#                 data = json.loads(ans)
#                 revenue = data.get("revenue", [])
#             except Exception:
#                 revenue = []
#
#             if revenue:
#                 self.state.filters["revenue"] = revenue
#
#             # 3. Штат (staff)
#             prompt_staff = f"""
#     <REASONING>
#     Запрос пользователя: "{user_message}"
#
#     Задача: Найди упоминания о количестве сотрудников и сопоставь с категориями.
#
#     Справочник штата:
#     - 1 человек → "1 чел."
#     - 2-5 человек → "2-5 чел."
#     - 6-30 человек → "6-30 чел."
#     - 31-100 человек → "31-100 чел."
#     - более 100 человек → "Более 100 чел."
#
#     Верни ТОЛЬКО JSON объект: {{ "staff": [...] }}.
#     Если в запросе нет упоминания о кол-ве сотрудников — верни {{ "staff": [] }}.
#     </REASONING>
#     <ANSWER>
#     Ответь JSON-объектом.
#     </ANSWER>
#     """
#             try:
#                 ans = self.llm.chat(prompt_staff)
#                 data = json.loads(ans)
#                 staff = data.get("staff", [])
#             except Exception:
#                 staff = []
#
#             if staff:
#                 self.state.filters["staff"] = staff
#
#             # 4. Территориальные банки (tb)
#             prompt_tb = f"""
#     <REASONING>
#     Запрос пользователя: "{user_message}"
#
#     Задача: Найди упоминания о регионах или территориальных банках и сопоставь с ТБ.
#
#     Справочник ТБ (используй ТОЛЬКО эти коды):
#     - "ЦА"
#     - "ББ"
#     - "ВВБ"
#     - "ДВБ"
#     - "МБ"
#     - "ПБ"
#     - "СЗБ"
#     - "СибБ"
#     - "СРБ"
#     - "УБ"
#     - "ЦЧБ"
#     - "ЮЗБ"
#
#     Примеры:
#     - "Москва", "Московская область" → "МБ"
#     - "Урал", "Екатеринбург", "Челябинск" → "УБ"
#     - "Сибирь", "Новосибирск", "Красноярск" → "СибБ"
#     - "Санкт-Петербург", "Ленинградская область" → "СЗБ"
#
#     Верни ТОЛЬКО JSON объект: {{ "tb": [...] }}.
#     Если регион определить нельзя — верни {{ "tb": [] }}.
#     </REASONING>
#     <ANSWER>
#     Ответь JSON-объектом.
#     </ANSWER>
#     """
#             try:
#                 ans = self.llm.chat(prompt_tb)
#                 data = json.loads(ans)
#                 tb = data.get("tb", [])
#             except Exception:
#                 tb = []
#
#             if tb:
#                 self.state.filters["tb"] = tb
#
#             # 5. Тип продукта (product_type)
#             prompt_product = f"""
#     <REASONING>
#     Запрос пользователя: "{user_message}"
#
#     Задача: Определи тип продукта - "Коробка" или "Кастом".
#
#     Правила:
#     - По умолчанию: "Коробка".
#     - Используй "Кастом" только если явно указано: "кастом", "кастомный", "индивидуальный", "персональный".
#
#     Верни ТОЛЬКО JSON: {{ "product_type": "Коробка" }} или {{ "product_type": "Кастом" }}.
#     </REASONING>
#     <ANSWER>
#     Ответь JSON-объектом.
#     </ANSWER>
#     """
#             try:
#                 ans = self.llm.chat(prompt_product)
#                 data = json.loads(ans)
#                 product_type = data.get("product_type")
#             except Exception:
#                 product_type = None
#
#             if product_type in {"Коробка", "Кастом"}:
#                 self.state.product_type = product_type
#
#             # 6. Параметры расчёта (segment_params через mmb_dolya/kpr и т.п.)
#             prompt_params = f"""
#     <REASONING>
#     Запрос пользователя: "{user_message}"
#
#     Задача: Найди числовые параметры для расчета.
#
#     Параметры (используй значения по умолчанию, если не указано явно):
#     - mmb_dolya: доля владения для ММБ (по умолчанию 6.0)
#     - mmb_kpr: Кприб для ММБ (по умолчанию 15.0)
#     - other_dolya: доля владения для других сегментов (по умолчанию 10.0)
#     - other_kpr: Кприб для других сегментов (по умолчанию 20.0)
#
#     Верни ТОЛЬКО JSON вида:
#     {{
#       "mmb_dolya": 6.0,
#       "mmb_kpr": 15.0,
#       "other_dolya": 10.0,
#       "other_kpr": 20.0
#     }}
#     </REASONING>
#     <ANSWER>
#     Ответь JSON-объектом.
#     </ANSWER>
#     """
#             try:
#                 ans = self.llm.chat(prompt_params)
#                 data = json.loads(ans)
#             except Exception:
#                 data = {}
#
#             # если модель что-то вернула — обновляем segment_params
#             if data:
#                 mmb_dolya = float(data.get("mmb_dolya", 6.0))
#                 mmb_kpr = float(data.get("mmb_kpr", 15.0))
#                 other_dolya = float(data.get("other_dolya", 10.0))
#                 other_kpr = float(data.get("other_kpr", 20.0))
#
#                 self.state.segment_params = {
#                     "ММБ": {"dolya": mmb_dolya, "kpr": mmb_kpr},
#                     "КСБ": {"dolya": other_dolya, "kpr": other_kpr},
#                     "СКМ": {"dolya": other_dolya, "kpr": other_kpr},
#                     "РГС": {"dolya": other_dolya, "kpr": other_kpr},
#                     # немного усиливаем KeyClients относительно остальных
#                     "KeyClients": {"dolya": other_dolya + 5.0, "kpr": other_kpr + 10.0},
#                 }
#
#     # ==== 3. Показ текущих фильтров ====
#
#     def describe_current_filters(self) -> str:
#         f = self.state.filters
#         seg = self.state.segment_params
#         lines = []
#
#         lines.append("Текущие фильтры:")
#         lines.append(f"- Отрасли (ОКВЭД): {f['industries'] or 'все'}")
#         lines.append(f"- Выручка: {f['revenue'] or 'все'}")
#         lines.append(f"- Штат: {f['staff'] or 'все'}")
#         lines.append(f"- ТБ: {f['tb'] or 'все'}")
#         lines.append(f"- Тип продукта: {self.state.product_type}")
#         if seg:
#             lines.append(f"- Параметры сегментов: {seg}")
#         else:
#             lines.append("- Параметры сегментов: по умолчанию/не заданы")
#
#         return "\n".join(lines)
#
#     # ==== 4. Запуск расчёта ====
#
#     def run_calculation(self) -> str:
#         """
#         Запуск расчёта потенциала + форматированный текстовый вывод.
#         """
#         # Если не заданы параметры сегментов – ставим дефолтные
#         if not self.state.segment_params:
#             self.state.segment_params = {
#                 "ММБ": {"dolya": 6.0, "kpr": 15.0},
#                 "КСБ": {"dolya": 10.0, "kpr": 20.0},
#                 "СКМ": {"dolya": 10.0, "kpr": 20.0},
#                 "РГС": {"dolya": 8.0, "kpr": 18.0},
#                 "KeyClients": {"dolya": 15.0, "kpr": 30.0},
#             }
#
#         result = self.core.run_calculation(
#             filters=self.state.filters,
#             segment_params=self.state.segment_params,
#             product_type=self.state.product_type,
#         )
#         self.state.last_results = result
#
#         # Формируем человеко-читаемый отчёт
#         text_report = self.format_results(result)
#         return text_report
#
#     def format_results(self, results: Dict[str, Any]) -> str:
#         """
#         Форматированный текстовый отчёт по результатам расчёта.
#         Аналог того, что мы делали в _display_results, только в виде строки.
#         """
#         lines: List[str] = []
#
#         segment_metrics = results.get("segment_metrics", {})
#         potential_results = results.get("potential_results", [])
#         filtered_count = results.get("filtered_records_count", 0)
#
#         lines.append("📊 РЕЗУЛЬТАТЫ РАСЧЁТА")
#         lines.append("=" * 50)
#
#         # Шаг 1 — по сегментам
#         lines.append("\n📌 Шаг 1. Аналитика по сегментам")
#
#         if not segment_metrics:
#             lines.append("Нет сегментов после фильтрации.")
#         else:
#             for segment, metrics in segment_metrics.items():
#                 if segment == "Неизвестно":
#                     continue
#                 lines.append(f"\n🔹 Сегмент: {segment}")
#                 lines.append(f"  • Рынок: {metrics.get('Рынок', 0):,.0f}")
#                 lines.append(f"  • Активные клиенты: {metrics.get('Активные клиенты Банка', 0):,.0f}")
#                 lines.append(f"  • Спящие и не клиенты: {metrics.get('Спящие клиенты и не клиенты Банка', 0):,.0f}")
#                 lines.append(
#                     f"  • Средняя выручка: {metrics.get('Средняя выручка, млн. р.', 0):.3f} млн ₽"
#                 )
#                 lines.append(
#                     f"  • Среднее число сотрудников: {metrics.get('Среднее кол-во сотрудников', 0)}"
#                 )
#                 avg_check = metrics.get("avg_check")
#                 if avg_check is not None:
#                     lines.append(f"  • Средний чек (оценка): {avg_check:,.0f} ₽")
#
#         # Шаг 2 — по каналам
#         lines.append("\n" + "-" * 50)
#         lines.append("📌 Шаг 2. Расчёт потенциала по каналам")
#
#         if not potential_results:
#             lines.append("Нет результатов по каналам.")
#             lines.append(f"\n📊 Обработано записей после фильтров: {filtered_count}")
#             return "\n".join(lines)
#
#         successful_results = [r for r in potential_results if r.get("Решение") == "да"]
#         failed_results = [r for r in potential_results if r.get("Решение") != "да"]
#
#         # Каналы с "да"
#         lines.append("\n✅ Каналы, где продажа возможна (Решение = 'да'):")
#
#         if not successful_results:
#             lines.append("  • Нет каналов с решением 'да'.")
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
#                 avg_check = None
#                 if seg in segment_metrics:
#                     avg_check = segment_metrics[seg].get("avg_check")
#
#                 lines.append(f"\n🔹 Канал: {ch_name}")
#                 lines.append(f"  • Сегмент: {seg}")
#                 lines.append(f"  • Клиентов в сегменте: {calc_clients:,.0f}")
#                 if avg_check is not None:
#                     lines.append(f"  • Средний чек сегмента: {avg_check:,.0f} ₽")
#                 lines.append(
#                     f"  • Потенциал (с учётом утилизации): {potential_amount:.3f} млн ₽"
#                 )
#                 lines.append(f"  • Ставка AB: {rate_ab:.1f}%")
#                 lines.append(f"  • Сумма AB: {amount_ab:.3f} млн ₽")
#                 lines.append(f"  • ЧКД: {amount_chkd:.3f} млн ₽")
#                 lines.append(f"  • Прибыль: {revenue_val:.3f} млн ₽")
#                 lines.append(f"  🏆 Итоговый потенциал по каналу: {total:.3f} млн ₽")
#
#             lines.append(
#                 f"\n💰 Суммарный потенциал по каналам с решением 'да': {total_potential:.3f} млн ₽"
#             )
#
#         # Каналы с "нет"
#         lines.append("\n❌ Каналы, где продажа НЕ рекомендуется (Решение ≠ 'да'):")
#
#         if not failed_results:
#             lines.append("  • Таких каналов нет.")
#         else:
#             for r in failed_results:
#                 seg = r.get("Сегмент")
#                 ch_name = r.get("Канал")
#                 calc_clients = r.get("calc_clients", 0)
#                 reason = r.get("Пояснение", "без пояснения")
#                 lines.append(f"\n🔹 Канал: {ch_name}")
#                 lines.append(f"  • Сегмент: {seg}")
#                 lines.append(f"  • Клиентов в сегменте: {calc_clients:,.0f}")
#                 lines.append(f"  • Причина отказа: {reason}")
#
#         lines.append(f"\n📊 Обработано записей после фильтров: {filtered_count}")
#
#         return "\n".join(lines)
#
#
#     # ==== 5. Основной метод: обработать сообщение пользователя ====
#
#     def handle_message(self, user_message: str) -> str:
#         intent = self.classify_intent(user_message)
#
#         if intent == "set_filters":
#             self.update_filters_from_message(user_message)
#             return "Параметры обновил. Можешь спросить 'какие сейчас фильтры' или 'посчитай'."
#
#         elif intent == "show_filters":
#             return self.describe_current_filters()
#
#         elif intent == "run_calc":
#             return self.run_calculation()
#
#         elif intent == "reset_filters":
#             self.state = SessionState()
#             return "Все фильтры и параметры сброшены."
#
#         else:
#             # Прочие вопросы — можно просто переслать LLM с контекстом текущих фильтров
#             context = self.describe_current_filters()
#             prompt = f"""
# <REASONING>
# Пользователь задаёт общий вопрос. У тебя есть текущий контекст фильтров.
# Сформулируй полезный ответ, можешь подсказать, что можно сделать дальше.
# </REASONING>
# <ANSWER>
# Контекст:
# {context}
#
# Вопрос:
# {user_message}
# </ANSWER>
# """
#             return self.llm.chat(prompt)
