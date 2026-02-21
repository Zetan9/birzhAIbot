"""
Главный файл запуска бота.
"""
import asyncio
import logging
import threading
import services
from telegram import Update
from telegram.ext import Application, CommandHandler
from config import TELEGRAM_BOT_TOKEN, TINKOFF_TOKEN
from ai_trader import start_auto_trading
from ai_monitor import start_monitoring
from pulse_monitor import PulseMonitor
from bot import (  # все команды
    start, help_command, news_command, price_command,
    advice_command, status_command, subscribe_command,
    unsubscribe_command, mysubs_command, search_command,
    tickers_command, portfolio_command,
    trader_start_command, trader_stop_command,
    trader_status_command, trader_analyze_command,
    backtest_command, monitor_command, stats_command,
    chart_command, pulse_command, analyze_chart_command,
    ratings_command, analyze_ticker_command
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NOTIFICATION_CHAT_ID = 5049120800  # твой Telegram ID

async def load_instruments():
    """Загружает все инструменты и сохраняет в БД."""
    logger.info("🔄 Загрузка инструментов началась...")
    try:
        stock_provider = services.stock_provider()
        db = services.db()

        if stock_provider is None:
            logger.error("❌ stock_provider не инициализирован")
            return
        if db is None:
            logger.error("❌ db не инициализирована")
            return

        instruments = stock_provider.get_all_instruments()
        if instruments:
            logger.info(f"📊 Получено {len(instruments)} инструментов из API")
            db.save_instruments(instruments)
            logger.info(f"📈 База данных инструментов обновлена, всего {len(instruments)} записей")
        else:
            logger.warning("⚠️ get_all_instruments вернул пустой список")
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке инструментов: {e}", exc_info=True)

async def run_bot():
    logger.info("🚀 Создание приложения бота...")
    
    # Сначала загружаем инструменты (они нам нужны для работы)
    await load_instruments()
    
    # Создаём приложение
    app = Application.builder().token(TELEGRAM_BOT_TOKEN)\
        .connect_timeout(30)\
        .read_timeout(30)\
        .build()
    
    # Регистрация обработчиков команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("advice", advice_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    app.add_handler(CommandHandler("mysubs", mysubs_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("tickers", tickers_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("backtest", backtest_command))
    app.add_handler(CommandHandler("monitor", monitor_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("chart", chart_command))
    app.add_handler(CommandHandler("pulse", pulse_command))
    app.add_handler(CommandHandler("analyze_chart", analyze_chart_command))
    app.add_handler(CommandHandler("ratings", ratings_command))
    app.add_handler(CommandHandler("analyze_ticker", analyze_ticker_command))
    # Альтернативные имена команд
    app.add_handler(CommandHandler("traderstart", trader_start_command))
    app.add_handler(CommandHandler("traderstop", trader_stop_command))
    app.add_handler(CommandHandler("traderstatus", trader_status_command))
    app.add_handler(CommandHandler("traderanalyze", trader_analyze_command))
    
    # Запуск бота
    await app.initialize()
    await app.start()
    if app.updater:
        await app.updater.start_polling()
    else:
        logger.error("❌ Updater is None")
        return
    
    logger.info("✅ Бот запущен и готов к работе")

    # ---- Теперь инициализируем сервисы и запускаем фоновые задачи ----
    services.news_parser()
    services.db()
    services.stock_provider()
    services.ai_advisor()
    trader = services.ai_trader()
    
    # Запуск трейдера
    if trader:
        trading_thread = threading.Thread(
            target=start_auto_trading,
            args=(trader, 300),
            daemon=True
        )
        trading_thread.start()
        logger.info(f"💰 Трейдер автоматически запущен! Баланс: {trader.balance:,.0f} ₽")
    else:
        logger.error("❌ Не удалось создать трейдера")

    # Запуск мониторинга новостей
    if NOTIFICATION_CHAT_ID:
        asyncio.create_task(start_monitoring(app.bot, NOTIFICATION_CHAT_ID))
        logger.info(f"🚀 Мониторинг новостей запущен для чата {NOTIFICATION_CHAT_ID}")

    # # Запуск мониторинга Пульса
    # if NOTIFICATION_CHAT_ID:
    #     pulse_monitor = PulseMonitor(app.bot, NOTIFICATION_CHAT_ID)
    #     asyncio.create_task(pulse_monitor.start_monitoring())
    #     logger.info("📱 Мониторинг Tinkoff Пульс запущен")

    # Запуск мониторинга Smart-Lab
    if NOTIFICATION_CHAT_ID:
        from smartlab_monitor import SmartLabMonitor
        smartlab_monitor = SmartLabMonitor(app.bot, NOTIFICATION_CHAT_ID)
        asyncio.create_task(smartlab_monitor.start_monitoring())
        logger.info("📊 Мониторинг Smart-Lab запущен")

    # Основной цикл
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Остановка бота...")
        if trader:
            trader.stop_trading()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run_bot())