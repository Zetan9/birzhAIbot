import os
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)



def get_bot_token() -> str:
    """Получает токен Telegram бота"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN не найден в .env")
    return token

def get_tinkoff_token() -> str:
    """Получает токен Т-Банка API"""
    token = os.getenv("TINKOFF_TOKEN")
    if not token:
        raise ValueError(
            "TINKOFF_TOKEN не найден в .env\n"
            "Добавь в .env файл: TINKOFF_TOKEN=твой_токен"
        )
    return token

TELEGRAM_BOT_TOKEN = get_bot_token()
TINKOFF_TOKEN = get_tinkoff_token()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

TG_API_ID = int(os.getenv("TG_API_ID", 0))
TG_API_HASH = os.getenv("TG_API_HASH", "")

# Параметры трейдера (можно задать в .env)
PROFIT_TIERS = os.getenv("PROFIT_TIERS", "10:0.3,15:0.3,20:0.4")  # level:sell_fraction
USE_TRAILING_STOP = os.getenv("USE_TRAILING_STOP", "true").lower() == "true"
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "5.0"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "5.0"))

# Для отладки (закомментируй, если не нужно)
print(f"✅ Токен загружен: {TELEGRAM_BOT_TOKEN[:5]}...{TELEGRAM_BOT_TOKEN[-5:]}")