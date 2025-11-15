# # main.py
# from logs.dialog_agent import DialogAgent
#
# def main():
#     agent = DialogAgent(data_directory="./resources/csv")
#
#     print("🤖 Агент расчёта потенциала. Пиши запросы на русском.")
#     print("Например: 'проанализируй розничную торговлю', 'посчитай потенциал', 'какие сейчас фильтры'.")
#
#     while True:
#         try:
#             msg = input("\nТы: ").strip()
#             if not msg:
#                 continue
#             if msg.lower() in {"выход", "exit", "quit"}:
#                 print("Пока 👋")
#                 break
#
#             reply = agent.handle_message(msg)
#             print(f"Бот: {reply}")
#
#         except KeyboardInterrupt:
#             print("\nПока 👋")
#             break
#
# if __name__ == "__main__":
#     main()
