# graph_app.py
from typing import cast

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage

from state import AgentState
from potential_agent import PotentialCalculationAgent
from llm_client import GigaChatLLM


# === Инициализация LLM и бизнес-агента ===

llm = GigaChatLLM()
business_agent = PotentialCalculationAgent(
    llm=llm,
    data_dir="./resources/csv",  # путь к каталогу с файлами, которые использует analytics_engine
)


def agent_turn(state: AgentState) -> AgentState:
    last_msg = state["messages"][-1]
    last_msg = cast(HumanMessage, last_msg)
    user_text = last_msg.content

    # 1) Показать фильтры по явной просьбе
    if business_agent.is_show_filters_request(user_text):
        reply_text = business_agent.format_filters_for_user(state)
        state["messages"].append(AIMessage(content=reply_text))
        state["ready_to_calculate"] = False
        return state

    # 2) Просьба посчитать — просто ставим флаг (без изменения фильтров/параметров)
    if business_agent.is_calculation_request(user_text):
        state["ready_to_calculate"] = True
        return state

    # 3) Обычное сообщение — обновляем фильтры и параметры
    business_agent.update_filters_from_message(state, user_text)
    business_agent.update_params_from_message(state, user_text)

    # 4) Формируем ответ: текущие фильтры + опциональный комментарий
    summary = business_agent.format_filters_for_user(state)
    comment = business_agent.build_agent_reply(state, user_text)

    reply_text = summary
    if comment:
        reply_text = summary + "\n\n" + comment

    state["messages"].append(AIMessage(content=reply_text))
    state["ready_to_calculate"] = False
    return state




def run_calculation(state: AgentState) -> AgentState:
    """
    Запуск пайплайна и формирование итогового ответа.
    После этого — сброс бизнес-состояния.
    """
    result = business_agent.run_full_calculation(state)
    state["last_result"] = result

    summary_text = business_agent.summarize_result_for_user(result)
    state["messages"].append(AIMessage(content=summary_text))

    # Сброс состояния после расчёта (как ты и хотел)
    state["filters"] = {}
    state["segment_params"] = {}
    state["product_type"] = "Коробка"
    state["ready_to_calculate"] = False

    return state


def should_run_calc(state: AgentState) -> str:
    """
    Router: если пользователь явно попросил считать — идём в run_calc,
    иначе завершаем шаг диалога.
    """
    if state.get("ready_to_calculate"):
        return "run_calc"
    return "end"


def build_app():
    workflow = StateGraph(AgentState)

    workflow.add_node("agent_turn", agent_turn)
    workflow.add_node("run_calc", run_calculation)

    workflow.set_entry_point("agent_turn")

    workflow.add_conditional_edges(
        "agent_turn",
        should_run_calc,
        {
            "run_calc": "run_calc",
            "end": END,
        },
    )

    workflow.add_edge("run_calc", END)

    app = workflow.compile()
    return app


app = build_app()


def main_cli():
    state: AgentState = {
        "messages": [],
        "filters": {},
        "segment_params": {},
        "product_type": "Коробка",
        "ready_to_calculate": False,
        "last_result": None,
        "avg_amount_mmb": None,
        "avg_amount_other": None,
        "k": None,
        "own_share": None,
    }

    print("Запущен CLI-агент. Напиши 'выход' для завершения.\n")

    # стартовое сообщение от агента
    start_message = (
        "Привет! Я агент по расчёту потенциала.\n"
        "Опиши, какой бизнес или рынок нужно проанализировать "
        "(например: \"розничная торговля по Москве, выручка до 120 млн\").\n"
        "Я сам извлеку фильтры, покажу их, а по команде \"считай\" или \"посчитай\" "
        "запущу расчёт."
    )
    print("Агент:", start_message, "\n")
    # сохраним в историю, чтобы при желании можно было учитывать в контексте
    state["messages"].append(AIMessage(content=start_message))

    while True:
        user_text = input("Пользователь: ").strip()
        if user_text.lower() in {"выход", "exit", "quit"}:
            print("До связи!")
            break

        state["messages"].append(HumanMessage(content=user_text))
        state = app.invoke(state)

        ai_msgs = [m for m in state["messages"] if isinstance(m, AIMessage)]
        if ai_msgs:
            print("\nАгент:", ai_msgs[-1].content, "\n")



if __name__ == "__main__":
    main_cli()
