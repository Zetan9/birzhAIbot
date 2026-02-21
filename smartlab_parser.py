"""
Модуль для парсинга RSS-ленты Smart-Lab.
"""
import feedparser
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import requests
import os
import uuid
from urllib.parse import urljoin
from bs4 import BeautifulSoup

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
    image_path: Optional[str] = None

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
        # Кэш для URL страниц: {url: image_path or None}
        self.image_cache = {}
        # Стоп-слова в URL картинок (реклама, иконки, аватарки)
        self.url_blacklist = [
            'banner', 'advert', 'adv/', 'promo', 'sponsored',
            'avatar', 'icon', 'logo', 'favicon', 'pixel',
            'doubleclick', 'yandex.ru', 'googleads', 'mail.ru',
            'counter', 'tracker', 'analytics'
        ]

    def _extract_image_from_url(self, url: str) -> Optional[str]:
        """Загружает HTML страницы, извлекает первое подходящее изображение и сохраняет его локально."""
        # Проверяем кэш
        if url in self.image_cache:
            cached = self.image_cache[url]
            logger.debug(f"Использую кэш для {url}: {cached}")
            return cached

        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                self.image_cache[url] = None
                return None

            soup = BeautifulSoup(response.text, 'html.parser')

            # 1. Open Graph (самый надёжный)
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = str(og_image['content'])
                if not self._is_ad_url(img_url):
                    downloaded = self._download_image(img_url)
                    self.image_cache[url] = downloaded
                    return downloaded

            # 2. Ищем контейнер поста (классы Smart-Lab)
            post_container = soup.find('div', class_=re.compile(r'content|post-text|blog-post|article'))
            if post_container:
                # Ищем все картинки внутри контейнера
                images = post_container.find_all('img')
                for img in images:
                    src_val = img.get('src')
                    if src_val is None:
                        continue
                    # Преобразуем в строку
                    if isinstance(src_val, list):
                        src = str(src_val[0]) if src_val else None
                    else:
                        src = str(src_val)
                    if src and not self._is_ad_url(src):
                        full_url = urljoin(url, src)
                        downloaded = self._download_image(full_url)
                        if downloaded:
                            self.image_cache[url] = downloaded
                            return downloaded

            # 3. Перебираем все картинки, фильтруем
            for img_tag in soup.find_all('img'):
                src_val = img_tag.get('src')
                if src_val is None:
                    continue
                if isinstance(src_val, list):
                    src = str(src_val[0]) if src_val else None
                else:
                    src = str(src_val)
                if not src:
                    continue
                full_url = urljoin(url, src)

                # Пропускаем рекламу по URL
                if self._is_ad_url(full_url):
                    continue

                # Проверяем размер (если есть атрибуты width/height)
                # Проверяем размер (если есть атрибуты width/height)
                width_val = img_tag.get('width')
                height_val = img_tag.get('height')

                # Если значение — список (например, для class, но width не должен быть списком, но на всякий случай)
                if isinstance(width_val, list):
                    width_val = width_val[0] if width_val else None
                if isinstance(height_val, list):
                    height_val = height_val[0] if height_val else None

                try:
                    w = int(width_val) if width_val is not None else None
                    h = int(height_val) if height_val is not None else None
                    if w is not None and w < 150 or h is not None and h < 150:
                        continue  # слишком маленькая, вероятно иконка
                except (ValueError, TypeError):
                    pass

                # Проверяем классы на рекламу (безопасное получение)
                cls = img_tag.get('class')
                if cls is None:
                    cls = []
                elif not isinstance(cls, list):
                    cls = [cls]  # если строка, превращаем в список
                if any('banner' in c or 'adv' in c or 'advert' in c for c in cls if isinstance(c, str)):
                    continue

                downloaded = self._download_image(full_url)
                self.image_cache[url] = downloaded
                return downloaded

        except Exception as e:
            logger.debug(f"Не удалось извлечь картинку из {url}: {e}")

        self.image_cache[url] = None
        return None

    def _is_ad_url(self, img_url: str) -> bool:
        """Проверяет, содержит ли URL картинки рекламные/мусорные слова."""
        img_url_lower = img_url.lower()
        for word in self.url_blacklist:
            if word in img_url_lower:
                logger.debug(f"Пропущена рекламная картинка: {img_url} (содержит {word})")
                return True
        return False

    def _safe_get_str(self, value: Any, default: str = "") -> str:
        """Безопасно преобразует значение в строку, обрабатывая списки и None."""
        if value is None:
            return default
        if isinstance(value, list):
            return str(value[0]) if value else default
        return str(value)

    def _download_image(self, img_url: str) -> Optional[str]:
        """Скачивает изображение в папку smartlab_images."""
        try:
            os.makedirs('smartlab_images', exist_ok=True)
            ext = os.path.splitext(img_url.split('?')[0])[1]
            if not ext or ext.lower() not in ('.jpg', '.jpeg', '.png', '.gif'):
                ext = '.jpg'
            filename = f"smartlab_{uuid.uuid4().hex}{ext}"
            filepath = os.path.join('smartlab_images', filename)

            response = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                logger.info(f"✅ Сохранено изображение: {filepath}")
                return filepath
        except Exception as e:
            logger.debug(f"Не удалось скачать {img_url}: {e}")
        return None

    def fetch_posts(self, limit: int = 20) -> List[SmartLabPost]:
        """Получает последние посты из RSS-ленты."""
        try:
            feed = feedparser.parse(self.RSS_URL)
            posts = []
            for entry in feed.entries[:limit]:
                # Безопасное извлечение строк
                title = self._safe_get_str(entry.get('title'))
                link = self._safe_get_str(entry.get('link'))
                published = self._parse_date(self._safe_get_str(entry.get('published')))
                summary = self._safe_get_str(entry.get('description'))
                author = self._safe_get_str(entry.get('author', 'Неизвестно'))

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

                # Определяем, нужно ли скачивать картинку
                should_download = False
                if tickers:
                    should_download = True
                else:
                    # Ключевые слова для отбора (можно дополнить)
                    important_keywords = [
                        'график', 'анализ', 'обзор', 'технический', 'фундаментальный',
                        'дивиденды', 'отчет', 'рекомендация', 'прогноз', 'trend', 'chart',
                        'индекс', 'рынок', 'акции', 'инвестиции', 'стратегия', 'доходность',
                        'свечи', 'уровни', 'поддержка', 'сопротивление', 'тренд'
                    ]
                    text_lower = (title + " " + summary).lower()
                    if any(keyword in text_lower for keyword in important_keywords):
                        should_download = True

                image_path = None
                if should_download and link:
                    image_path = self._extract_image_from_url(link)
                # иначе image_path остаётся None

                post = SmartLabPost(
                    title=title,
                    link=link,
                    published=published,
                    summary=summary[:200] + '...' if len(summary) > 200 else summary,
                    author=author,
                    tickers=tickers,
                    sentiment_score=sentiment_score,
                    sentiment_category=sentiment_category,
                    image_path=image_path
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
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str)
        except:
            return datetime.now()