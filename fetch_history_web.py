from moextrades_web_parser import MoexWebParser
import services

parser = MoexWebParser()
messages = parser.get_all_messages(limit=25)  # или больше

db = services.db()
for msg in messages:
    signal = parser.convert_to_signal(msg)
    if signal:
        db.save_moex_signal(signal)
        print(f"Сохранён сигнал {signal['ticker']} от {signal['time']}")