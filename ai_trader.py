"""
Автономный ИИ-трейдер
Управляет виртуальным портфелем на основе рекомендаций ИИ
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import os
import time
import services
from collections import defaultdict
from config import TINKOFF_TOKEN
import pandas as pd

logger = logging.getLogger(__name__)

class VirtualTrader:
    """Автономный трейдер с виртуальным портфелем"""
    
    def __init__(self, initial_balance: float = 1000000):
        self.ai_advisor = services.ai_advisor()
        self.stock_provider = services.stock_provider()

        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.portfolio = {}

        self.trades = []
        self.performance_history = []
        self.ai_decisions = []

        # ===== НОВЫЕ АГРЕССИВНЫЕ НАСТРОЙКИ =====
        self.max_position_size = 0.45          # макс доля одной акции (было 0.35)
        self.min_confidence = 0.5               # порог уверенности (было 0.7)
        self.trade_fee = 0.003
        # =========================================

        # Параметры трейлинг-стопа
        self.use_trailing_stop = True
        self.trailing_stop_pct = 5.0  # откат от максимума в %

        self.highest_price = {}  # для трейлинг-стопа

        self.price_history_cache = {}  # ticker -> (timestamp, DataFrame)
        self.history_cache_ttl = 3600  # 1 час

        self.is_trading = True
        self.last_analysis = None
        self.daily_pnl = 0

        # Параметры для технических продаж
        self.sell_rsi_overbought = 80          # RSI выше этого - продаём часть
        self.sell_rsi_fraction = 0.3            # какая часть позиции продаётся при RSI > 80
        self.sell_ma5_break = True              # продавать при пробое MA5 вниз
        self.sell_ma5_fraction = 0.4            # часть при пробое MA5
        self.sell_ma20_break = True             # продавать всё при пробое MA20 вниз

        self._load_state()
        self.start_trading()
        logger.info(f"💰 VirtualTrader инициализирован. Баланс: {self.balance:,.0f} ₽")

    def _get_history_df(self, ticker: str, days: int = 30) -> Optional[pd.DataFrame]:
        """Получает исторические цены и возвращает DataFrame с индикаторами."""
        now = datetime.now()
        # Проверяем кэш
        if ticker in self.price_history_cache:
            cache_time, df = self.price_history_cache[ticker]
            if (now - cache_time).total_seconds() < self.history_cache_ttl:
                return df

        # Запрашиваем через stock_provider
        history = self.stock_provider.get_history(ticker, days=days)
        if not history or len(history) < 20:
            return None

        df = pd.DataFrame(history)
        df.set_index('time', inplace=True)
        df.sort_index(inplace=True)

        # Рассчитываем индикаторы
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # Сохраняем в кэш
        self.price_history_cache[ticker] = (now, df)
        return df

    # def _check_technical_filters(self, ticker: str, current_price: float) -> tuple[bool, float, str]:
    #     """
    #     Проверяет технические фильтры для входа.
    #     Возвращает (разрешена_покупка, техническая_уверенность_0_1, причина_отказа).
    #     """
    #     df = self._get_history_df(ticker)
    #     if df is None or df.empty:
    #         return False, 0.0, "нет данных"

    #     last = df.iloc[-1]
    #     ma5 = last.get('MA5')
    #     ma20 = last.get('MA20')
    #     rsi = last.get('RSI')

    #     if pd.isna(ma5) or pd.isna(ma20) or pd.isna(rsi):
    #         return False, 0.0, "недостаточно данных для индикаторов"

    #     trend_ok = (current_price > ma20) or (ma5 > ma20)
    #     rsi_ok = rsi < 70

    #     tech_conf = 0.0
    #     reasons = []
    #     if trend_ok:
    #         tech_conf += 0.5
    #     else:
    #         reasons.append("тренд")
    #     if rsi_ok:
    #         tech_conf += 0.5
    #     else:
    #         reasons.append("RSI")

    #     allow = trend_ok and rsi_ok
    #     reason_str = ", ".join(reasons) if reasons else "все ок"
    #     return allow, tech_conf, reason_str

    def _check_technical_filters(self, ticker: str, current_price: float) -> tuple[bool, float, str]:
        """
        Упрощённая проверка: только RSI < 70 (не перекупленность).
        Тренд игнорируем для агрессивной торговли.
        """
        df = self._get_history_df(ticker)
        if df is None or df.empty:
            return False, 0.0, "нет данных"

        last = df.iloc[-1]
        rsi = last.get('RSI')

        if pd.isna(rsi):
            return False, 0.0, "нет RSI"

        # Условие: RSI < 70
        rsi_ok = rsi < 70

        # Техническая уверенность: 1.0 если RSI ок, иначе 0.0
        tech_conf = 1.0 if rsi_ok else 0.0
        reason = "" if rsi_ok else "RSI перекуплен"

        return rsi_ok, tech_conf, reason

    def start_trading(self):
        """Запускает автономную торговлю"""
        self.is_trading = True
        logger.info("🚀 Автономная торговля запущена")
        
        # Немедленный анализ
        self.analyze_and_trade()
    
    def stop_trading(self):
        """Останавливает автономную торговлю"""
        self.is_trading = False
        logger.info("⏹️ Автономная торговля остановлена")
        self._save_state()
    
    def analyze_and_trade(self):
        """Анализирует рынок и совершает сделки"""
        if not self.is_trading:
            return
        
        logger.info("🤖 ИИ анализирует рынок для принятия решений...")
        
        # Получаем анализ от ИИ
        analysis = self.ai_advisor.analyze_all()
        self.last_analysis = analysis
        
        # Запоминаем решение ИИ
        self.ai_decisions.append({
            'timestamp': datetime.now(),
            'analysis': analysis,
            'portfolio_before': self.get_portfolio_summary()
        })
        
        # Принимаем торговые решения на основе анализа
        self._execute_trades(analysis)
        
        # Обновляем статистику
        self._update_performance()
        
        logger.info(f"✅ Торговый цикл завершён. Баланс: {self.balance:,.0f} ₽")

    def _execute_trades(self, analysis: Dict):
        """Выполняет сделки на основе анализа ИИ – агрессивная версия с тех. фильтрами."""
        
        current_prices = self._get_current_prices()
        if not current_prices:
            logger.warning("Нет текущих цен, пропускаем торговлю")
            return

        # Собираем кандидатов (до 7)
        candidates = []

        # Из top_picks (если есть)
        for pick in analysis.get('top_picks', [])[:7]:
            ticker = pick.get('ticker')
            action = pick.get('action', 'HOLD')
            confidence = pick.get('confidence', 0.5)
            if action in ('BUY', 'HOLD') and ticker in current_prices:
                candidates.append((ticker, confidence, action))

        # Добавляем главную рекомендацию, если её нет
        main_ticker = analysis.get('top_pick')
        main_action = analysis.get('action')
        main_conf = analysis.get('confidence', 0.5)
        if (main_action in ('BUY', 'HOLD') and main_ticker and 
            main_ticker in current_prices and 
            not any(t for t, _, _ in candidates if t == main_ticker)):
            candidates.append((main_ticker, main_conf, main_action))

        if not candidates:
            logger.info("Нет кандидатов для торговли")
            return

        # Сортируем по уверенности
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:7]

        # === РАСПРЕДЕЛЕНИЕ КАПИТАЛА ===
        buy_candidates = [(t, c) for t, c, a in candidates if a == 'BUY' and c >= self.min_confidence]
        hold_candidates = [(t, c) for t, c, a in candidates if a == 'HOLD' and c >= 0.8]

        total_conf_buy = sum(c for _, c in buy_candidates)
        total_conf_hold = sum(c for _, c in hold_candidates)

        invest_capital = self.balance * 0.8
        if invest_capital < 1000:
            logger.info("Слишком мало средств для инвестиций")
            return

        # === ПОКУПКИ ПО BUY ===
        if buy_candidates:
            for ticker, conf in buy_candidates:
                price = current_prices[ticker]

                # --- ТЕХНИЧЕСКИЙ ФИЛЬТР ---
                allow, tech_conf, reason = self._check_technical_filters(ticker, price)
                if not allow:
                    logger.info(f"⏸️ {ticker}: пропущен (тех. фильтры: {reason})")
                    continue
                # Корректируем уверенность
                adj_conf = (conf + tech_conf) / 2.0
                # Доля от invest_capital на основе исходной уверенности
                share = conf / total_conf_buy if total_conf_buy else 0
                base_amount = invest_capital * share
                # Корректируем сумму пропорционально отношению уверенностей
                amount = base_amount * (adj_conf / conf) if conf > 0 else base_amount
                logger.debug(f"{ticker}: BUY orig_conf={conf:.2f}, tech_conf={tech_conf:.2f}, adj_conf={adj_conf:.2f}, amount={amount:,.0f}")
                self._buy(ticker, price, adj_conf, max_amount=amount)

        # === ДОКУПКИ ПО HOLD ===
        if hold_candidates:
            hold_budget = invest_capital * 0.2
            for ticker, conf in hold_candidates:
                if ticker not in self.portfolio:
                    continue
                price = current_prices[ticker]

                # --- ТЕХНИЧЕСКИЙ ФИЛЬТР (для докупки тоже применяем) ---
                allow, tech_conf, reason = self._check_technical_filters(ticker, price)
                if not allow:
                    logger.info(f"⏸️ {ticker} (докупка): пропущен (тех. фильтры: {reason})")
                    continue
                adj_conf = (conf + tech_conf) / 2.0
                share = conf / total_conf_hold if total_conf_hold else 0
                base_amount = hold_budget * share
                amount = base_amount * (adj_conf / conf) if conf > 0 else base_amount
                logger.debug(f"{ticker}: HOLD orig_conf={conf:.2f}, tech_conf={tech_conf:.2f}, adj_conf={adj_conf:.2f}, amount={amount:,.0f}")
                self._buy(ticker, price, adj_conf, max_amount=amount)

        # Проверка стоп-лоссов и тейк-профитов
        self._check_positions(current_prices)

    def _process_recommendation(self, ticker: str, action: str, price: float, confidence: float):
        """Обрабатывает одну рекомендацию"""
        
        if action == 'BUY':
            self._buy(ticker, price, confidence)
        elif action == 'SELL':
            self._sell(ticker, price, confidence)
        elif action == 'HOLD':
            # Для HOLD ничего не делаем, но можем докупить если уверенность высокая
            if confidence > 0.9:
                self._buy(ticker, price, confidence * 0.8)
    
    def _buy(self, ticker: str, price: float, confidence: float, max_amount: Optional[float] = None):
        """Покупает акции с ограничением по сумме"""
        
        current_value = self.get_portfolio_value()
        max_position_value = current_value * self.max_position_size
        
        current_position_value = self.portfolio.get(ticker, {}).get('shares', 0) * price
        if current_position_value >= max_position_value:
            logger.info(f"⏸️ {ticker}:достигнут максимальный размер позиции")
            return

        # Определяем доступную сумму для этой сделки
        if max_amount is None:
            # Старое поведение – процент от баланса
            available = self.balance * 0.3 * confidence
        else:
            available = max_amount

        # Ограничиваем размер позиции
        max_allowed = max_position_value - current_position_value
        available = min(available, max_allowed, self.balance)

        if available < price * 10:
            logger.info(f"⏸️ {ticker}: сумма слишком мала для покупки")
            return

        shares = int(available / price)
        cost = shares * price
        fee = cost * self.trade_fee

        if cost + fee > self.balance:
            shares = int((self.balance * 0.9) / price)
            cost = shares * price
            fee = cost * self.trade_fee

        if shares == 0:
            return

        # Совершаем покупку
        self.balance -= (cost + fee)

        if ticker in self.portfolio:
            old_shares = self.portfolio[ticker]['shares']
            old_cost = old_shares * self.portfolio[ticker]['avg_price']
            new_shares = old_shares + shares
            new_avg_price = (old_cost + cost) / new_shares
            self.portfolio[ticker] = {'shares': new_shares, 'avg_price': new_avg_price}
        else:
            self.portfolio[ticker] = {'shares': shares, 'avg_price': price}

        trade = {
            'timestamp': datetime.now(),
            'ticker': ticker,
            'action': 'BUY',
            'shares': shares,
            'price': price,
            'cost': cost,
            'fee': fee,
            'confidence': confidence,
            'balance_after': self.balance
        }
        self.trades.append(trade)

        db = services.db()
        if db:
            db.save_trade(trade)

        logger.info(f"🟢 BUY {shares} {ticker} @ {price:.2f} = {cost:,.0f} ₽ (fee: {fee:.0f})")

    def _sell(self, ticker: str, price: float, confidence: float, reason: str = 'manual', shares: Optional[int] = None, sell_all: bool = False):
        if ticker not in self.portfolio:
            return

        total_shares = self.portfolio[ticker]['shares']
        avg_price = self.portfolio[ticker]['avg_price']

        if sell_all:
            sell_shares = total_shares
        elif shares is not None:
            sell_shares = min(shares, total_shares)
        else:
            # Старая логика на основе confidence (оставляем для обратной совместимости)
            if confidence > 0.9:
                sell_shares = total_shares
            elif confidence > 0.7:
                sell_shares = int(total_shares * 0.7)
            else:
                sell_shares = int(total_shares * 0.5)

        if sell_shares == 0:
            return

        revenue = sell_shares * price
        fee = revenue * self.trade_fee
        profit = (price - avg_price) * sell_shares

        self.balance += (revenue - fee)

        # Обновляем портфель
        if sell_shares >= total_shares:
            del self.portfolio[ticker]
            # Очищаем данные трейлинга и уровней
            self.highest_price.pop(ticker, None)
        else:
            self.portfolio[ticker]['shares'] -= sell_shares

        trade = {
            'timestamp': datetime.now(),
            'ticker': ticker,
            'action': 'SELL',
            'shares': sell_shares,
            'price': price,
            'revenue': revenue,
            'fee': fee,
            'profit': profit,
            'confidence': confidence,
            'balance_after': self.balance,
            'reason': reason,
        }
        self.trades.append(trade)

        db = services.db()
        if db:
            db.save_trade(trade)

        logger.info(f"{'🟢' if profit>0 else '🔴'} SELL {sell_shares} {ticker} @ {price:.2f} = {revenue:,.0f} ₽ (profit: {profit:+,.0f}) reason: {reason}")

    def _check_positions(self, current_prices: Dict):
        """
        Проверяет позиции на предмет продажи по техническим сигналам:
        - RSI > 80 (перекупленность) → продажа части
        - цена ниже MA5 → продажа части
        - цена ниже MA20 → продажа всей позиции
        Также оставляем трейлинг-стоп и обычный стоп-лосс.
        """
        for ticker, position in list(self.portfolio.items()):
            if ticker not in current_prices:
                continue

            current_price = current_prices[ticker]
            avg_price = position['avg_price']
            shares = position['shares']

            # Получаем технические индикаторы
            df = self._get_history_df(ticker)
            if df is None or df.empty:
                continue

            last = df.iloc[-1]
            ma5 = last.get('MA5')
            ma20 = last.get('MA20')
            rsi = last.get('RSI')

            if pd.isna(ma5) or pd.isna(ma20) or pd.isna(rsi):
                continue

            # --- 1. Технические сигналы на продажу ---
            # Приоритет: MA20 (полная продажа) -> MA5 -> RSI

            # Пробой MA20 (ниже)
            if self.sell_ma20_break and current_price < ma20:
                logger.info(f"📉 {ticker}: пробой MA20 ({ma20:.2f}), продажа всей позиции")
                self._sell(ticker, current_price, 1.0, reason='ma20_break', sell_all=True)
                continue  # позиция закрыта, дальше не проверяем

            # Пробой MA5 (ниже)
            if self.sell_ma5_break and current_price < ma5:
                shares_to_sell = int(shares * self.sell_ma5_fraction)
                if shares_to_sell > 0:
                    logger.info(f"📉 {ticker}: пробой MA5 ({ma5:.2f}), продажа {shares_to_sell} шт. ({self.sell_ma5_fraction*100:.0f}%)")
                    self._sell(ticker, current_price, 0.8, reason='ma5_break', shares=shares_to_sell)
                # после частичной продажи позиция ещё остаётся, проверяем дальше (но RSI уже не проверяем, если не хотим)

            # Перекупленность RSI
            if rsi > self.sell_rsi_overbought:
                shares_to_sell = int(shares * self.sell_rsi_fraction)
                if shares_to_sell > 0:
                    logger.info(f"📈 {ticker}: RSI={rsi:.1f} > {self.sell_rsi_overbought}, продажа {shares_to_sell} шт. ({self.sell_rsi_fraction*100:.0f}%)")
                    self._sell(ticker, current_price, 0.7, reason='rsi_overbought', shares=shares_to_sell)

            # --- 2. Трейлинг-стоп (оставляем как есть) ---
            if self.use_trailing_stop:
                if ticker not in self.highest_price:
                    self.highest_price[ticker] = current_price
                else:
                    self.highest_price[ticker] = max(self.highest_price[ticker], current_price)

                trailing_stop_level = self.highest_price[ticker] * (1 - self.trailing_stop_pct / 100)
                if current_price <= trailing_stop_level:
                    logger.info(f"📉 Трейлинг-стоп для {ticker} при {current_price:.2f} (макс {self.highest_price[ticker]:.2f})")
                    self._sell(ticker, current_price, 1.0, reason='trailing_stop', sell_all=True)
                    continue

            # --- 3. Обычный стоп-лосс (оставляем) ---
            profit_pct = (current_price - avg_price) / avg_price * 100
            if profit_pct < -5:
                logger.info(f"🛑 Стоп-лосс для {ticker}: {profit_pct:.1f}%")
                self._sell(ticker, current_price, 1.0, reason='stop_loss', sell_all=True)

    def _get_current_prices(self) -> Dict[str, float]:
        """Получает текущие цены всех активов в портфеле"""
        prices = {}
        all_tickers = set(self.portfolio.keys()) | {'SBER', 'GAZP', 'YDEX', 'VTBR', 'TATN', 'LKOH'}
        
        for ticker in all_tickers:
            try:
                price_info = self.stock_provider.get_price(ticker)
                if price_info and price_info.get('last_price'):
                    prices[ticker] = price_info['last_price']
            except:
                continue
        
        return prices
    
    def get_portfolio_value(self) -> float:
        """Рассчитывает текущую стоимость портфеля"""
        total = self.balance
        prices = self._get_current_prices()
        
        for ticker, position in self.portfolio.items():
            if ticker in prices:
                total += position['shares'] * prices[ticker]
        
        return total
    
    def get_portfolio_summary(self) -> Dict:
        """Возвращает сводку по портфелю"""
        prices = self._get_current_prices()
        total_value = self.balance
        positions = []
        
        for ticker, position in self.portfolio.items():
            if ticker in prices:
                current_price = prices[ticker]
                current_value = position['shares'] * current_price
                invested = position['shares'] * position['avg_price']
                profit = current_value - invested
                profit_percent = (profit / invested) * 100 if invested else 0
                
                total_value += current_value
                
                positions.append({
                    'ticker': ticker,
                    'shares': position['shares'],
                    'avg_price': position['avg_price'],
                    'current_price': current_price,
                    'current_value': current_value,
                    'profit': profit,
                    'profit_percent': profit_percent
                })
        
        # Сортируем по размеру позиции
        positions.sort(key=lambda x: x['current_value'], reverse=True)
        
        total_profit = total_value - self.initial_balance
        total_profit_percent = (total_profit / self.initial_balance) * 100
        
        return {
            'balance': self.balance,
            'total_value': total_value,
            'invested': total_value - self.balance,
            'positions': positions,
            'total_profit': total_profit,
            'total_profit_percent': total_profit_percent,
            'position_count': len(positions)
        }
    
    def _update_performance(self):
        """Обновляет историю доходности"""
        summary = self.get_portfolio_summary()
        summary['timestamp'] = datetime.now()
        self.performance_history.append(summary)
        
        # Оставляем только последние 100 записей
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
    
    def _save_state(self):
        """Сохраняет состояние портфеля"""
        state = {
            'balance': self.balance,
            'portfolio': self.portfolio,
            'trades': self.trades[-100:],  # Последние 100 сделок
            'performance_history': self.performance_history[-50:],
            'last_save': datetime.now().isoformat(),
            'is_trading': self.is_trading,
        }
        
        os.makedirs('data', exist_ok=True)
        with open('data/trader_state.json', 'w') as f:
            json.dump(state, f, indent=2, default=str)
        
        logger.info("💾 Состояние трейдера сохранено")
    
    def _load_state(self):
        """Загружает состояние портфеля"""
        try:
            if os.path.exists('data/trader_state.json'):
                with open('data/trader_state.json', 'r') as f:
                    state = json.load(f)
                
                self.balance = state.get('balance', self.initial_balance)
                self.portfolio = state.get('portfolio', {})
                self.trades = state.get('trades', [])
                self.performance_history = state.get('performance_history', [])
                self.is_trading = state.get('is_trading', False)

                logger.info(f"📂 Загружено состояние: баланс {self.balance:,.0f} ₽")
        except Exception as e:
            logger.error(f"Ошибка загрузки состояния: {e}")
    
    def format_portfolio_message(self) -> str:
        """Форматирует сообщение о портфеле для Telegram"""
        summary = self.get_portfolio_summary()
        
        lines = []
        lines.append("💰 *ВИРТУАЛЬНЫЙ ПОРТФЕЛЬ*\n")
        lines.append(f"💵 Баланс: {summary['balance']:,.0f} ₽")
        lines.append(f"📊 Инвестировано: {summary['invested']:,.0f} ₽")
        lines.append(f"🏦 Всего: {summary['total_value']:,.0f} ₽\n")
        
        # Общая доходность
        if summary['total_profit'] >= 0:
            profit_emoji = "🟢"
        else:
            profit_emoji = "🔴"
        
        lines.append(f"{profit_emoji} *Общая доходность:* {summary['total_profit']:+,.0f} ₽ ({summary['total_profit_percent']:+.1f}%)\n")
        
        if summary['positions']:
            lines.append("*Текущие позиции:*")
            for pos in summary['positions'][:10]:
                if pos['profit'] >= 0:
                    pos_emoji = "🟢"
                else:
                    pos_emoji = "🔴"
                
                lines.append(
                    f"{pos_emoji} *{pos['ticker']}*: {pos['shares']} шт × {pos['current_price']:.2f} = {pos['current_value']:,.0f} ₽\n"
                    f"   Средняя: {pos['avg_price']:.2f} | {pos_emoji} {pos['profit']:+,.0f} ({pos['profit_percent']:+.1f}%)"
                )
        else:
            lines.append("📭 Нет открытых позиций")
        
        # Последние сделки
        if self.trades:
            lines.append("\n*Последние сделки:*")
            for trade in self.trades[-3:]:
                if isinstance(trade['timestamp'], str):
                    date = datetime.fromisoformat(trade['timestamp']).strftime('%d.%m.%y %H:%M')
                else:
                    date = trade['timestamp'].strftime('%d.%m.%y %H:%M')
                    
                if trade['action'] == 'BUY':
                    lines.append(f"🟢 {date} BUY {trade['shares']} {trade['ticker']} @ {trade['price']:.2f}")
                else:
                    profit = trade.get('profit', 0)
                    emoji = "🟢" if profit > 0 else "🔴"
                    lines.append(f"{emoji} {date} SELL {trade['shares']} {trade['ticker']} @ {trade['price']:.2f} ({profit:+,.0f})")
        
        return "\n".join(lines)


# Функция для периодической торговли
def start_auto_trading(trader: VirtualTrader, interval_minutes: int = 60):
    """Запускает автоматическую торговлю с заданным интервалом"""
    
    trader.start_trading()
    
    while trader.is_trading:
        try:
            trader.analyze_and_trade()
            trader._save_state()
            
            # Ждём до следующего анализа
            for _ in range(interval_minutes * 60):
                if not trader.is_trading:
                    break
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Ошибка в торговом цикле: {e}")
            time.sleep(60)