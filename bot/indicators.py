
import pandas as pd

def add_indicators(df):

    df["ema9"] = df["close"].ewm(span=9).mean()
    df["ema21"] = df["close"].ewm(span=21).mean()

    delta = df["close"].diff()

    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()

    rs = gain / loss

    df["rsi"] = 100 - (100/(1+rs))

    df["vol_avg"] = df["volume"].rolling(20).mean()

    return df

