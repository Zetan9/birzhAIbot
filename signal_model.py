import os
import pandas as pd
import numpy as np
import joblib
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
import logging

logger = logging.getLogger(__name__)

MODEL_PATH = 'models/moex_signal_model.pkl'
FEATURE_NAMES = ['price', 'delta_p', 'volume', 'buy_pct', 'sell_pct', 'hour', 'day_of_week']

def prepare_features(df):
    """
    Преобразует DataFrame с колонками из таблицы moex_signals
    в матрицу признаков для модели.
    """
    df = df.copy()
    df['signal_time'] = pd.to_datetime(df['signal_time'])
    df['hour'] = df['signal_time'].dt.hour
    df['day_of_week'] = df['signal_time'].dt.dayofweek

    ticker_dummies = pd.get_dummies(df['ticker'], prefix='ticker')

    numeric = df[FEATURE_NAMES].copy()
    numeric['volume'] = numeric['volume'].fillna(0)
    numeric['buy_pct'] = numeric['buy_pct'].fillna(50)
    numeric['sell_pct'] = numeric['sell_pct'].fillna(50)

    features = pd.concat([numeric, ticker_dummies], axis=1)
    return features

def train_model():
    from database import NewsDatabase
    db = NewsDatabase()
    df = db.get_labeled_signals()

    if df.empty or len(df) < 100:
        logger.warning("❌ Недостаточно данных для обучения (нужно минимум 100 размеченных сигналов)")
        return None

    features = prepare_features(df)
    target = df['outcome']

    X_train, X_test, y_train, y_test = train_test_split(features, target, test_size=0.2, random_state=42)

    scale_pos_weight = (len(y_train) - y_train.sum()) / y_train.sum() if y_train.sum() > 0 else 1

    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss'
    )
    model.fit(X_train, y_train)

    accuracy = model.score(X_test, y_test)
    logger.info(f"✅ Точность модели на тесте: {accuracy:.2f}")

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({
        'model': model,
        'feature_names': features.columns.tolist()
    }, MODEL_PATH)
    logger.info(f"💾 Модель сохранена в {MODEL_PATH}")

    return model

def load_model():
    if not os.path.exists(MODEL_PATH):
        logger.warning("⚠️ Модель не найдена. Сначала обучите её.")
        return None, None
    data = joblib.load(MODEL_PATH)
    return data['model'], data['feature_names']

def predict_signal(signal_dict: dict, model, feature_names):
    df = pd.DataFrame([{
        'ticker': signal_dict['ticker'],
        'signal_time': signal_dict['time'],
        'price': signal_dict.get('price', 0),
        'delta_p': signal_dict.get('delta_p', 0),
        'volume': signal_dict.get('volume', 0),
        'buy_pct': signal_dict.get('buy_pct', 50),
        'sell_pct': signal_dict.get('sell_pct', 50),
    }])
    features = prepare_features(df)
    # Убеждаемся, что все нужные колонки есть
    for col in feature_names:
        if col not in features.columns:
            features[col] = 0
    features = features[feature_names]
    proba = model.predict_proba(features)[0][1]
    return proba