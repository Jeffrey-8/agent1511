# potential_agent.py
import json
import logging
import re
from typing import Dict, Any, List, Union

from langchain_core.messages import HumanMessage, AIMessage

from analytics_engine import calculate_potential_full_pipeline
from llm_client import GigaChatLLM

logger = logging.getLogger(__name__)

DEFAULT_AVG_MMB = 500_000.0
DEFAULT_AVG_OTHER = 500_000.0
DEFAULT_K = 15.0
DEFAULT_OWN_SHARE = 10.0

class PotentialCalculationAgent:
    """
    Агент, который:
    - обновляет фильтры и параметры расчёта из сообщений пользователя,
    - строит ответы пользователю,
    - запускает пайплайн расчёта потенциала.
    """

    def __init__(self, llm: GigaChatLLM, data_dir: str):
        self.llm = llm
        self.data_dir = data_dir

    # ==== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==============================================

    def _extract_answer_block(self, text: str) -> str:
        """
        Вырезает содержимое тега <ANSWER>...</ANSWER>.
        Если тегов нет — возвращает исходный текст.
        """
        pattern = r"<ANSWER>(.*?)</ANSWER>"
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return text.strip()

    # def _safe_json_loads(self, text: str):
    #     text = (text or "").strip()
    #
    #     # 1. Сначала пытаемся обычный json.loads на весь текст
    #     try:
    #         return json.loads(text)
    #     except Exception:
    #         pass
    #
    #     # 2. Вырезаем все {...} блоки и пробуем их по очереди (с конца)
    #     candidates = re.findall(r"\{[\s\S]*?\}", text)
    #     for raw in reversed(candidates):
    #         cleaned = raw.strip()
    #
    #         # если внутри есть плейсхолдеры вида <...> — это явно шаблон, пропускаем
    #         if "<" in cleaned and ">" in cleaned:
    #             continue
    #
    #         try:
    #             return json.loads(cleaned)
    #         except Exception:
    #             continue
    #
    #     # 3. Если так и не смогли — логируем и возвращаем None
    #     logger.warning(f"[safe_json] не удалось распарсить JSON даже после перебора: {text!r}")
    #     return None

    def _safe_json_loads(self, raw: str):
        """
        Надёжно достаём JSON из ответа LLM.

        Поддерживаем случаи:
        1) Ответ = чистый JSON: { ... }
        2) Ответ содержит <REASONING>...</REASONING><ANSWER>{...}</ANSWER>
        3) Ответ содержит <ANSWER>{...} БЕЗ закрывающего </ANSWER>
        4) Ответ - просто текст с вкраплённым JSON { ... }.

        Стратегия:
        - если есть <ANSWER>...</ANSWER> — берём то, что внутри.
        - иначе работаем со всем текстом.
        - далее ищем первую '{' и последнюю '}' и пробуем json.loads().
        """
        if not raw:
            return None

        text = str(raw).strip()
        if not text:
            return None

        # 1. Если есть <ANSWER>...</ANSWER> — забираем его содержимое
        m = re.search(r"<ANSWER>(.*?)</ANSWER>", text, re.DOTALL | re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
        else:
            # 2. Если закрывающего тега нет (как в твоём случае) —
            #    работаем со всем текстом и вырезаем { ... }
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                logger.warning(f"[safe_json] не нашёл JSON-скобок в ответе: {text!r}")
                return None
            candidate = text[start : end + 1].strip()

        try:
            data = json.loads(candidate)
            logger.info(f"[safe_json] parsed={data!r}")
            return data
        except Exception as e:
            logger.warning(f"[safe_json] не удалось распарсить JSON: {candidate!r}; err={e}")
            return None


    # ==== 1. Вспомогательные методы для фильтров ==============================

    def is_show_filters_request(self, text: str) -> bool:
        """
        Определяем, что пользователь хочет посмотреть текущие фильтры.
        """
        t = text.lower()
        triggers = [
            "покажи фильтры",
            "какие фильтры",
            "какие сейчас фильтры",
            "выведи фильтры",
            "что отфильтровали",
            "что сейчас фильтруем",
        ]
        return any(tr in t for tr in triggers)

    def format_filters_for_user(self, state) -> str:
        """
        Человекочитаемый вывод текущих фильтров и параметров.
        """

        filters = state.get("filters") or {}
        industries = filters.get("industries") or []
        revenue = filters.get("revenue") or []
        staff = filters.get("staff") or []
        tb = filters.get("tb") or []
        product_type = state.get("product_type", "Коробка") or "Коробка"

        lines = []
        lines.append("📌 Текущие применённые фильтры и параметры:")

        # 1. Отрасли
        if industries:
            lines.append(f"• Отрасли (ОКВЭД): {industries}")
        else:
            lines.append("• Отрасли (ОКВЭД): не заданы (берём все отрасли)")

        # 2. Выручка
        if revenue:
            lines.append(f"• Диапазоны выручки: {revenue}")
        else:
            lines.append("• Диапазоны выручки: не заданы (любой уровень выручки)")

        # 3. Штат
        if staff:
            lines.append(f"• Размер штата: {staff}")
        else:
            lines.append("• Размер штата: не задан (любой размер штата)")

        # 4. ТБ
        if tb:
            lines.append(f"• Территориальные банки (ТБ): {tb}")
        else:
            lines.append("• Территориальные банки (ТБ): не задан (все регионы)")

        # 5. Тип продукта
        lines.append(f"• Тип продукта: {product_type}")

        # 6. Параметры расчёта (новый блок)
        avg_mmb = state.get("avg_amount_mmb")
        avg_other = state.get("avg_amount_other")
        k = state.get("k")
        own_share = state.get("own_share")

        def fmt_rub(val: float) -> str:
            return f"{int(val):,} руб.".replace(",", " ")

        def fmt_pct(val: float) -> str:
            # можно с одним знаком после запятой, но для простоты — целое
            return f"{val:.1f}%".rstrip("0").rstrip(".")

        lines.append("• Параметры расчёта:")

        if avg_mmb is None:
            lines.append(
                f"  • Средний чек в ММБ: не задан (по умолчанию {fmt_rub(DEFAULT_AVG_MMB)})"
            )
        else:
            lines.append(f"  • Средний чек в ММБ: {fmt_rub(avg_mmb)}")

        if avg_other is None:
            lines.append(
                f"  • Средний чек в других сегментах: не задан (по умолчанию {fmt_rub(DEFAULT_AVG_OTHER)})"
            )
        else:
            lines.append(f"  • Средний чек в других сегментах: {fmt_rub(avg_other)}")

        if k is None:
            lines.append(
                f"  • Кприб (k): не задан (по умолчанию {fmt_pct(DEFAULT_K)})"
            )
        else:
            lines.append(f"  • Кприб (k): {fmt_pct(k)}")

        if own_share is None:
            lines.append(
                f"  • Доля владения (own_share): не задана (по умолчанию {fmt_pct(DEFAULT_OWN_SHARE)})"
            )
        else:
            lines.append(f"  • Доля владения (own_share): {fmt_pct(own_share)}")

        return "\n".join(lines)

    # ==== 2. Обновление фильтров (маленькие промпты) ==========================

    def update_filters_from_message(self, state: Dict[str, Any], user_message: str) -> None:
        """
        Использует промпты:
        - отрасли (industries)
        - выручка (revenue)
        - штат (staff)
        - территориальные банки (tb)
        - тип продукта (product_type)
        - параметры расчёта (segment_params: доля и Кприб по сегментам)

        Обновляет:
        - state["filters"]["industries"/"revenue"/"staff"/"tb"]
        - state["product_type"]
        - state["segment_params"]
        """

        if "filters" not in state or state["filters"] is None:
            state["filters"] = {}
        filters = state["filters"]
        # 1. Отрасли (industries) — определяем ОКВЭД, обрезаем к формату XX.X
        # 1. Отрасли (industries) — определяем ОКВЭД, обрезаем к формату XX.X
        prompt_industries = f"""
        Ты модуль, который извлекает отрасли (ОКВЭД 2) из пользовательского запроса.

        Формат работы:
        1) Внутри <REASONING> ты можешь думать и расписывать логику.
        2) Внутри <ANSWER> ты ДОЛЖЕН вернуть ЧИСТЫЙ JSON-объект.

        Твоя задача:
        1) Определить вид деятельности по запросу пользователя.
        2) Найти релевантные коды ОКВЭД 2.
        3) Привести их к формату класс.подкласс = XX.X:
           - 2 цифры, точка, 1 цифра.
           - например: "47.1", "56.3", "62.0", "10.2".

        ОСОБЫЕ ПРАВИЛА ДЛЯ ОБЩИХ ЗАПРОСОВ:

        - Если в запросе встречаются слова "промышленность", "промышленный сектор",
          и НЕТ других уточнений про конкретный вид деятельности,
          ты обязан вернуть ШИРОКИЙ набор кодов, соответствующих промышленности.
          Пример такого набора (можешь немного корректировать, но он не должен быть пустым):
          [
            "10.1",
            "14.1",
            "16.1",
            "16.2",
            "20.0",
            "24.0",
            "25.0",
            "29.0",
            "30.0"
          ]
          В этом случае НЕЛЬЗЯ возвращать пустой массив.

        ОБЩИЕ ПРАВИЛА:

        - Если модель находит длинный код ("62.01", "56.10.1", "47.19.2") → приведи к формату:
            "62.01" → "62.0"
            "56.10.1" → "56.1"
            "47.19.2" → "47.1"
        - Пустой массив допустим ТОЛЬКО если запрос вообще НЕ относится к видам деятельности
          (например, что-то про погоду, личную жизнь и т.п.).

        Запрос пользователя:
        "{user_message}"

        <REASONING>
        Проанализируй запрос и определи виды деятельности и примерные ОКВЭД.
        Если запрос общим словом описывает крупный сектор ("промышленность"),
        верни широкий набор кодов, а не пустой список.
        </REASONING>

        <ANSWER>
        {{
          "industries": []
        }}
        </ANSWER>
                """.strip()

        try:
            ans_raw = self.llm.chat(prompt_industries)
            logger.info(f"[filters][industries] raw_answer={ans_raw!r}")
            data = self._safe_json_loads(ans_raw) or {}
            industries_raw = data.get("industries", [])
        except Exception as e:
            logger.exception(f"Не удалось разобрать industries из ответа LLM: {e}")
            industries_raw = []

        # пост-обработка: приводим к формату XX.X
        industries: List[str] = []
        for code in industries_raw:
            if not isinstance(code, str):
                code = str(code)

            clean = "".join(ch for ch in code if ch.isdigit() or ch == ".")
            if not clean:
                continue

            parts = clean.split(".")

            # вариант 1: только класс → XX.0
            if len(parts) == 1 and parts[0].isdigit():
                industries.append(f"{parts[0]}.0")
                continue

            # вариант 2: класс.подкласс → XX.X
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                industries.append(f"{parts[0]}.{parts[1][0]}")
                continue

        if industries:
            industries = list(set(industries))  # убираем дубли
            state["filters"]["industries"] = industries
            logger.info(f"[filters] industries={industries}")

        # 2. Выручка (revenue)
        prompt_revenue = f"""
Ты извлекаешь фильтры из пользовательских запросов.

Сначала подумай и запиши рассуждения внутри тегов <REASONING>...</REASONING>.
Затем запиши итоговый JSON-ответ внутри тегов <ANSWER>...</ANSWER>.

<REASONING>
Запрос пользователя: "{user_message}"

Задача: Найди упоминания о выручке и сопоставь с категориями.

Справочник выручки:
- "Менее 1 млн.р."
- "1-10 млн.р."
- "10-120 млн.р."
- "120-800 млн.р."
- "Более 800 млн.р."

Примеры:
- "выручка 5 млн" → "1-10 млн.р."
- "выручка 50 млн" → "10-120 млн.р."
- "оборот 100-500 млн" → ["10-120 млн.р."]
- "доход менее 1 млн" → "Менее 1 млн.р."
- "более 1 млрд" → "Более 800 млн.р."
</REASONING>

<ANSWER>
{{
  "revenue": []
}}
</ANSWER>
        """.strip()

        try:
            ans_raw = self.llm.chat(prompt_revenue)
            logger.info(f"[filters][revenue] raw_answer={ans_raw}")
            data = self._safe_json_loads(ans_raw) or {}
            revenue = data.get("revenue", [])
        except Exception as e:
            logger.exception(f"Не удалось разобрать revenue из ответа LLM: {e}")
            revenue = []

        if revenue:
            filters["revenue"] = revenue
            logger.info(f"[filters] revenue={revenue}")

        # 3. Штат (staff)
        # 3. Штат (staff)
        prompt_staff = f"""
    Ты модуль, который извлекает категорию количества сотрудников из запроса.

    Сначала подумай и запиши рассуждения внутри тегов <REASONING>...</REASONING>.
    Затем запиши итоговый JSON-ответ внутри тегов <ANSWER>...</ANSWER>.

    Справочник штата:
    - 1 человек → "1 чел."
    - 2-5 человек → "2-5 чел."
    - 6-30 человек → "6-30 чел."
    - 31-100 человек → "31-100 чел."
    - более 100 человек → "Более 100 чел."

    Требования к ответу:
    - Верни ТОЛЬКО JSON-объект с ключом "staff".
    - Значение "staff" — массив строк с названиями категорий из справочника.
    - Примеры корректных ответов:
      {{
        "staff": ["Более 100 чел."]
      }}
      либо
      {{
        "staff": []
      }}
      если в запросе нет информации о количестве сотрудников.

    Запрос пользователя:
    "{user_message}"

    <REASONING>
    Найди упоминания о численности штата и сопоставь их с категориями из справочника.
    </REASONING>

    <ANSWER>
    {{
      "staff": []
    }}
    </ANSWER>
            """.strip()

        try:
            ans_raw = self.llm.chat(prompt_staff)
            logger.info(f"[filters][staff] raw_answer={ans_raw!r}")
            data = self._safe_json_loads(ans_raw) or {}
            staff_raw = data.get("staff", [])
        except Exception as e:
            logger.exception(f"Не удалось разобрать staff из ответа LLM: {e}")
            staff_raw = []

        # Нормализуем к списку строк категорий
        staff_categories: List[str] = []

        if isinstance(staff_raw, list):
            for item in staff_raw:
                if isinstance(item, str):
                    staff_categories.append(item.strip())
                elif isinstance(item, dict):
                    cat = item.get("category")
                    if isinstance(cat, str) and cat.strip():
                        staff_categories.append(cat.strip())

        staff_categories = list({c for c in staff_categories if c})

        if staff_categories:
            filters["staff"] = staff_categories
            logger.info(f"[filters] staff={staff_categories}")

            # 4. Территориальные банки (tb) — только через LLM, без safe_json

        prompt_tb = f"""
    Ты извлекаешь территориальные банки (ТБ) из текста запроса.

    Твой формат ответа:
    1) Сначала рассуждения в тегах <REASONING>...</REASONING>.
    2) Потом ЧИСТЫЙ JSON в тегах <ANSWER>...</ANSWER>, без комментариев и лишнего текста.

    Важно:
    - Верни ТОЛЬКО JSON-объект с ключом "tb".
    - Значение "tb" — это массив строк с кодами ТБ.
    - Используй ТОЛЬКО коды из справочника.
    - Если в запросе явно встречается "Москва" или "Московская область",
      ОБЯЗАТЕЛЬНО включи в массив код "МБ".
    - Если в запросе нет регионов и ты не можешь определить ТБ — верни пустой массив.

    Справочник ТБ:
    - "ЦА", "ББ", "ВВБ", "ДВБ", "МБ", "ПБ",
      "СЗБ", "СибБ", "СРБ", "УБ", "ЦЧБ", "ЮЗБ"

    Запрос пользователя:
    "{user_message}"

    <REASONING>
    Проанализируй запрос и определи, к каким регионам он относится,
    затем сопоставь их с кодами ТБ.
    </REASONING>

    <ANSWER>
    {{
      "tb": []
    }}
    </ANSWER>
            """.strip()

        try:
            ans_raw = self.llm.chat(prompt_tb)
            # ans_raw здесь уже ДОЛЖЕН быть только JSON из <ANSWER>, без REASONING
            logger.info(f"[filters][tb] ans_raw_for_parse={ans_raw!r}")
            data = self._safe_json_loads(ans_raw) or {}
            tb = data.get("tb", [])
        except Exception as e:
            logger.exception(f"Не удалось разобрать tb из ответа LLM: {e}")
            tb = []

        if tb:
            filters["tb"] = tb
            logger.info(f"[filters] tb={tb}")

        # 5. Тип продукта (product_type)
        prompt_product = f"""
Ты извлекаешь фильтры из пользовательских запросов.

Сначала подумай и запиши рассуждения внутри тегов <REASONING>...</REASONING>.
Затем запиши итоговый ответ внутри тегов <ANSWER>...</ANSWER>.

<REASONING>
Запрос пользователя: "{user_message}"

Задача: Определи тип продукта - "Коробка" или "Кастом".

Правила:
- По умолчанию: "Коробка".
- Используй "Кастом" только если явно указано: "кастом", "кастомный", "индивидуальный", "персональный".
</REASONING>

<ANSWER>
{{
  "product_type": "Коробка"
}}
</ANSWER>
        """.strip()

        product_type = None
        try:
            ans_raw = self.llm.chat(prompt_product)
            logger.info(f"[filters][product_type] raw_answer={ans_raw}")
            data = self._safe_json_loads(ans_raw) or {}

            if isinstance(data, dict):
                product_type = data.get("product_type")
            else:
                # если модель вдруг вернула просто строку
                text_val = self._extract_answer_block(ans_raw).strip().strip('"').strip("'")
                if text_val in {"Коробка", "Кастом"}:
                    product_type = text_val
        except Exception as e:
            logger.exception(f"Не удалось разобрать product_type из ответа LLM: {e}")
            product_type = None

        if product_type in {"Коробка", "Кастом"}:
            state["product_type"] = product_type
            logger.info(f"[filters] product_type={product_type}")

        # 6. Параметры расчёта (segment_params)
        prompt_params = f"""
Ты извлекаешь параметры расчёта из пользовательских запросов.

Сначала подумай и запиши рассуждения внутри тегов <REASONING>...</REASONING>.
Затем запиши итоговый JSON-ответ внутри тегов <ANSWER>...</ANSWER>.

Важно:
- Итоговый ответ в <ANSWER> должен быть СТРОГО валидным JSON.
- Только один JSON-объект, без пояснений.
- Все ключи и строки в двойных кавычках.
- Без комментариев, без лишних запятых в конце.

<REASONING>
Запрос пользователя: "{user_message}"

Задача: Найди числовые параметры для расчета.

Параметры (используй значения по умолчанию, если не указано явно):
- mmb_dolya: доля владения для ММБ (по умолчанию 6.0)
- mmb_kpr: Кприб для ММБ (по умолчанию 15.0)
- other_dolya: доля владения для других сегментов (по умолчанию 10.0)
- other_kpr: Кприб для других сегментов (по умолчанию 20.0)
</REASONING>

<ANSWER>
{{
  "mmb_dolya": 6.0,
  "mmb_kpr": 15.0,
  "other_dolya": 10.0,
  "other_kpr": 20.0
}}
</ANSWER>
        """.strip()

        try:
            ans_raw = self.llm.chat(prompt_params)
            logger.info(f"[filters][segment_params] raw_answer={ans_raw}")
            data = self._safe_json_loads(ans_raw) or {}
        except Exception as e:
            logger.exception(f"Не удалось разобрать segment_params из ответа LLM: {e}")
            data = {}

        if data:
            mmb_dolya = float(data.get("mmb_dolya", 6.0))
            mmb_kpr = float(data.get("mmb_kpr", 15.0))
            other_dolya = float(data.get("other_dolya", 10.0))
            other_kpr = float(data.get("other_kpr", 20.0))

            state["segment_params"] = {
                "ММБ": {"dolya": mmb_dolya, "kpr": mmb_kpr},
                "КСБ": {"dolya": other_dolya, "kpr": other_kpr},
                "СКМ": {"dolya": other_dolya, "kpr": other_kpr},
                "РГС": {"dolya": other_dolya, "kpr": other_kpr},
                "KeyClients": {"dolya": other_dolya + 5.0, "kpr": other_kpr + 10.0},
            }
            logger.info(f"[filters] segment_params={state['segment_params']}")

        logger.info(f"[filters] итоговое состояние filters={state.get('filters')}")

    # ==== 3. Логика диалога и расчёта =========================================

    def is_calculation_request(self, text: str) -> bool:
        text_low = text.lower()
        triggers = [
            "посчитай",
            "запусти расчет",
            "считай",
            "считать",
            "расчёт",
            "запусти расчёт",
            "рассчитай",
            "давай считать",
            "можно считать",
            "сделай расчет",
            "сделай расчёт",
            "начни расчет",
            "начни расчёт",
        ]
        return any(t in text_low for t in triggers)

    def build_agent_reply(self, state: Dict[str, Any], user_text: str) -> str:
        filters = state.get("filters", {})
        segment_params = state.get("segment_params", {})
        product_type = state.get("product_type", "Коробка")

        system_context = f"""
Ты помощник по расчёту потенциала продаж.

У тебя есть текущие фильтры и параметры:
- Отрасли (industries): {filters.get("industries")}
- Выручка (revenue): {filters.get("revenue")}
- Штат (staff): {filters.get("staff")}
- Территориальный банк (tb): {filters.get("tb")}
- Тип продукта: {product_type}
- Параметры сегментов (доля, Кприб): {json.dumps(segment_params, ensure_ascii=False)}

Твоя задача:
1. Уточнять недостающие фильтры, если они критичны для корректного расчёта.
2. Кратко переформулировать, какой срез рынка сейчас будет считаться.
3. Объяснять пользователю, что как только его устраивают фильтры, он может сказать "запусти расчет" или "посчитай".

Говори по-деловому, но простым языком, не более 3–4 предложений.
Последняя фраза — всегда с безусловным указанием, что для запуска расчёта нужно явно попросить об этом.
        """.strip()

        prompt = f"""
{system_context}

Сначала подумай и запиши свои рассуждения внутри тегов <REASONING>...</REASONING>.
Затем запиши короткий ответ пользователю внутри тегов <ANSWER>...</ANSWER>.

<REASONING>
Проанализируй реплику пользователя и текущие фильтры и реши, нужно ли что-то уточнить.
Реплика пользователя: "{user_text}"
</REASONING>

<ANSWER>
Сформулируй финальный ответ пользователю с учётом текущих фильтров.
Не более 3–4 предложений, по-русски.
Последней фразой обязательно укажи, что для запуска расчёта нужно явно сказать
что-то вроде "запусти расчет" или "посчитай".
</ANSWER>
        """.strip()

        ans_raw = self.llm.chat(prompt)
        answer = self._extract_answer_block(ans_raw)
        logger.info(f"[dialog] reply_answer={answer}")
        return answer

    def run_full_calculation(self, state) -> dict:
        """
        Запуск пайплайна расчета потенциала.

        Берём:
        - фильтры из state["filters"]
        - пользовательские параметры, если заданы
        - остальное — дефолты
        и сохраняем, какие параметры были взяты по умолчанию,
        чтобы потом предупредить пользователя.
        """
        filters = state.get("filters") or {}

        used_defaults = []  # сюда сложим, что именно было взято по умолчанию

        # средний чек в ММБ
        if state.get("avg_amount_mmb") is None:
            avg_amount_mmb = 500_000.0
            used_defaults.append(("avg_amount_mmb", avg_amount_mmb))
        else:
            avg_amount_mmb = float(state["avg_amount_mmb"])

        # средний чек в других сегментах
        if state.get("avg_amount_other") is None:
            avg_amount_other = 500_000.0
            used_defaults.append(("avg_amount_other", avg_amount_other))
        else:
            avg_amount_other = float(state["avg_amount_other"])

        # Кприб, %
        if state.get("k") is None:
            k = 15.0
            used_defaults.append(("k", k))
        else:
            k = float(state["k"])

        # доля владения, %
        if state.get("own_share") is None:
            own_share = 10.0
            used_defaults.append(("own_share", own_share))
        else:
            own_share = float(state["own_share"])

        product_type = state.get("product_type", "Коробка") or "Коробка"

        result = calculate_potential_full_pipeline(
            data_dir=self.data_dir,
            filters=filters,
            avg_amount_mmb=avg_amount_mmb,
            avg_amount_other=avg_amount_other,
            k=k,
            own_share=own_share,
            product_type=product_type,
        )

        # приклеиваем метаданные к результату
        result["meta"] = {
            "avg_amount_mmb": avg_amount_mmb,
            "avg_amount_other": avg_amount_other,
            "k": k,
            "own_share": own_share,
            "used_defaults": used_defaults,
        }

        return result

    def summarize_result_for_user(self, result: dict) -> str:
        """
        Витринный вывод по новой аналитике.

        Важно:
        - В расчётах используем "Рынок" как есть.
        - В тексте для пользователя "оценка рынка" = клиенты + не клиенты,
          чтобы соответствовать формулировке аналитики: Рынок = Клиент + НеКлиент.
        """
        segment_metrics = result.get("segment_metrics", {})
        rows = result.get("channel_results", [])
        filtered_count = result.get("filtered_records_count", 0)

        meta = result.get("meta", {}) or {}
        used_defaults = meta.get("used_defaults") or []

        lines: List[str] = []

        lines.append(f"✔ Расчёт завершён. В выборку попало {filtered_count} записей.\n")

        # ⚠ Предупреждение о дефолтных параметрах
        if used_defaults:
            names_map = {
                "avg_amount_mmb": "средний чек в ММБ",
                "avg_amount_other": "средний чек в других сегментах",
                "k": "Кприб, %",
                "own_share": "доля владения, %",
            }
            warn_lines = []
            for key, val in used_defaults:
                label = names_map.get(key, key)
                if key in {"k", "own_share"}:
                    warn_lines.append(f"• {label}: использовано значение по умолчанию {val}%")
                else:
                    warn_lines.append(
                        f"• {label}: использовано значение по умолчанию {int(val):,} руб.".replace(",", " "))

            lines.append("⚠ Некоторые параметры не были указаны, использованы значения по умолчанию:")
            lines.extend(warn_lines)
            lines.append(
                "Если хочешь задать их явно, напиши, например: "
                "\"средний чек в ММБ 500 тысяч, в других сегментах 800 тысяч, "
                "Кприб 15%, доля владения 10%\".\n"
            )

        # агрегируем по сегментам сумму amount_ab только по "да"
        seg_amount: Dict[str, float] = {}
        seg_has_yes: Dict[str, bool] = {}

        for r in rows:
            seg = r["Сегмент"]
            if r.get("Решение") == "да":
                seg_amount[seg] = seg_amount.get(seg, 0.0) + float(r.get("amount_ab", 0.0))
                seg_has_yes[seg] = True
            else:
                seg_has_yes.setdefault(seg, False)

        lines.append("📊 Потенциал по сегментам (суммарное значение дохода сегмента по всем каналам)")

        all_segs = sorted(seg_has_yes.keys(), key=lambda s: seg_amount.get(s, 0.0), reverse=True)

        for seg in all_segs:
            if not seg_has_yes.get(seg):
                lines.append(f"• {seg}: продажа не возможна")
            else:
                val = seg_amount.get(seg, 0.0)
                lines.append(f"• {seg}: {round(val, 3)} млн руб.")

        lines.append("\n📌 Детализация по каналам:")

        seg_rows: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            seg = r["Сегмент"]
            seg_rows.setdefault(seg, []).append(r)

        for seg in all_segs:
            lines.append(f"\n▶ Сегмент: {seg}")

            metrics = segment_metrics.get(seg, {})

            market_raw = float(metrics.get("Рынок", 0.0))
            clients = int(round(float(metrics.get("Активные клиенты Банка", 0.0))))
            non_clients = int(round(float(metrics.get("Спящие клиенты и не клиенты Банка", 0.0))))
            market_for_output = clients + non_clients

            for r in seg_rows.get(seg, []):
                channel = r["Канал"]
                if r.get("Решение") != "да":
                    reason = r.get("Причина")
                    if reason:
                        lines.append(f"• Канал: {channel}; продажа в канале не возможна ({reason})")
                    else:
                        lines.append(f"• Канал: {channel}; продажа в канале не возможна")
                else:
                    amount_ab = float(r.get("amount_ab", 0.0))
                    lines.append(
                        f"• Канал: {channel}; оценка рынка = {market_for_output}, "
                        f"из них клиенты = {clients} и не клиенты = {non_clients}, "
                        f"потенциальный доход сегмента ~ {round(amount_ab, 3)} млн руб."
                    )

        return "\n".join(lines)

    def update_params_from_message(self, state, user_message: str) -> None:
            """
            Достаём из текста параметры:
            - avg_amount_mmb      — средний чек в ММБ, руб.
            - avg_amount_other    — средний чек в других сегментах, руб.
            - k                   — Кприб, %
            - own_share           — доля владения, %
            """

            prompt = f"""
    <REASONING>
    Запрос пользователя: "{user_message}"

    Твоя задача — извлечь числовые параметры для расчёта потенциала.

    Параметры:
    - avg_amount_mmb: средний чек в ММБ, в рублях;
    - avg_amount_other: средний чек в других сегментах, в рублях;
    - k: Кприб, в процентах (0–100);
    - own_share: доля владения, в процентах (0–100).

    Если параметр явно не указан — верни null.
    Ничего не выдумывай: только то, что явно указано или однозначно следует из текста.
    </REASONING>
    <ANSWER>
    Ответь строго ОДНИМ JSON-объектом БЕЗ пояснений, БЕЗ примеров и БЕЗ markdown.

    Только такой формат:

    {{
      "avg_amount_mmb": 500000,
      "avg_amount_other": 800000,
      "k": 15,
      "own_share": 10
    }}

    Если какой-то параметр не указан — поставь null:

    {{
      "avg_amount_mmb": 500000,
      "avg_amount_other": null,
      "k": 20,
      "own_share": null
    }}
    </ANSWER>
    """

            ans_raw = self.llm.chat(prompt)
            logger.debug(f"[params] raw_answer={ans_raw!r}")

            data = self._safe_json_loads(ans_raw) or {}

            def _upd(name: str):
                val = data.get(name)
                if val is None:
                    return
                try:
                    f = float(val)
                except (TypeError, ValueError):
                    return
                state[name] = f

            _upd("avg_amount_mmb")
            _upd("avg_amount_other")
            _upd("k")
            _upd("own_share")

            # небольшой хелпер: если задан только один чек — второй приравниваем к нему
            if state.get("avg_amount_mmb") and not state.get("avg_amount_other"):
                state["avg_amount_other"] = state["avg_amount_mmb"]
            if state.get("avg_amount_other") and not state.get("avg_amount_mmb"):
                state["avg_amount_mmb"] = state["avg_amount_other"]

    def get_missing_params(self, state) -> list[str]:
        missing = []
        if not state.get("avg_amount_mmb"):
            missing.append("средний чек в ММБ (avg_amount_mmb)")
        if not state.get("avg_amount_other"):
            missing.append("средний чек в других сегментах (avg_amount_other)")
        if not state.get("k"):
            missing.append("Кприб, % (k)")
        if not state.get("own_share"):
            missing.append("доля владения, % (own_share)")
        return missing

    def build_missing_params_reply(self, state) -> str:
        missing = self.get_missing_params(state)
        if not missing:
            return ""

        lines = []
        lines.append("Перед расчётом нужно уточнить несколько параметров:\n")
        for item in missing:
            lines.append(f"• {item}")
        lines.append(
            "\nНапиши, пожалуйста, значения в свободной форме. "
            "Например: \"средний чек в ММБ 500 тысяч, в других сегментах 800 тысяч, "
            "Кприб 15%, доля владения 10%\"."
        )
        return "\n".join(lines)