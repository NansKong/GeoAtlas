from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "ret_1",
    "ret_3",
    "ret_6",
    "ret_24",
    "vol_6",
    "vol_24",
    "range_pct",
    "body_pct",
    "volume_z24",
    "num_trades_log",
    "taker_buy_ratio",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
]


def engineer_features(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.sort_values("open_time").copy()
    for col in ["open", "high", "low", "close", "volume", "num_trades", "taker_buy_volume"]:
        if col not in df.columns:
            df[col] = np.nan

    df["ret_1"] = df["close"].pct_change(1)
    df["ret_3"] = df["close"].pct_change(3)
    df["ret_6"] = df["close"].pct_change(6)
    df["ret_24"] = df["close"].pct_change(24)
    df["vol_6"] = df["ret_1"].rolling(6, min_periods=6).std()
    df["vol_24"] = df["ret_1"].rolling(24, min_periods=24).std()
    df["range_pct"] = (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
    df["body_pct"] = (df["close"] - df["open"]) / df["open"].replace(0, np.nan)

    vol_mean_24 = df["volume"].rolling(24, min_periods=24).mean()
    vol_std_24 = df["volume"].rolling(24, min_periods=24).std()
    df["volume_z24"] = (df["volume"] - vol_mean_24) / vol_std_24.replace(0, np.nan)
    df["num_trades_log"] = np.log1p(df["num_trades"].clip(lower=0))
    df["taker_buy_ratio"] = (df["taker_buy_volume"] / df["volume"].replace(0, np.nan)).clip(lower=0, upper=1)

    ts = pd.to_datetime(df["open_time"], unit="ms", utc=True, errors="coerce")
    hours = ts.dt.hour.astype("float64")
    dows = ts.dt.dayofweek.astype("float64")
    df["hour_sin"] = np.sin((2 * np.pi * hours) / 24.0)
    df["hour_cos"] = np.cos((2 * np.pi * hours) / 24.0)
    df["dow_sin"] = np.sin((2 * np.pi * dows) / 7.0)
    df["dow_cos"] = np.cos((2 * np.pi * dows) / 7.0)
    return df


def build_training_frame(frame: pd.DataFrame, threshold: float = 0.0010) -> pd.DataFrame:
    df = engineer_features(frame)
    df["future_ret_1h"] = df["close"].shift(-1) / df["close"] - 1.0
    df["label"] = np.select(
        [df["future_ret_1h"] > threshold, df["future_ret_1h"] < -threshold],
        ["up", "down"],
        default="flat",
    )
    df = df.dropna(subset=FEATURE_COLUMNS + ["future_ret_1h"]).copy()
    return df


def build_latest_feature_row(frame: pd.DataFrame) -> pd.DataFrame:
    df = engineer_features(frame)
    df = df.dropna(subset=FEATURE_COLUMNS).copy()
    if df.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    return df.tail(1)[FEATURE_COLUMNS]
