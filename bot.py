"""
Модуль с обработчиками команд Telegram.
Все объекты извлекаются из context.bot_data.
"""
import os
from telegram import Update
from telegram.ext import ContextTypes
import logging
from datetime import datetime, time, timedelta
import pandas as pd
from backtester import Backtester
import services
import pandas as pd
# import ollama
logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

def escape_markdown(text: str) -> str:
    """Экранирует спецсимволы для Markdown."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def _log_user_activity(update: Update) -> None:
    if update.effective_user:
        db = services.db()
        if db is not None:
            db.update_user_activity(
                update.effective_user.id,
                update.effective_user.first_name,
                update.effective_user.username
            )
    else:
        logger.warning("Попытка логирования активности без effective_user")

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _log_user_activity(update)
    if not update.effective_chat:
        return
    if not update.effective_user:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось определить пользователя")
        return

    ADMIN_ID = 5049120800
    if update.effective_user.id != ADMIN_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⛔ Доступ запрещён.")
        return

    db = services.db()
    if db is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка базы данных")
        return

    stats = db.get_user_stats()
    text = (
        f"📊 *Статистика пользователей*\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"🟢 Активных за 24 часа: {stats['day_active']}\n"
        f"📆 Активных за неделю: {stats['week_active']}"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _log_user_activity(update)
    """Приветственное сообщение."""
    if not update.effective_chat:
        return
    text = (
        "📰 Бот для отслеживания финансовых новостей и цен акций\n\n"
        "Я помогу тебе следить за новостями компаний и отслеживать цены акций.\n\n"
        "ИИ-трейдер (автозапуск):\n"
        "/traderstart - Запустить трейдера\n"
        "/traderstatus - 📊 Состояние портфеля\n"
        "/traderanalyze - 🔍 Принудительный анализ\n"
        "/traderstop - ⏹️ Остановить (если нужно)\n\n"
        "Новости:\n"
        "/news - последние новости\n"
        "/subscribe SBER - подписаться на новости\n"
        "/search SBER - поиск новостей\n"
        "/pulse – 📱 Посты из Tinkoff Пульс\n\n"
        "Цены акций:\n"
        "/price SBER - цена акции\n"
        "/portfolio - цены по подпискам\n"
        "/tickers - список доступных тикеров\n\n"
        "Аналитика:\n"
        "/advice - 🤖 ИИ-рекомендации\n"
        "/backtest TICKER дней - 📊 бэктест стратегии\n"
        "/chart TICKER [дней] [rsi] [macd] – 📈 график с анализом\n"
        "/analyze_ticker TICKER – 🧠 глубокий анализ акции\n"
        "/ratings – 📊 рейтинг компаний по новостям\n\n"
        "Управление:\n"
        "/mysubs - мои подписки\n"
        "/status - статус бота\n"
        "/help - подробная помощь"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text
        # parse_mode='Markdown' убрали!
    )

async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _log_user_activity(update)
    if not update.effective_chat:
        return
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Укажи тикер. Пример: /chart SBER 30 rsi"
        )
        return

    ticker = context.args[0].upper()
    days = 30
    show_rsi = False
    show_macd = False
    for arg in context.args[1:]:
        if arg.isdigit():
            days = int(arg)
        elif arg.lower() == 'rsi':
            show_rsi = True
        elif arg.lower() == 'macd':
            show_macd = True

    sp = services.stock_provider()
    if sp is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации модуля цен")
        return

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔄 Загружаю исторические данные для {ticker} за {days} дней..."
    )

    history = sp.get_history(ticker, days=days)
    if not history:
        await msg.edit_text("❌ Не удалось загрузить историю.")
        return

    from chart_generator import plot_candlestick
    file_path = plot_candlestick(
        history,
        ticker,
        ma_periods=[5, 20],
        show_rsi=show_rsi,
        show_macd=show_macd
    )

    if not file_path:
        await msg.edit_text("❌ Не удалось построить график.")
        return

    with open(file_path, 'rb') as photo:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=photo,
            caption=f"📊 График {ticker} за {days} дней"
        )
    os.unlink(file_path)
    await msg.delete()

    # после отправки графика анализируем его
    # if file_path:
    #     advisor = services.ai_advisor()
    #     analysis = advisor.analyze_image(file_path, f"График {ticker}")
    #     if analysis:
    #         await context.bot.send_message(
    #             chat_id=update.effective_chat.id,
    #             text=f"🧠 *AI-анализ графика:*\n{analysis}"
    #         )

async def analyze_chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализирует график (по фото или тикеру)."""
    import os
    await _log_user_activity(update)
    if not update.effective_chat:
        return

    # Проверяем, есть ли сообщение
    if not update.message:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Нет сообщения для анализа.")
        return

    # Если пользователь прикрепил фото
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            advisor = services.ai_advisor()
            if advisor is None:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации ИИ")
                return
            analysis = advisor.analyze_image(tmp.name, "Анализ графика по запросу")
            os.unlink(tmp.name)
            if analysis:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🧠 *AI-анализ графика:*\n{analysis}"
                )
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось проанализировать изображение")
        return

    # Если нет фото, но есть аргумент (тикер)
    if context.args:
        ticker = context.args[0].upper()
        sp = services.stock_provider()
        if sp is None:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации провайдера цен")
            return
        history = sp.get_history(ticker, days=30)
        if not history:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Нет данных для построения графика")
            return
        from chart_generator import plot_candlestick
        file_path = plot_candlestick(history, ticker)
        if not file_path:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось построить график")
            return
        with open(file_path, 'rb') as f:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=f, caption=f"📊 График {ticker}")
        advisor = services.ai_advisor()
        if advisor is None:
            os.unlink(file_path)
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации ИИ")
            return
        analysis = advisor.analyze_image(file_path, f"График {ticker}")
        os.unlink(file_path)
        if analysis:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🧠 *AI-анализ графика:*\n{analysis}")
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось проанализировать график")
        return

    await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Отправь фото графика или укажи тикер: /analyze_chart SBER")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробная помощь."""
    await start(update, context)

async def ratings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает рейтинг компаний на основе сентимента последних новостей."""
    await _log_user_activity(update)
    if not update.effective_chat:
        return

    np = services.news_parser()
    db = services.db()

    # Проверяем, что сервисы инициализированы
    if np is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации парсера")
        return
    if db is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка базы данных")
        return

    recent_news = db.get_recent_news(limit=50)
    if not recent_news:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="😕 Нет новостей для анализа")
        return

    # Простая функция сентимента (можно вынести отдельно)
    def simple_sentiment(text: str) -> float:
        text_lower = text.lower()
        positive = ['растет', 'вырастет', 'прибыль', 'дивиденды', 'успех', 'дорожает', 'buy', 'long']
        negative = ['падает', 'упадет', 'убыток', 'проблемы', 'кризис', 'дешевеет', 'sell', 'short']
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        if pos_count + neg_count == 0:
            return 0
        return (pos_count - neg_count) / (pos_count + neg_count)

    sentiment_sum = {}
    for item in recent_news:
        tickers = item.get('related_tickers', [])
        if not tickers:
            continue
        sentiment = simple_sentiment(item['title'])
        for ticker in tickers:
            if ticker not in sentiment_sum:
                sentiment_sum[ticker] = [0.0, 0]
            sentiment_sum[ticker][0] += sentiment
            sentiment_sum[ticker][1] += 1

    ratings = [(ticker, total / count) for ticker, (total, count) in sentiment_sum.items()]
    if not ratings:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="📭 Нет данных по тикерам")
        return

    ratings.sort(key=lambda x: x[1], reverse=True)

    lines = ["📊 *Рейтинг компаний по новостному сентименту*\n"]
    for i, (ticker, avg) in enumerate(ratings[:10], 1):
        emoji = "🟢" if avg > 0.2 else "🔴" if avg < -0.2 else "🟡"
        lines.append(f"{i}. {emoji} *{ticker}*: {avg:.2f}")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines), parse_mode='Markdown')

async def analyze_ticker_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глубокий ИИ-анализ конкретного тикера."""
    # Проверяем наличие пользователя перед логированием
    if not update.effective_user:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось определить пользователя") # type: ignore
        return
    

    if not update.effective_chat or not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Укажи тикер. Пример: /analyze_ticker SBER") # type: ignore
        return
    await _log_user_activity(update)
    
    ticker = context.args[0].upper()
    sp = services.stock_provider()
    np = services.news_parser()
    advisor = services.ai_advisor()

    # Проверки на None
    if sp is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации модуля цен")
        return
    if np is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации парсера")
        return
    if advisor is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации ИИ")
        return

    msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 Анализирую {ticker}, подожди...")

    # 1. Текущая цена
    price_info = sp.get_price(ticker)
    if not price_info:
        await msg.edit_text(f"❌ Не удалось получить цену для {ticker}")
        return
    current_price = price_info['last_price']
    change = price_info.get('change_percent', 0)

    # 2. Дивидендная доходность
    div_yield = advisor.company_info.get(ticker, {}).get('div_yield', 'N/A')

    # 3. Последние новости
    news = np.get_news_by_ticker(ticker, hours=168)  # за неделю
    news_titles = [f"- {n.title}" for n in news[:5]] if news else ["Новостей нет"]

    # 4. Технические данные (история цен за 30 дней)
    history = sp.get_history(ticker, days=30)
    tech_summary = "Недостаточно данных для технического анализа"
    if history and len(history) >= 20:
        df = pd.DataFrame(history)
        closes = df['close'].values
        # Скользящие средние
        ma5 = np.mean(closes[-5:])
        ma20 = np.mean(closes)
        trend = "восходящий" if ma5 > ma20 else "нисходящий" if ma5 < ma20 else "боковой"
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean().iloc[-1]
        rsi = 50
        if loss != 0:
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
        tech_summary = f"Тренд: {trend}, MA5: {ma5:.2f}, MA20: {ma20:.2f}, RSI: {rsi:.1f}"

    # 5. Формируем промпт
    prompt = f"""
    Ты профессиональный аналитик. Проведи детальный анализ акции {ticker}.

    Текущая цена: {current_price:.2f} ₽ (изм. за день: {change:+.2f}%)
    Дивидендная доходность: {div_yield}%

    Техническая картина (за 30 дней):
    {tech_summary}

    Последние новости:
    {chr(10).join(news_titles)}

    Дай развёрнутый ответ:
    1. Общая оценка ситуации (фундаментальная и техническая).
    2. Ключевые риски и возможности.
    3. Рекомендация (BUY/SELL/HOLD) с обоснованием.
    4. Целевой уровень (приблизительно) и стоп-лосс.
    """

    # 6. Отправляем запрос к модели
    try:
        # Используем метод `_call_ollama`, который уже должен быть в `advisor`
        result = advisor._call_ollama(prompt, temperature=0.3)
        if result:
            # _call_ollama возвращает словарь (распарсенный JSON) или None
            # Здесь нужно сформировать ответ. Можно просто взять поле 'content' из результата?
            # Но в _call_ollama мы возвращаем распарсенный JSON. Лучше переделать _call_ollama так,
            # чтобы он возвращал полный текст ответа, если не ожидается JSON.
            # Для простоты я предлагаю использовать другой подход: отправить запрос через httpx прямо здесь.
            import httpx
            from config import OLLAMA_HOST
            url = f"{OLLAMA_HOST}/api/chat"
            payload = {
                "model": advisor.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.3},
                "stream": False
            }
            response = httpx.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                answer = data['message']['content']
                await msg.edit_text(f"🧠 *Анализ {ticker}*\n\n{answer}", parse_mode='Markdown')
            else:
                await msg.edit_text(f"❌ Ошибка при анализе {ticker} (HTTP {response.status_code})")
        else:
            await msg.edit_text(f"❌ Не удалось получить ответ от модели")
    except Exception as e:
        logger.error(f"Ошибка при анализе {ticker}: {e}")
        await msg.edit_text(f"❌ Ошибка при анализе {ticker}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статус бота."""
    if not update.effective_chat:
        return

    # Получаем или создаём news_parser
    news_parser = context.bot_data.get('news_parser')
    if news_parser is None:
        try:
            from news_parser import NewsParser
            news_parser = NewsParser()
            context.bot_data['news_parser'] = news_parser
            logger.info("✅ news_parser создан автоматически в status_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать news_parser: {e}")

    # Получаем или создаём stock_provider
    stock_provider = context.bot_data.get('stock_provider')
    if stock_provider is None:
        try:
            from tinkoff_stocks import TinkoffStockProvider
            from config import TINKOFF_TOKEN
            stock_provider = TinkoffStockProvider(TINKOFF_TOKEN)
            context.bot_data['stock_provider'] = stock_provider
            logger.info("✅ stock_provider создан автоматически в status_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать stock_provider: {e}")

    # Если после всех попыток чего-то нет – выводим частичную статистику
    news_sources = len(news_parser.rss_sources) if news_parser else "N/A"
    tickers_count = len(stock_provider.priority_figi) if stock_provider else "N/A"

    text = (
        "📊 *СТАТУС БОТА*\n"
        "═══════════════════════════\n\n"
        f"📰 Источников новостей: {news_sources}\n"
        f"💰 Доступных тикеров: {tickers_count}\n"
        f"📊 Источник цен: Tinkoff API\n"
        f"🤖 Модель ИИ: gemma3:12b\n"
        f"✅ Бот работает"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode='Markdown'
    )

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последние новости."""
    if not update.effective_chat:
        return

    # Получаем или создаём news_parser
    news_parser = context.bot_data.get('news_parser')
    if news_parser is None:
        try:
            from news_parser import NewsParser
            news_parser = NewsParser()
            context.bot_data['news_parser'] = news_parser
            logger.info("✅ news_parser создан автоматически в news_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать news_parser: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации парсера"
            )
            return

    # Получаем или создаём db
    db = context.bot_data.get('db')
    if db is None:
        try:
            from database import NewsDatabase
            db = NewsDatabase()
            context.bot_data['db'] = db
            logger.info("✅ db создан автоматически в news_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать db: {e}")
            # Если нет базы, просто покажем новости без сохранения
            db = None

    loading_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔍 *Собираю свежие новости...*",
        parse_mode='Markdown'
    )

    try:
        news = news_parser.fetch_all_news(limit_per_source=2, max_total=20)
        if not news:
            await loading_msg.edit_text("😕 Не удалось получить новости. Попробуй позже.")
            return

        saved = 0
        if db:
            saved = db.save_news(news)

        lines = ["📰 *СВЕЖИЕ НОВОСТИ*\n"]
        lines.append(f"📊 Всего: {len(news)} | Новых: {saved}\n")
        lines.append("═" * 40)

        for item in news[:7]:
            source_emoji = {
                'interfax': '📰', 'tass': '🇷🇺', 'prime': '💼', 'cbr': '🏦',
                'bloomberg': '💰', 'reuters': '📈', 'ft': '📉', 'wsj': '📊',
                'cnbc': '📺', 'investing': '💹', 'smartlab': '🧠',
                'kommersant': '📌', 'vedomosti': '🗞️', 'rbc': '🔴',
            }.get(item.source, '📰')

            safe_title = escape_markdown(item.title)
            tickers = f" `{', '.join(item.related_tickers)}`" if item.related_tickers else ''
            lines.append(f"\n{source_emoji} *{safe_title}*{tickers}")
            lines.append(f"   🕒 {item.published.strftime('%H:%M')} | 📍 {item.source}")
            lines.append(f"   🔗 {item.link}")

        lines.append("\n" + "═" * 40)
        lines.append("💡 Используй /advice для ИИ-анализа")

        full = "\n".join(lines)
        if len(full) > 4000:
            full = full[:4000] + "\n\n... (обрезано)"

        await loading_msg.edit_text(full, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в news_command: {e}")
        await loading_msg.edit_text("❌ Ошибка при получении новостей")

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Цена акции."""
    if not update.effective_chat or not context.args:
        return

    ticker = context.args[0].upper()

    # Получаем или создаём stock_provider
    stock_provider = context.bot_data.get('stock_provider')
    if stock_provider is None:
        try:
            from tinkoff_stocks import TinkoffStockProvider
            from config import TINKOFF_TOKEN
            stock_provider = TinkoffStockProvider(TINKOFF_TOKEN)
            context.bot_data['stock_provider'] = stock_provider
            logger.info("✅ stock_provider создан автоматически в price_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать stock_provider: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации модуля цен"
            )
            return

    loading = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 Получаю данные по *{ticker}*...",
        parse_mode='Markdown'
    )

    price_info = stock_provider.get_price(ticker)
    if price_info:
        price = price_info['last_price']
        name = stock_provider.company_names.get(ticker, ticker)
        now = datetime.now().time()
        market_open = (time(6,50) <= now <= time(9,30)) or (time(10,0) <= now <= time(18,45))
        status = "🟢 Рынок открыт" if market_open else "🔴 Рынок закрыт"
        
        text = f"📈 *{ticker}* — {name}\n💰 *Цена:* {price:.2f} ₽\n{status}"
        await loading.edit_text(text, parse_mode='Markdown')
    else:
        await loading.edit_text(f"❌ Не удалось получить цену для {ticker}")

async def advice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИИ-рекомендации."""
    if not update.effective_chat:
        return

    # Получаем или создаём AIAdvisor
    advisor = context.bot_data.get('ai_advisor')
    if advisor is None:
        try:
            from ai_advisor import AIAdvisor
            from config import TINKOFF_TOKEN
            advisor = AIAdvisor(TINKOFF_TOKEN)
            context.bot_data['ai_advisor'] = advisor
            logger.info("✅ AIAdvisor создан автоматически в advice_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать AIAdvisor: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации ИИ"
            )
            return

    loading = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🤖 *ИИ анализирует рынок...*",
        parse_mode='Markdown'
    )

    try:
        analysis = advisor.analyze_all()
        message = advisor.format_advice_message(analysis)
        await loading.edit_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка в advice_command: {e}")
        await loading.edit_text("❌ Ошибка анализа")

async def monitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус мониторинга рынка"""
    if not update.effective_chat:
        return

    # Проверяем, запущен ли мониторинг (по наличию chat_id в bot_data или по флагу)
    # В текущей реализации мониторинг запускается автоматически в main.py,
    # поэтому просто покажем сообщение о том, что он работает.

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "📡 *Мониторинг рынка*\n\n"
            "✅ Автоматический мониторинг запущен и работает в фоне.\n"
            "Он проверяет новости каждый час и присылает уведомления о важных событиях.\n\n"
            "Используй:\n"
            "• `/advice` — получить рекомендацию от ИИ\n"
            "• `/trader_status` — состояние портфеля\n"
            "• `/news` — свежие новости"
        ),
        parse_mode='Markdown'
    )

async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    # Проверяем аргументы
    if context.args is None or len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Используй: /backtest TICKER дней\nНапример: /backtest SBER 30"
        )
        return

    ticker = context.args[0].upper()
    try:
        days = int(context.args[1])
    except:
        days = 30

    # Получаем или создаём stock_provider
    stock_provider = context.bot_data.get('stock_provider')
    if stock_provider is None:
        try:
            from tinkoff_stocks import TinkoffStockProvider
            from config import TINKOFF_TOKEN
            stock_provider = TinkoffStockProvider(TINKOFF_TOKEN)
            context.bot_data['stock_provider'] = stock_provider
            logger.info("✅ stock_provider создан автоматически в backtest_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать stock_provider: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации модуля цен"
            )
            return

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔄 Загружаю исторические данные для {ticker} за {days} дней..."
    )

    history = stock_provider.get_history(ticker, days=days)
    if not history:
        await msg.edit_text("❌ Не удалось загрузить историю.")
        return

    df = pd.DataFrame(history)
    if len(df) < 20:
        await msg.edit_text("❌ Недостаточно исторических данных.")
        return

    df['ma_short'] = df['close'].rolling(window=5).mean()
    df['ma_long'] = df['close'].rolling(window=20).mean()
    signals = [0] * len(df)
    for i in range(1, len(df)):
        if df['ma_short'].iloc[i] > df['ma_long'].iloc[i] and df['ma_short'].iloc[i-1] <= df['ma_long'].iloc[i-1]:
            signals[i] = 1
        elif df['ma_short'].iloc[i] < df['ma_long'].iloc[i] and df['ma_short'].iloc[i-1] >= df['ma_long'].iloc[i-1]:
            signals[i] = -1

    bt = Backtester()
    result = bt.run(ticker, history, signals)
    if not result:
        await msg.edit_text("❌ Ошибка при выполнении бэктеста.")
        return

    trades = result.get('trades', [])

    report = (
        f"📊 *Бэктест {ticker} за {days} дней*\n"
        f"💰 Начальный капитал: {result['initial_capital']:,.0f} ₽\n"
        f"💵 Итоговый капитал: {result['final_equity']:,.0f} ₽\n"
        f"📈 Доходность: {result['total_return']:+.2f}%\n"
        f"📉 Макс. просадка: {result['max_drawdown']:.2f}%\n"
        f"⚖️ Коэф. Шарпа: {result['sharpe_ratio']:.2f}\n"
        f"📋 Сделок: {len(trades)}\n\n"
        f"*Последние сделки:*\n"
    )
    for t in trades[-3:]:
        emoji = "🟢" if t['action'] == 'BUY' else "🔴"
        date_str = t['date'].strftime('%d.%m') if hasattr(t['date'], 'strftime') else str(t['date'])[5:10]
        report += f"{emoji} {date_str} {t['action']} {t['shares']} @ {t['price']:.2f}\n"

    await msg.edit_text(report, parse_mode='Markdown')

# ========== КОМАНДЫ ПОДПИСОК ==========

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user or not context.args:
        return
    ticker = context.args[0].upper()
    if not update.effective_user:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось определить пользователя.")
        return
    user_id = update.effective_user.id
    db = context.bot_data.get('db')
    if db is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка базы данных")
        return
    success = db.add_subscription(user_id, ticker)
    text = f"✅ Ты подписался на новости *{ticker}*!" if success else f"⚠️ Ты уже подписан на *{ticker}*"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not update.effective_user or not context.args:
        return
    ticker = context.args[0].upper()

    if not update.effective_user:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Не удалось определить пользователя.")
        return
    user_id = update.effective_user.id

    db = context.bot_data.get('db')
    if db is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка базы данных")
        return
    success = db.remove_subscription(user_id, ticker)
    text = f"✅ Отписался от *{ticker}*" if success else f"❌ Ты не был подписан на *{ticker}*"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def mysubs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    if not update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Не удалось определить пользователя."
        )
        return

    # Получаем или создаём db
    db = context.bot_data.get('db')
    if db is None:
        try:
            from database import NewsDatabase
            db = NewsDatabase()
            context.bot_data['db'] = db
            logger.info("✅ db создан автоматически в mysubs_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать db: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка базы данных"
            )
            return

    user_id = update.effective_user.id
    raw_subs = db.get_user_subscriptions(user_id)
    subs = raw_subs if raw_subs is not None else []

    if subs:
        text = "📋 *Твои подписки:*\n" + "\n".join(f"• {t}" for t in subs)
    else:
        text = "📭 У тебя пока нет подписок."

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode='Markdown'
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or not context.args:
        return
    ticker = context.args[0].upper()

    # Получаем или создаём news_parser
    news_parser = context.bot_data.get('news_parser')
    if news_parser is None:
        try:
            from news_parser import NewsParser
            news_parser = NewsParser()
            context.bot_data['news_parser'] = news_parser
            logger.info("✅ news_parser создан автоматически в search_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать news_parser: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации парсера"
            )
            return

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"🔍 Ищу новости по *{ticker}*...",
        parse_mode='Markdown'
    )

    try:
        news = news_parser.get_news_by_ticker(ticker, hours=24)
        if not news:
            await msg.edit_text(f"😕 Не найдено новостей по {ticker} за 24 часа")
            return
        lines = [f"📰 *Новости по {ticker}*\n"]
        for item in news[:5]:
            lines.append(f"\n• *{escape_markdown(item.title)}*")
            lines.append(f"  🕒 {item.published.strftime('%H:%M %d.%m')} | 📍 {item.source}")
            lines.append(f"  🔗 {item.link}")
        lines.append(f"\n📊 Всего найдено: {len(news)}")
        await msg.edit_text("\n".join(lines), parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Ошибка в search_command: {e}")
        await msg.edit_text(f"❌ Ошибка при поиске")

async def tickers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    db = services.db()
    if db is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка базы данных")
        return

    tickers = db.get_all_tickers()
    logger.info(f"📋 get_all_tickers вернул {len(tickers)} записей, первые 5: {tickers[:5]}")

    # Фильтруем числовые тикеры (оставляем только те, в которых есть хотя бы одна буква)
    filtered = [t for t in tickers if not t.isdigit()]

    if not filtered:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="📭 Список тикеров пока пуст")
        return

    sample = filtered[:50]
    text = "📋 *Доступные тикеры (первые 50):*\n" + ", ".join(sample)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return
    if not update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Не удалось определить пользователя."
        )
        return

    # Получаем или создаём db
    db = context.bot_data.get('db')
    if db is None:
        try:
            from database import NewsDatabase
            db = NewsDatabase()
            context.bot_data['db'] = db
            logger.info("✅ db создан автоматически в portfolio_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать db: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка базы данных"
            )
            return

    # Получаем или создаём stock_provider
    stock_provider = context.bot_data.get('stock_provider')
    if stock_provider is None:
        try:
            from tinkoff_stocks import TinkoffStockProvider
            from config import TINKOFF_TOKEN
            stock_provider = TinkoffStockProvider(TINKOFF_TOKEN)
            context.bot_data['stock_provider'] = stock_provider
            logger.info("✅ stock_provider создан автоматически в portfolio_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать stock_provider: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации модуля цен"
            )
            return

    user_id = update.effective_user.id
    raw_subs = db.get_user_subscriptions(user_id)
    subs = raw_subs if raw_subs is not None else []

    if not subs:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📭 У тебя пока нет подписок."
        )
        return

    lines = ["📊 *Твой портфель*\n"]
    for t in subs:
        price_info = stock_provider.get_price(t)
        if price_info:
            lines.append(f"• *{t}*: {price_info['last_price']:.2f} ₽")
        else:
            lines.append(f"• *{t}*: ❌ нет данных")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(lines),
        parse_mode='Markdown'
    )

# ========== КОМАНДЫ ТРЕЙДЕРА ==========

async def trader_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    # Получаем или создаём трейдера
    trader = context.bot_data.get('ai_trader')
    if trader is None:
        try:
            from ai_trader import VirtualTrader
            from config import TINKOFF_TOKEN
            trader = VirtualTrader(initial_balance=1000000)
            context.bot_data['ai_trader'] = trader
            logger.info("✅ VirtualTrader создан автоматически в trader_start_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать трейдера: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации трейдера"
            )
            return

    if trader.is_trading:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🤖 *ИИ-трейдер уже работает!*\nОн был запущен автоматически.",
            parse_mode='Markdown'
        )
    else:
        trader.start_trading()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🚀 *ИИ-трейдер запущен!*",
            parse_mode='Markdown'
        )

async def trader_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    trader = context.bot_data.get('ai_trader')
    if trader is None:
        try:
            from ai_trader import VirtualTrader
            from config import TINKOFF_TOKEN
            trader = VirtualTrader(initial_balance=1000000)
            context.bot_data['ai_trader'] = trader
            logger.info("✅ VirtualTrader создан автоматически в trader_stop_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать трейдера: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации трейдера"
            )
            return

    if trader.is_trading:
        trader.stop_trading()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⏹️ *ИИ-трейдер остановлен*",
            parse_mode='Markdown'
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Трейдер уже остановлен",
            parse_mode='Markdown'
        )

async def trader_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    trader = context.bot_data.get('ai_trader')
    if trader is None:
        try:
            from ai_trader import VirtualTrader
            from config import TINKOFF_TOKEN
            trader = VirtualTrader(initial_balance=1000000)
            context.bot_data['ai_trader'] = trader
            logger.info("✅ VirtualTrader создан автоматически в trader_status_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать трейдера: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации трейдера"
            )
            return

    msg = trader.format_portfolio_message()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        parse_mode='Markdown'
    )

async def pulse_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последние посты из Tinkoff Пульс."""
    await _log_user_activity(update)
    if not update.effective_chat:
        return

    parser = services.pulse_parser()
    if parser is None:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Ошибка инициализации Пульс")
        return

    # Получаем ленту
    posts = parser.get_feed(limit=5)
    if not posts:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="😕 Не удалось получить посты")
        return

    lines = ["📱 *Tinkoff Пульс*\n"]
    for post in posts:
        emoji = "🟢" if post.sentiment_category == 'positive' else "🔴" if post.sentiment_category == 'negative' else "🟡"
        tickers = f" [{', '.join(post.tickers)}]" if post.tickers else ""
        lines.append(f"{emoji} *{post.author}*{tickers}")
        lines.append(f"   {post.text[:100]}...")
        lines.append(f"   👍 {post.likes}  💬 {post.comments}  🕒 {post.date.strftime('%H:%M %d.%m')}\n")

    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(lines), parse_mode='Markdown')

async def trader_analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat:
        return

    trader = context.bot_data.get('ai_trader')
    if trader is None:
        try:
            from ai_trader import VirtualTrader
            from config import TINKOFF_TOKEN
            trader = VirtualTrader(initial_balance=1000000)
            context.bot_data['ai_trader'] = trader
            logger.info("✅ VirtualTrader создан автоматически в trader_analyze_command")
        except Exception as e:
            logger.error(f"❌ Не удалось создать трейдера: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Ошибка инициализации трейдера"
            )
            return

    if not trader.is_trading:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ Трейдер остановлен. Запустите /traderstart"
        )
        return

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🤖 ИИ анализирует рынок..."
    )
    trader.analyze_and_trade()
    portfolio = trader.format_portfolio_message()
    await msg.edit_text(f"✅ *Анализ завершён*\n\n{portfolio}", parse_mode='Markdown')