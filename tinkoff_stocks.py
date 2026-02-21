"""
Модуль для получения цен акций через Tinkoff API с автоматическим получением FIGI
Исправленная версия с приоритетом правильных FIGI и методом get_history
"""

import requests
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional, Any
from figi_manager import FigiManager
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

class TinkoffStockProvider:
    """Провайдер для получения цен через Tinkoff API с авто-FIGI"""

    def __init__(self, token):
        self.token = token
        self.base_url = "https://invest-public-api.tinkoff.ru/rest"
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        self.session = requests.Session()
        retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

        # Инициализируем менеджер FIGI
        self.figi_manager = FigiManager(token)

        # Приоритетные FIGI (проверенные рабочие)
        self.priority_figi = {
            'SBER': 'BBG004730N88',      # Сбербанк - РАБОТАЕТ
            'GAZP': 'BBG004730RP0',      # Газпром - РАБОТАЕТ
            'LKOH': 'BBG004731032',      # Лукойл - РАБОТАЕТ
            'YDEX': 'TCS00A107T19',      # Яндекс - РАБОТАЕТ
            'VTBR': 'BBG004730ZJ9',      # ВТБ - РАБОТАЕТ
            'TATN': 'BBG004RVFFC0',      # Татнефть - РАБОТАЕТ
            'ROSN': 'BBG0047314D0',      # Роснефть
            'GMKN': 'BBG00475J7X2',      # Норникель
            'MTSS': 'BBG00475NY50',      # МТС
            'CHMF': 'BBG00475KX63',      # Северсталь
            'NLMK': 'BBG00475J5C7',      # НЛМК
            'PLZL': 'BBG00475K3V3',      # Полюс
            'ALRS': 'BBG004S68B21',      # Алроса
            'MGNT': 'BBG004PYF2Y2',      # Магнит
            'FIVE': 'BBG004PXMLJ7',      # X5 Group
            'IRAO': 'BBG0047315D0',      # Интер РАО
            'HYDR': 'BBG00475J816',      # РусГидро
            'NVTK': 'BBG0047315G5',      # Новатэк
            'LNZLP': 'BBG000SR0YS4',     # Лензолото - привилегированные акции
        }

        # Кэш для цен
        self.price_cache = {}
        self.last_update = {}

        # Названия компаний
        self.company_names = {
            'SBER': 'Сбербанк',
            'GAZP': 'Газпром',
            'LKOH': 'Лукойл',
            'YDEX': 'Яндекс',
            'VTBR': 'ВТБ',
            'ROSN': 'Роснефть',
            'GMKN': 'Норникель',
            'TATN': 'Татнефть',
            'MTSS': 'МТС',
            'CHMF': 'Северсталь',
            'NLMK': 'НЛМК',
            'PLZL': 'Полюс',
            'ALRS': 'Алроса',
            'MGNT': 'Магнит',
            'FIVE': 'X5 Group',
            'IRAO': 'Интер РАО',
            'HYDR': 'РусГидро',
            'NVTK': 'Новатэк',
        }

        logger.info("✅ Tinkoff Stock Provider инициализирован")

    def get_all_instruments(self) -> List[Dict]:
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
        payload = {"instrument_status": "INSTRUMENT_STATUS_BASE"}
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                instruments = data.get('instruments', [])
                result = []
                for instr in instruments:
                    result.append({
                        'ticker': instr.get('ticker'),
                        'figi': instr.get('figi'),
                        'name': instr.get('name'),
                        'sector': instr.get('sector'),
                        'currency': instr.get('currency'),
                    })
                logger.info(f"✅ Загружено {len(result)} инструментов из Tinkoff API")
                return result
            else:
                logger.error(f"Ошибка HTTP {response.status_code} при получении списка инструментов")
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка инструментов: {e}")
        return []

    def get_price(self, ticker):
        """Получает цену акции с приоритетом проверенных FIGI"""
        ticker = ticker.upper()

        # Проверка кэша цен
        if ticker in self.last_update:
            if datetime.now() - self.last_update[ticker] < timedelta(minutes=5):
                logger.debug(f"🔄 Кэш для {ticker}: {self.price_cache[ticker]:.2f} ₽")
                return {'last_price': self.price_cache[ticker]}

        # Сначала пробуем приоритетный FIGI
        if ticker in self.priority_figi:
            figi = self.priority_figi[ticker]
            logger.debug(f"🔍 {ticker}: пробуем приоритетный FIGI {figi}")

            price = self._get_price_by_figi(ticker, figi)
            if price:
                return {'last_price': price}

        # Если не получилось, пробуем через менеджер FIGI
        logger.debug(f"🔍 {ticker}: пробуем найти FIGI через API")
        figi_info = self.figi_manager.find_figi(ticker)

        if figi_info and figi_info.get('figi'):
            figi = figi_info['figi']
            price = self._get_price_by_figi(ticker, figi)
            if price:
                # Если нашёлся рабочий FIGI, запоминаем его в приоритетные
                self.priority_figi[ticker] = figi
                return {'last_price': price}

        logger.warning(f"⚠️ {ticker}: не удалось получить цену")
        return None

    def _get_price_by_figi(self, ticker: str, figi: str) -> Optional[float]:
        """Получает цену по FIGI"""
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"
        payload = {"figi": [figi]}

        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)

            if response.status_code == 200:
                data = response.json()

                if 'lastPrices' in data and len(data['lastPrices']) > 0:
                    price_data = data['lastPrices'][0]

                    if 'price' in price_data:
                        price_info = price_data['price']
                        units = price_info.get('units', 0)
                        nano = price_info.get('nano', 0)
                        # Приводим к int, если пришли строки
                        try:
                            units = int(units)
                        except (ValueError, TypeError):
                            units = 0
                        try:
                            nano = int(nano)
                        except (ValueError, TypeError):
                            nano = 0
                        price = units + nano / 1_000_000_000

                        self.price_cache[ticker] = price
                        self.last_update[ticker] = datetime.now()

                        logger.info(f"✅ {ticker}: {price:.2f} ₽ (FIGI: {figi})")
                        return price
                    else:
                        logger.debug(f"⚠️ {ticker}: нет price в ответе")
                else:
                    logger.debug(f"⚠️ {ticker}: нет lastPrices в ответе")
            else:
                logger.debug(f"⚠️ {ticker}: HTTP {response.status_code}")

        except Exception as e:
            logger.debug(f"⚠️ Ошибка для {ticker}: {e}")

        return None

    def _quotation_to_float(self, quotation: Dict[str, Any]) -> float:
        """Преобразует quotation из API в число с плавающей точкой.
        quotation должен содержать ключи 'units' и 'nano' (могут быть int или str).
        """
        units = quotation.get('units', 0)
        nano = quotation.get('nano', 0)
        try:
            units = int(units)
        except (ValueError, TypeError):
            units = 0
        try:
            nano = int(nano)
        except (ValueError, TypeError):
            nano = 0
        return units + nano / 1_000_000_000

    def get_history(self, ticker: str, days: int = 30) -> List[Dict[str, Any]]:
        """
        Получает исторические цены (OHLCV) за последние N дней.
        Используем свечи с дневным интервалом.
        """
        ticker = ticker.upper()
        try:
            days = int(days)
        except:
            days = 30

        # Сначала пробуем взять FIGI из приоритетного списка
        figi = self.priority_figi.get(ticker)
        if not figi:
            # Если нет в приоритетных, ищем через менеджер FIGI
            logger.debug(f"🔍 {ticker}: ищем FIGI для истории через API")
            figi_info = self.figi_manager.find_figi(ticker)
            if figi_info and figi_info.get('figi'):
                figi = figi_info['figi']
                # Можно добавить в priority_figi для будущих запросов
                self.priority_figi[ticker] = figi
            else:
                logger.warning(f"⚠️ Нет FIGI для {ticker}, история не может быть получена")
                return []

        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
        from_date = (datetime.now() - timedelta(days=days)).isoformat() + "Z"
        to_date = datetime.now().isoformat() + "Z"

        payload = {
            "figi": figi,
            "from": from_date,
            "to": to_date,
            "interval": "CANDLE_INTERVAL_DAY"
        }

        try:
            response = self.session.post(url, headers=self.headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                candles = data.get('candles', [])
                history = []
                for c in candles:
                    if not all(k in c for k in ('time', 'open', 'high', 'low', 'close', 'volume')):
                        logger.warning(f"Пропуск свечи: отсутствуют ключи {c.keys()}")
                        continue
                    history.append({
                        'time': datetime.fromisoformat(c['time'].replace('Z', '+00:00')),
                        'open': self._quotation_to_float(c['open']),
                        'high': self._quotation_to_float(c['high']),
                        'low': self._quotation_to_float(c['low']),
                        'close': self._quotation_to_float(c['close']),
                        'volume': c['volume']
                    })
                return history
            else:
                logger.error(f"Ошибка HTTP {response.status_code} при получении истории {ticker}")
                logger.debug(f"Ответ: {response.text[:200]}")
        except Exception as e:
            logger.error(f"Ошибка получения истории {ticker}: {e}", exc_info=True)
        return []

    def get_price_with_details(self, ticker):
        """Получает цену и детальную информацию о компании"""
        ticker = ticker.upper()
        price_info = self.get_price(ticker)
        if not price_info:
            return None
        figi = self.priority_figi.get(ticker)
        return {
            'ticker': ticker,
            'name': self.company_names.get(ticker, ticker),
            'price': price_info['last_price'],
            'figi': figi,
            'last_updated': datetime.now()
        }

    def get_prices_batch(self, tickers):
        """Получает цены для списка тикеров"""
        results = {}
        for ticker in tickers:
            price_info = self.get_price(ticker)
            if price_info:
                results[ticker] = price_info['last_price']
        return results

    def refresh_figi_cache(self):
        """Обновляет кэш FIGI"""
        return self.figi_manager.refresh_all_figi()


# Для тестирования
if __name__ == "__main__":
    from config import TINKOFF_TOKEN
    provider = TinkoffStockProvider(TINKOFF_TOKEN)
    test_tickers = ['SBER', 'GAZP', 'YDEX', 'VTBR', 'TATN', 'LKOH']
    print("\n" + "="*60)
    print("💰 ТЕСТ: Получение цен с авто-FIGI")
    print("="*60)
    for ticker in test_tickers:
        print(f"\n🔍 {ticker}...")
        result = provider.get_price_with_details(ticker)
        if result:
            print(f"   ✅ {result['name']}")
            print(f"   💰 Цена: {result['price']:.2f} ₽")
            if result.get('figi'):
                print(f"   📌 FIGI: {result['figi']}")
        else:
            print(f"   ❌ Ошибка")
        print("-"*40)