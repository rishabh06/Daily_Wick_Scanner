DAILY WICK SCANNER — SETUP GUIDE
================================

This package recreates the project on this laptop. It does not contain your
Zerodha API key, API secret, access token, or account credentials.

PROJECT FILTERS
---------------
- NIFTY 500 constituents only
- Minimum LTP: Rs 50
- Current day's lower wick: at least 50% of candle range
- Lower-wick/body ratio: at least 2
- Current LTP in the top 30% of the day's range
- At least 4 consecutive red daily candles in the previous completed sessions

IMPORTANT
---------
The scanner reads the current live quote. Before 3:30 PM, today's candle is
still forming, so results can change. Recheck around 3:20-3:25 PM. This is a
screening tool, not a buy recommendation or an automated trading system.

RECOMMENDED PYTHON
------------------
Use Python 3.12 or 3.13 if possible. Very new Python releases may not yet have
compatible prebuilt packages. The scanner intentionally does not use pandas.

STEP 1 — EXTRACT
---------------
Extract the ZIP to:
Desktop\Daily_Wick_Scanner

STEP 2 — CREATE YOUR PRIVATE .env
--------------------------------
In the extracted folder, copy .env.example and rename the copy to .env.
Open .env and enter your own Kite Connect API key and API secret.
Do not share .env or access_token.txt.

STEP 3 — OPEN COMMAND PROMPT IN THE PROJECT FOLDER
--------------------------------------------------
Open the folder in File Explorer. Click the address bar, type cmd, and press
Enter.

STEP 4 — CREATE A VIRTUAL ENVIRONMENT
-------------------------------------
python -m venv venv
venv\Scripts\activate

STEP 5 — INSTALL PACKAGES
-------------------------
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

If your company security policy blocks a package/DLL, do not bypass the policy.
Use an IT-approved personal development environment or ask IT to approve the
required Python runtime/package.

STEP 6 — ZERODHA LOGIN
----------------------
python login.py

Open the displayed URL, log in, and paste the request_token from the redirected
URL into the terminal. This creates access_token.txt. The access token normally
expires daily; run login.py again on a new trading day.

STEP 7 — DOWNLOAD NSE INSTRUMENTS
---------------------------------
python download_instruments.py

This creates nse_instruments.csv.

STEP 8 — DOWNLOAD NIFTY 500 CONSTITUENTS
----------------------------------------
python download_nifty500.py

This creates nifty500_symbols.txt. The script attempts to download the list
from NSE Indices. If that download is blocked, follow the manual fallback
instructions printed by the script. Verify the constituent file is current.

STEP 9 — TEST THE CONNECTION
----------------------------
python test_market_data.py

STEP 10 — RUN THE SCANNER
-------------------------
python scanner.py

A timestamped scanner_output_YYYYMMDD_HHMMSS.csv file is created.

DAILY RUN ROUTINE
-----------------
1. Activate the environment:
   venv\Scripts\activate
2. Refresh login:
   python login.py
3. Run the scanner:
   python scanner.py

Refresh nse_instruments.csv periodically and refresh NIFTY 500 constituents
when the index changes.

TROUBLESHOOTING
---------------
- API_KEY missing: check that .env exists and is named exactly .env, not
  .env.txt. Windows may hide file extensions.
- access_token.txt missing/invalid: run login.py again.
- nse_instruments.csv missing: run download_instruments.py.
- nifty500_symbols.txt missing: run download_nifty500.py.
- Fewer than 450 matching stocks: refresh both instrument data and constituent
  symbols; check the NIFTY 500 source CSV.
- Historical data errors: confirm the Kite access token is valid and the
  account/API has the required market-data access. The scanner excludes a
  candidate if its history request fails.

FILES
-----
scanner.py                 Main NIFTY 500 wick scanner
login.py                   Generates the daily access token
test_kite.py               Checks Kite Connect setup and prints login URL
test_market_data.py        Tests live RELIANCE quote
download_instruments.py    Downloads NSE instruments from Kite
download_nifty500.py       Downloads NIFTY 500 constituent symbols
requirements.txt           Python dependencies
.env.example               Credentials template; copy to .env
.gitignore                 Helps prevent sharing credentials/output
