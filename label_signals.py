#!/usr/bin/env python
import logging
from datetime import datetime, timedelta
import services
from database import NewsDatabase
from tinkoff_stocks import TinkoffStockProvider
from stock_prices import StockPriceProvider  # импортируем новый провайдер
from config import TINKOFF_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def label_signals(interval_hours=1):
    db = NewsDatabase()
    tinkoff_provider = TinkoffStockProvider(token=TINKOFF_TOKEN)
    moex_provider = StockPriceProvider()  # альтернативный источник

    signals = db.get_unlabeled_signals(limit=1000)

    if not signals:
        logger.info("Нет неразмеченных сигналов")
        return

    for sig_id, ticker, signal_time_str, entry_price, sig_type in signals:
        signal_time = datetime.fromisoformat(signal_time_str)
        end_time = signal_time + timedelta(hours=interval_hours)

        # Пытаемся сначала через Tinkoff
        days = (end_time - signal_time).days + 2
        history = tinkoff_provider.get_history(ticker, days=days)
        source = "Tinkoff"

        # Если Tinkoff не дал данных, пробуем MOEX
        if not history:
            logger.debug(f"Tinkoff не дал истории для {ticker}, пробуем MOEX")
            history = moex_provider.get_history(ticker, days=days)
            source = "MOEX"

        if not history:
            logger.warning(f"Нет истории для {ticker} (сигнал {sig_id}) ни из одного источника")
            continue

        # Находим цену, ближайшую к end_time (не раньше end_time)
        exit_price = None
        for bar in history:
            # Приводим время свечи к naive для сравнения
            if bar['time'].replace(tzinfo=None) >= end_time:
                exit_price = bar['close']
                break
        if exit_price is None:
            # если не нашли, берём последнюю доступную цену
            exit_price = history[-1]['close']

        if sig_type == 'bullish':
            success = 1 if exit_price > entry_price * 1.01 else 0
        else:  # bearish
            success = 1 if exit_price < entry_price * 0.99 else 0

        db.update_signal_outcome(sig_id, success, interval_hours * 3600)
        logger.debug(f"Сигнал {sig_id} ({ticker}) размечен: success={success} (источник: {source})")

    logger.info(f"Размечено {len(signals)} сигналов")

if __name__ == "__main__":
    label_signals(interval_hours=1)