import logging
import asyncio
import nest_asyncio
import torch

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from src.config import settings, setup_logging
from src.dialogue.dialogue_manager import DialogueManager

# --- Начальная настройка (выполняется один раз при импорте) ---
nest_asyncio.apply()
torch.set_num_threads(1)

# Настраиваем логирование ДО того, как что-либо логировать
setup_logging()
logger = logging.getLogger(__name__)

# Создаем менеджер диалогов
dialogue_manager = DialogueManager()
# -------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dialogue_manager.start_dialogue(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dialogue_manager.handle_text_message(update, context)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await dialogue_manager.handle_callback_query(update, context)

def main() -> None:
    """Основная функция для запуска бота."""
    logger.info("Запуск Telegram-бота...")
    
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN == "ВАШ_ТЕЛЕГРАМ_ТОКЕН":
        logger.critical("Токен Telegram-бота не установлен! Зайдите в src/config.py и укажите TELEGRAM_BOT_TOKEN.")
        return  # Завершаем выполнение, если токена нет

    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    logger.info("Бот запущен и готов к работе. Нажмите Ctrl+C для остановки.")
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Добавим обработку исключений на верхнем уровне, чтобы увидеть любую ошибку
        logger.critical("Произошла непредвиденная ошибка при запуске бота!", exc_info=True)