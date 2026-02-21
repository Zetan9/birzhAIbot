"""
Модуль для парсинга RSS-ленты Smart-Lab.
"""
import feedparser
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class SmartLabPost:
    title: str
    link: str
    published: datetime
    summary: str
    author: str
    tickers: List[str] = field(default_factory=list)
    sentiment_score: Optional[float] = None
    sentiment_category: str = 'neutral'

class SmartLabParser:
    """Парсер RSS-ленты Smart-Lab."""
    
    RSS_URL = "https://smart-lab.ru/rss/"
    
    # Список тикеров для поиска (можно расширить)
    TICKER_PATTERNS = {
        'SBER': r'\bSBER\b',
        'GAZP': r'\bGAZP\b',
        'LKOH': r'\bLKOH\b',
        'YDEX': r'\bYDEX\b',
        'VTBR': r'\bVTBR\b',
        'ROSN': r'\bROSN\b',
        'GMKN': r'\bGMKN\b',
        'TATN': r'\bTATN\b',
        'MTSS': r'\bMTSS\b',
        'CHMF': r'\bCHMF\b',
        'NLMK': r'\bNLMK\b',
        'PLZL': r'\bPLZL\b',
        'ALRS': r'\bALRS\b',
        'MGNT': r'\bMGNT\b',
        'FIVE': r'\bFIVE\b',
        'IRAO': r'\bIRAO\b',
        'HYDR': r'\bHYDR\b',
        'NVTK': r'\bNVTK\b',
    }
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def fetch_posts(self, limit: int = 20) -> List[SmartLabPost]:
        """Получает последние посты из RSS-ленты."""
        try:
            feed = feedparser.parse(self.RSS_URL)
            posts = []
            for entry in feed.entries[:limit]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                published = self._parse_date(entry.get('published', ''))
                summary = entry.get('description', '')
                author = entry.get('author', 'Неизвестно')

                # Ищем тикеры в заголовке и описании
                tickers = self._extract_tickers(title + " " + summary)

                # Простой анализ сентимента
                sentiment_score = self._simple_sentiment(title + " " + summary)
                if sentiment_score > 0.2:
                    sentiment_category = 'positive'
                elif sentiment_score < -0.2:
                    sentiment_category = 'negative'
                else:
                    sentiment_category = 'neutral'

                post = SmartLabPost(
                    title=title,
                    link=link,
                    published=published,
                    summary=summary[:200] + '...' if len(summary) > 200 else summary,
                    author=author,
                    tickers=tickers,
                    sentiment_score=sentiment_score,
                    sentiment_category=sentiment_category
                )
                posts.append(post)
            return posts
        except Exception as e:
            logger.error(f"Ошибка при парсинге Smart-Lab: {e}")
            return []

    def _extract_tickers(self, text: str) -> List[str]:
        """Извлекает тикеры из текста."""
        found = []
        for ticker, pattern in self.TICKER_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                found.append(ticker)
        return found

    def _simple_sentiment(self, text: str) -> float:
        """Простой анализ сентимента."""
        text_lower = text.lower()
        positive = ['растет', 'вырастет', 'прибыль', 'дивиденды', 'успех', 'дорожает', 'buy', 'long']
        negative = ['падает', 'упадет', 'убыток', 'проблемы', 'кризис', 'дешевеет', 'sell', 'short']
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        if pos_count + neg_count == 0:
            return 0
        return (pos_count - neg_count) / (pos_count + neg_count)

    def _parse_date(self, date_str: str) -> datetime:
        """Парсит дату из RSS."""
        try:
            # Пример формата: "Sat, 21 Feb 2026 10:00:00 +0300"
            # feedparser умеет парсить, но возвращает struct_time; преобразуем
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except:
            return datetime.now()