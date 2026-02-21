"""
Модуль для парсинга Tinkoff Пульс (неофициальное API).
"""
import requests
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class PulsePost:
    id: str
    text: str
    author: str
    likes: int
    comments: int
    date: datetime
    tickers: List[str] = field(default_factory=list)
    sentiment_score: Optional[float] = None
    sentiment_category: str = 'neutral'

class TinkoffPulseParser:
    """Класс для получения данных из Tinkoff Пульс."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.base_urls = [
            "https://api.tinkoff.ru/trading/social/api/v1",
            "https://www.tinkoff.ru/api/trading/social"
        ]
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Origin': 'https://www.tinkoff.ru',
            'Referer': 'https://www.tinkoff.ru/invest/social/feed/'
        }
        # Добавляем Authorization только если токен передан и не пустой
        if token and token.strip():
            self.headers['Authorization'] = f'Bearer {token}'

    def get_feed(self, limit: int = 20, offset: int = 0, retries: int = 2) -> List[PulsePost]:
        """
        Получает ленту постов (основная лента) с повторными попытками.
        """
        for base_url in self.base_urls:
            url = f"{base_url}/feed"
            params = {'limit': limit, 'offset': offset}
            try:
                logger.info(f"Пробуем URL: {url}")
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_posts(data)
                elif response.status_code == 202:
                    logger.warning(f"URL {url} вернул 202, пробуем следующий...")
                    time.sleep(1)
                else:
                    logger.error(f"URL {url} вернул {response.status_code}, текст: {response.text[:200]}")
            except Exception as e:
                logger.error(f"Ошибка при запросе {url}: {e}")
        return []

    def get_posts_by_ticker(self, ticker: str, limit: int = 20) -> List[PulsePost]:
        """
        Получает посты, упоминающие конкретный тикер.
        """
        for base_url in self.base_urls:
            url = f"{base_url}/instruments/{ticker}/posts"
            params = {'limit': limit, 'offset': 0}
            try:
                logger.info(f"Пробуем URL для тикера {ticker}: {url}")
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_posts(data)
                elif response.status_code == 202:
                    logger.warning(f"URL {url} вернул 202, пробуем следующий...")
                    time.sleep(1)
                else:
                    logger.error(f"URL {url} вернул {response.status_code}")
            except Exception as e:
                logger.error(f"Ошибка при запросе {ticker}: {e}")
        return []

    def _parse_posts(self, data: Dict) -> List[PulsePost]:
        """
        Парсит ответ API и возвращает список постов.
        """
        posts = []
        # Разные возможные структуры ответа
        items = []
        if 'payload' in data and 'items' in data['payload']:
            items = data['payload']['items']
        elif 'items' in data:
            items = data['items']
        elif isinstance(data, list):
            items = data

        for item in items:
            try:
                post_id = item.get('id')
                text = item.get('text', '')
                author = item.get('author', {}).get('nickname', 'Неизвестно')
                likes = item.get('likes', {}).get('count', 0) if isinstance(item.get('likes'), dict) else item.get('likes', 0)
                comments = item.get('comments', {}).get('count', 0) if isinstance(item.get('comments'), dict) else item.get('comments', 0)
                date_str = item.get('createdAt', '')
                date = self._parse_date(date_str)

                # Извлекаем тикеры
                tickers = []
                if 'instruments' in item:
                    for instr in item['instruments']:
                        ticker = instr.get('ticker')
                        if ticker:
                            tickers.append(ticker)

                # Простой анализ сентимента
                sentiment_score = self._simple_sentiment(text)
                if sentiment_score > 0.2:
                    sentiment_category = 'positive'
                elif sentiment_score < -0.2:
                    sentiment_category = 'negative'
                else:
                    sentiment_category = 'neutral'

                post = PulsePost(
                    id=post_id,
                    text=text,
                    author=author,
                    likes=likes,
                    comments=comments,
                    date=date,
                    tickers=tickers,
                    sentiment_score=sentiment_score,
                    sentiment_category=sentiment_category
                )
                posts.append(post)
            except Exception as e:
                logger.debug(f"Ошибка парсинга поста: {e}")
        return posts

    def _parse_date(self, date_str: str) -> datetime:
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return datetime.now()

    def _simple_sentiment(self, text: str) -> float:
        """Простой анализ на основе ключевых слов."""
        text_lower = text.lower()
        positive = ['растет', 'вырастет', 'прибыль', 'дивиденды', 'успех', 'дорожает', 'buy', 'long']
        negative = ['падает', 'упадет', 'убыток', 'проблемы', 'кризис', 'дешевеет', 'sell', 'short']
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        if pos_count + neg_count == 0:
            return 0
        return (pos_count - neg_count) / (pos_count + neg_count)