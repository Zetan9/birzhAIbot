"""
Мониторинг Tinkoff Пульс и уведомления о резких изменениях сентимента.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import services
from tinkoff_pulse import TinkoffPulseParser, PulsePost

logger = logging.getLogger(__name__)

class PulseMonitor:
    def __init__(self, bot, chat_id: Optional[int] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.parser = services.pulse_parser()
        self.tracked_tickers = {'SBER', 'GAZP', 'LKOH', 'YDEX', 'VTBR', 'ROSN', 'GMKN', 'TATN', 'MTSS', 'CHMF'}
        self.sentiment_history: Dict[str, List[float]] = defaultdict(list)
        self.history_size = 5
        self.check_interval = 900  # 15 минут
        self.last_check = datetime.now()

    async def start_monitoring(self):
        logger.info("🚀 Запуск мониторинга Tinkoff Пульс...")
        while True:
            try:
                await self.check_pulse()
            except Exception as e:
                logger.error(f"Ошибка в мониторинге Пульса: {e}")
            await asyncio.sleep(self.check_interval)

    async def check_pulse(self):
        logger.info("🔍 Проверка Пульса...")
        for ticker in self.tracked_tickers:
            try:
                posts = self.parser.get_posts_by_ticker(ticker, limit=20)
                if not posts:
                    continue
                avg_sentiment = self._calculate_avg_sentiment(posts)
                self.sentiment_history[ticker].append(avg_sentiment)
                if len(self.sentiment_history[ticker]) > self.history_size:
                    self.sentiment_history[ticker].pop(0)
                self._check_sentiment_change(ticker, avg_sentiment)
            except Exception as e:
                logger.error(f"Ошибка при обработке {ticker}: {e}")
        self.last_check = datetime.now()

    def _calculate_avg_sentiment(self, posts: List[PulsePost]) -> float:
        if not posts:
            return 0.0
        scores = [p.sentiment_score for p in posts if p.sentiment_score is not None]
        return sum(scores) / len(scores) if scores else 0.0

    def _check_sentiment_change(self, ticker: str, current: float):
        history = self.sentiment_history[ticker]
        if len(history) < 2:
            return
        previous = history[-2]
        change = current - previous
        if abs(change) > 0.3:
            direction = "📈 УЛУЧШИЛСЯ" if change > 0 else "📉 УХУДШИЛСЯ"
            message = (
                f"📊 *Tinkoff Пульс: {ticker}*\n"
                f"Сентимент {direction}\n"
                f"Было: {previous:.2f} → Стало: {current:.2f}\n"
                f"Изменение: {change:+.2f}"
            )
            if self.chat_id:
                asyncio.create_task(self._send_alert(message))

    async def _send_alert(self, message: str):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")