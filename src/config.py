import os
import logging


class Settings:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    TELEGRAM_BOT_TOKEN = os.getenv(
        "TELEGRAM_BOT_TOKEN_BTA", "НАПРАВЛЮ ЛИЧНО"
    )
    GIGACHAT_CREDENTIALS = os.getenv(
        "GIGACHAT_CREDENTIALS_BTA",
        "ВСТАВИТЬ СВОЙ АПИ==",
    )
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE_BTA", "GIGACHAT_API_PERS")

    CLIENT_DATABASE_PATH = os.path.join(BASE_DIR, "data", "client_database.xlsx")

    GIGACHAT_MODEL = "GigaChat-Max"
    GIGACHAT_VERIFY_SSL_CERTS = False
    GIGACHAT_TIMEOUT = 90
    GIGACHAT_PROFANITY_CHECK = False
    GIGACHAT_TEMPERATURE_SUMMARIZE = 0.3
    GIGACHAT_MAX_TOKENS_SUMMARIZE = 2100
    GIGACHAT_TEMPERATURE_NLU = 0.01
    GIGACHAT_MAX_TOKENS_NLU = 2100

    LOG_LEVEL = logging.DEBUG
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"


settings = Settings()


GOLDEN_LIST_URLS = [
    "https://www.expocentr.ru/ru/events/",
    "https://worldexpo.pro/calendar",
    "https://expomap.ru/all/",
    "https://www.interfax.ru/business/exhibitions",
    # Добавьте еще 3-5 релевантных вашему бизнесу агрегаторов
]


def setup_logging():
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format=settings.LOG_FORMAT,
        handlers=[logging.StreamHandler()],
    )
    for lib_logger_name in ["httpx", "httpcore", "telegram", "gigachat", "playwright"]:
        logging.getLogger(lib_logger_name).setLevel(logging.WARNING)
