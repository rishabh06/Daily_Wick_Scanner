import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()
api_key = os.getenv("API_KEY")
api_secret = os.getenv("API_SECRET")

if not api_key or not api_secret:
    raise SystemExit("API_KEY or API_SECRET is missing in .env.")

kite = KiteConnect(api_key=api_key)
print("\n1. Open this URL in your browser and log in to Zerodha:\n")
print(kite.login_url())
print("\n2. After login, copy the request_token value from the redirected URL.")
request_token = input("\nPaste request_token here: ").strip()

if not request_token:
    raise SystemExit("No request token entered.")

data = kite.generate_session(request_token, api_secret=api_secret)
with open("access_token.txt", "w", encoding="utf-8") as f:
    f.write(data["access_token"])

print("\nLogin successful. access_token.txt has been created.")
print("Keep this file private. You normally need to repeat login each trading day.")
