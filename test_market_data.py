import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()
api_key = os.getenv("API_KEY")

try:
    with open("access_token.txt", "r", encoding="utf-8") as f:
        access_token = f.read().strip()
except FileNotFoundError:
    raise SystemExit("access_token.txt not found. Run login.py first.")

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

quote = kite.ltp("NSE:RELIANCE")["NSE:RELIANCE"]
print("Successfully connected to Zerodha!")
print("Stock: RELIANCE")
print("Last traded price:", quote["last_price"])
