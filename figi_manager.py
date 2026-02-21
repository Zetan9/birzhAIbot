"""
Менеджер для автоматического получения и обновления FIGI через Tinkoff API
"""

import requests
import json
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, List
import sqlite3
import time

logger = logging.getLogger(__name__)

class FigiManager:
    """
    Класс для автоматического получения и кэширования FIGI
    """
    
    def __init__(self, token: str, db_path: str = "figi_cache.db"):
        self.token = token
        self.base_url = "https://invest-public-api.tinkoff.ru/rest"
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Инициализируем базу данных для кэширования FIGI
        self.db_path = db_path
        self._init_database()
        
        # Кэш в памяти для быстрого доступа
        self.cache: Dict[str, Dict] = {}
        self._load_cache_from_db()
        
        logger.info(f"✅ FigiManager инициализирован")
    
    def _init_database(self):
        """Создаёт таблицы для хранения FIGI"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица для хранения FIGI
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS figi_cache (
                    ticker TEXT PRIMARY KEY,
                    figi TEXT,
                    uid TEXT,
                    name TEXT,
                    sector TEXT,
                    currency TEXT,
                    last_updated TIMESTAMP,
                    is_valid BOOLEAN DEFAULT 1
                )
            ''')
            
            # Таблица для истории поиска
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS figi_search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT,
                    query TEXT,
                    found_tickers TEXT,
                    timestamp TIMESTAMP,
                    success BOOLEAN
                )
            ''')
            
            conn.commit()
        
        logger.info("📦 База данных FIGI инициализирована")
    
    def _load_cache_from_db(self):
        """Загружает кэш из базы данных в память"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT * FROM figi_cache 
                WHERE is_valid = 1 
                AND last_updated > datetime('now', '-30 days')
            ''')
            
            rows = cursor.fetchall()
            for row in rows:
                self.cache[row['ticker']] = dict(row)
        
        logger.info(f"📚 Загружено {len(self.cache)} FIGI из кэша")
    
    def find_figi(self, ticker: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Находит FIGI по тикеру (с кэшированием)
        
        Args:
            ticker: тикер компании (например, 'SBER')
            force_refresh: принудительное обновление даже если есть в кэше
        
        Returns:
            Dict с информацией о FIGI или None
        """
        ticker = ticker.upper().strip()
        
        # Проверяем кэш, если не нужно обновлять
        if not force_refresh and ticker in self.cache:
            cache_entry = self.cache[ticker]
            cache_age = datetime.now() - datetime.fromisoformat(cache_entry['last_updated'])
            
            # Если кэш свежий (меньше 30 дней)
            if cache_age < timedelta(days=30):
                logger.debug(f"✅ {ticker}: найден в кэше")
                return cache_entry
        
        # Ищем через API
        logger.info(f"🔍 Ищем FIGI для {ticker} через API...")
        
        # Метод 1: Поиск по тикеру
        result = self._search_by_ticker(ticker)
        if result:
            self._save_to_cache(ticker, result)
            return result
        
        # Метод 2: Поиск по названию (если не нашли по тикеру)
        result = self._search_by_name(ticker)
        if result:
            self._save_to_cache(ticker, result)
            return result
        
        logger.warning(f"❌ {ticker}: FIGI не найден")
        return None
    
    def _search_by_ticker(self, ticker: str) -> Optional[Dict]:
        """Поиск по точному тикеру"""
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/FindInstrument"
        payload = {"query": ticker}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                instruments = data.get('instruments', [])
                
                # Ищем точное совпадение по тикеру
                for inst in instruments:
                    if inst.get('ticker') == ticker:
                        # Проверяем, что это акция, а не фьючерс
                        if 'фьючерс' not in inst.get('name', '').lower():
                            return self._parse_instrument(inst, ticker)
                
                # Если нет точного совпадения, берём первый подходящий
                for inst in instruments:
                    if 'фьючерс' not in inst.get('name', '').lower():
                        return self._parse_instrument(inst, ticker)
            
            # Сохраняем историю поиска
            self._save_search_history(ticker, response.text[:500], bool(instruments))
            
        except Exception as e:
            logger.error(f"Ошибка поиска {ticker}: {e}")
        
        return None
    
    def _search_by_name(self, query: str) -> Optional[Dict]:
        """Поиск по названию компании"""
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/FindInstrument"
        payload = {"query": query}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                instruments = data.get('instruments', [])
                
                for inst in instruments:
                    if 'фьючерс' not in inst.get('name', '').lower():
                        return self._parse_instrument(inst, query)
            
        except Exception as e:
            logger.error(f"Ошибка поиска по названию {query}: {e}")
        
        return None
    
    def _parse_instrument(self, instrument: Dict, original_ticker: str) -> Dict:
        """Парсит информацию об инструменте"""
        return {
            'ticker': original_ticker,
            'figi': instrument.get('figi'),
            'uid': instrument.get('uid'),
            'name': instrument.get('name'),
            'sector': instrument.get('sector'),
            'currency': instrument.get('currency'),
            'exchange': instrument.get('exchange'),
            'isin': instrument.get('isin'),
            'lot': instrument.get('lot'),
            'api_ticker': instrument.get('ticker'),  # реальный тикер в API
            'last_updated': datetime.now().isoformat(),
            'is_valid': True
        }
    
    def _save_to_cache(self, ticker: str, data: Dict):
        """Сохраняет FIGI в кэш"""
        self.cache[ticker] = data
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO figi_cache 
                (ticker, figi, uid, name, sector, currency, last_updated, is_valid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ticker,
                data.get('figi'),
                data.get('uid'),
                data.get('name'),
                data.get('sector'),
                data.get('currency'),
                data['last_updated'],
                True
            ))
            
            conn.commit()
        
        logger.info(f"💾 Сохранён FIGI для {ticker}: {data.get('figi')}")
    
    def _save_search_history(self, ticker: str, response: str, success: bool):
        """Сохраняет историю поиска"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO figi_search_history (ticker, query, found_tickers, timestamp, success)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                ticker,
                ticker,
                response[:500],
                datetime.now().isoformat(),
                success
            ))
            
            conn.commit()
    
    def batch_find_figi(self, tickers: List[str]) -> Dict[str, Optional[Dict]]:
        """Массовый поиск FIGI для списка тикеров"""
        results = {}
        
        for ticker in tickers:
            results[ticker] = self.find_figi(ticker)
            time.sleep(0.5)  # Задержка чтобы не нагружать API
        
        return results
    
    def refresh_all_figi(self) -> Dict[str, bool]:
        """Обновляет все FIGI в кэше"""
        results = {}
        
        for ticker in list(self.cache.keys()):
            new_figi = self.find_figi(ticker, force_refresh=True)
            results[ticker] = new_figi is not None
            time.sleep(0.5)
        
        logger.info(f"🔄 Обновлено {sum(results.values())} FIGI")
        return results
    
    def get_all_cached_tickers(self) -> List[str]:
        """Возвращает список всех тикеров в кэше"""
        return list(self.cache.keys())
    
    def get_invalid_figi(self) -> List[str]:
        """Возвращает список невалидных FIGI"""
        invalid = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ticker FROM figi_cache WHERE is_valid = 0')
            invalid = [row[0] for row in cursor.fetchall()]
        return invalid
    
    def mark_invalid(self, ticker: str):
        """Помечает FIGI как невалидный"""
        if ticker in self.cache:
            del self.cache[ticker]
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE figi_cache SET is_valid = 0 WHERE ticker = ?
            ''', (ticker,))
            conn.commit()
        
        logger.warning(f"⚠️ {ticker} помечен как невалидный")


# Функция для тестирования
def test_figi_manager():
    """Тестирует FigiManager"""
    from config import TINKOFF_TOKEN
    
    manager = FigiManager(TINKOFF_TOKEN)
    
    test_tickers = ['SBER', 'GAZP', 'YDEX', 'VTBR', 'TATN', 'UNKNOWN']
    
    print("\n" + "="*60)
    print("🔍 ТЕСТ: Поиск FIGI")
    print("="*60)
    
    for ticker in test_tickers:
        print(f"\n🔎 Ищем {ticker}...")
        result = manager.find_figi(ticker)
        
        if result:
            print(f"   ✅ Найден!")
            print(f"   📌 FIGI: {result.get('figi')}")
            print(f"   🏷️  Название: {result.get('name')}")
            print(f"   💱 Валюта: {result.get('currency')}")
            print(f"   🏭 Сектор: {result.get('sector')}")
        else:
            print(f"   ❌ Не найден")
        
        print("-"*40)


if __name__ == "__main__":
    test_figi_manager()