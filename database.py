"""
Модуль для работы с базой данных
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
from news_parser import NewsItem
import json
import logging

logger = logging.getLogger(__name__)

class NewsDatabase:
    """Класс для работы с базой данных новостей"""
    
    def __init__(self, db_path: str = "news.db"):
        """
        Args:
            db_path: путь к файлу базы данных
        """
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Создает таблицы, если их нет"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица для новостей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    link TEXT UNIQUE,
                    published TIMESTAMP,
                    related_tickers TEXT,
                    sentiment_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица для подписок пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, ticker)
                )
            ''')
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Список инструментов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS instruments (
                    ticker TEXT PRIMARY KEY,
                    figi TEXT,
                    name TEXT,
                    sector TEXT,
                    currency TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            
        logger.info("База данных инициализирована")

    def save_instruments(self, instruments: List[Dict]) -> int:
        saved = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for inst in instruments:
                try:
                    cursor.execute('''
                        INSERT OR REPLACE INTO instruments (ticker, figi, name, sector, currency)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (inst['ticker'], inst['figi'], inst['name'], inst['sector'], inst['currency']))
                    saved += 1
                except Exception as e:
                    logger.error(f"Ошибка сохранения {inst['ticker']}: {e}")
            conn.commit()
        logger.info(f"💾 Сохранено {saved} инструментов")
        return saved

    def get_all_tickers(self) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ticker FROM instruments ORDER BY ticker')
            return [row[0] for row in cursor.fetchall()]

    def update_user_activity(self, user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (user_id, first_name, username, last_seen)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = COALESCE(EXCLUDED.first_name, first_name),
                    username = COALESCE(EXCLUDED.username, username),
                    last_seen = CURRENT_TIMESTAMP
            ''', (user_id, first_name, username))
            conn.commit()

    def get_user_stats(self) -> dict:
        """Возвращает статистику пользователей."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            total = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM users WHERE last_seen > datetime("now", "-1 day")')
            day_active = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM users WHERE last_seen > datetime("now", "-7 day")')
            week_active = cursor.fetchone()[0]
            return {'total': total, 'day_active': day_active, 'week_active': week_active}

    def save_news(self, news_items: List[NewsItem]) -> int:
        """
        Сохраняет новости в базу данных
        
        Args:
            news_items: список объектов NewsItem
        
        Returns:
            количество сохраненных новостей
        """
        saved_count = 0
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            for item in news_items:
                try:
                    # Преобразуем список тикеров в JSON строку
                    tickers_json = json.dumps(item.related_tickers, ensure_ascii=False)
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO news 
                        (source, title, summary, link, published, related_tickers)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        item.source,
                        item.title,
                        item.summary,
                        item.link,
                        item.published,
                        tickers_json
                    ))
                    
                    if cursor.rowcount > 0:
                        saved_count += 1
                        
                except Exception as e:
                    logger.error(f"Ошибка при сохранении новости: {e}")
            
            conn.commit()
        
        logger.info(f"Сохранено {saved_count} новых новостей")
        return saved_count

    def get_recent_news(self, limit: int = 20) -> List[Dict]:
        """
        Получает последние новости из базы
        
        Args:
            limit: максимальное количество новостей
        
        Returns:
            список последних новостей
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM news 
                ORDER BY published DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            
            news_list = []
            for row in rows:
                news_dict = dict(row)
                # Преобразуем JSON строку обратно в список
                if news_dict['related_tickers']:
                    news_dict['related_tickers'] = json.loads(news_dict['related_tickers'])
                else:
                    news_dict['related_tickers'] = []
                news_list.append(news_dict)
            
            return news_list
    
    def get_news_by_ticker(self, ticker: str, limit: int = 20) -> List[Dict]:
        """
        Получает новости по тикеру
        
        Args:
            ticker: тикер компании
            limit: максимальное количество новостей
        
        Returns:
            список новостей по тикеру
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Ищем новости, в related_tickers есть нужный тикер
            # Это не самый эффективный способ, но для начала пойдет
            cursor.execute('''
                SELECT * FROM news 
                WHERE related_tickers LIKE ? 
                ORDER BY published DESC 
                LIMIT ?
            ''', (f'%{ticker}%', limit))
            
            rows = cursor.fetchall()
            
            news_list = []
            for row in rows:
                news_dict = dict(row)
                if news_dict['related_tickers']:
                    news_dict['related_tickers'] = json.loads(news_dict['related_tickers'])
                else:
                    news_dict['related_tickers'] = []
                news_list.append(news_dict)
            
            return news_list
    
    def add_subscription(self, user_id: int, ticker: str) -> bool:
        """
        Добавляет подписку пользователя на тикер
        
        Args:
            user_id: ID пользователя в Telegram
            ticker: тикер компании
        
        Returns:
            True если успешно, False если уже подписан
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                    INSERT INTO subscriptions (user_id, ticker)
                    VALUES (?, ?)
                ''', (user_id, ticker.upper()))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Уже подписан
                return False
    
    def remove_subscription(self, user_id: int, ticker: str) -> bool:
        """
        Удаляет подписку пользователя
        
        Args:
            user_id: ID пользователя в Telegram
            ticker: тикер компании
        
        Returns:
            True если успешно, False если не был подписан
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                DELETE FROM subscriptions 
                WHERE user_id = ? AND ticker = ?
            ''', (user_id, ticker.upper()))
            
            conn.commit()
            return cursor.rowcount > 0
    
    def get_user_subscriptions(self, user_id: int) -> List[str]:
        """
        Получает список тикеров, на которые подписан пользователь
        
        Args:
            user_id: ID пользователя в Telegram
        
        Returns:
            список тикеров
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT ticker FROM subscriptions 
                WHERE user_id = ?
                ORDER BY ticker
            ''', (user_id,))
            
            rows = cursor.fetchall()
            return [row[0] for row in rows]