"""
Автоматический ИИ-мониторинг рынка
Бот сам анализирует новости и присылает уведомления при важных событиях
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import os
from config import TINKOFF_TOKEN
import services
# import ollama

logger = logging.getLogger(__name__)

class AIMarketMonitor:
    """Автоматический мониторинг рынка с ИИ"""
    
    def __init__(self, bot, chat_id: Optional[int] = None):
        self.bot = bot
        self.chat_id: Optional[int] = chat_id
        self.ai_advisor = services.ai_advisor()
        self.news_parser = services.news_parser()
        self.db = services.db()
        
        # Настройки мониторинга
        self.check_interval = 3600  # Проверка каждый час
        self.last_check = datetime.now()
        self.last_news_count = 0
        self.notified_events = set()  # Чтобы не повторяться
        self.last_sentiment = 0
        self.last_analysis_time = datetime.now() - timedelta(hours=6)
        
        # Пороги для уведомлений
        self.thresholds = {
            'sentiment_change': 0.3,      # Резкое изменение сентимента
            'important_news': True,        # Важные новости
            'price_movement': 5.0,         # Движение цены >5%
            'recommendation_change': True, # Новая рекомендация
        }
        
        logger.info(f"✅ AI Market Monitor инициализирован" + (f" для чата {chat_id}" if chat_id else ""))
    
    async def start_monitoring(self):
        """Запускает бесконечный мониторинг"""
        logger.info("🚀 Запуск автоматического мониторинга...")
        
        # Отправляем приветственное сообщение
        await self._send_startup_message()
        
        while True:
            try:
                await self.check_market()
            except Exception as e:
                logger.error(f"Ошибка в мониторинге: {e}")
            
            # Ждём следующий цикл
            logger.info(f"⏳ Следующая проверка через {self.check_interval/3600} часов")
            await asyncio.sleep(self.check_interval)
    
    async def _send_startup_message(self):
        """Отправляет сообщение о запуске мониторинга"""
        if not self.chat_id:
            logger.warning("⚠️ chat_id не указан, уведомления не будут отправляться")
            return
        
        message = (
            "🤖 *АВТОМАТИЧЕСКИЙ ИИ-МОНИТОРИНГ ЗАПУЩЕН*\n\n"
            "Я буду следить за рынком 24/7 и присылать:\n"
            "• 🚨 *Важные новости* (кризисы, рекорды, санкции)\n"
            "• 📊 *Изменения настроений* рынка\n"
            "• 💡 *Инвестиционные идеи* от ИИ\n"
            "• ⚠️ *Предупреждения* о рисках\n\n"
            f"🕒 Проверка каждые {self.check_interval/3600:.0f} час(а)\n"
            "🔍 Анализ при появлении важных событий\n\n"
            "Используй /monitor для управления"
        )
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение: {e}")
            logger.info("⚠️ Уведомления будут сохраняться в логах")
    
    async def check_market(self):
        """Проверяет рынок и отправляет уведомления"""
        
        logger.info("🔍 Проверка рынка...")
        
        # 1. Собираем свежие новости
        news = self.news_parser.fetch_all_news(limit_per_source=3, max_total=50)
        current_news_count = len(news)
        
        logger.info(f"📰 Собрано {current_news_count} новостей")
        
        # 2. Проверяем важные новости
        important_news = self._find_important_news(news)
        if important_news:
            logger.info(f"🚨 Найдено {len(important_news)} важных новостей")
            await self._send_important_news(important_news)
        
        # 3. Анализируем сентимент
        current_sentiment = self._analyze_market_sentiment(news)
        logger.info(f"📊 Текущий сентимент: {current_sentiment:.2f}")
        
        if self._is_significant_sentiment_change(current_sentiment):
            logger.info(f"🔄 Значительное изменение сентимента")
            await self._send_sentiment_alert(current_sentiment)
        
        # 4. Проверяем, нужно ли сделать полный анализ
        if self._should_do_full_analysis(news, current_sentiment):
            logger.info("🤖 Запуск полного ИИ-анализа...")
            analysis = self.ai_advisor.analyze_all()
            await self._send_market_analysis(analysis)
            self.last_analysis_time = datetime.now()
        
        # 5. Проверяем изменение количества новостей (активность)
        news_diff = current_news_count - self.last_news_count
        if abs(news_diff) > 15:
            logger.info(f"📊 Резкое изменение активности: {news_diff:+d}")
            await self._send_activity_alert(current_news_count, news_diff)
        
        self.last_news_count = current_news_count
        self.last_sentiment = current_sentiment
        self.last_check = datetime.now()
    
    def _find_important_news(self, news_list: List) -> List:
        """Находит важные новости для уведомления"""
        important = []
        
        # Ключевые слова для важных новостей
        important_keywords = {
            'кризис': 1.0, 'обвал': 1.0, 'рекорд': 0.8, 'санкции': 1.0,
            'дефолт': 1.0, 'слияние': 0.7, 'поглощение': 0.7, 'дивиденды': 0.6,
            'отчетность': 0.5, 'иск': 0.6, 'штраф': 0.6, 'расследование': 0.6,
            'назначение': 0.4, 'отставка': 0.5, 'теракт': 1.0, 'война': 1.0,
            'катастрофа': 1.0, 'эмбарго': 0.9, 'забастовка': 0.6,
            'банкротство': 0.9, 'национализация': 0.9, 'рекордный': 0.7
        }
        
        for news in news_list[:15]:  # Проверяем первые 15
            title_lower = news.title.lower()
            
            for keyword, weight in important_keywords.items():
                if keyword in title_lower:
                    # Проверяем, не уведомляли ли уже
                    news_hash = hash(news.title + news.link)
                    if news_hash not in self.notified_events:
                        self.notified_events.add(news_hash)
                        
                        # Добавляем вес важности
                        news.importance = weight
                        important.append(news)
                        
                        logger.info(f"🔥 Важная новость: {news.title[:50]}...")
                        break
        
        # Сортируем по важности
        important.sort(key=lambda x: x.importance, reverse=True)
        return important
    
    def _analyze_market_sentiment(self, news_list: List) -> float:
        """Анализирует общий сентимент рынка"""
        if not news_list:
            return self.last_sentiment
        
        positive_words = ['рост', 'прибыль', 'успех', 'рекорд', 'повышение', 
                         'увеличение', 'выигрыш', 'доход', 'дивиденды']
        negative_words = ['падение', 'убыток', 'кризис', 'санкции', 'снижение',
                         'обвал', 'потеря', 'долг', 'проблема']
        
        total_score = 0
        news_analyzed = 0
        
        for news in news_list[:30]:  # Анализируем до 30 новостей
            text = (news.title + " " + news.summary).lower()
            
            # Считаем позитивные и негативные слова
            pos = sum(1 for w in positive_words if w in text)
            neg = sum(1 for w in negative_words if w in text)
            
            # Учитываем важность источника
            source_weight = 1.0
            if news.source in ['interfax', 'tass', 'bloomberg', 'reuters']:
                source_weight = 1.5
            
            if pos + neg > 0:
                news_score = ((pos - neg) / (pos + neg)) * source_weight
                total_score += news_score
                news_analyzed += 1
        
        if news_analyzed > 0:
            return total_score / news_analyzed
        
        return self.last_sentiment
    
    def _is_significant_sentiment_change(self, current_sentiment: float) -> bool:
        """Проверяет, значительное ли изменение сентимента"""
        if abs(current_sentiment - self.last_sentiment) > self.thresholds['sentiment_change']:
            return True
        return False
    
    def _should_do_full_analysis(self, news_list: List, current_sentiment: float) -> bool:
        """Определяет, нужно ли сделать полный анализ"""
        hours_since = (datetime.now() - self.last_analysis_time).total_seconds() / 3600
        
        # Полный анализ если:
        # 1. Прошло больше 6 часов
        if hours_since >= 6:
            return True
        
        # 2. Много новых важных новостей
        important_count = len([n for n in news_list if hasattr(n, 'importance')])
        if important_count >= 5:
            return True
        
        # 3. Резкое изменение сентимента
        if abs(current_sentiment - self.last_sentiment) > 0.4:
            return True
        
        return False
    
    async def _send_important_news(self, news_list: List):
        """Отправляет уведомление о важных новостях"""
        if not self.chat_id:
            logger.info(f"🚨 Важные новости: {len(news_list)}")
            return
        
        for news in news_list[:2]:  # Максимум 2 новости за раз
            # Выбираем эмодзи по важности
            if news.importance >= 0.9:
                emoji = "🚨🚨🚨"
            elif news.importance >= 0.7:
                emoji = "🚨🚨"
            else:
                emoji = "🚨"
            
            message = (
                f"{emoji} *СРОЧНАЯ НОВОСТЬ*\n\n"
                f"📰 *{news.title}*\n"
                f"📍 Источник: {news.source}\n"
                f"🕒 {news.published.strftime('%H:%M %d.%m.%Y')}\n"
                f"🔗 [Читать]({news.link})"
            )
            
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                await asyncio.sleep(2)  # Пауза между сообщениями
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
    
    async def _send_sentiment_alert(self, sentiment: float):
        """Отправляет alert об изменении сентимента"""
        if not self.chat_id:
            logger.info(f"📊 Изменение сентимента: {sentiment:.2f}")
            return
        
        if sentiment > self.last_sentiment:
            trend = "📈 УЛУЧШАЕТСЯ"
            emoji = "🟢"
        else:
            trend = "📉 УХУДШАЕТСЯ"
            emoji = "🔴"
        
        change = sentiment - self.last_sentiment
        
        message = (
            f"{emoji} *ИЗМЕНЕНИЕ РЫНОЧНЫХ НАСТРОЕНИЙ*\n\n"
            f"Тренд: {trend}\n"
            f"Текущий сентимент: {sentiment:.2f}\n"
            f"Изменение: {change:+.2f}\n\n"
            f"💡 Используй /advice для детального анализа"
        )
        
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode='Markdown'
        )
    
    async def _send_market_analysis(self, analysis: Dict):
        """Отправляет полный анализ рынка"""
        if not self.chat_id:
            logger.info("🤖 Полный анализ рынка выполнен")
            return
        
        message = "🤖 *АВТОМАТИЧЕСКИЙ АНАЛИЗ РЫНКА*\n\n"
        message += self.ai_advisor.format_advice_message(analysis)
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки анализа: {e}")
    
    async def _send_activity_alert(self, news_count: int, diff: int):
        """Отправляет уведомление о высокой активности"""
        if not self.chat_id:
            logger.info(f"📊 Активность: {news_count} ({diff:+d})")
            return
        
        if diff > 0:
            message = (
                f"📊 *ПОВЫШЕННАЯ АКТИВНОСТЬ*\n\n"
                f"За последний час появилось {diff} новых новостей\n"
                f"Всего в ленте: {news_count}\n\n"
                f"Рекомендую проверить /news"
            )
        else:
            message = (
                f"📊 *СНИЖЕНИЕ АКТИВНОСТИ*\n\n"
                f"Новостей стало на {abs(diff)} меньше\n"
                f"Всего в ленте: {news_count}"
            )
        
        await self.bot.send_message(
            chat_id=self.chat_id,
            text=message,
            parse_mode='Markdown'
        )


# Функция для запуска мониторинга
async def start_monitoring(bot, chat_id: Optional[int] = None):
    """Запускает мониторинг для бота"""
    monitor = AIMarketMonitor(bot, chat_id)
    await monitor.start_monitoring()