# chat_interface.py
import logging
from typing import Dict, Any

from langchain_core.messages import HumanMessage, AIMessage

from potential_agent import PotentialCalculationAgent
from llm_client import GigaChatLLM

logger = logging.getLogger("chat_interface")

# === 1. Инициализация LLM и бизнес-агента ===

_llm = GigaChatLLM()
_business_agent = PotentialCalculationAgent(
    llm=_llm,
    data_dir="./resources/csv",
)

# === 2. Память по пользователям (простейший in-memory) ===

_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _make_initial_state() -> Dict[str, Any]:
    """Стартовое состояние для нового пользователя."""
    return {
        "messages": [],
        "filters": {},
        "segment_params": {},
        "product_type": "Коробка",
        "ready_to_calculate": False,
        "last_result": None,

        # новые параметры расчёта
        "avg_amount_mmb": None,
        "avg_amount_other": None,
        "k": None,
        "own_share": None,
    }


def _get_state(user_id: int) -> Dict[str, Any]:
    """Берём или создаём состояние для конкретного пользователя."""
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = _make_initial_state()
    return _SESSIONS[user_id]


# === 3. Основная функция: строка на вход, строка на выход ===

def chat_with_agent(user_id: int, user_text: str) -> str:
    """
    Главный интерфейс для интеграции.

    Вход:
      - user_id: любой идентификатор пользователя (для Telegram — update.effective_user.id)
      - user_text: текст сообщения

    Выход:
      - текст ответа агента (одна строка)
    """
    state = _get_state(user_id)
    user_text = (user_text or "").strip()

    if not user_text:
        return "Напиши, пожалуйста, текст запроса 🙂"

    # —–– 1. Сохраним сообщение в истории (если тебе важен контекст)
    state["messages"].append(HumanMessage(content=user_text))

    # —–– 2. Явный запрос «фильтры?» — просто показать состояние, без LLM
    if _business_agent.is_show_filters_request(user_text):
        reply_text = _business_agent.format_filters_for_user(state)
        state["messages"].append(AIMessage(content=reply_text))
        state["ready_to_calculate"] = False
        return reply_text

    # —–– 3. Просьба посчитать — НЕ трогаем фильтры/параметры, просто считаем
    if _business_agent.is_calculation_request(user_text):
        # run_full_calculation сам подставит дефолты, если что-то не задано
        result = _business_agent.run_full_calculation(state)
        state["last_result"] = result

        reply_text = _business_agent.summarize_result_for_user(result)
        state["messages"].append(AIMessage(content=reply_text))

        # после расчёта очищаем фильтры/сегменты, но не трогаем параметры чеков
        state["filters"] = {}
        state["segment_params"] = {}
        state["product_type"] = "Коробка"
        state["ready_to_calculate"] = False

        return reply_text

    # —–– 4. Обычное сообщение: обновляем фильтры и параметры через LLM
    _business_agent.update_filters_from_message(state, user_text)
    _business_agent.update_params_from_message(state, user_text)

    # —–– 5. Формируем ответ: текущие фильтры + параметры + комментарий
    summary = _business_agent.format_filters_for_user(state)
    comment = _business_agent.build_agent_reply(state, user_text)

    reply_text = summary
    if comment:
        reply_text = summary + "\n\n" + comment

    state["messages"].append(AIMessage(content=reply_text))
    state["ready_to_calculate"] = False

    return reply_text
