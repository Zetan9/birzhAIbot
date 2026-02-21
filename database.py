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
            # Таблица для хранения анализов новостей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS news_analysis (
                    news_id INTEGER PRIMARY KEY,
                    source TEXT,
                    title TEXT,
                    published TIMESTAMP,
                    tickers TEXT,
                    analysis_json TEXT,
                    sentiment_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE
                )
            ''')
            # Таблица сделок трейдера
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP,
                    ticker TEXT,
                    action TEXT,
                    shares INTEGER,
                    price REAL,
                    cost REAL,
                    fee REAL,
                    profit REAL,
                    balance_after REAL,
                    reason TEXT
                )
            ''')
            # Таблица для хранения сентимента из Tinkoff Пульс (агрегированного)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pulse_sentiment (
                    ticker TEXT NOT NULL,
                    date DATE NOT NULL,
                    avg_sentiment REAL,
                    post_count INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (ticker, date)
                )
            ''')
            # Таблица сигналов из телеграмм канала MOEX
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS moex_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    signal_time TIMESTAMP NOT NULL,
                    signal_type TEXT,           -- 'bullish' / 'bearish'
                    price REAL,
                    delta_p REAL,
                    volume REAL,
                    buy_pct INTEGER,
                    sell_pct INTEGER,
                    outcome REAL,                -- целевая переменная: 1 если успех, 0 если неудача
                    checked_after INTERVAL,      -- через какой интервал оценивали (в секундах)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            
        logger.info("База данных инициализирована")

    def save_moex_signal(self, signal_data: dict) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO moex_signals 
                (ticker, signal_time, signal_type, price, delta_p, volume, buy_pct, sell_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_data['ticker'],
                signal_data['time'].isoformat(),
                signal_data['type'],
                signal_data.get('price'),
                signal_data.get('delta_p'),
                signal_data.get('volume'),
                signal_data.get('buy_pct'),
                signal_data.get('sell_pct')
            ))
            conn.commit()
            return cursor.lastrowid

    def update_signal_outcome(self, signal_id: int, outcome: float, checked_after: int):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE moex_signals SET outcome = ?, checked_after = ? WHERE id = ?
            ''', (outcome, checked_after, signal_id))
            conn.commit()

    def update_signal_model_score(self, signal_id: int, score: float):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE moex_signals SET model_score = ? WHERE id = ?', (score, signal_id))
            conn.commit()

    def get_unlabeled_signals(self, limit: int = 1000):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, ticker, signal_time, price, signal_type FROM moex_signals
                WHERE outcome IS NULL ORDER BY signal_time DESC LIMIT ?
            ''', (limit,))
            return cursor.fetchall()

    def get_labeled_signals(self):
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('SELECT * FROM moex_signals WHERE outcome IS NOT NULL', conn)
        return df

    def save_trade(self, trade_dict):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO trades 
                (timestamp, ticker, action, shares, price, cost, fee, profit, balance_after, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_dict['timestamp'].isoformat() if isinstance(trade_dict['timestamp'], datetime) else trade_dict['timestamp'],
                trade_dict['ticker'],
                trade_dict['action'],
                trade_dict['shares'],
                trade_dict['price'],
                trade_dict.get('cost', 0),
                trade_dict.get('fee', 0),
                trade_dict.get('profit', 0),
                trade_dict.get('balance_after', 0),
                trade_dict.get('reason', 'manual')
            ))
            conn.commit()

    def save_news_analysis(self, news_item, analysis_dict):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            tickers_json = json.dumps(news_item.related_tickers, ensure_ascii=False)
            analysis_json = json.dumps(analysis_dict, ensure_ascii=False)
            cursor.execute('''
                INSERT OR REPLACE INTO news_analysis 
                (news_id, source, title, published, tickers, analysis_json, sentiment_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                news_item.id,  # нужно добавить id в NewsItem? или использовать link как ключ
                news_item.source,
                news_item.title,
                news_item.published.isoformat(),
                tickers_json,
                analysis_json,
                analysis_dict.get('sentiment_score', 0.0)
            ))
            conn.commit()

    def get_recent_analysis_by_ticker(self, ticker, days=7, limit=5):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT analysis_json, published FROM news_analysis
                WHERE tickers LIKE ? AND published > datetime('now', ?)
                ORDER BY published DESC
                LIMIT ?
            ''', (f'%{ticker}%', f'-{days} days', limit))
            rows = cursor.fetchall()
            return [json.loads(row[0]) for row in rows]

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
        
    def save_pulse_sentiment(self, ticker: str, avg_sentiment: float, post_count: int):
        """Сохраняет агрегированный сентимент для тикера за сегодня."""
        today = datetime.now().date()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO pulse_sentiment (ticker, date, avg_sentiment, post_count, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (ticker, today.isoformat(), avg_sentiment, post_count))
            conn.commit()

    def get_pulse_sentiment(self, ticker: str = None, days: int = 7) -> List[Dict]:
        """Получает сентимент из Пульса за последние N дней. Если ticker не указан, возвращает по всем."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if ticker:
                cursor.execute('''
                    SELECT ticker, date, avg_sentiment, post_count FROM pulse_sentiment
                    WHERE ticker = ? AND date >= date('now', ?)
                    ORDER BY date DESC
                ''', (ticker, f'-{days} days'))
            else:
                cursor.execute('''
                    SELECT ticker, date, avg_sentiment, post_count FROM pulse_sentiment
                    WHERE date >= date('now', ?)
                    ORDER BY ticker, date DESC
                ''', (f'-{days} days',))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


