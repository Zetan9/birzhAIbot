"""
Модуль для сбора и парсинга финансовых новостей с улучшенной фильтрацией
"""

import feedparser
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
import logging
from dataclasses import dataclass, field
import requests
import hashlib
import re
import dateutil.parser
import os
import uuid
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)

@dataclass
class NewsItem:
    """Класс для представления новости"""
    source: str
    title: str
    summary: str
    link: str
    published: datetime
    related_tickers: List[str] = field(default_factory=list)
    sentiment_score: Optional[float] = None
    importance: float = 1.0
    language: str = 'ru'
    category: str = 'unknown'  # finance, economy, politics, other
    image_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source': self.source,
            'title': self.title,
            'summary': self.summary,
            'link': self.link,
            'published': self.published,
            'related_tickers': self.related_tickers,
            'sentiment_score': self.sentiment_score,
            'importance': self.importance,
            'language': self.language,
            'category': self.category
        }

class NewsParser:
    """Класс для сбора и фильтрации финансовых новостей"""
    
    def __init__(self, finance_only: bool = True):
        self.finance_only = finance_only
        
        # ТОЛЬКО РОССИЙСКИЕ ИСТОЧНИКИ (можно дополнить)
        self.rss_sources = {
            # Официальные источники
            'cbr': 'https://www.cbr.ru/rss/eventrss',
            'minfin': 'https://minfin.gov.ru/ru/rss/',
            'economy': 'https://economy.gov.ru/rss/feed',
            
            # Информационные агентства
            'interfax': 'http://www.interfax.ru/rss.asp',
            'tass': 'http://tass.ru/rss/v2.xml',
            'ria': 'https://ria.ru/export/rss2/economy/index.xml',
            'prime': 'https://1prime.ru/export/rss2/index.xml',
            'finmarket': 'https://www.finmarket.ru/rss/mainnews.asp',
            'finam': 'https://www.finam.ru/analysis/conferences/export/rsspoint.asp',
            
            # Деловые СМИ
            'rbc': 'https://rssexport.rbc.ru/rbcnews/news/30/full.sn',
            'kommersant': 'https://www.kommersant.ru/RSS/main.xml',
            'vedomosti': 'https://vedomosti.ru/rss/news',
            'forbes_russia': 'https://www.forbes.ru/rss',
            'bfm': 'https://www.bfm.ru/rss',
            'dp': 'https://www.dp.ru/rss/all.xml',
            
            # Нефть и газ
            'oilru': 'https://oilru.com/news/rss/',
            'neftegaz': 'https://neftegaz.ru/export/rss/',
            'oilcapital': 'https://oilcapital.ru/export/rss/',
            
            # Металлы и добыча
            'metaltorg': 'https://www.metaltorg.ru/export/rss/',
            
            # Инвестиционные порталы
            'investing': 'https://www.investing.com/rss/news.rss',
            'smartlab': 'https://smart-lab.ru/rss/',
            'bcs_express': 'https://bcs-express.ru/rss/all',
            'tinkoff_invest': 'https://www.tinkoff.ru/api/v1/rss/invest',
        }
        
        # Ключевые слова для фильтрации (только экономика/финансы)
        self.finance_keywords = [
            # Русские
            'акци', 'рубль', 'доллар', 'нефть', 'газ', 'рынок', 'инвестиц',
            'прибыль', 'убыток', 'капитал', 'биржа', 'котировк', 'индекс',
            'сбер', 'газпром', 'лукойл', 'роснефть', 'яндекс', 'акция',
            'дивиденд', 'отчет', 'финанс', 'экономик', 'бизнес', 'торги',
            'росс', 'компани', 'корпорац', 'банк', 'кредит', 'ставк',
            'московская биржа', 'moex', 'rts', 'инвестор', 'портфель',
            'фондовый', 'облигац', 'валюта', 'инфляц', 'ввп', 'бюджет',
            'налог', 'пошлин', 'санкц', 'эмбарго', 'дефолт', 'кризис',
            'рецесси', 'ставка', 'ключевая', 'цебо', 'центробанк',
            'сбербанк', 'втб', 'тинькофф', 'мосбиржа', 'спб биржа',
            
            # English
            'stock', 'market', 'invest', 'trading', 'finance', 'econom',
            'fed', 'federal reserve', 'inflation', 'gdp', 'oil', 'gas',
            'commodity', 'gold', 'silver', 'copper', 'bond', 'yield',
            'dividend', 'earnings', 'revenue', 'profit', 'loss',
            'bank', 'credit', 'loan', 'mortgage', 'rate', 'interest',
            'dollar', 'euro', 'currency', 'forex', 'crypto',
            'sberbank', 'gazprom', 'lukoil', 'yandex', 'rosneft',
            'moex', 'rts', 'micex', 'tinkoff', 'vtb'
        ]
        
        # Стоп-слова (новости для отбрасывания)
        self.stop_keywords = [
            # Спорт
            'футбол', 'хоккей', 'теннис', 'олимпиад', 'чемпионат', 'турнир',
            'спорт', 'матч', 'игрок', 'тренер', 'стадион', 'гол', 'счет',
            
            # Шоу-бизнес
            'актрис', 'актер', 'певец', 'певиц', 'фильм', 'кино', 'сериал',
            'шоу', 'ведущ', 'звезд', 'знаменитост', 'светская жизнь',
            
            # Погода
            'погод', 'дождь', 'снег', 'ветер', 'температур', 'похолодание',
            'потепление', 'циклон', 'антициклон',
            
            # Разное
            'рецепт', 'кулинар', 'здоровье', 'медицин', 'коронавирус',
            'covid', 'праздник', 'поздравление', 'день рождения',
            'гороскоп', 'магия', 'эзотерик'
        ]
        
        # Торговые пары (тикер -> названия компаний)
        self.company_tickers = {
            'SBER': ['сбербанк', 'сбер', 'sberbank', 'sber'],
            'VTBR': ['втб', 'vtb', 'vtbr'],
            'TCSG': ['тинькофф', 'тбанк', 'tinkoff', 'tcs'],
            'GAZP': ['газпром', 'gazprom'],
            'LKOH': ['лукойл', 'lukoil'],
            'ROSN': ['роснефть', 'rosneft'],
            'TATN': ['татнефть', 'tatneft'],
            'NVTK': ['новатэк', 'novatek'],
            'YDEX': ['яндекс', 'yandex', 'ydex'],
            'GMKN': ['норникель', 'nornickel'],
            'MTSS': ['мтс', 'mts'],
            'CHMF': ['северсталь', 'severstal'],
            'NLMK': ['нлмк', 'nlmk'],
            'PLZL': ['полюс', 'polyus'],
            'ALRS': ['алроса', 'alrosa'],
            'MGNT': ['магнит', 'magnit'],
            'FIVE': ['х5', 'x5', 'пятерочка'],
        }
        
        # Кэш для избежания дубликатов
        self.seen_links = set()
        self.seen_titles = set()
        
        logger.info(f"✅ NewsParser инициализирован с {len(self.rss_sources)} источниками")
        if self.finance_only:
            logger.info("💰 Режим: только финансовые новости")

    def _safe_get_str(self, value, default: str = "") -> str:
        """
        Безопасно преобразует значение в строку, обрабатывая списки и None.
        """
        if value is None:
            return default
        if isinstance(value, list):
            # Если пришёл список, берём первый элемент или пустую строку
            return str(value[0]) if value else default
        return str(value)

    def is_finance_news(self, title: str, summary: str = "") -> bool:
        """Проверяет, относится ли новость к финансам/экономике"""
        text = (title + " " + summary).lower()
        
        # Проверяем стоп-слова (если есть - не финансы)
        for word in self.stop_keywords:
            if word in text:
                return False
        
        # Проверяем ключевые слова финансов
        finance_count = 0
        for word in self.finance_keywords:
            if word in text:
                finance_count += 1
                if finance_count >= 2:  # Достаточно 2 совпадений
                    return True
        
        # Если есть тикеры - точно финансы
        if self._find_tickers(text):
            return True
        
        return finance_count >= 1  # Хотя бы 1 совпадение
    
    def fetch_all_news(self, limit_per_source: int = 3, max_total: int = 50) -> List[NewsItem]:
        """Собирает новости из всех источников с фильтрацией"""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        all_news = []
        self.seen_links.clear()
        self.seen_titles.clear()
        
        logger.info(f"📡 Сбор новостей из {len(self.rss_sources)} источников...")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_source = {
                executor.submit(self.fetch_from_source, source_name, url, limit_per_source): source_name
                for source_name, url in self.rss_sources.items()
            }
            
            for future in as_completed(future_to_source):
                source_name = future_to_source[future]
                try:
                    news_items = future.result(timeout=15)
                    
                    # Фильтруем только финансовые новости
                    if self.finance_only:
                        finance_news = [
                            item for item in news_items 
                            if self.is_finance_news(item.title, item.summary)
                        ]
                        logger.info(f"✅ {source_name}: {len(news_items)} → {len(finance_news)} фин.")
                        all_news.extend(finance_news)
                    else:
                        all_news.extend(news_items)
                        
                except Exception as e:
                    logger.warning(f"❌ {source_name}: {e}")
        
        # Убираем дубликаты
        unique_news = self._deduplicate_news(all_news)
        
        # Сортируем по дате
        unique_news.sort(key=lambda x: x.published, reverse=True)
        
        logger.info(f"📰 Всего собрано: {len(unique_news)} уникальных финансовых новостей")
        return unique_news[:max_total]
    
    def _extract_image_from_url(self, url: str, source_name: str) -> Optional[str]:
        """
        Загружает HTML страницы, извлекает первое подходящее изображение и сохраняет его локально.
        Возвращает путь к сохранённому файлу или None.
        """
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return None
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем Open Graph изображение (самое важное для соцсетей)
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                img_url = str(og_image['content'])  # ← добавить str()
                return self._download_image(img_url, source_name)
            
            # Иначе ищем первую картинку в статье (тег <img>)
            img_tag = soup.find('img', class_=re.compile(r'(article|news|content|main)'))
            if not img_tag:
                img_tag = soup.find('img')
            if img_tag and img_tag.get('src'):
                img_url = str(img_tag['src'])  # ← добавить str()
                img_url = urljoin(url, img_url)
                return self._download_image(img_url, source_name)
        except Exception as e:
            logger.debug(f"Не удалось извлечь картинку из {url}: {e}")
        return None

    def _download_image(self, img_url: str, source_name: str) -> Optional[str]:
        """
        Скачивает изображение и сохраняет в папку 'news_images'.
        Возвращает путь к файлу или None.
        """
        try:
            # Создаём папку, если её нет
            os.makedirs('news_images', exist_ok=True)
            # Уникальное имя файла
            ext = os.path.splitext(img_url.split('?')[0])[1]
            if not ext or ext.lower() not in ('.jpg', '.jpeg', '.png', '.gif'):
                ext = '.jpg'  # по умолчанию
            filename = f"{source_name}_{uuid.uuid4().hex}{ext}"
            filepath = os.path.join('news_images', filename)
            
            response = requests.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                logger.info(f"✅ Сохранено изображение: {filepath}")
                return filepath
        except Exception as e:
            logger.debug(f"Не удалось скачать {img_url}: {e}")
        return None

    def fetch_from_source(self, source_name: str, url: str, limit: int) -> List[NewsItem]:
        """Собирает новости из одного источника"""
        news_list = []
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=10)
            
            # Пробуем определить кодировку
            if source_name == 'finmarket':
                # Для finmarket принудительно ставим windows-1251
                response.encoding = 'windows-1251'
            else:
                # Для остальных - автоопределение
                response.encoding = response.apparent_encoding or 'utf-8'
            
            logger.info(f"📡 {source_name}: кодировка {response.encoding}")
            feed = feedparser.parse(response.text)
            
            for entry in feed.entries[:limit]:
                try:
                    title = self._safe_get_str(entry.get('title'))
                    # summary может быть в полях summary или description
                    summary = self._safe_get_str(entry.get('summary'))
                    if not summary:
                        summary = self._safe_get_str(entry.get('description', ''))
                    link = self._safe_get_str(entry.get('link'))
                    
                    # Пропускаем пустые заголовки
                    if not title or len(title) < 10:
                        continue
                    
                    published = self._parse_date(entry)
                    
                    # Проверяем дубликаты
                    if link in self.seen_links or title in self.seen_titles:
                        continue
                    
                    # Определяем категорию
                    text = f"{title} {summary}".lower()
                    category = self._determine_category(text)
                    
                    # Ищем тикеры
                    related_tickers = self._find_tickers(text)
                    
                    # Важность
                    importance = self._calculate_importance(title, source_name)
                    
                    # Язык (примитивно)
                    language = 'ru' if any(c in title.lower() for c in ['а','б','в','г','д']) else 'en'
                    
                    # Обрезаем summary при необходимости
                    if len(summary) > 300:
                        summary = summary[:300] + '...'
                    
                    # Извлечение картинки (если есть)
                    image_path = None
                    
                    if link:
                        image_path = self._extract_image_from_url(str(link), source_name)

                    news_item = NewsItem(
                        source=source_name,
                        title=title,
                        summary=summary,
                        link=link,
                        published=published,
                        related_tickers=related_tickers,
                        importance=importance,
                        language=language,
                        category=category,
                        image_path=image_path,
                    )
                    
                    news_list.append(news_item)
                    
                except Exception as e:
                    logger.debug(f"Ошибка обработки записи: {e}")
                    continue
            
        except Exception as e:
            logger.debug(f"Ошибка загрузки {source_name}: {e}")
        
        return news_list
    
    def _determine_category(self, text: str) -> str:
        """Определяет категорию новости"""
        categories = {
            'macro': ['ввп', 'инфляция', 'ставка', 'цб', 'минфин', 'бюджет', 'налоги'],
            'company': ['отчет', 'прибыль', 'дивиденды', 'акции', 'собрание'],
            'oil_gas': ['нефть', 'газ', 'баррель', 'газпром', 'лукойл'],
            'metal': ['металл', 'золото', 'серебро', 'медь', 'норникель'],
            'bank': ['банк', 'сбер', 'втб', 'кредит', 'ипотека'],
            'tech': ['технологии', 'яндекс', 'it', 'компьютер'],
        }
        
        for cat, keywords in categories.items():
            for kw in keywords:
                if kw in text:
                    return cat
        
        return 'finance'
    
    def _find_tickers(self, text: str) -> List[str]:
        """Находит тикеры в тексте"""
        found = set()
        text_lower = text.lower()
        
        for ticker, keywords in self.company_tickers.items():
            for keyword in keywords:
                if keyword in text_lower:
                    found.add(ticker)
                    break
        
        return list(found)
    
    def _calculate_importance(self, title: str, source: str) -> float:
        """Рассчитывает важность новости"""
        importance = 1.0
        
        important_words = ['кризис', 'обвал', 'рост', 'падение', 'санкции', 
                          'рекорд', 'прибыль', 'дивиденды', 'слияние', 'поглощение',
                          'война', 'эмбарго', 'дефолт', 'шок']
        
        title_lower = title.lower()
        for word in important_words:
            if word in title_lower:
                importance += 0.3
        
        important_sources = ['interfax', 'tass', 'rbc', 'reuters', 'bloomberg']
        if source in important_sources:
            importance += 0.2
        
        return min(importance, 2.5)

    def _parse_date(self, entry) -> datetime:
        """
        Парсит дату из RSS и конвертирует в московское время (MSK, UTC+3)
        """
        # По умолчанию - текущее московское время
        msk_time = datetime.now() + timedelta(hours=3)
        
        try:
            # Способ 1: через published_parsed (структурированная дата от feedparser)
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                time_tuple = entry.published_parsed
                if time_tuple and len(time_tuple) >= 6:
                    # feedparser возвращает время в UTC
                    dt_utc = datetime(
                        int(time_tuple[0]),  # год
                        int(time_tuple[1]),  # месяц
                        int(time_tuple[2]),  # день
                        int(time_tuple[3]),  # час
                        int(time_tuple[4]),  # минута
                        int(time_tuple[5]),  # секунда
                        tzinfo=timezone.utc  # Явно указываем, что это UTC
                    )
                    # Конвертируем в московское время (UTC+3)
                    dt_msk = dt_utc.astimezone(timezone(timedelta(hours=3)))
                    # Убираем информацию о часовом поясе для совместимости
                    return dt_msk.replace(tzinfo=None)
            
            # Способ 2: через published (строка с датой)
            if hasattr(entry, 'published') and entry.published:
                try:
                    # Парсим строку с датой
                    dt_parsed = dateutil.parser.parse(entry.published)
                    
                    # Если в дате нет часового пояса, считаем что это UTC
                    if dt_parsed.tzinfo is None:
                        dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
                    
                    # Конвертируем в MSK
                    dt_msk = dt_parsed.astimezone(timezone(timedelta(hours=3)))
                    return dt_msk.replace(tzinfo=None)
                    
                except Exception as e:
                    logger.debug(f"Не удалось распарсить строку даты: {e}")
            
            # Способ 3: через updated (если есть)
            if hasattr(entry, 'updated') and entry.updated:
                try:
                    dt_parsed = dateutil.parser.parse(entry.updated)
                    if dt_parsed.tzinfo is None:
                        dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
                    dt_msk = dt_parsed.astimezone(timezone(timedelta(hours=3)))
                    return dt_msk.replace(tzinfo=None)
                except Exception as e:
                    logger.debug(f"Не удалось распарсить updated: {e}")
                    
        except Exception as e:
            logger.warning(f"Ошибка при парсинге даты: {e}")
        
        # Если ничего не сработало, возвращаем текущее московское время
        return msk_time
    
    def _deduplicate_news(self, news_list: List[NewsItem]) -> List[NewsItem]:
        """Убирает дубликаты новостей"""
        seen = set()
        unique = []
        
        for news in news_list:
            key = hashlib.md5(f"{news.title}{news.link}".encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                unique.append(news)
        
        return unique
    
    def get_finance_news(self, hours: int = 24) -> List[NewsItem]:
        """Получает только финансовые новости за последние N часов"""
        all_news = self.fetch_all_news(limit_per_source=3, max_total=100)
        
        cutoff = datetime.now() - timedelta(hours=hours)
        
        return [news for news in all_news if news.published > cutoff]
    
    def get_news_by_ticker(self, ticker: str, hours: int = 24) -> List[NewsItem]:
        """Получает новости по конкретному тикеру за последние N часов"""
        all_news = self.fetch_all_news(limit_per_source=3, max_total=100)
        
        ticker = ticker.upper()
        cutoff = datetime.now() - timedelta(hours=hours)
        
        filtered = [
            news for news in all_news
            if news.published > cutoff and ticker in news.related_tickers
        ]
        
        return filtered


# Функция для тестирования
def test_news_parser():
    parser = NewsParser(finance_only=True)
    news = parser.fetch_all_news(limit_per_source=2, max_total=20)
    
    print(f"\n{'='*60}")
    print(f"💰 ФИНАНСОВЫЕ НОВОСТИ ({len(news)})")
    print('='*60)
    
    # Статистика по категориям
    categories = {}
    for item in news:
        cat = item.category
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"\n📊 Категории:")
    for cat, count in categories.items():
        print(f"  {cat}: {count}")
    
    print(f"\n{'='*60}")
    
    for i, item in enumerate(news, 1):
        tickers = f" [{', '.join(item.related_tickers)}]" if item.related_tickers else ""
        print(f"\n{i}. [{item.source}] {item.category} {tickers}")
        print(f"   {item.title[:100]}...")
        print(f"   🕒 {item.published.strftime('%H:%M %d.%m')}")


if __name__ == "__main__":
    test_news_parser()