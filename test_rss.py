import logging
logging.basicConfig(level=logging.DEBUG)
from moex_rss import fetch_signals

signals = fetch_signals(limit=20)
print(f"Найдено сигналов: {len(signals)}")
if signals:
    print("Первый сигнал:", signals[0])