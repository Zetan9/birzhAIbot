"""
Генератор графиков для технического анализа.
"""
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from typing import List, Dict, Optional
import tempfile
import os

def plot_candlestick(
    history: List[Dict],
    ticker: str,
    ma_periods: List[int] = [5, 20],
    show_rsi: bool = False,
    show_macd: bool = False
) -> Optional[str]:
    """
    Строит свечной график с индикаторами и сохраняет во временный PNG.
    Возвращает путь к файлу или None при ошибке.
    """
    if not history:
        return None

    # Преобразование данных
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

    # Стиль графика
    mc = mpf.make_marketcolors(up='g', down='r', inherit=True)
    style = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=False)

    # Сбор панелей и соотношений высот
    panel_ratios = [6]      # основная панель (свечи)
    add_plots = []

    # Скользящие средние (на основную панель)
    for ma in ma_periods:
        ma_series = df['Close'].rolling(window=ma).mean()
        add_plots.append(mpf.make_addplot(ma_series, panel=0, width=0.7, label=f'MA{ma}'))

    current_panel = 1       # следующая свободная панель

    # RSI
    if show_rsi:
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        df['RSI'] = rsi
        add_plots.append(mpf.make_addplot(df['RSI'], panel=current_panel, color='purple', ylabel='RSI'))
        panel_ratios.append(2)   # высота для RSI
        current_panel += 1

    # MACD (две панели: линия и гистограмма)
    if show_macd:
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp12 - exp26
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal
        df['MACD'] = macd
        df['Signal'] = signal
        df['Histogram'] = histogram

        add_plots.append(mpf.make_addplot(df['MACD'], panel=current_panel, color='blue', ylabel='MACD'))
        add_plots.append(mpf.make_addplot(df['Signal'], panel=current_panel, color='red'))
        panel_ratios.append(3)   # высота для линии MACD
        current_panel += 1

        add_plots.append(mpf.make_addplot(df['Histogram'], type='bar', panel=current_panel, color='gray', alpha=0.5, ylabel='Hist'))
        panel_ratios.append(2)   # высота для гистограммы
        current_panel += 1

    # Панель объёмов (всегда последняя)
    add_plots.append(mpf.make_addplot(df['Volume'], type='bar', panel=current_panel, color='gray', alpha=0.5, ylabel='Volume'))
    panel_ratios.append(1.5)      # высота для объёмов # type: ignore

    # Построение и сохранение графика
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            fig, axes = mpf.plot(
                df,
                type='candle',
                style=style,
                title=f'{ticker} – свечной график',
                ylabel='Цена (₽)',
                volume=False,               # отключаем автоматические объёмы
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