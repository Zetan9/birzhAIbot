import feedparser
import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

RSS_URL = "https://rsshub.rss3.workers.dev/telegram/channel/moextrades"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def fetch_feed():
    try:
        response = requests.get(RSS_URL, headers=HEADERS, timeout=10)
        response.raise_for_status()
        feed = feedparser.parse(response.text)
        logger.info(f"RSS загружен, записей: {len(feed.entries)}")
        return feed
    except Exception as e:
        logger.error(f"Ошибка загрузки RSS: {e}")
        return None

def clean_html(html: str) -> str:
    """Удаляет HTML-теги, возвращает чистый текст."""
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text(separator=' ')

def parse_signal_from_item(item) -> Optional[Dict]:
    title = item.get('title', '')
    description = item.get('description', '')
    link = item.get('link', '')
    pub_date = item.get('published', '')

    # Очищаем описание от HTML
    clean_text = clean_html(description)
    logger.debug(f"Чистый текст: {clean_text[:200]}")

    # Определяем тип по эмодзи в заголовке
    if '📈' in title or '🟢' in title:
        signal_type = 'bullish'
    elif '🔴' in title or '📉' in title:
        signal_type = 'bearish'
    else:
        logger.debug("Не удалось определить тип сигнала, пропускаем")
        return None

    # Тикер (после #)
    ticker_match = re.search(r'#([A-Z]+)', title)
    if not ticker_match:
        logger.debug("Не найден тикер в заголовке")
        return None
    ticker = ticker_match.group(1)

    # Цена
    price_match = re.search(r'Цена:\s*([\d\.]+)', clean_text)
    price = float(price_match.group(1)) if price_match else None
    if not price:
        # Попробуем найти цену в другом формате (например, после "Цена: <b>")
        price_match = re.search(r'Цена:.*?([\d\.]+)', description, re.DOTALL)
        price = float(price_match.group(1)) if price_match else None

    # Изменение цены ΔP
    delta_p_match = re.search(r'ΔP\s*([+-]?[\d\.]+)%', clean_text)
    delta_p = float(delta_p_match.group(1)) if delta_p_match else None

    # Аномальный объём
    volume_match = re.search(r'Аномальный объём:\s*([\d\.]+)([МК]?)', clean_text)
    volume = None
    if volume_match:
        val = float(volume_match.group(1))
        unit = volume_match.group(2)
        if unit == 'М':
            volume = val * 1_000_000
        elif unit == 'К':
            volume = val * 1_000
        else:
            volume = val

    # Процент покупки/продажи
    buy_match = re.search(r'Покупка:\s*(\d+)%', clean_text)
    sell_match = re.search(r'Продажа:\s*(\d+)%', clean_text)
    buy_pct = int(buy_match.group(1)) if buy_match else None
    sell_pct = int(sell_match.group(1)) if sell_match else None

    # Время сигнала
    time_match = re.search(r'Время:\s*([\d\.: ]+)', clean_text)
    if time_match:
        try:
            signal_time = datetime.strptime(time_match.group(1), '%d.%m.%Y %H:%M:%S')
        except Exception as e:
            logger.debug(f"Ошибка парсинга времени: {e}")
            signal_time = datetime.now()
    else:
        signal_time = datetime.now()

    post_id = link.split('/')[-1] if link else None

    signal = {
        'id': post_id,
        'ticker': ticker,
        'type': signal_type,
        'price': price,
        'delta_p': delta_p,
        'volume': volume,
        'buy_pct': buy_pct,
        'sell_pct': sell_pct,
        'time': signal_time,
        'raw_text': description[:200]
    }
    logger.debug(f"Найден сигнал: {signal}")
    return signal

def fetch_signals(limit: int = 50) -> List[Dict]:
    feed = fetch_feed()
    if not feed:
        return []
    signals = []
    for entry in feed.entries[:limit]:
        sig = parse_signal_from_item(entry)
        if sig:
            signals.append(sig)
    logger.info(f"Получено {len(signals)} сигналов из RSS")
    return signals