"""
ИИ-советник для анализа новостей (оптимизирован для CPU)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from collections import defaultdict
import json
import hashlib
import os
import time
import base64
import re
from news_parser import NewsItem
import ollama
import pandas as pd
import services
import httpx
from config import OLLAMA_HOST

# DISABLE_AI = os.getenv("DISABLE_AI", "false").lower() == "false"

logger = logging.getLogger(__name__)

class AIAdvisor:
    """ИИ-советник для инвестиций"""
    
    # Константы
    CACHE_TTL: int = 1800  # 30 минут
    MAX_NEWS_ANALYZE: int = 12
    MAX_NEWS_QUICK: int = 8
    TEMPERATURE: float = 0.3
    
    def __init__(self, tinkoff_token: str) -> None:
        self.vision_model = "moondream:latest"  # "llava:13b" или "bakllava:7b"
        self.vision_enabled = False

        self.stock_provider = services.stock_provider()
        self.news_parser = services.news_parser()
        self.db = services.db()
        
        self.llm_model: str = "gemma3:12b"
        self.max_news: int = self.MAX_NEWS_ANALYZE
        self.cache_enabled: bool = True
        self.cache_dir: str = "cache/ai_advisor"
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.company_info: Dict[str, Dict[str, Any]] = {
            # Нефть и газ (8)
            'GAZP': {'name': 'Газпром', 'sector': 'Нефть и газ', 'div_yield': 15.0, 'figi': 'BBG004730RP0'},
            'LKOH': {'name': 'Лукойл', 'sector': 'Нефть и газ', 'div_yield': 10.5, 'figi': 'BBG004731032'},
            'ROSN': {'name': 'Роснефть', 'sector': 'Нефть и газ', 'div_yield': 6.8, 'figi': 'BBG0047314D0'},
            'TATN': {'name': 'Татнефть', 'sector': 'Нефть и газ', 'div_yield': 12.3, 'figi': 'BBG004RVFFC0'},
            'NVTK': {'name': 'Новатэк', 'sector': 'Нефть и газ', 'div_yield': 5.2, 'figi': 'BBG0047315G5'},
            'SNGS': {'name': 'Сургутнефтегаз', 'sector': 'Нефть и газ', 'div_yield': 4.5, 'figi': 'BBG0047315D0'},
            'SNGSP': {'name': 'Сургутнефтегаз (пр)', 'sector': 'Нефть и газ', 'div_yield': 8.0, 'figi': 'BBG0047315F8'},
            'TATNP': {'name': 'Татнефть (пр)', 'sector': 'Нефть и газ', 'div_yield': 15.0, 'figi': 'BBG004RVFCY3'},
            
            # Банки и финансы (5)
            'SBER': {'name': 'Сбербанк', 'sector': 'Банки', 'div_yield': 8.5, 'figi': 'BBG004730N88'},
            'SBERP': {'name': 'Сбербанк (пр)', 'sector': 'Банки', 'div_yield': 9.0, 'figi': 'BBG0047315D0'},
            'VTBR': {'name': 'ВТБ', 'sector': 'Банки', 'div_yield': 0.0, 'figi': 'BBG004730ZJ9'},
            'TCSG': {'name': 'Т-Банк', 'sector': 'Банки', 'div_yield': 0.0, 'figi': 'BBG00QPYJ5H0'},
            'CBOM': {'name': 'МКБ', 'sector': 'Банки', 'div_yield': 3.2, 'figi': 'BBG00B3T3HF3'},
            
            # Металлы и добыча (8)
            'GMKN': {'name': 'Норникель', 'sector': 'Металлы', 'div_yield': 7.8, 'figi': 'BBG00475J7X2'},
            'NLMK': {'name': 'НЛМК', 'sector': 'Металлы', 'div_yield': 9.1, 'figi': 'BBG00475J5C7'},
            'CHMF': {'name': 'Северсталь', 'sector': 'Металлы', 'div_yield': 11.4, 'figi': 'BBG00475KX63'},
            'MAGN': {'name': 'ММК', 'sector': 'Металлы', 'div_yield': 5.2, 'figi': 'BBG00475J5C8'},
            'PLZL': {'name': 'Полюс', 'sector': 'Металлы', 'div_yield': 3.2, 'figi': 'BBG00475K3V3'},
            'ALRS': {'name': 'Алроса', 'sector': 'Металлы', 'div_yield': 5.8, 'figi': 'BBG004S68B21'},
            'RUAL': {'name': 'Русал', 'sector': 'Металлы', 'div_yield': 0.0, 'figi': 'BBG00B3T3HF3'},
            'MTLR': {'name': 'Мечел', 'sector': 'Металлы', 'div_yield': 0.0, 'figi': 'BBG00475J5C9'},
            
            # Технологии и телеком (4)
            'YDEX': {'name': 'Яндекс', 'sector': 'Технологии', 'div_yield': 0.0, 'figi': 'TCS00A107T19'},
            'MTSS': {'name': 'МТС', 'sector': 'Телеком', 'div_yield': 10.2, 'figi': 'BBG00475NY50'},
            'VKCO': {'name': 'VK', 'sector': 'Технологии', 'div_yield': 0.0, 'figi': 'BBG00Y24YJ84'},
            'ROST': {'name': 'Ростелеком', 'sector': 'Телеком', 'div_yield': 5.0, 'figi': 'BBG00475J5D0'},
            
            # Ритейл (4)
            'MGNT': {'name': 'Магнит', 'sector': 'Ритейл', 'div_yield': 8.7, 'figi': 'BBG004PYF2Y2'},
            'FIVE': {'name': 'X5 Group', 'sector': 'Ритейл', 'div_yield': 0.0, 'figi': 'BBG004PXMLJ7'},
            'LENT': {'name': 'Лента', 'sector': 'Ритейл', 'div_yield': 4.5, 'figi': 'BBG00B3T3HF4'},
            'FIXP': {'name': 'Fix Price', 'sector': 'Ритейл', 'div_yield': 3.2, 'figi': 'BBG00Z23B2X5'},
            
            # Энергетика (4)
            'IRAO': {'name': 'Интер РАО', 'sector': 'Энергетика', 'div_yield': 6.5, 'figi': 'BBG0047315D0'},
            'HYDR': {'name': 'РусГидро', 'sector': 'Энергетика', 'div_yield': 7.2, 'figi': 'BBG00475J816'},
            'OGKB': {'name': 'ОГК-2', 'sector': 'Энергетика', 'div_yield': 5.1, 'figi': 'BBG00475J5E0'},
            'MSNG': {'name': 'Мосэнерго', 'sector': 'Энергетика', 'div_yield': 4.8, 'figi': 'BBG00475J5F0'},
            
            # Химия и удобрения (3)
            'PHOR': {'name': 'Фосагро', 'sector': 'Химия', 'div_yield': 8.2, 'figi': 'BBG00B3T3HF5'},
            'AKRN': {'name': 'Акрон', 'sector': 'Химия', 'div_yield': 6.5, 'figi': 'BBG00475J5G0'},
            'KAZT': {'name': 'Казаньоргсинтез', 'sector': 'Химия', 'div_yield': 7.0, 'figi': 'BBG00475J5H0'},
            
            # Транспорт (2)
            'AFLT': {'name': 'Аэрофлот', 'sector': 'Транспорт', 'div_yield': 0.0, 'figi': 'BBG00475J5I0'},
            'GLTR': {'name': 'Globaltrans', 'sector': 'Транспорт', 'div_yield': 9.0, 'figi': 'BBG00B3T3HF6'},
        }

        logger.info(f"✅ AIAdvisor инициализирован с {len(self.company_info)} компаниями")
        
        self.advice_history: List[Dict[str, Any]] = []
        
        logger.info(f"✅ AIAdvisor с {self.llm_model} инициализирован")
    
    def _call_ollama_json(self, messages: List[Dict], options: Optional[Dict] = None) -> Optional[Dict]:
        """
        Отправляет запрос к Ollama и ожидает JSON-ответ.
        Возвращает распарсенный JSON или None при ошибке.
        """
        # if DISABLE_AI:
        #     logger.info("AI disabled, returning None")
        #     return None

        url = f"{OLLAMA_HOST}/api/chat"
        payload = {
            "model": self.llm_model,
            "messages": messages,
            "options": options or {},
            "stream": False
        }
        try:
            response = httpx.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                content = data['message']['content']
                return self._extract_json(content)
            else:
                logger.error(f"Ollama вернул {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка вызова Ollama: {e}")
        return None

    def analyze_with_image(self, image_path: str, text: str) -> Optional[str]:
        """Анализирует новость с картинкой"""
        try:
            with open(image_path, 'rb') as f:
                image_base64: str = base64.b64encode(f.read()).decode()
            
            prompt = f"""
            Ты финансовый аналитик. Проанализируй изображение и новость.

            НОВОСТЬ: {text}

            ИЗОБРАЖЕНИЕ приложено.

            Опиши кратко:
            1. Тип изображения (график, диаграмма, фото) и что на нём.
            2. Технические сигналы (тренд, уровни, объёмы).
            3. Связь с новостью.
            4. Рекомендация для инвестора.

            Ответь в формате JSON:
            {{
                "image_type": "candle/line/bar/photo/other",
                "technical_summary": "одно-два предложения",
                "trend": "up/down/sideways",
                "key_levels": ["support: X", "resistance: Y"],
                "relation": "как связано с новостью",
                "action": "buy/sell/hold",
                "confidence": 0.8,
                "detailed_analysis": "развёрнутое объяснение (2-3 предложения)"
            }}
            """
            url = f"{OLLAMA_HOST}/api/chat"
            payload = {
                "model": self.llm_model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64]
                }],
                "options": {"temperature": self.TEMPERATURE},
                "stream": False
            }
            try:
                response = httpx.post(url, json=payload, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    return data['message']['content']
                else:
                    logger.error(f"Ошибка при анализе картинки: {response.status_code}")
            except Exception as e:
                logger.error(f"Ошибка анализа картинки: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка анализа картинки: {e}")
            return None

    def _analyze_news_with_images(self, news_list: List[NewsItem]) -> List[Dict]:
        """Анализирует новости с изображениями, возвращает структурированный результат."""
        results = []
        for news in news_list[:3]:  # анализируем топ‑3 новости
            # Текстовый анализ
            text_analysis = self._analyze_text(news.title + " " + news.summary)
            
            # Анализ картинки, если есть
            image_analysis = None
            if news.image_path and os.path.exists(news.image_path):
                try:
                    image_analysis = self.analyze_image(news.image_path, news.title)
                except Exception as e:
                    logger.error(f"Ошибка при анализе картинки {news.image_path}: {e}")
            
            # Объединяем результаты
            combined = self._combine_analysis(text_analysis, image_analysis)
            
            results.append({
                'title': news.title,
                'source': news.source,
                'text_analysis': text_analysis,
                'image_analysis': image_analysis,
                'combined': combined,
                'has_image': image_analysis is not None
            })
        return results

    def _analyze_text(self, text: str) -> Dict[str, Any]:
        prompt = f"""
        Проанализируй этот текст и определи его влияние на рынок:
        
        {text[:500]}
        
        Ответь JSON:
        {{
            "sentiment": "positive/negative/neutral",
            "score": от -1 до 1,
            "key_points": ["пункт1", "пункт2"],
            "impact": "high/medium/low"
        }}
        """
        messages = [{'role': 'user', 'content': prompt}]
        options = {'temperature': self.TEMPERATURE}
        result = self._call_ollama_json(messages, options)
        if result:
            return result
        return {'sentiment': 'neutral', 'score': 0, 'key_points': [], 'impact': 'low'}

    def analyze_image(self, image_path: str, news_text: str) -> Optional[str]:
        """Анализирует изображение с использованием мультимодальной модели."""
        if not self.vision_enabled:
            return None

        try:
            with open(image_path, 'rb') as f:
                image_base64 = base64.b64encode(f.read()).decode()

            prompt = f"""
    Ты финансовый аналитик. Проанализируй это изображение в контексте поста:

    ЗАГОЛОВОК ПОСТА: {news_text.split(chr(10))[0] if chr(10) in news_text else news_text}
    ТЕКСТ ПОСТА: {news_text}

    Если изображение НЕ ОТНОСИТСЯ к теме поста или не несёт полезной информации для инвестора (например, это логотип, иконка, реклама или случайная картинка), просто напиши: "Изображение не связано с содержанием поста".

    Если изображение относится к посту, опиши кратко:
    1. Что изображено (график, диаграмма, фото) — какие детали важны для инвестора?
    2. Какой вывод для инвестора можно сделать на основе этого изображения?

    Ответь максимум 4 предложениями.
    """

            url = f"{OLLAMA_HOST}/api/chat"
            payload = {
                "model": self.vision_model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64]
                }],
                "options": {"temperature": self.TEMPERATURE},
                "stream": False
            }

            response = httpx.post(url, json=payload, timeout=60)  # Увеличим timeout для картинок
            if response.status_code == 200:
                data = response.json()
                content = data['message']['content']
                return content.strip()  # возвращаем текст
            else:
                logger.error(f"Ошибка при анализе картинки: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Ошибка анализа картинки: {e}")
            return None

    def _combine_analysis(self, text_analysis: Dict[str, Any], image_analysis: Optional[str]) -> Dict[str, Any]:
        """
        Объединяет анализ текста и изображения.
        Учитывает, является ли изображение графиком, и корректирует общий счёт.
        """
        result: Dict[str, Any] = {
            'text_sentiment': text_analysis.get('sentiment', 'neutral'),
            'text_score': text_analysis.get('score', 0),
            'key_points': text_analysis.get('key_points', []),
            'image_insight': image_analysis,
            'combined_score': text_analysis.get('score', 0)
        }

        if image_analysis:
            # Пытаемся определить, является ли изображение графиком
            if 'график' in image_analysis.lower():
                if any(word in image_analysis.lower() for word in ['рост', 'увелич']):
                    result['combined_score'] = min(1.0, result['combined_score'] + 0.2)
                    result['key_points'].append('📈 Технический сигнал: график показывает рост')
                elif any(word in image_analysis.lower() for word in ['падени', 'снижен']):
                    result['combined_score'] = max(-1.0, result['combined_score'] - 0.2)
                    result['key_points'].append('📉 Технический сигнал: график показывает падение')
                else:
                    # График есть, но направление не определено – небольшой бонус
                    result['combined_score'] = min(1.0, result['combined_score'] + 0.05)
                    result['key_points'].append('📊 Проанализирован график')
            else:
                # Изображение другого типа – тоже добавляем немного уверенности
                result['combined_score'] = min(1.0, result['combined_score'] + 0.05)
                result['key_points'].append('📷 Проанализировано изображение')

        return result

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Извлекает JSON из текста ответа"""
        try:
            start: int = text.find('{')
            end: int = text.rfind('}') + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except:
            pass
        return {}

    def analyze_all(self) -> Dict[str, Any]:
        start_time = time.time()
        logger.info(f"🔍 Запускаю анализ с {self.llm_model}...")

        # 1. Собираем новости и цены
        news = self.news_parser.fetch_all_news(limit_per_source=2, max_total=self.max_news)
        logger.info(f"📰 Собрано {len(news)} новостей за {time.time()-start_time:.1f} сек")

        prices = self._get_current_prices()
        logger.info(f"💰 Получены цены для {len(prices)} компаний")

        # 2. Проверяем свежий кэш
        if self.cache_enabled:
            cached = self._check_cache(news)
            if cached:
                logger.info(f"✅ Использован свежий кэш (время: {time.time()-start_time:.1f} сек)")
                return cached

        # 3. Пытаемся выполнить анализ через модель
        analysis = None
        try:
            analysis = self._quick_analysis(news, prices)
        except Exception as e:
            logger.error(f"❌ Ошибка при вызове модели: {e}")
            analysis = None

        # 4. Если анализ не удался, пробуем использовать последний сохранённый
        if analysis is None:
            if self.advice_history:
                last = self.advice_history[-1]
                logger.info("⚠️ Модель недоступна, использую последний успешный анализ из истории")
                last['analysis_time'] = time.time() - start_time
                return last
            else:
                logger.warning("⚠️ Нет истории, возвращаю fallback")
                return self._get_fallback_analysis(news, prices)

        # 5. Если анализ успешен, сохраняем в кэш и историю
        if self.cache_enabled:
            self._save_cache(news, analysis)

        total_time = time.time() - start_time
        logger.info(f"✅ Анализ завершён за {total_time:.1f} сек")
        analysis['analysis_time'] = total_time
        self.advice_history.append(analysis)
        return analysis

    def _quick_analysis(self, news: List[NewsItem], prices: Dict[str, float]) -> Dict[str, Any]:
        # Формируем сводку по новостям (как было, ограничиваем MAX_NEWS_QUICK)
        news_summary = "\n".join([f"- [{n.source}] {n.title[:100]}" for n in news[:self.MAX_NEWS_QUICK]])

        # --- ИЗМЕНЕНИЕ: теперь берем ВСЕ тикеры, для которых есть цена ---
        tickers_with_price = [ticker for ticker in self.company_info if ticker in prices]
        companies_summary = "\n".join([
            f"- {self.company_info[ticker]['name']} ({ticker}): {prices[ticker]:.0f}₽, див.{self.company_info[ticker]['div_yield']}%"
            for ticker in tickers_with_price
        ])

        # Получаем историю анализов для компаний (топ-5 по ценам, как было)
        history_context = ""
        tickers_list = list(prices.keys())[:5]
        for ticker in tickers_list:
            past = self.db.get_recent_analysis_by_ticker(ticker, days=7, limit=3)
            if past:
                history_context += f"\nПоследние события по {ticker}:\n"
                for p in past:
                    history_context += f"- {p.get('summary', '')} (сентимент {p.get('sentiment')})\n"

        prompt = f"""Ты агрессивный инвест-советник, склонный к покупкам при малейших позитивных сигналах. 
        Если новости нейтральные, но компания фундаментально сильна, рекомендуй BUY.

        НОВОСТИ:
        {news_summary}

        КОМПАНИИ (все доступные):
        {companies_summary}

        Ответь ТОЛЬКО JSON:
        {{
            "sentiment": "positive/neutral/negative",
            "top_pick": "SBER",
            "action": "BUY/HOLD/SELL",
            "reason": "кратко (10 слов)",
            "confidence": 0.8
        }}

        На основе истории новостей: 
        {history_context}
        """

        messages = [{'role': 'user', 'content': prompt}]
        options = {'temperature': self.TEMPERATURE, 'num_predict': 200}
        result = self._call_ollama_json(messages, options)

        if result is None:
            logger.warning("Не удалось получить ответ от Ollama, использую fallback")
            return self._get_fallback_analysis(news, prices)

        return {
            'timestamp': datetime.now(),
            'news_count': len(news),
            'companies_analyzed': len(prices),  # теперь это количество компаний с ценами
            'market_sentiment': result.get('sentiment', 'neutral'),
            'top_pick': result.get('top_pick', 'SBER'),
            'action': result.get('action', 'HOLD'),
            'reason': result.get('reason', 'Анализ завершён'),
            'confidence': result.get('confidence', 0.5),
            'prices': prices,
        }

    def _check_cache(self, news: List[NewsItem]) -> Optional[Dict[str, Any]]:
        """Проверяет кэш"""
        if not news:
            return None
        
        titles: str = "".join([n.title for n in news[:5]])
        cache_key: str = hashlib.md5(titles.encode()).hexdigest()
        cache_file: str = f"{self.cache_dir}/{cache_key}.json"
        
        if os.path.exists(cache_file):
            file_age: float = time.time() - os.path.getmtime(cache_file)
            if file_age < self.CACHE_TTL:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data: Dict[str, Any] = json.load(f)
                    data['from_cache'] = True
                    data['cache_age'] = f"{file_age/60:.0f} мин"
                    return data
        
        return None
    
    def _save_cache(self, news: List[NewsItem], analysis: Dict[str, Any]) -> None:
        """Сохраняет анализ в кэш"""
        try:
            titles: str = "".join([n.title for n in news[:5]])
            cache_key: str = hashlib.md5(titles.encode()).hexdigest()
            cache_file: str = f"{self.cache_dir}/{cache_key}.json"
            
            cache_data: Dict[str, Any] = {
                'timestamp': analysis['timestamp'].isoformat(),
                'news_count': analysis['news_count'],
                'companies_analyzed': analysis['companies_analyzed'],
                'market_sentiment': analysis['market_sentiment'],
                'top_pick': analysis['top_pick'],
                'action': analysis['action'],
                'reason': analysis['reason'],
                'confidence': analysis['confidence'],
                'prices': analysis['prices'],
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша: {e}")

    # def _get_current_prices(self) -> Dict[str, float]:
    #     """Получает текущие цены для всех тикеров из БД (или из company_info, если БД недоступна)."""
    #     prices = {}
    #     tickers = []

    #     # Пытаемся получить список из БД
    #     try:
    #         db = services.db()
    #         if db is not None:
    #             tickers = db.get_all_tickers()
    #             if tickers:
    #                 # ограничим, чтобы не зависнуть
    #                 tickers = tickers[:50]
    #     except Exception as e:
    #         logger.error(f"Не удалось получить список тикеров из БД: {e}")

    #     # Если не получилось, используем статический список
    #     if not tickers:
    #         tickers = list(self.company_info.keys())
    #         logger.info("Использую статический список company_info для получения цен")

    #     for ticker in tickers:
    #         try:
    #             price_info = self.stock_provider.get_price(ticker)
    #             if price_info and price_info.get('last_price'):
    #                 prices[ticker] = price_info['last_price']
    #         except Exception:
    #             continue
    #     return prices

    def _get_current_prices(self) -> Dict[str, float]:
        """Получает цены только для интересующих нас тикеров (из company_info)."""
        prices = {}
        for ticker in self.company_info.keys():
            try:
                price_info = self.stock_provider.get_price(ticker)
                if price_info and price_info.get('last_price'):
                    prices[ticker] = price_info['last_price']
            except Exception:
                continue
        return prices

    def _get_fallback_analysis(self, news: List[NewsItem], prices: Dict[str, float]) -> Dict[str, Any]:
        """Запасной вариант если ИИ не отвечает"""
        return {
            'timestamp': datetime.now(),
            'news_count': len(news),
            'companies_analyzed': len(prices),
            'market_sentiment': 'neutral',
            'top_pick': 'SBER',
            'action': 'HOLD',
            'reason': 'Анализ временно недоступен',
            'confidence': 0.5,
            'prices': prices,
        }
    
    def format_advice_message(self, analysis: Dict[str, Any]) -> str:
        lines: List[str] = []
        lines.append(f"🤖 *ИИ-АНАЛИЗ ({self.llm_model})*")
        lines.append("═" * 40)
        lines.append(f"📊 Компаний: {analysis.get('companies_analyzed', 0)}")
        lines.append(f"📰 Новостей: {analysis.get('news_count', 0)}")

        sentiment: str = analysis.get('market_sentiment', 'neutral')
        if sentiment == 'positive':
            lines.append("🌡 Рынок: 🟢 ПОЗИТИВНЫЙ")
        elif sentiment == 'negative':
            lines.append("🌡 Рынок: 🔴 НЕГАТИВНЫЙ")
        else:
            lines.append("🌡 Рынок: 🟡 НЕЙТРАЛЬНЫЙ")

        lines.append("")
        lines.append(f"🏆 *ТОП-ВЫБОР:* {analysis.get('top_pick', 'N/A')}")
        lines.append(f"🎯 *Действие:* {analysis.get('action', 'HOLD')}")
        lines.append(f"💡 *Причина:* {analysis.get('reason', 'N/A')}")
        lines.append(f"📊 *Уверенность:* {analysis.get('confidence', 0)*100:.0f}%")

        # 👇 НОВЫЙ БЛОК: детальный анализ новостей с изображениями
        if analysis.get('detailed_news'):
            lines.append("")
            lines.append("*📸 Детальный анализ новостей с изображениями:*")
            for item in analysis['detailed_news'][:2]:  # показываем первые две
                lines.append(f"  • {item['title'][:60]}...")
                if item.get('image_insight'):
                    # Обрезаем длинный ответ для компактности
                    # insight = item['image_insight'][:1000] + ('...' if len(item['image_insight']) > 100 else '')
                    # lines.append(f"    💡 {insight}")
                    # Без обрезки
                    if item.get('image_insight'):
                        lines.append(f"    💡 {item['image_insight']}")

        if analysis.get('from_cache'):
            lines.append(f"\n💾 *Из кэша:* {analysis.get('cache_age', 'N/A')}")

        if analysis.get('analysis_time'):
            lines.append(f"\n⏱ *Время:* {analysis['analysis_time']:.1f} сек")

        return "\n".join(lines)

    def generate_signals_ma(self, prices: List[Dict], short_window=5, long_window=20) -> List[int]:
        """
        Простая стратегия: когда короткая средняя пересекает длинную сверху — продаём,
        снизу — покупаем.
        """
        df = pd.DataFrame(prices)
        df['ma_short'] = df['close'].rolling(window=short_window).mean()
        df['ma_long'] = df['close'].rolling(window=long_window).mean()
        
        signals = [0] * len(df)
        for i in range(1, len(df)):
            if df['ma_short'].iloc[i] > df['ma_long'].iloc[i] and df['ma_short'].iloc[i-1] <= df['ma_long'].iloc[i-1]:
                signals[i] = 1  # buy
            elif df['ma_short'].iloc[i] < df['ma_long'].iloc[i] and df['ma_short'].iloc[i-1] >= df['ma_long'].iloc[i-1]:
                signals[i] = -1  # sell
        return signals

def test_ai_advisor() -> None:
    """Тестирование"""
    from config import TINKOFF_TOKEN
    
    advisor: AIAdvisor = AIAdvisor(TINKOFF_TOKEN)
    analysis: Dict[str, Any] = advisor.analyze_all()
    print(advisor.format_advice_message(analysis))


if __name__ == "__main__":
    test_ai_advisor()