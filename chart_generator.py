"""
Генератор графиков для технического анализа.
"""
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Должен быть перед любым другим импортом matplotlib
import matplotlib.pyplot as plt
import mplfinance as mpf
from typing import List, Dict, Optional
import tempfile
import os
import logging

logger = logging.getLogger(__name__)

def plot_candlestick(
    history: List[Dict],
    ticker: str,
    ma_periods: List[int] = [5, 20],
    show_rsi: bool = False,
    show_macd: bool = False
) -> Optional[str]:
    if not history:
        return None

    df = pd.DataFrame(history)
    df.set_index('time', inplace=True)
    df.sort_index(inplace=True)
    df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume'
    }, inplace=True)
    df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)

    mc = mpf.make_marketcolors(up='g', down='r', inherit=True)
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=False)

    panel_ratios = [6.0]
    add_plots = []

    # Скользящие средние
    for ma in ma_periods:
        ma_series = df['Close'].rolling(window=ma).mean()
        add_plots.append(mpf.make_addplot(ma_series, panel=0, width=0.7, label=f'MA{ma}'))

    current_panel = 1

    # RSI
    if show_rsi:
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        df['RSI'] = rsi

        rsi_valid = rsi.dropna()
        if not rsi_valid.empty:
            add_plots.append(mpf.make_addplot(rsi_valid, panel=current_panel, color='purple', ylabel='RSI'))
            panel_ratios.append(2)
            current_panel += 1
        else:
            logger.warning("Недостаточно данных для RSI, пропускаем")

    # MACD
    if show_macd:
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        df['MACD'] = macd
        df['Signal'] = signal
        df['Histogram'] = histogram

        macd_valid = macd.dropna()
        signal_valid = signal.dropna()
        hist_valid = histogram.dropna()

        if not macd_valid.empty and not signal_valid.empty:
            add_plots.append(mpf.make_addplot(macd_valid, panel=current_panel, color='blue', ylabel='MACD'))
            add_plots.append(mpf.make_addplot(signal_valid, panel=current_panel, color='red'))
            panel_ratios.append(3)
            current_panel += 1
        else:
            logger.warning("Недостаточно данных для MACD, пропускаем")

        if not hist_valid.empty:
            add_plots.append(mpf.make_addplot(hist_valid, type='bar', panel=current_panel, color='gray', alpha=0.5, ylabel='Hist'))
            panel_ratios.append(2)
            current_panel += 1
        else:
            logger.warning("Недостаточно данных для гистограммы MACD, пропускаем")

    # Объёмы
    add_plots.append(mpf.make_addplot(df['Volume'], type='bar', panel=current_panel, color='gray', alpha=0.5, ylabel='Volume'))
    panel_ratios.append(1.5)

    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            fig, axes = mpf.plot(
                df,
                type='candle',
                style=style,
                title=f'{ticker} – свечной график',
                ylabel='Цена (₽)',
                volume=False,
                addplot=add_plots,
                panel_ratios=panel_ratios,
                returnfig=True,
                savefig=tmp.name
            )
            plt.close(fig)
            return tmp.name
    except Exception as e:
        if 'tmp' in locals() and os.path.exists(tmp.name):
            os.unlink(tmp.name)
        raise e