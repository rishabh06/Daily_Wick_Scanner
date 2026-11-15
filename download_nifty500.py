"""
Downloads the NIFTY 500 constituent list from NSE Indices.
If the website blocks the request, download the NIFTY 500 constituents CSV
manually from https://www.niftyindices.com/ and save it as nifty500_source.csv
in this folder, then rerun this script.
"""
import csv
import io
import requests
from pathlib import Path

URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
OUT = Path("nifty500_symbols.txt")
SOURCE = Path("nifty500_source.csv")

def write_symbols(rows):
    symbols = set()
    for row in rows:
        # Official file commonly uses the column name "Symbol".
        symbol = (row.get("Symbol") or row.get("symbol") or "").strip().upper()
        if symbol:
            symbols.add(symbol)
    if not symbols:
        raise ValueError("Could not find a Symbol column in the constituent CSV.")
    OUT.write_text("\n".join(sorted(symbols)) + "\n", encoding="utf-8")
    print(f"Saved {len(symbols)} symbols to {OUT}")
    if len(symbols) != 500:
        print("WARNING: The file contains fewer/more than 500 symbols. Verify the source file.")

try:
    response = requests.get(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*",
            "Referer": "https://www.niftyindices.com/",
        },
        timeout=30,
    )
    response.raise_for_status()
    rows = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    write_symbols(rows)
except Exception as exc:
    print(f"Automatic download failed: {exc}")
    if SOURCE.exists():
        print("Using nifty500_source.csv already present in this folder.")
        with SOURCE.open("r", encoding="utf-8-sig", newline="") as f:
            write_symbols(csv.DictReader(f))
    else:
        print("\nManual fallback:")
        print("1. Visit https://www.niftyindices.com/ and find the NIFTY 500 constituent list.")
        print("2. Download its CSV and save it here as nifty500_source.csv.")
        print("3. Run: python download_nifty500.py")
        raise SystemExit(1)
