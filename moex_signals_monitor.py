import asyncio
import logging
import os
from datetime import datetime
from typing import Optional

import services
from moex_rss import fetch_signals

logger = logging.getLogger(__name__)

class MoexSignalsMonitor:
    def __init__(self, bot, chat_id: Optional[int] = None, trader=None):
        self.bot = bot
        self.chat_id = chat_id
        self.trader = trader
        self.processed_ids = set()
        self.model = None
        self.feature_names = None
        self.confidence_threshold = 0.7
        self.check_interval = 30  # секунд между проверками RSS

        # Попытаемся загрузить модель (если есть)
        from signal_model import load_model
        self.model, self.feature_names = load_model()
        if self.model:
            logger.info("✅ Модель сигналов загружена")
        else:
            logger.info("⏳ Модель сигналов не загружена, использую все сигналы")

    async def start(self):
        logger.info("🚀 Запуск мониторинга MOEX Signals через RSS...")
        while True:
            try:
                await self.check_rss()
            except Exception as e:
                logger.error(f"Ошибка в мониторинге: {e}")
            await asyncio.sleep(self.check_interval)

    async def check_rss(self):
        """Периодически проверяет RSS и обрабатывает новые сигналы."""
        signals = fetch_signals(limit=20)  # получаем последние 20
        if not signals:
            return

        db = services.db()
        for sig in signals:
            # Используем id поста как уникальный идентификатор
            sig_id = sig.get('id')
            if not sig_id or sig_id in self.processed_ids:
                continue
            self.processed_ids.add(sig_id)

            # Сохраняем в БД
            signal_id = db.save_moex_signal(sig)
            logger.debug(f"Сигнал #{signal_id} сохранён")

            # Оценка модели
            model_score = None
            use_signal = True
            if self.model and self.feature_names:
                try:
                    from signal_model import predict_signal
                    model_score = predict_signal(sig, self.model, self.feature_names)
                    db.update_signal_model_score(signal_id, model_score)
                    logger.info(f"📊 Оценка модели для {sig['ticker']}: {model_score:.2f}")
                    use_signal = model_score >= self.confidence_threshold
                except Exception as e:
                    logger.error(f"Ошибка при предсказании модели: {e}")

            if not use_signal:
                logger.debug(f"Сигнал {sig['ticker']} отклонён моделью (score={model_score:.2f})")
                continue

            # Передаём трейдеру
            if self.trader:
                await self._execute_trade(sig, model_score)

            # Отправляем уведомление в Telegram
            if self.chat_id:
                await self._send_notification(sig, model_score)

    async def _execute_trade(self, signal, model_score):
        """Совершает сделку на основе сигнала."""
        ticker = signal['ticker']
        price = signal['price']
        if not price:
            logger.warning(f"Сигнал {ticker} без цены, пропускаю")
            return

        confidence = 0.7
        if model_score:
            confidence = model_score

        if signal['type'] == 'bullish':
            self.trader._buy(ticker, price, confidence, max_amount=None)
        else:
            if ticker in self.trader.portfolio:
                shares = self.trader.portfolio[ticker]['shares']
                sell_shares = int(shares * 0.5)
                if sell_shares > 0:
                    self.trader._sell(ticker, price, confidence, reason='moex_signal', shares=sell_shares)

    async def _send_notification(self, signal, model_score=None):
        emoji = "🟢" if signal['type'] == 'bullish' else "🔴"
        text = f"{emoji} *MOEX Signal: {signal['ticker']}*\n"
        if signal['price']:
            text += f"💰 Цена: {signal['price']:.2f} ₽\n"
        if signal['delta_p']:
            text += f"📈 ΔP: {signal['delta_p']:+.2f}%\n"
        if signal['volume']:
            vol_m = signal['volume'] / 1_000_000
            text += f"📊 Объём: {vol_m:.1f}M ₽\n"
        if signal['buy_pct'] is not None:
            text += f"📊 Покупка: {signal['buy_pct']}% / Продажа: {signal['sell_pct']}%\n"
        if model_score is not None:
            text += f"🧠 Оценка модели: {model_score:.2f}\n"
        text += f"⏱ {signal['time'].strftime('%H:%M:%S')}"
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")