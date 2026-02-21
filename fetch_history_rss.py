#!/usr/bin/env python
import asyncio
from moex_rss import fetch_signals
import services

def main():
    signals = fetch_signals(limit=500)  # получим последние 500
    db = services.db()
    for sig in signals:
        db.save_moex_signal(sig)
    print(f"Сохранено {len(signals)} сигналов")

if __name__ == '__main__':
    main()