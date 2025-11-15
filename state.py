# state.py
from typing import Dict, Any, Optional, List
from typing_extensions import TypedDict, Annotated

from langgraph.graph import add_messages
from langchain_core.messages import AnyMessage


class AgentState(TypedDict):
    """
    Состояние агента для LangGraph.
    """

    # Диалог (история сообщений)
    messages: Annotated[List[AnyMessage], add_messages]

    # Бизнес-состояние
    filters: Dict[str, Any]                      # industries / revenue / staff / tb
    segment_params: Dict[str, Dict[str, float]]  # параметры сегментов
    product_type: str                            # "Коробка" или "Кастом"

    # Управляющие флаги и результаты
    ready_to_calculate: bool                     # пользователь явно попросил посчитать
    last_result: Optional[Dict[str, Any]]        # результат последнего расчёта
