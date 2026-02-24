#!/usr/bin/env python
# label_signals.py
# Разметка сигналов по дневным данным: успех = рост > 1% на следующий день (для бычьего) или падение > 1% (для медвежьего)

import logging
from datetime import datetime, timedelta
import services
from database import NewsDatabase
from tinkoff_stocks import TinkoffStockProvider
from stock_prices import StockPriceProvider
from config import TINKOFF_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def label_signals(interval_days=1):
    """
    interval_days: сколько торговых дней вперёд смотрим (по умолчанию 1).
    """
    db = NewsDatabase()
    tinkoff_provider = TinkoffStockProvider(token=TINKOFF_TOKEN)
    moex_provider = StockPriceProvider()

    signals = db.get_unlabeled_signals(limit=2000)
    if not signals:
        logger.info("Нет неразмеченных сигналов")
        return

    for sig_id, ticker, signal_time_str, entry_price, sig_type in signals:
        signal_time = datetime.fromisoformat(signal_time_str)
        signal_date = signal_time.date()
        target_date = signal_date + timedelta(days=interval_days)

        # Запрашиваем историю с запасом (например, 10 дней)
        days_to_fetch = 10
        history = tinkoff_provider.get_history(ticker, days=days_to_fetch)
        source = "Tinkoff"
        if not history:
            logger.debug(f"Tinkoff не дал истории для {ticker}, пробуем MOEX")
            history = moex_provider.get_history(ticker, days=days_to_fetch)
            source = "MOEX"

        if not history:
            logger.warning(f"Нет истории для {ticker} (сигнал {sig_id}) ни из одного источника")
            continue

        # Ищем свечу на дату сигнала (entry) и на дату выхода (exit)
        entry_candle = None
        exit_candle = None

        # Проходим по всем свечам (они уже отсортированы по дате)
        for candle in history:
            # Получаем дату свечи (если это datetime, берём .date())
            candle_date = candle['time']
            if hasattr(candle_date, 'date'):
                candle_date = candle_date.date()
            elif isinstance(candle_date, str):
                candle_date = datetime.fromisoformat(candle_date).date()

            # Если свеча на дату сигнала или позже – запоминаем как entry_candle (берём первую после или точно в день)
            if candle_date >= signal_date and entry_candle is None:
                entry_candle = candle
                entry_actual_date = candle_date

            # Если свеча на дату выхода или позже – запоминаем как exit_candle (первая после target_date)
            if candle_date >= target_date and exit_candle is None:
                exit_candle = candle
                exit_actual_date = candle_date
                break  # нашли exit, можно выйти

        if entry_candle is None:
            logger.warning(f"Не найдена свеча после {signal_date} для {ticker} (сигнал {sig_id})")
            continue
        if exit_candle is None:
            logger.warning(f"Не найдена свеча после {target_date} для {ticker} (сигнал {sig_id})")
            continue

        # Берём цены закрытия
        entry_close = entry_candle['close']
        exit_close = exit_candle['close']

        # Определяем успех: движение > 1% в сторону сигнала
        if sig_type == 'bullish':
            success = 1 if exit_close > entry_close * 1.01 else 0
        else:  # bearish
            success = 1 if exit_close < entry_close * 0.99 else 0

        db.update_signal_outcome(sig_id, success, interval_days * 24 * 3600)
        logger.info(f"Сигнал {sig_id} ({ticker}) размечен: success={success} (источник: {source}, дата входа={entry_actual_date}, выхода={exit_actual_date})")

    logger.info(f"Размечено {len(signals)} сигналов")

if __name__ == "__main__":
    label_signals(interval_days=1)