import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()
api_key = os.getenv("API_KEY")

if not api_key:
    raise SystemExit("API_KEY is missing. Create .env from .env.example first.")

kite = KiteConnect(api_key=api_key)
print("Kite Connect package is working.")
print("Login URL:")
print(kite.login_url())
