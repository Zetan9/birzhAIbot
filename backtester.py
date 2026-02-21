import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class Backtester:
    def __init__(self, initial_capital: float = 100000, commission: float = 0.003):
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self, ticker: str, prices: List[Dict], signals: List[int]) -> Dict:
        """
        prices: список баров с ключами 'time', 'close'
        signals: список сигналов (1 = купить, -1 = продать, 0 = держать)
        """
        df = pd.DataFrame(prices)
        df['signal'] = signals[:len(df)]

        capital = self.initial_capital
        position = 0
        trades = []
        equity_curve = []

        for i, row in df.iterrows():
            price = row['close']

            if row['signal'] == 1 and capital > 0:
                shares = int(capital * 0.95 / price)
                cost = shares * price * (1 + self.commission)
                if cost <= capital:
                    position += shares
                    capital -= cost
                    trades.append({
                        'date': row['time'],
                        'action': 'BUY',
                        'price': price,
                        'shares': shares,
                        'cost': cost
                    })

            elif row['signal'] == -1 and position > 0:
                revenue = position * price * (1 - self.commission)
                capital += revenue
                trades.append({
                    'date': row['time'],
                    'action': 'SELL',
                    'price': price,
                    'shares': position,
                    'revenue': revenue
                })
                position = 0

            equity = capital + position * price
            equity_curve.append({'date': row['time'], 'equity': equity})

        if position > 0:
            price = df.iloc[-1]['close']
            revenue = position * price * (1 - self.commission)
            capital += revenue
            trades.append({
                'date': df.iloc[-1]['time'],
                'action': 'SELL (close)',
                'price': price,
                'shares': position,
                'revenue': revenue
            })

        final_equity = capital
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100

        df_equity = pd.DataFrame(equity_curve)
        df_equity['peak'] = df_equity['equity'].cummax()
        df_equity['drawdown'] = (df_equity['equity'] - df_equity['peak']) / df_equity['peak'] * 100
        max_drawdown = df_equity['drawdown'].min()

        returns = df_equity['equity'].pct_change().dropna()
        sharpe = np.sqrt(252) * returns.mean() / returns.std() if returns.std() != 0 else 0

        return {
            'ticker': ticker,
            'initial_capital': self.initial_capital,
            'final_equity': final_equity,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe,
            'trades': trades,
            'equity_curve': equity_curve
        }