import re
import asyncio
import logging
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError



logger = logging.getLogger(__name__)

class MoexSignalsParser:
    def __init__(self, api_id: int, api_hash: str, session_name: str = 'moex_signals', channel: str = 'moextrades'):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.channel = channel
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.callback = None  # функция, вызываемая при новом сигнале

        

    def set_callback(self, callback):
        self.callback = callback

    async def start(self):
        """Запускает прослушивание новых сообщений."""
        await self.client.start()
        if not await self.client.is_user_authorized():
            logger.info("Требуется авторизация. Введите номер телефона и код.")
            await self.client.send_code_request(await self.client.get_me())
            try:
                await self.client.sign_in(phone=input('Введите номер: '))
            except SessionPasswordNeededError:
                await self.client.sign_in(password=input('Введите пароль (2FA): '))

        try:
            entity = await self.client.get_entity(self.channel)
        except Exception as e:
            logger.error(f"Не удалось получить канал {self.channel}: {e}")
            return

        @self.client.on(events.NewMessage(chats=entity))
        async def handler(event):
            await self._parse_message(event.message)

        logger.info(f"✅ Подключён к каналу {self.channel}, жду сообщений...")
        await self.client.run_until_disconnected()

    async def _parse_message(self, message):
        text = message.text
        if not text:
            return None

        if '📈' in text or '🟢' in text:
            signal_type = 'bullish'
        elif '🔴' in text:
            signal_type = 'bearish'
        else:
            return None

        ticker_match = re.search(r'#([A-Z]+)', text)
        if not ticker_match:
            return None
        ticker = ticker_match.group(1)

        price_match = re.search(r'Цена: ([\d\.]+)', text)
        price = float(price_match.group(1)) if price_match else None

        delta_p_match = re.search(r'ΔP ([+-]?[\d\.]+)%', text)
        delta_p = float(delta_p_match.group(1)) if delta_p_match else None

        volume_match = re.search(r'Аномальный объём: ([\d\.]+)([МК]?)', text)
        volume = None
        if volume_match:
            val = float(volume_match.group(1))
            unit = volume_match.group(2)
            if unit == 'М':
                volume = val * 1_000_000
            elif unit == 'К':
                volume = val * 1_000
            else:
                volume = val

        buy_match = re.search(r'Покупка: (\d+)%', text)
        sell_match = re.search(r'Продажа: (\d+)%', text)
        buy_pct = int(buy_match.group(1)) if buy_match else None
        sell_pct = int(sell_match.group(1)) if sell_match else None

        time_match = re.search(r'Время: ([\d\.: ]+)', text)
        if time_match:
            try:
                signal_time = datetime.strptime(time_match.group(1), '%d.%m.%Y %H:%M:%S')
            except:
                signal_time = message.date
        else:
            signal_time = message.date

        signal = {
            'ticker': ticker,
            'type': signal_type,
            'price': price,
            'delta_p': delta_p,
            'volume': volume,
            'buy_pct': buy_pct,
            'sell_pct': sell_pct,
            'time': signal_time,
            'raw_text': text[:200]
        }

        logger.info(f"📡 Получен сигнал: {ticker} {signal_type} цена={price} ΔP={delta_p}%")
        if self.callback:
            await self.callback(signal)
        return signal

    async def fetch_recent(self, limit=100):
        """Загружает последние limit сообщений из канала (для исторических данных)."""
        await self.client.start()
        entity = await self.client.get_entity(self.channel)
        messages = await self.client.get_messages(entity, limit=limit)
        signals = []
        for msg in messages:
            sig = await self._parse_message(msg)
            if sig:
                signals.append(sig)
        return signals