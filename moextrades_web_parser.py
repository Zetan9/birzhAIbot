import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time
from typing import List, Dict

class MoexWebParser:
    BASE_URL = "https://t.me/s/moextrades"
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
    
    def get_page(self, before=None, retries=3):
        if before:
            url = f"{self.BASE_URL}?before={before}"
        else:
            url = self.BASE_URL
        
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=15)
                response.raise_for_status()
                return response.text
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                print(f"Попытка {attempt+1} не удалась: {e}")
                time.sleep(5)  # ждём перед повтором
        raise Exception(f"Не удалось загрузить {url} после {retries} попыток")

    def parse_messages(self, html):
        """Извлекает сообщения из HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        messages = soup.find_all('div', class_='tgme_widget_message_wrap')
        
        result = []
        for msg in messages:
            try:
                # ID сообщения (из ссылки)
                link_elem = msg.find('a', class_='tgme_widget_message_date')
                if not link_elem:
                    continue
                link = link_elem.get('href', '')
                msg_id = link.split('/')[-1]
                
                # Текст сообщения
                text_elem = msg.find('div', class_='tgme_widget_message_text')
                text = text_elem.get_text() if text_elem else ''
                
                # Дата (из атрибута datetime)
                date_elem = msg.find('time', class_='time')
                date_str = date_elem.get('datetime') if date_elem else ''
                if date_str:
                    # Пример: 2026-02-24T22:35:00+00:00
                    date = datetime.fromisoformat(date_str.replace('+00:00', ''))
                else:
                    date = datetime.now()
                
                result.append({
                    'id': msg_id,
                    'text': text,
                    'date': date,
                    'link': link
                })
            except Exception as e:
                print(f"Ошибка парсинга сообщения: {e}")
        
        return result
    
    def get_all_messages(self, limit=1000):
        """Собирает до limit сообщений, проходя по страницам."""
        messages = []
        before = None
        while len(messages) < limit:
            print(f"Загрузка страницы... (получено {len(messages)} сообщений)")
            html = self.get_page(before)
            new_msgs = self.parse_messages(html)
            if not new_msgs:
                break
            
            # Определяем before для следующей страницы (ID самого старого сообщения)
            before = new_msgs[-1]['id']
            
            # Добавляем новые сообщения, избегая дубликатов
            existing_ids = {m['id'] for m in messages}
            for msg in new_msgs:
                if msg['id'] not in existing_ids:
                    messages.append(msg)
            
            # Небольшая задержка, чтобы не нагружать сервер
            time.sleep(2)
        
        return messages[:limit]

    def convert_to_signal(self, msg):
        """Преобразует сообщение в формат сигнала (как в moex_rss)."""
        from moex_rss import parse_signal_from_item
        # Из текста извлекаем заголовок и описание
        lines = msg['text'].split('\n')
        title = lines[0] if lines else ''
        description = msg['text']
        
        # Создаём словарь, а не объект
        item = {
            'title': title,
            'description': description,
            'link': msg['link'],
            'published': msg['date'].isoformat()
        }
        return parse_signal_from_item(item)