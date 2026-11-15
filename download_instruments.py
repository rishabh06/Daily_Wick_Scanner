import csv
from kiteconnect import KiteConnect
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv("API_KEY")
if not api_key:
    raise SystemExit("API_KEY is missing in .env.")

try:
    with open("access_token.txt", "r", encoding="utf-8") as f:
        access_token = f.read().strip()
except FileNotFoundError:
    raise SystemExit("Run login.py first.")

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("Downloading NSE instruments...")
instruments = kite.instruments("NSE")
if not instruments:
    raise SystemExit("No instruments returned.")

with open("nse_instruments.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=instruments[0].keys())
    writer.writeheader()
    writer.writerows(instruments)

print(f"Downloaded {len(instruments):,} NSE instruments to nse_instruments.csv")
