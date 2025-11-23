# telegram_bot.py
import logging
import os

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from chat_interface import chat_with_agent  # это твоя обёртка user_id+text -> ответ


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Привет! Я агент по расчёту потенциала.\n\n"
        "Опиши, какой бизнес или рынок нужно проанализировать.\n"
        "Например: «розничная торговля по Москве, выручка до 120 млн, чек 500 тыс».\n\n"
        "Я сам извлеку фильтры и параметры, покажу их,\n"
        "а по команде «посчитай» запущу расчёт."
    )
    if update.message:
        await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user_id = update.effective_user.id
    user_text = update.message.text

    try:
        reply = chat_with_agent(user_id, user_text)
    except Exception:
        logger.exception("Ошибка в chat_with_agent")
        reply = "Что-то пошло не так при обработке запроса. Попробуй ещё раз."

    await update.message.reply_text(reply)


def main() -> None:
    token = "8379457676:AAE12owj8J_dyy7PnJ5wsnYF_HK95LQFvSw"
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

    application = ApplicationBuilder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
