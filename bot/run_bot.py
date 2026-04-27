import sys
import os

# project root path force add
ROOT_PATH = "/root/chanakya_v3"

if ROOT_PATH not in sys.path:
    sys.path.insert(0, ROOT_PATH)

from angel_login import angel_login
from angel_data import get_data

from bot.indicators import add_indicators
from bot.breakout_strategy import check_breakout
from bot.trade_manager import place_trade


SYMBOLTOKEN = "XXXXX"   # replace later

print("Starting Chanakya bot...")

api = angel_login()

if not api:
    print("Login failed")
    exit()

df = get_data()

df = add_indicators(df)

signal = check_breakout(df)

print("Signal:", signal)

place_trade(api, SYMBOLTOKEN, signal)

print("Bot execution completed")

