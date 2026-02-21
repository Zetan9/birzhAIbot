"""
Модуль для получения цен акций с Московской биржи
Исправленная версия с правильным получением сегодняшних цен закрытия
"""

import requests
from typing import Dict, Optional, Any, List
from datetime import datetime, time, timedelta
import logging
import time as time_module

logger = logging.getLogger(__name__)

class StockPriceProvider:
    """Класс для получения цен акций"""
    
    def __init__(self):
        self.base_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        
        # Кэш для цен
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 30  # секунд
        
        # Время работы MOEX (основная сессия)
        self.moex_open = time(9, 30)    # 9:30 утра
        self.moex_close = time(18, 45)  # 18:45 вечера
        
        # Информация о тикерах
        self.ticker_info = self._init_ticker_info()
    
    def _init_ticker_info(self) -> Dict[str, Dict[str, Any]]:
        """Инициализирует информацию о популярных тикерах"""
        return {
            'SBER': {'name': 'Сбербанк', 'full_name': 'Сбербанк России ПАО ао'},
            'GAZP': {'name': 'Газпром', 'full_name': 'Газпром ао'},
            'LKOH': {'name': 'Лукойл', 'full_name': 'Лукойл'},
            'YDEX': {'name': 'Яндекс', 'full_name': 'Яндекс Класс А'},
            'VTBR': {'name': 'ВТБ', 'full_name': 'ВТБ ао'},
            'ROSN': {'name': 'Роснефть', 'full_name': 'Роснефть'},
            'GMKN': {'name': 'Норникель', 'full_name': 'ГМК Норникель ао'},
            'TATN': {'name': 'Татнефть', 'full_name': 'Татнефть ао'},
            'MTSS': {'name': 'МТС', 'full_name': 'МТС ао'},
            'CHMF': {'name': 'Северсталь', 'full_name': 'Северсталь ао'}
        }
    
    def is_market_open(self) -> bool:
        """
        Проверяет, открыта ли биржа в данный момент
        Учитывает утреннюю (06:50-09:29) и основную (10:00-18:45) сессии
        """
        now = datetime.now().time()
        is_weekday = datetime.now().weekday() < 5  # 0-4 понедельник-пятница
        
        if not is_weekday:
            return False  # Выходной
        
        # Утренняя сессия: 06:50 - 09:29
        morning_start = time(6, 50)
        morning_end = time(9, 29)
        
        # Основная сессия: 10:00 - 18:45
        main_start = time(10, 0)
        main_end = time(18, 45)
        
        # Проверяем обе сессии
        return (morning_start <= now <= morning_end) or (main_start <= now <= main_end)
    
    def get_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Получает цену акции по тикеру
        """
        ticker = ticker.upper().strip()
        
        # Проверяем кэш
        if ticker in self.cache:
            cached = self.cache[ticker]
            cache_age = (datetime.now() - cached['timestamp']).seconds
            if cache_age < self.cache_ttl:
                logger.info(f"Возвращаем кэшированные данные для {ticker}")
                return cached['data']
        
        try:
            market_open = self.is_market_open()
            logger.info(f"Запрашиваем данные для {ticker}. Биржа {'открыта' if market_open else 'закрыта'}")
            
            if market_open:
                # Биржа открыта - пробуем получить текущую цену
                price_info = self._get_current_price(ticker)
                if price_info and price_info.get('last_price'):
                    price_info['market_status'] = 'open'
                    self.cache[ticker] = {'data': price_info, 'timestamp': datetime.now()}
                    return price_info
            
            # Биржа закрыта или не удалось получить текущую цену
            # Показываем последнюю цену закрытия (сегодняшнюю)
            price_info = self._get_today_close_price(ticker)
            if price_info and price_info.get('last_price'):
                price_info['market_status'] = 'closed'
                self.cache[ticker] = {'data': price_info, 'timestamp': datetime.now()}
                return price_info
            
            return self._get_fallback_info(ticker)
            
        except Exception as e:
            logger.error(f"Ошибка при получении цены {ticker}: {e}")
            return self._get_fallback_info(ticker)
    
    def _get_current_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Получает текущую цену (для открытого рынка)"""
        try:
            # Запрос к marketdata для получения последней цены
            url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
            params = {
                'iss.meta': 'off',
                'iss.only': 'marketdata'
            }
            
            response = requests.get(url, params=params, headers=self.base_headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_current_price(data, ticker)
            
            return None
            
        except Exception as e:
            logger.debug(f"_get_current_price error for {ticker}: {e}")
            return None
    
    def _get_today_close_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Получает сегодняшнюю цену закрытия из истории
        """
        try:
            # Запрос к истории за сегодня
            today = datetime.now().strftime('%Y-%m-%d')
            
            url = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{ticker}.json"
            params = {
                'iss.meta': 'off',
                'iss.only': 'history',
                'limit': 1,  # берем последнюю запись
                'sort_order': 'desc',
                'sort_column': 'TRADEDATE'
            }
            
            response = requests.get(url, params=params, headers=self.base_headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                history = data.get('history', {}).get('data', [])
                columns = data.get('history', {}).get('columns', [])
                
                if history and len(history) > 0:
                    # Первая запись - самая свежая
                    latest = dict(zip(columns, history[0]))
                    info = self.ticker_info.get(ticker, {})
                    
                    # Получаем цену закрытия
                    close_price = self._safe_float(latest.get('CLOSE'))
                    if not close_price:
                        close_price = self._safe_float(latest.get('LEGALCLOSEPRICE'))
                    
                    trade_date = latest.get('TRADEDATE', 'сегодня')
                    
                    if close_price:
                        return {
                            'ticker': ticker,
                            'short_name': info.get('name', ticker),
                            'sec_name': info.get('full_name', ''),
                            'last_price': close_price,
                            'prev_price': close_price,
                            'trade_date': trade_date,
                            'price_type': 'closed'
                        }
            
            return None
            
        except Exception as e:
            logger.debug(f"_get_today_close_price error for {ticker}: {e}")
            return None
    
    def _parse_current_price(self, data: Dict, ticker: str) -> Optional[Dict[str, Any]]:
        """Парсит текущую цену из marketdata"""
        try:
            marketdata = data.get('marketdata', {}).get('data', [])
            columns = data.get('marketdata', {}).get('columns', [])
            
            if not marketdata or len(marketdata) == 0:
                return None
            
            market_dict = dict(zip(columns, marketdata[0]))
            info = self.ticker_info.get(ticker, {})
            
            # Пробуем получить текущую цену (LAST)
            last_price = self._safe_float(market_dict.get('LAST'))
            
            # Если нет LAST, пробуем LCURRENTPRICE
            if last_price is None:
                last_price = self._safe_float(market_dict.get('LCURRENTPRICE'))
            
            prev_price = self._safe_float(market_dict.get('PREVPRICE'))
            open_price = self._safe_float(market_dict.get('OPEN'))
            high_price = self._safe_float(market_dict.get('HIGH'))
            low_price = self._safe_float(market_dict.get('LOW'))
            volume = self._safe_int(market_dict.get('VOLTODAY'))
            
            result = {
                'ticker': ticker,
                'short_name': info.get('name', ticker),
                'sec_name': info.get('full_name', ''),
                'last_price': last_price,
                'prev_price': prev_price,
                'open_price': open_price,
                'high_price': high_price,
                'low_price': low_price,
                'volume': volume,
                'change': None,
                'change_percent': None,
                'price_type': 'current' if last_price else 'unknown'
            }
            
            # Рассчитываем изменение
            if result['last_price'] and result['prev_price'] and result['prev_price'] != 0:
                result['change'] = result['last_price'] - result['prev_price']
                result['change_percent'] = (result['change'] / result['prev_price']) * 100
            
            return result
            
        except Exception as e:
            logger.error(f"Ошибка парсинга current price: {e}")
            return None
    
    def _safe_float(self, value: Any) -> Optional[float]:
        """Безопасно преобразует значение в float"""
        try:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value) if value != 0 else None
            if isinstance(value, str):
                value = value.replace(',', '.').strip()
                if value and value not in ('null', 'None', ''):
                    return float(value)
            return None
        except (ValueError, TypeError):
            return None
    
    def _safe_int(self, value: Any) -> Optional[int]:
        """Безопасно преобразует значение в int"""
        try:
            if value is None:
                return None
            return int(value) if value != 0 else None
        except (ValueError, TypeError):
            return None
    
    def _get_fallback_info(self, ticker: str) -> Dict[str, Any]:
        """Возвращает информацию, когда не удалось получить цену"""
        info = self.ticker_info.get(ticker, {})
        name = info.get('name', ticker)
        
        return {
            'ticker': ticker,
            'short_name': name,
            'sec_name': info.get('full_name', ''),
            'last_price': None,
            'error': 'no_data',
            'message': f'Нет данных для {name}'
        }
    
    def format_price_message(self, price_info: Dict[str, Any]) -> str:
        """Форматирует информацию о цене для отправки в Telegram"""
        if not price_info:
            return "❌ Не удалось получить информацию о цене"
        
        ticker = price_info['ticker']
        name = price_info['short_name'] or price_info['sec_name'] or ticker
        last_price = price_info.get('last_price')
        price_type = price_info.get('price_type', 'unknown')
        
        if last_price is None:
            return f"📊 *{ticker}* — {name}\n\n⏳ Нет данных о цене"
        
        # Определяем статус рынка
        market_status = "🟢 Рынок открыт" if self.is_market_open() else "🔴 Рынок закрыт"
        
        # Заголовок в зависимости от типа цены
        if price_type == 'closed' or not self.is_market_open():
            date_str = price_info.get('trade_date', 'сегодня')
            lines = [
                f"📈 *{ticker}* — {name}",
                f"📅 *Цена закрытия ({date_str}):* {last_price:.2f} ₽",
                f"{market_status}"
            ]
        else:
            lines = [
                f"📈 *{ticker}* — {name}",
                f"💰 *Текущая цена:* {last_price:.2f} ₽",
                f"⏱ *Время:* {datetime.now().strftime('%H:%M:%S')}",
                f"{market_status}"
            ]
        
        # Добавляем изменение (если есть данные)
        if price_info.get('change') is not None and price_info.get('prev_price'):
            change = price_info['change']
            change_percent = price_info['change_percent']
            emoji = "📈" if change > 0 else "📉" if change < 0 else "➖"
            sign = "+" if change > 0 else ""
            lines.append(f"{emoji} *Изм.:* {sign}{change:.2f} ₽ ({sign}{change_percent:.2f}%)")
        
        # Добавляем дневные данные (если есть и это не исторические данные)
        if price_type != 'closed' and self.is_market_open():
            daily = []
            if price_info.get('open_price'):
                daily.append(f"Откр.: {price_info['open_price']:.2f}")
            if price_info.get('high_price'):
                daily.append(f"Макс.: {price_info['high_price']:.2f}")
            if price_info.get('low_price'):
                daily.append(f"Мин.: {price_info['low_price']:.2f}")
            
            if daily:
                lines.append(f"📊 *День:* {' | '.join(daily)}")
            
            if price_info.get('volume'):
                volume = price_info['volume']
                if volume > 1000000:
                    volume_str = f"{volume/1000000:.2f}M"
                elif volume > 1000:
                    volume_str = f"{volume/1000:.2f}K"
                else:
                    volume_str = str(volume)
                lines.append(f"📊 *Объём:* {volume_str}")
        
        return "\n".join(lines)


# Словарь популярных тикеров
POPULAR_TICKERS = {
    'SBER': 'Сбербанк',
    'GAZP': 'Газпром',
    'LKOH': 'Лукойл',
    'YDEX': 'Яндекс',
    'MGNT': 'Магнит',
    'ROSN': 'Роснефть',
    'GMKN': 'Норникель',
    'VTBR': 'ВТБ',
    'TATN': 'Татнефть',
    'NVTK': 'Новатэк',
    'PLZL': 'Полюс',
    'ALRS': 'Алроса',
    'MTSS': 'МТС',
    'CHMF': 'Северсталь',
    'AFLT': 'Аэрофлот'
}


def test_stock_prices():
    """Тестирование получения цен"""
    provider = StockPriceProvider()
    
    print("="*60)
    print("ТЕСТ: Получение цен акций")
    print("="*60)
    print(f"Время теста: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}")
    print(f"Статус рынка: {'🟢 ОТКРЫТ' if provider.is_market_open() else '🔴 ЗАКРЫТ'}")
    print("="*60)
    
    test_tickers = ['SBER', 'GAZP', 'YDEX', 'LKOH', 'VTBR', 'ROSN', 'GMKN']
    
    for ticker in test_tickers:
        print(f"\n🔍 Запрашиваем {ticker}...")
        price_info = provider.get_price(ticker)
        
        if price_info:
            print(provider.format_price_message(price_info))
        else:
            print(f"❌ Не удалось получить цену для {ticker}")
        
        print("-"*30)
        time_module.sleep(1)


if __name__ == "__main__":
    test_stock_prices()