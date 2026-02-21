"""
Непрерывный анализ новостей с памятью.
Запускается каждые 10 минут, анализирует новые новости и сохраняет результаты.
"""

import asyncio
import logging
from datetime import datetime, timedelta
import services

logger = logging.getLogger(__name__)

class ContinuousNewsAnalyzer:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        self.ai_advisor = services.ai_advisor()
        self.news_parser = services.news_parser()
        self.db = services.db()
        self.last_check = datetime.now() - timedelta(minutes=10)
        self.check_interval = 600  # 10 секунд * 60 = 600 (10 минут)

    async def run(self):
        logger.info("🚀 Запуск непрерывного анализа новостей (интервал 10 мин)")
        while True:
            try:
                await self.check_new_news()
            except Exception as e:
                logger.error(f"Ошибка в анализе новостей: {e}")
            await asyncio.sleep(self.check_interval)

    async def check_new_news(self):
        logger.info("🔍 Проверка новых новостей...")
        if self.news_parser is None:
            logger.error("❌ news_parser не инициализирован")
            return
        if self.db is None:
            logger.error("❌ db не инициализирована")
            return
        if self.ai_advisor is None:
            logger.error("❌ ai_advisor не инициализирован")
            return

        all_news = self.news_parser.fetch_all_news(limit_per_source=3, max_total=50)
        new_news = [n for n in all_news if n.published > self.last_check]

        if not new_news:
            logger.info("Новых новостей нет")
            return

        logger.info(f"Найдено {len(new_news)} новых новостей, начинаю анализ...")
        for news in new_news:
            try:
                history_context = ""
                if news.related_tickers:
                    for ticker in news.related_tickers[:3]:
                        past = self.db.get_recent_analysis_by_ticker(ticker, days=7, limit=3)
                        if past:
                            history_context += f"\nРанее по {ticker}:\n"
                            for p in past:
                                history_context += f"- {p.get('summary', '')}\n"

                prompt = f"""
                Проанализируй эту новость и её влияние на рынок.

                НОВОСТЬ: {news.title}
                ИСТОЧНИК: {news.source}

                {history_context}

                Определи:
                - сентимент (positive/negative/neutral) и оценку от -1 до 1
                - важность (high/medium/low)
                - какие компании/сектора затронуты
                - краткое резюме (1-2 предложения)

                Ответь ТОЛЬКО JSON:
                {{
                    "sentiment": "positive/negative/neutral",
                    "score": 0.0,
                    "importance": "high/medium/low",
                    "tickers": ["SBER"],
                    "summary": "текст",
                    "key_points": ["пункт1", "пункт2"]
                }}
                """
                result = self.ai_advisor._call_ollama(prompt)
                if result:
                    result['timestamp'] = datetime.now().isoformat()
                    result['news_title'] = news.title
                    self.db.save_news_analysis(news, result)
                    logger.info(f"✅ Проанализирована новость: {news.title[:50]}...")
                    if self.bot and self.chat_id and result.get('importance') == 'high':
                        await self._send_alert(news, result)
                else:
                    logger.warning(f"Не удалось проанализировать новость: {news.title[:50]}")
            except Exception as e:
                logger.error(f"Ошибка при анализе новости {news.title[:30]}: {e}")

        self.last_check = datetime.now()

    async def _send_alert(self, news, analysis):
        if not self.bot or not self.chat_id:
            return
        emoji = "🟢" if analysis['sentiment'] == 'positive' else "🔴" if analysis['sentiment'] == 'negative' else "🟡"
        text = f"{emoji} *Важная новость*\n{news.title}\n{analysis['summary']}"
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")