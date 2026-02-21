"""
Мониторинг Smart-Lab и уведомления о резких изменениях сентимента,
а также анализ изображений из постов.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

import services
from smartlab_parser import SmartLabParser, SmartLabPost

logger = logging.getLogger(__name__)

class SmartLabMonitor:
    def __init__(self, bot, chat_id: Optional[int] = None):
        self.bot = bot
        self.chat_id = chat_id
        self.parser = SmartLabParser()
        self.tracked_tickers = {'SBER', 'GAZP', 'LKOH', 'YDEX', 'VTBR', 'ROSN', 'GMKN', 'TATN', 'MTSS', 'CHMF'}
        self.sentiment_history: Dict[str, List[float]] = defaultdict(list)
        self.history_size = 5
        self.check_interval = 900  # 15 минут
        self.last_check = datetime.now()
        # Для отслеживания уже обработанных постов (чтобы не анализировать повторно)
        self.processed_posts = set()

    async def start_monitoring(self):
        logger.info("🚀 Запуск мониторинга Smart-Lab...")
        while True:
            try:
                await self.check_smartlab()
            except Exception as e:
                logger.error(f"Ошибка в мониторинге Smart-Lab: {e}")
            await asyncio.sleep(self.check_interval)

    async def check_smartlab(self):
        logger.info("🔍 Проверка Smart-Lab...")
        posts = self.parser.fetch_posts(limit=20)
        if not posts:
            logger.warning("Нет постов из Smart-Lab")
            return

        # Группируем по тикерам для анализа сентимента
        ticker_posts = defaultdict(list)
        for post in posts:
            # Проверяем, нужно ли анализировать картинку
            await self._process_image_if_needed(post)

            for ticker in post.tickers:
                ticker_posts[ticker].append(post)

        for ticker in self.tracked_tickers:
            if ticker not in ticker_posts:
                continue
            avg_sentiment = self._calculate_avg_sentiment(ticker_posts[ticker])
            self.sentiment_history[ticker].append(avg_sentiment)
            if len(self.sentiment_history[ticker]) > self.history_size:
                self.sentiment_history[ticker].pop(0)
            self._check_sentiment_change(ticker, avg_sentiment)

        self.last_check = datetime.now()

    async def _process_image_if_needed(self, post: SmartLabPost):
        """
        Если у поста есть изображение, и оно ещё не обрабатывалось,
        запускаем анализ ИИ и отправляем результат (только если картинка релевантна).
        """
        if not post.image_path:
            return

        # Используем ссылку как уникальный идентификатор поста
        if post.link in self.processed_posts:
            return

        # Помечаем как обработанное до анализа, чтобы не дублировать
        self.processed_posts.add(post.link)

        # Проверяем, существует ли файл
        if not os.path.exists(post.image_path):
            logger.warning(f"Файл изображения не найден: {post.image_path}")
            return

        advisor = services.ai_advisor()
        if not advisor:
            logger.error("AI Advisor не доступен")
            return

        try:
            # Анализируем изображение в контексте заголовка и текста поста
            analysis_text = advisor.analyze_image(
                post.image_path,
                f"{post.title}\n\n{post.summary}"
            )
            if analysis_text:
                # Проверяем, не говорит ли модель, что изображение нерелевантно
                irrelevant_phrases = [
                    "не связано с содержанием поста",
                    "не относится к теме поста",
                    "не несёт полезной информации",
                    "логотип",
                    "иконка",
                    "реклама",
                    "случайная картинка"
                ]
                if any(phrase in analysis_text.lower() for phrase in irrelevant_phrases):
                    logger.info(f"Пропущена нерелевантная картинка для поста: {post.title[:50]}...")
                    return  # Не отправляем
                # Если релевантно - отправляем
                await self._send_image_analysis(post, analysis_text)
            else:
                logger.warning(f"Не удалось проанализировать изображение для {post.link}")
        except Exception as e:
            logger.error(f"Ошибка при анализе изображения {post.image_path}: {e}")

        # Небольшая задержка, чтобы не перегружать ИИ
        await asyncio.sleep(20)

    async def _send_image_analysis(self, post: SmartLabPost, analysis_text: str):
        """Отправляет результат анализа изображения в Telegram."""
        if not self.chat_id:
            logger.info("Анализ изображения (чат не указан): " + analysis_text)
            return

        message = (
            f"🖼️ *Анализ изображения от Smart-Lab*\n\n"
            f"📌 *{post.title}*\n"
            f"👤 {post.author}\n"
        )
        if post.tickers:
            message += f"🏷️ {', '.join(post.tickers)}\n"
        message += f"\n💡 *Вывод ИИ:*\n{analysis_text}"

        try:
            # Отправляем картинку вместе с подписью
            if post.image_path and os.path.exists(post.image_path):
                with open(post.image_path, 'rb') as f:
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=f,
                        caption=message[:1024],  # ограничение на длину caption
                        parse_mode='Markdown'
                    )
            else:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Ошибка отправки анализа: {e}")

    def _calculate_avg_sentiment(self, posts: List[SmartLabPost]) -> float:
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
                f"📊 *Smart-Lab: {ticker}*\n"
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