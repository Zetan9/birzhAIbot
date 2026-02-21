# services.py
"""
Централизованное хранилище сервисов для всего бота.
"""
import logging
from config import TINKOFF_TOKEN

# Словарь для хранения всех глобальных объектов
_services = {}

logger = logging.getLogger(__name__)

def get_service(name: str, creator_func=None):
    """
    Возвращает сервис по имени. Если сервис ещё не создан, вызывает creator_func.
    """
    if name not in _services:
        if creator_func:
            _services[name] = creator_func()
            logger.info(f"✅ Сервис '{name}' создан.")
        else:
            return None
    return _services[name]

def set_service(name: str, instance):
    """Принудительно устанавливает сервис (полезно для тестов или явной инициализации)."""
    _services[name] = instance
    logger.info(f"✅ Сервис '{name}' установлен вручную.")

def get_all_services():
    """Возвращает словарь всех созданных сервисов (для отладки)."""
    return _services

# Функции-создатели для каждого сервиса
def create_news_parser():
    from news_parser import NewsParser
    return NewsParser()

def create_db():
    from database import NewsDatabase
    return NewsDatabase()

def create_stock_provider():
    from tinkoff_stocks import TinkoffStockProvider
    return TinkoffStockProvider(TINKOFF_TOKEN)

def create_ai_advisor():
    from ai_advisor import AIAdvisor
    return AIAdvisor(TINKOFF_TOKEN)

def create_ai_trader():
    from ai_trader import VirtualTrader
    return VirtualTrader(initial_balance=1_000_000)

# Удобные обёртки для получения сервисов (ВОЗВРАЩАЮТ ЭКЗЕМПЛЯРЫ)
def news_parser():
    return get_service('news_parser', create_news_parser)

def db():
    return get_service('db', create_db)

def stock_provider():
    return get_service('stock_provider', create_stock_provider)

def ai_advisor():
    return get_service('ai_advisor', create_ai_advisor)

def ai_trader():
    return get_service('ai_trader', create_ai_trader)

def create_pulse_parser():
    from tinkoff_pulse import TinkoffPulseParser
    from config import TINKOFF_TOKEN
    return TinkoffPulseParser(token=TINKOFF_TOKEN)

def pulse_parser():
    return get_service('pulse_parser', create_pulse_parser)