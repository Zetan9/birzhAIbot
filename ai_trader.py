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
from collections import defaultdict
from ai_advisor import AIAdvisor
from tinkoff_stocks import TinkoffStockProvider
from config import TINKOFF_TOKEN

logger = logging.getLogger(__name__)

class VirtualTrader:
    """Автономный трейдер с виртуальным портфелем"""
    
    def __init__(self, initial_balance: float = 1000000):
        self.ai_advisor = AIAdvisor(TINKOFF_TOKEN)
        self.stock_provider = TinkoffStockProvider(TINKOFF_TOKEN)
        
        # Начальный баланс (1 млн рублей)
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.portfolio = {}  # {ticker: {'shares': int, 'avg_price': float}}
        
        # История торговли
        self.trades = []  # Все сделки
        self.performance_history = []  # История доходности
        self.ai_decisions = []  # Решения ИИ
        
        # Настройки торговли
        self.max_position_size = 0.4  # Макс 25% портфеля на одну позицию
        self.min_confidence = 0.5  # Минимальная уверенность для сделки
        self.trade_fee = 0.003  # Комиссия 0.3%
        
        # Состояние
        self.is_trading = False
        self.last_analysis = None
        self.daily_pnl = 0
        
        # Загружаем сохранённое состояние
        self._load_state()
        
        logger.info(f"💰 VirtualTrader инициализирован. Баланс: {self.balance:,.0f} ₽")
    
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
        """Выполняет сделки на основе анализа ИИ с диверсификацией"""
        
        current_prices = self._get_current_prices()
        if not current_prices:
            logger.warning("Нет текущих цен, пропускаем торговлю")
            return

        # Собираем рекомендации из top_picks и главной
        recommendations = []

        # 1. Добавляем все top_picks
        for pick in analysis.get('top_picks', []):
            ticker = pick.get('ticker')
            action = pick.get('action', 'HOLD')
            confidence = pick.get('confidence', 0.5)
            if action == 'BUY' and ticker in current_prices:
                recommendations.append((ticker, confidence))

        # 2. Добавляем главную рекомендацию, если её нет в списке
        main_ticker = analysis.get('top_pick')
        main_action = analysis.get('action')
        main_conf = analysis.get('confidence', 0.5)
        if (main_action == 'BUY' and main_ticker and 
            main_ticker in current_prices and 
            not any(t for t, _ in recommendations if t == main_ticker)):
            recommendations.append((main_ticker, main_conf))

        if not recommendations:
            logger.info("Нет рекомендаций BUY, пропускаем")
            return

        # Докупка при HOLD с уверенностью > 0.8 (усиление позиции)
        for pick in analysis.get('top_picks', []):
            ticker = pick.get('ticker')
            action = pick.get('action', 'HOLD')
            confidence = pick.get('confidence', 0.5)
            if action == 'HOLD' and confidence > 0.8 and ticker in current_prices:
                # Докупаем, но с уменьшенным весом (например, 30% от обычного)
                self._buy(ticker, current_prices[ticker], confidence * 0.7, max_amount=self.balance * 0.1)

        main_action = analysis.get('action')
        main_conf = analysis.get('confidence', 0.5)
        if main_action == 'HOLD' and main_conf > 0.8 and main_ticker in current_prices:
            self._buy(main_ticker, current_prices[main_ticker], main_conf * 0.7, max_amount=self.balance * 0.1)

        # Сортируем по убыванию уверенности и берём топ‑3
        recommendations.sort(key=lambda x: x[1], reverse=True)
        recommendations = recommendations[:5]

        # Нормируем уверенности (сумма = 1) для распределения капитала
        total_conf = sum(conf for _, conf in recommendations)
        if total_conf == 0:
            return

        # Доступный для инвестиций капитал (не более 70% свободных средств)
        invest_capital = self.balance * 0.7
        if invest_capital < 1000:  # слишком мало
            logger.info("Слишком мало средств для инвестиций")
            return

        # Распределяем капитал пропорционально уверенности
        allocations = []
        for ticker, conf in recommendations:
            share = conf / total_conf
            amount = invest_capital * share
            allocations.append((ticker, amount, conf))

        # Покупаем по очереди
        for ticker, amount, conf in allocations:
            price = current_prices[ticker]
            self._buy(ticker, price, conf, amount)

        # Проверка стоп‑лоссов и тейк‑профитов
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
            logger.info(f"⏸️ {ticker}:已达 максимальный размер позиции")
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

        logger.info(f"🟢 BUY {shares} {ticker} @ {price:.2f} = {cost:,.0f} ₽ (fee: {fee:.0f})")

    def _sell(self, ticker: str, price: float, confidence: float):
        """Продаёт акции"""
        
        if ticker not in self.portfolio:
            return
        
        shares = self.portfolio[ticker]['shares']
        avg_price = self.portfolio[ticker]['avg_price']
        
        # Рассчитываем сколько продавать (на основе уверенности)
        if confidence > 0.9:
            sell_shares = shares  # Продаём всё
        elif confidence > 0.7:
            sell_shares = int(shares * 0.7)  # Продаём 70%
        else:
            sell_shares = int(shares * 0.5)  # Продаём 50%
        
        if sell_shares == 0:
            return
        
        # Совершаем продажу
        revenue = sell_shares * price
        fee = revenue * self.trade_fee
        profit = (price - avg_price) * sell_shares
        
        self.balance += (revenue - fee)
        
        # Обновляем портфель
        if sell_shares >= shares:
            del self.portfolio[ticker]
        else:
            self.portfolio[ticker]['shares'] -= sell_shares
        
        # Записываем сделку
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
            'balance_after': self.balance
        }
        self.trades.append(trade)
        
        profit_emoji = "🟢" if profit > 0 else "🔴"
        logger.info(f"{profit_emoji} SELL {sell_shares} {ticker} @ {price:.2f} = {revenue:,.0f} ₽ (profit: {profit:+,.0f})")
        
        # Обновляем дневную прибыль
        self.daily_pnl += profit
    
    def _check_positions(self, current_prices: Dict):
        """Проверяет текущие позиции на стоп-лосс и тейк-профит"""
        
        for ticker, position in list(self.portfolio.items()):
            if ticker not in current_prices:
                continue
            
            current_price = current_prices[ticker]
            avg_price = position['avg_price']
            
            # Расчёт доходности
            profit_percent = (current_price - avg_price) / avg_price * 100
            
            # Стоп-лосс -5%
            if profit_percent < -5:
                logger.info(f"🛑 Стоп-лосс для {ticker}: {profit_percent:.1f}%")
                self._sell(ticker, current_price, 1.0)
            
            # Тейк-профит +15%
            elif profit_percent > 15:
                logger.info(f"🎯 Тейк-профит для {ticker}: {profit_percent:.1f}%")
                self._sell(ticker, current_price, 1.0)
    
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
            'last_save': datetime.now().isoformat()
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
                    date = datetime.fromisoformat(trade['timestamp']).strftime('%H:%M')
                else:
                    date = trade['timestamp'].strftime('%H:%M')
                    
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