"""
Мониторинг Tinkoff Пульс и уведомления о резких изменениях сентимента.
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

import services
from tinkoff_pulse import TinkoffPulseParser, PulsePost

logger = logging.getLogger(__name__)

class PulseMonitor:
    def __init__(self, bot, chat_id: Optional[int] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.parser = services.pulse_parser()  # получаем экземпляр из services
        self.tracked_tickers = {'SBER', 'GAZP', 'LKOH', 'YDEX', 'VTBR', 'ROSN', 'GMKN', 'TATN', 'MTSS', 'CHMF'}
        self.sentiment_history: Dict[str, List[float]] = defaultdict(list)
        self.history_size = 5
        self.check_interval = 900  # 15 минут
        self.last_check = datetime.now()
        # Для отслеживания уже обработанных постов (чтобы не анализировать повторно)
        self.processed_posts = set()

    async def start_monitoring(self):
        logger.info("🚀 Запуск мониторинга Tinkoff Пульс...")
        while True:
            try:
                await self.check_pulse()
            except Exception as e:
                logger.error(f"Ошибка в мониторинге Пульса: {e}")
            await asyncio.sleep(self.check_interval)

    async def check_pulse(self):
        logger.info("🔍 Проверка Tinkoff Пульс...")
        posts = self.parser.collect_all(limit_per_feed=20, max_total=50)
        if not posts:
            logger.warning("Нет постов из Tinkoff Пульс")
            return

        # Группируем по тикерам для анализа сентимента
        ticker_posts = defaultdict(list)
        for post in posts:
            # Отмечаем пост как обработанный (чтобы не дублировать)
            if post.id in self.processed_posts:
                continue
            self.processed_posts.add(post.id)

            for ticker in post.tickers:
                ticker_posts[ticker].append(post)

        # Обновляем историю сентимента по отслеживаемым тикерам
        for ticker in self.tracked_tickers:
            if ticker not in ticker_posts:
                continue
            # Берём средний сентимент за последние посты
            avg_sentiment = self._calculate_avg_sentiment(ticker_posts[ticker])
            self.sentiment_history[ticker].append(avg_sentiment)
            if len(self.sentiment_history[ticker]) > self.history_size:
                self.sentiment_history[ticker].pop(0)
            self._check_sentiment_change(ticker, avg_sentiment)

        db = services.db()
        if db:
            today = datetime.now().date()
            for ticker in self.tracked_tickers:
                if ticker in ticker_posts:
                    avg = self._calculate_avg_sentiment(ticker_posts[ticker])
                    count = len(ticker_posts[ticker])
                    db.save_pulse_sentiment(ticker, avg, count)
        
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