
"""
DAILY WICK SCANNER
==================
1. Fetches 15-minute OHLCV data from Zerodha Kite.
2. Constructs higher timeframes locally.
3. Stage 1: Screens NIFTY 500 using recent candles.
4. Stage 2: Downloads longer history only for shortlisted stocks.
5. Calculates volume, RSI divergence, support and scoring.
6. Caches 15-minute data locally to reduce repeat downloads.

Required files in the same folder:
    .env
    access_token.txt
    nse_instruments.csv
    nifty500_symbols.txt

.env:
    KITE_API_KEY=your_api_key

Install:
    python -m pip install kiteconnect python-dotenv
"""

import csv
import os
import re
import time
from datetime import datetime, timedelta, date, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CACHE_DIR = BASE_DIR / "cache"
RESULTS_FILE_PREFIX = "wick_scanner_results"

INSTRUMENTS_FILE = BASE_DIR / "nse_instruments.csv"
SYMBOLS_FILE = BASE_DIR / "nifty500_symbols.txt"
TOKEN_FILE = BASE_DIR / "access_token.txt"
ENV_FILE = BASE_DIR / ".env"

IST = ZoneInfo("Asia/Kolkata")

# Mandatory candle filters
MIN_PRICE = 50.0
MIN_LOWER_WICK_PERCENT = 50.0
MIN_WICK_BODY_RATIO = 2.0
MIN_CLOSE_POSITION = 0.70
REQUIRED_PREVIOUS_RED_CANDLES = 2

# Stage 2 history
STAGE2_HISTORY_DAYS = 180

# Stage 1 recent history by selected timeframe
STAGE1_DAYS = {
    "15m": 3,
    "30m": 5,
    "45m": 7,
    "60m": 7,
    "75m": 9,
    "90m": 10,
    "2h": 12,
    "1D": 15,
    "1W": 65
}

REQUEST_DELAY_SECONDS = 1.00  # Conservative pacing for per-symbol live quote + history requests
CACHE_KEEP_DAYS = 200

TIMEFRAME_OPTIONS = {
    "1": ("15m", "15-minute"),
    "2": ("30m", "30-minute"),
    "3": ("45m", "45-minute"),
    "4": ("60m", "1-hour"),
    "5": ("75m", "75-minute"),
    "6": ("90m", "90-minute"),
    "7": ("2h", "2-hour"),
    "8": ("1D", "Daily"),
    "9": ("1W", "Weekly")
}

# Number of 15-minute candles per aggregated candle
INTRADAY_GROUP_SIZE = {
    "15m": 1,
    "30m": 2,
    "45m": 3,
    "60m": 4,
    "75m": 5,
    "90m": 6,
    "2h": 8
}


# ============================================================
# ENVIRONMENT AND CONNECTION
# ============================================================

def now_ist():
    return datetime.now(IST)


def to_naive_ist(value):
    if value.tzinfo is not None:
        value = value.astimezone(IST).replace(tzinfo=None)
    return value


def parse_datetime(value):
    if isinstance(value, datetime):
        return to_naive_ist(value)

    return to_naive_ist(datetime.fromisoformat(str(value)))


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_environment():

    if not ENV_FILE.exists():
        raise FileNotFoundError(
            f".env file not found:\n{ENV_FILE}"
        )

    if load_dotenv:
        load_dotenv(
            dotenv_path=ENV_FILE,
            override=True
        )
    else:
        with ENV_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = (
                        value.strip().strip('"').strip("'")
                    )

    api_key = (
        os.getenv("KITE_API_KEY")
        or os.getenv("API_KEY")
        or os.getenv("api_key")
    )

    if not api_key:
        raise ValueError(
            "KITE_API_KEY not found in .env file."
        )

    return api_key.strip()


def connect_kite():

    api_key = load_environment()

    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            "access_token.txt not found. "
            "Run login.py first."
        )

    access_token = TOKEN_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if not access_token:
        raise ValueError(
            "access_token.txt is empty. Run login.py again."
        )

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    profile = kite.profile()

    print(
        "Successfully connected to Zerodha:",
        profile.get("user_name", "Kite user")
    )

    return kite


# ============================================================
# LOAD NIFTY 500 INSTRUMENTS
# ============================================================

def load_nifty500_symbols():

    if not SYMBOLS_FILE.exists():
        raise FileNotFoundError(
            "nifty500_symbols.txt not found."
        )

    symbols = set()

    with SYMBOLS_FILE.open(
        "r",
        encoding="utf-8-sig"
    ) as f:

        for line in f:

            text = line.strip().upper()

            if not text or text.startswith("#"):
                continue

            first = re.split(r"[,;\t ]+", text)[0]
            first = first.strip().strip('"')

            if first in {
                "SYMBOL",
                "TRADINGSYMBOL",
                "COMPANY"
            }:
                continue

            if first:
                symbols.add(first)

    return symbols


def load_nse_instruments(target_symbols):

    if not INSTRUMENTS_FILE.exists():
        raise FileNotFoundError(
            "nse_instruments.csv not found. "
            "Run download_instruments.py first."
        )

    selected = {}

    with INSTRUMENTS_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        required = {
            "instrument_token",
            "tradingsymbol",
            "exchange",
            "segment",
            "instrument_type"
        }

        if not reader.fieldnames or not required.issubset(
            set(reader.fieldnames)
        ):
            raise ValueError(
                "Unexpected nse_instruments.csv format."
            )

        for row in reader:

            symbol = (
                row.get("tradingsymbol") or ""
            ).strip().upper()

            if (
                symbol in target_symbols
                and row.get("exchange", "").upper() == "NSE"
                and row.get("segment", "").upper() == "NSE"
                and row.get("instrument_type", "").upper() == "EQ"
            ):

                try:
                    selected[symbol] = int(
                        row["instrument_token"]
                    )
                except (TypeError, ValueError):
                    continue

    print(
        f"Loaded {len(selected)} NIFTY 500 NSE equity instruments."
    )

    if len(selected) < 450:
        print(
            "WARNING: Fewer than 450 instruments matched. "
            "Check your NIFTY 500 symbol list."
        )

    return selected


# ============================================================
# LOCAL 15-MINUTE DATA CACHE
# ============================================================

def cache_path_for(token):

    return CACHE_DIR / f"{token}_15minute.csv"


def load_cached_candles(token):

    path = cache_path_for(token)

    if not path.exists():
        return {}

    candles = {}

    try:

        with path.open(
            "r",
            newline="",
            encoding="utf-8"
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                try:

                    stamp = parse_datetime(row["date"])

                    candles[stamp] = {
                        "date": stamp,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"])
                    }

                except (KeyError, TypeError, ValueError):
                    continue

    except OSError:
        return {}

    return candles


def save_cached_candles(token, candles):

    CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    cutoff = datetime.now() - timedelta(
        days=CACHE_KEEP_DAYS
    )

    rows = [
        candle
        for stamp, candle in candles.items()
        if stamp >= cutoff
    ]

    rows.sort(key=lambda x: x["date"])

    with cache_path_for(token).open(
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume"
            ]
        )

        writer.writeheader()

        for candle in rows:

            writer.writerow({
                "date": candle["date"].isoformat(sep=" "),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"]
            })


def fetch_15m_history(
    kite,
    token,
    symbol,
    days
):

    """
    Fetches 15-minute data and merges it into the local cache.

    On subsequent runs, refreshes from one day before the
    latest cached candle to capture corrections/new candles.
    """

    current_time = now_ist().replace(tzinfo=None)

    desired_start = (
        current_time - timedelta(days=days)
    )

    cache = load_cached_candles(token)

    if not cache:

        fetch_start = desired_start

    else:

        oldest = min(cache)
        latest = max(cache)

        if oldest > desired_start + timedelta(days=1):
            fetch_start = desired_start
        else:
            fetch_start = max(
                desired_start,
                latest - timedelta(days=1)
            )

    try:

        data = kite.historical_data(
            instrument_token=token,
            from_date=fetch_start,
            to_date=current_time,
            interval="15minute",
            continuous=False,
            oi=False
        )

        for item in data:

            stamp = parse_datetime(item["date"])

            cache[stamp] = {
                "date": stamp,
                "open": safe_float(item.get("open")),
                "high": safe_float(item.get("high")),
                "low": safe_float(item.get("low")),
                "close": safe_float(item.get("close")),
                "volume": safe_float(item.get("volume"))
            }

        save_cached_candles(token, cache)

    except Exception as exc:

        if not cache:
            raise RuntimeError(
                f"{symbol}: Kite data error: {exc}"
            )

        print(
            f"  Warning: {symbol} refresh failed. "
            "Using cached data."
        )

    result = sorted(
        [
            candle.copy()
            for stamp, candle in cache.items()
            if stamp >= desired_start
        ],
        key=lambda x: x["date"]
    )

    # Add a snapshot of the currently forming 15-minute candle.
    # The live candle is kept in memory only and is not written
    # into the historical cache.
    return apply_live_15m_candle(
        kite, token, symbol, result, current_time
    )


def apply_live_15m_candle(
    kite,
    token,
    symbol,
    candles,
    current_time=None
):
    """Overlay the current live 15-minute candle using Kite quote + 1m data."""

    current_time = current_time or now_ist().replace(tzinfo=None)
    current_time = to_naive_ist(current_time)

    session_start = datetime.combine(
        current_time.date(), dt_time(9, 15)
    )
    session_end = datetime.combine(
        current_time.date(), dt_time(15, 30)
    )

    # Do not manufacture live candles outside regular NSE sessions.
    if (
        current_time.weekday() >= 5
        or current_time < session_start
        or current_time >= session_end
    ):
        return candles

    minutes_from_open = int(
        (current_time - session_start).total_seconds() // 60
    )
    bucket_start = session_start + timedelta(
        minutes=(minutes_from_open // 15) * 15
    )

    try:
        quote_key = f"NSE:{symbol}"
        quote_result = kite.quote([quote_key])
        quote = quote_result.get(quote_key, {})
        last_price = safe_float(quote.get("last_price"))

        if last_price <= 0:
            print("  Warning: Live quote unavailable; using latest historical candle.")
            return candles

        # Fetch today's one-minute candles to obtain the current
        # 15-minute interval's true open/high/low.
        minute_data = kite.historical_data(
            instrument_token=token,
            from_date=session_start,
            to_date=current_time,
            interval="minute",
            continuous=False,
            oi=False
        )

        interval_minutes = [
            item for item in minute_data
            if bucket_start <= parse_datetime(item["date"]) < bucket_start + timedelta(minutes=15)
        ]

        interval_minutes.sort(
            key=lambda item: parse_datetime(item["date"])
        )

        if interval_minutes:
            live_open = safe_float(interval_minutes[0].get("open"), last_price)
            live_high = max(
                safe_float(item.get("high"), last_price)
                for item in interval_minutes
            )
            live_low = min(
                safe_float(item.get("low"), last_price)
                for item in interval_minutes
            )
            interval_volume = sum(
                safe_float(item.get("volume"))
                for item in interval_minutes
            )
        else:
            # At the very beginning of a new interval, a completed
            # one-minute candle may not exist yet.
            live_open = last_price
            live_high = last_price
            live_low = last_price
            interval_volume = 0.0

        live_high = max(live_high, last_price)
        live_low = min(live_low, last_price)

        # Prefer cumulative day volume from the live quote, less
        # completed one-minute volume before this 15-minute bucket.
        day_volume = safe_float(quote.get("volume"))
        if day_volume > 0:
            earlier_volume = sum(
                safe_float(item.get("volume"))
                for item in minute_data
                if parse_datetime(item["date"]) < bucket_start
            )
            live_volume = max(0.0, day_volume - earlier_volume)
        else:
            live_volume = interval_volume

        live_candle = {
            "date": bucket_start,
            "open": live_open,
            "high": live_high,
            "low": live_low,
            "close": last_price,
            "volume": live_volume,
            "is_live": True
        }

        # Replace any historical/cached candle with the same start time.
        candles = [
            candle for candle in candles
            if candle["date"] != bucket_start
        ]
        candles.append(live_candle)
        candles.sort(key=lambda candle: candle["date"])

        return candles

    except Exception as exc:
        print(
            f"  Warning: Could not build live candle for {symbol}: {exc}. "
            "Using latest historical data."
        )
        return candles


# ============================================================
# TIMEFRAME CONSTRUCTION
# ============================================================

def aggregate_group(candles, label):

    ordered = sorted(
        candles,
        key=lambda x: x["date"]
    )

    return {
        "date": ordered[0]["date"],
        "label": label,
        "open": ordered[0]["open"],
        "high": max(c["high"] for c in ordered),
        "low": min(c["low"] for c in ordered),
        "close": ordered[-1]["close"],
        "volume": sum(c["volume"] for c in ordered),
        "source_count": len(ordered),
        "is_live": any(c.get("is_live", False) for c in ordered)
    }


def completed_15m_candles(
    candles,
    current_time=None
):

    current_time = (
        current_time
        or now_ist().replace(tzinfo=None)
    )

    # Keep the current 15-minute candle as well as completed candles.
    # apply_live_15m_candle() refreshes this bar from the live quote.
    return [
        candle for candle in candles
        if candle["date"] <= current_time
    ]


def build_intraday_timeframe(
    candles,
    timeframe,
    current_time=None
):

    current_time = (
        current_time
        or now_ist().replace(tzinfo=None)
    )

    group_size = INTRADAY_GROUP_SIZE[timeframe]

    base = completed_15m_candles(
        candles,
        current_time
    )

    buckets = {}

    for candle in base:

        stamp = candle["date"]
        session_start = datetime.combine(
            stamp.date(), dt_time(9, 15)
        )
        minutes_from_open = int(
            (stamp - session_start).total_seconds() // 60
        )

        if minutes_from_open < 0 or stamp.time() >= dt_time(15, 30):
            continue

        bucket_number = minutes_from_open // (15 * group_size)
        key = (stamp.date(), bucket_number)
        buckets.setdefault(key, []).append(candle)

    result = []

    for (session_date, bucket_number), group in sorted(buckets.items()):

        group = sorted(group, key=lambda x: x["date"])
        expected_start = (
            datetime.combine(session_date, dt_time(9, 15))
            + timedelta(minutes=bucket_number * 15 * group_size)
        )

        # A normal bucket has group_size 15-minute bars. The final
        # bucket of a trading session may be shorter, and today's
        # currently forming bucket is intentionally partial.
        expected_times = [
            expected_start + timedelta(minutes=15 * i)
            for i in range(group_size)
            if (expected_start + timedelta(minutes=15 * i)).time() < dt_time(15, 30)
        ]

        if not expected_times:
            continue

        if session_date == current_time.date() and current_time.time() < dt_time(15, 30):
            expected_times = [stamp for stamp in expected_times if stamp <= current_time]

        actual_times = [c["date"] for c in group]

        # Require every 15-minute slot that should have started by now.
        if actual_times != expected_times:
            continue

        result.append(aggregate_group(group, timeframe))

    return result


def build_daily_timeframe(
    candles,
    current_time=None
):

    current_time = (
        current_time
        or now_ist().replace(tzinfo=None)
    )

    groups = {}

    for candle in completed_15m_candles(
        candles,
        current_time
    ):

        groups.setdefault(
            candle["date"].date(),
            []
        ).append(candle)

    result = []

    for session_date, group in sorted(groups.items()):

        # Include today's developing daily candle during market hours.
        if group:
            result.append(
                aggregate_group(group, "1D")
            )

    return result


def build_weekly_timeframe(
    candles,
    current_time=None
):

    current_time = (
        current_time
        or now_ist().replace(tzinfo=None)
    )

    groups = {}

    for candle in completed_15m_candles(
        candles,
        current_time
    ):

        iso = candle["date"].date().isocalendar()

        key = (iso.year, iso.week)

        groups.setdefault(key, []).append(candle)

    result = []

    for (year, week), group in sorted(groups.items()):

        # Include the current week's developing candle.
        if group:
            result.append(
                aggregate_group(group, "1W")
            )

    return result


def build_timeframe(
    candles,
    timeframe,
    current_time=None
):

    if timeframe in INTRADAY_GROUP_SIZE:

        return build_intraday_timeframe(
            candles,
            timeframe,
            current_time
        )

    if timeframe == "1D":

        return build_daily_timeframe(
            candles,
            current_time
        )

    if timeframe == "1W":

        return build_weekly_timeframe(
            candles,
            current_time
        )

    raise ValueError(
        f"Unsupported timeframe: {timeframe}"
    )


# ============================================================
# CANDLE ANALYSIS
# ============================================================

def candle_metrics(candle):

    open_price = candle["open"]
    high = candle["high"]
    low = candle["low"]
    close = candle["close"]

    full_range = max(high - low, 0.0)

    body = abs(close - open_price)

    lower_wick = min(
        open_price,
        close
    ) - low

    upper_wick = high - max(
        open_price,
        close
    )

    wick_percent = (
        lower_wick / full_range * 100
        if full_range > 0
        else 0
    )

    wick_body_ratio = (
        lower_wick / body
        if body > 0
        else (999.0 if lower_wick > 0 else 0.0)
    )

    close_position = (
        (close - low) / full_range
        if full_range > 0
        else 0
    )

    return {
        "range": full_range,
        "body": body,
        "lower_wick": lower_wick,
        "upper_wick": upper_wick,
        "wick_percent": wick_percent,
        "wick_body_ratio": wick_body_ratio,
        "close_position": close_position
    }


def count_previous_red_candles(
    candles,
    candidate_index
):

    count = 0

    index = candidate_index - 1

    while index >= 0:

        candle = candles[index]

        if candle["close"] < candle["open"]:
            count += 1
            index -= 1
        else:
            break

    return count


# ============================================================
# RSI AND EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    current = sum(values[:period]) / period

    for value in values[period:]:

        current = (
            (value - current) * multiplier
            + current
        )

    return current


def rsi_wilder(values, period=14):

    if len(values) <= period:
        return [None] * len(values)

    result = [None] * len(values)

    gains = []
    losses = []

    for i in range(1, period + 1):

        change = values[i] - values[i - 1]

        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def calculate_rsi(gain, loss):

        if loss == 0:
            return 100.0

        rs = gain / loss

        return 100 - (100 / (1 + rs))

    result[period] = calculate_rsi(
        avg_gain,
        avg_loss
    )

    for i in range(period + 1, len(values)):

        change = values[i] - values[i - 1]

        gain = max(change, 0)
        loss = max(-change, 0)

        avg_gain = (
            (avg_gain * (period - 1)) + gain
        ) / period

        avg_loss = (
            (avg_loss * (period - 1)) + loss
        ) / period

        result[i] = calculate_rsi(
            avg_gain,
            avg_loss
        )

    return result


# ============================================================
# STAGE 1: QUICK LONG-WICK SCREENING
# ============================================================

def stage1_candidate(candles):

    if len(candles) < REQUIRED_PREVIOUS_RED_CANDLES + 1:
        return None

    index = len(candles) - 1

    candidate = candles[index]

    metrics = candle_metrics(candidate)

    red_count = count_previous_red_candles(
        candles,
        index
    )

    if candidate["close"] < MIN_PRICE:
        return None

    if red_count < REQUIRED_PREVIOUS_RED_CANDLES:
        return None

    if metrics["wick_percent"] < MIN_LOWER_WICK_PERCENT:
        return None

    if metrics["wick_body_ratio"] < MIN_WICK_BODY_RATIO:
        return None

    if metrics["close_position"] < MIN_CLOSE_POSITION:
        return None

    return {
        "candidate": candidate,
        "metrics": metrics,
        "red_count": red_count
    }


# ============================================================
# STAGE 2: DETAILED ANALYSIS
# ============================================================

def stage2_analysis(
    candles,
    candidate_date
):

    if len(candles) < 30:
        return None

    matching = [
        i
        for i, candle in enumerate(candles)
        if candle["date"] == candidate_date
    ]

    if not matching:
        return None

    candidate_index = matching[-1]

    candidate = candles[candidate_index]

    metrics = candle_metrics(candidate)

    red_count = count_previous_red_candles(
        candles,
        candidate_index
    )

    if red_count < REQUIRED_PREVIOUS_RED_CANDLES:
        return None

    closes = [
        c["close"]
        for c in candles[:candidate_index + 1]
    ]

    volumes = [
        c["volume"]
        for c in candles[:candidate_index + 1]
    ]

    lows = [
        c["low"]
        for c in candles[:candidate_index + 1]
    ]

    # RSI
    rsi_series = rsi_wilder(
        closes,
        14
    )

    current_rsi = rsi_series[-1]

    # EMA 20
    current_ema20 = ema(
        closes,
        20
    )

    # Average volume over previous 20 candles
    previous_volumes = volumes[
        max(0, candidate_index - 20):candidate_index
    ]

    average_volume = (
        sum(previous_volumes) / len(previous_volumes)
        if previous_volumes
        else 0
    )

    volume_ratio = (
        candidate["volume"] / average_volume
        if average_volume > 0
        else 0
    )

    # Previous 20-candle support
    previous_lows = lows[
        max(0, candidate_index - 20):candidate_index
    ]

    support = (
        min(previous_lows)
        if previous_lows
        else None
    )

    support_distance = None

    if support and support > 0:

        support_distance = (
            abs(candidate["low"] - support)
            / support * 100
        )

    near_support = (
        support_distance is not None
        and support_distance <= 1.0
    )

    # Bullish RSI divergence heuristic
    bullish_divergence = False

    if candidate_index >= 20 and current_rsi is not None:

        start = candidate_index - 20

        prior_low_index = min(
            range(start, candidate_index),
            key=lambda i: candles[i]["low"]
        )

        prior_low = candles[prior_low_index]["low"]

        prior_low_rsi = rsi_series[prior_low_index]

        if (
            prior_low_rsi is not None
            and candidate["low"] < prior_low
            and current_rsi >= prior_low_rsi + 3
        ):

            bullish_divergence = True

    above_ema20 = (
        current_ema20 is not None
        and candidate["close"] > current_ema20
    )

    # SCORING
    score = 0
    reasons = []

    # Previous red candles
    if red_count >= 6:

        score += 20
        reasons.append(
            f"{red_count} previous red candles (+20)"
        )

    elif red_count >= 4:

        score += 15
        reasons.append(
            f"{red_count} previous red candles (+15)"
        )

    else:

        score += 10
        reasons.append(
            f"{red_count} previous red candles (+10)"
        )

    # Lower wick percentage
    if metrics["wick_percent"] > 60:

        score += 20
        reasons.append(
            "Lower wick above 60% (+20)"
        )

    else:

        score += 10
        reasons.append(
            "Lower wick 50-60% (+10)"
        )

    # Volume
    if volume_ratio >= 1.5:

        score += 20
        reasons.append(
            "Volume >= 1.5x average (+20)"
        )

    # RSI divergence
    if bullish_divergence:

        score += 20
        reasons.append(
            "Bullish RSI divergence (+20)"
        )

    # Support
    if near_support:

        score += 20
        reasons.append(
            "Near 20-candle support (+20)"
        )

    # EMA confirmation
    if above_ema20:

        score += 10
        reasons.append(
            "Close above EMA20 (+10)"
        )

    return {
        "date": candidate["date"],
        "candle_status": "LIVE / FORMING" if candidate.get("is_live") else "LATEST AVAILABLE",
        "close": candidate["close"],
        "low": candidate["low"],
        "red_candles": red_count,
        "wick_percent": metrics["wick_percent"],
        "wick_body_ratio": metrics["wick_body_ratio"],
        "close_position": metrics["close_position"],
        "volume": candidate["volume"],
        "average_volume": average_volume,
        "volume_ratio": volume_ratio,
        "rsi": current_rsi,
        "ema20": current_ema20,
        "above_ema20": above_ema20,
        "support": support,
        "support_distance_percent": support_distance,
        "bullish_rsi_divergence": bullish_divergence,
        "score": score,
        "reasons": "; ".join(reasons)
    }


# ============================================================
# USER TIMEFRAME SELECTION
# ============================================================

def choose_timeframe():

    print("\nSELECT SCANNER TIMEFRAME")
    print("-" * 40)

    for key, (timeframe, label) in TIMEFRAME_OPTIONS.items():

        print(
            f"{key}. {label} ({timeframe})"
        )

    while True:

        choice = input(
            "\nEnter option (1-9): "
        ).strip()

        if choice in TIMEFRAME_OPTIONS:

            return TIMEFRAME_OPTIONS[choice][0]

        print("Invalid selection. Enter 1-9.")


# ============================================================
# SAVE RESULTS
# ============================================================

def write_results(rows, timeframe):

    # Generate filename using timeframe and timestamp
    timestamp = now_ist().strftime("%Y%m%d_%H%M%S")

    filename = (
        f"{RESULTS_FILE_PREFIX}_{timeframe}_{timestamp}.csv"
    )

    results_file = BASE_DIR / filename

    fieldnames = [
        "symbol",
        "timeframe",
        "date",
        "candle_status",
        "close",
        "low",
        "red_candles",
        "wick_percent",
        "wick_body_ratio",
        "close_position",
        "volume",
        "average_volume",
        "volume_ratio",
        "rsi",
        "ema20",
        "above_ema20",
        "support",
        "support_distance_percent",
        "bullish_rsi_divergence",
        "score",
        "reasons"
    ]

    with results_file.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for row in rows:

            output = dict(row)

            output["timeframe"] = timeframe

            if isinstance(output.get("date"), datetime):

                output["date"] = output["date"].strftime(
                    "%Y-%m-%d %H:%M"
                )

            writer.writerow({
                key: output.get(key, "")
                for key in fieldnames
            })

    return results_file

# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():

    timeframe = choose_timeframe()

    kite = connect_kite()

    target_symbols = load_nifty500_symbols()

    instruments = load_nse_instruments(
        target_symbols
    )

    if not instruments:
        raise RuntimeError(
            "No matching NIFTY 500 instruments found."
        )

    symbols = sorted(
        instruments.items()
    )

    # --------------------------------------------------------
    # STAGE 1
    # --------------------------------------------------------

    stage1_matches = []

    stage1_days = STAGE1_DAYS[timeframe]

    print("\n" + "=" * 65)
    print(f"STAGE 1: QUICK SCREENING — {timeframe}")
    print("Mode: LIVE / FORMING CANDLE (where live quote is available)")
    print(f"Stocks to scan: {len(symbols)}")
    print("=" * 65)

    for count, (symbol, token) in enumerate(
        symbols,
        start=1
    ):

        print(
            f"[Stage 1: {count}/{len(symbols)}] {symbol}",
            end=""
        )

        try:

            raw = fetch_15m_history(
                kite,
                token,
                symbol,
                stage1_days
            )

            candles = build_timeframe(
                raw,
                timeframe
            )

            match = stage1_candidate(candles)

            if match:

                item = {
                    "symbol": symbol,
                    "token": token,
                    "candidate_date": match["candidate"]["date"],
                    "candle_status": "LIVE / FORMING" if match["candidate"].get("is_live") else "LATEST AVAILABLE",
                    "candidate_close": match["candidate"]["close"],
                    "candidate_low": match["candidate"]["low"],
                    "red_count": match["red_count"],
                    "wick_percent": match["metrics"]["wick_percent"]
                }

                stage1_matches.append(item)

                print(
                    f"  MATCH | {item['candle_status']}"
                    f" | Wick: {item['wick_percent']:.1f}%"
                    f" | Red candles: {item['red_count']}"
                )

            else:

                print("  - No match")

        except Exception as exc:

            print(f"  - ERROR: {exc}")

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print("\n" + "-" * 65)

    print(
        f"STAGE 1 COMPLETE: "
        f"{len(stage1_matches)} stocks shortlisted "
        f"out of {len(symbols)}"
    )

    print("-" * 65)

    if not stage1_matches:

        results_file = write_results(
            [],
            timeframe
        )

        print(
            f"No stocks matched. Results saved to {results_file}"
        )

        return

    # --------------------------------------------------------
    # STAGE 2
    # --------------------------------------------------------

    final_results = []

    print("\n" + "=" * 65)
    print("STAGE 2: DETAILED ANALYSIS")
    print(
        f"Shortlisted stocks: {len(stage1_matches)}"
    )
    print("=" * 65)

    for count, item in enumerate(
        stage1_matches,
        start=1
    ):

        symbol = item["symbol"]
        token = item["token"]

        print(
            f"[Stage 2: {count}/{len(stage1_matches)}] {symbol}",
            end=""
        )

        try:

            raw = fetch_15m_history(
                kite,
                token,
                symbol,
                STAGE2_HISTORY_DAYS
            )

            candles = build_timeframe(
                raw,
                timeframe
            )

            analysis = stage2_analysis(
                candles,
                item["candidate_date"]
            )

            if analysis is None:

                print(
                    "  - Insufficient history or candidate unavailable"
                )

            else:

                result = {
                    "symbol": symbol,
                    **analysis
                }

                final_results.append(result)

                print(
                    f"  SCORE: {analysis['score']}/100"
                    f" | {analysis.get('candle_status', 'LATEST AVAILABLE')}"
                )

        except Exception as exc:

            print(f"  - ERROR: {exc}")

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    # --------------------------------------------------------
    # SORT AND SAVE
    # --------------------------------------------------------

    final_results.sort(
        key=lambda row: (
            row.get("score", 0),
            row.get("wick_percent", 0),
            row.get("red_candles", 0)
        ),
        reverse=True
    )

    results_file = write_results(
        final_results,
        timeframe
    )

    print("\n" + "=" * 65)
    print("SCAN COMPLETE")
    print("=" * 65)

    print(f"Timeframe: {timeframe}")
    print("Candle mode: LIVE / FORMING for all timeframes")

    print(
        f"Stage 1 matches: {len(stage1_matches)}"
    )

    print(
        f"Stage 2 analysed: {len(final_results)}"
    )

    print(
        f"Results file: {results_file}"
    )

    print(
        f"Cache folder: {CACHE_DIR}"
    )

    if final_results:

        print("\nTOP RESULTS")
        print("-" * 65)

        for row in final_results[:20]:

            rsi_value = (
                f"{row['rsi']:.1f}"
                if row["rsi"] is not None
                else "N/A"
            )

            print(
                f"{row['symbol']:15s}"
                f" Score: {row['score']:3d}/100"
                f" | Wick: {row['wick_percent']:5.1f}%"
                f" | RSI: {rsi_value}"
                f" | Volume x: {row['volume_ratio']:.2f}"
            )

    else:

        print(
            "No shortlisted stocks passed detailed analysis."
        )


# ============================================================
# ENTRY POINT
# ============================================================

def main():

    try:

        run_scanner()

    except KeyboardInterrupt:

        print("\nScanner stopped by user.")

    except Exception as exc:

        print(f"\nSCANNER ERROR: {exc}")

    finally:

        input("\nPress Enter to exit...")


if __name__ == "__main__":

    main()
