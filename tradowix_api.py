"""
TradoWix Live Candle Data — Flask API Server
=============================================
Serves rolling 200 candles (1m) for any TradoWix pair.
Auto-updates every minute: new candle added, oldest removed.

Usage:
    python tradowix_api.py

Endpoints:
    GET  /                       → Health check
    POST /set-pair               → Set active pair  {"symbol": "EURUSD-OTC"}
    GET  /candles                → Get rolling 200 candles for active pair
    GET  /candles/<SYMBOL>       → Get rolling 200 candles for any pair
    GET  /pairs                  → List all available pairs

Environment Variables:
    TRADOWIX_EMAIL      → Login email
    TRADOWIX_PASSWORD   → Login password
    TRADOWIX_PAIR       → Default pair (default: EURUSD-OTC)
    TRADOWIX_OWNER      → Owner name (default: GHULAM MUJTABA)
    TRADOWIX_CONTACT    → Contact handle (default: @BINARYSUPPORT)
    PORT                → Server port (default: 5000)
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request

from tradowix_client import TradoWixClient

# ─── Config ───
EMAIL = os.environ.get("TRADOWIX_EMAIL", "")
PASSWORD = os.environ.get("TRADOWIX_PASSWORD", "")
DEFAULT_PAIR = os.environ.get("TRADOWIX_PAIR", "EURUSD-OTC")
OWNER = os.environ.get("TRADOWIX_OWNER", "GHULAM MUJTABA")
CONTACT = os.environ.get("TRADOWIX_CONTACT", "@BINARYSUPPORT")
PORT = int(os.environ.get("PORT", 5000))
MAX_CANDLES = 200

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("tradowix_api")

# ─── TradoWix Client ───
client = TradoWixClient()
active_pair = DEFAULT_PAIR
candle_lock = threading.Lock()

# UTC+5 timezone
UTC_PLUS_5 = timezone(timedelta(hours=5))


def format_candle(candle: dict) -> dict:
    """Convert internal candle dict to the user's required API format."""
    ts = candle["time"] // 1000 if candle["time"] > 1e12 else candle["time"]
    dt = datetime.fromtimestamp(ts, tz=UTC_PLUS_5)
    readable = dt.strftime("%d-%b-%Y, %H:%M:%S") + " UTC+5"

    o = candle["open"]
    c = candle["close"]
    color = "green" if c >= o else "red"
    direction = "up" if c >= o else "down"

    return {
        "time": ts,
        "readable_time": readable,
        "open": round(o, 6),
        "high": round(candle["high"], 6),
        "low": round(candle["low"], 6),
        "close": round(c, 6),
        "volume": candle.get("volume", 1),
        "color": color,
        "direction": direction,
    }


def get_payout_str(symbol: str) -> str:
    """Get payout percentage string for a symbol."""
    inst = client.find_instrument(symbol)
    if inst:
        rate = inst.get("effectiveTurboPayoutRate", inst.get("turboPayoutRate", 0))
        return f"{int(rate * 100)}%"
    return "!"


def get_rolling_candles(symbol: str) -> list:
    """Get the latest MAX_CANDLES candles for a symbol, formatted."""
    with candle_lock:
        raw = client._candle_history.get(symbol.upper(), [])
        if len(raw) > MAX_CANDLES:
            raw = raw[-MAX_CANDLES:]
        return [format_candle(c) for c in raw]


def ensure_subscribed(symbol: str):
    """Make sure we're subscribed to a symbol's tick feed."""
    symbol = symbol.upper()
    if symbol not in client._subscribed_symbols:
        client.subscribe(symbol, lookback_minutes=300, timeframe=60)
        # Wait for candle history to arrive
        event = client._candle_events.get(symbol)
        if event:
            event.wait(timeout=10)
        logger.info("Subscribed to %s", symbol)


# ─── Flask App ───
app = Flask(__name__)


@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "running",
        "connected": client.is_connected,
        "active_pair": active_pair,
        "instruments": len(client.instruments),
        "subscribed": list(client._subscribed_symbols),
    })


@app.route("/set-pair", methods=["POST"])
def set_pair():
    """Set the active trading pair."""
    global active_pair
    data = request.get_json(force=True, silent=True) or {}
    symbol = data.get("symbol", "").strip().upper()

    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    symbol = client._normalize_symbol(symbol)

    # Verify instrument exists
    inst = client.find_instrument(symbol)
    if not inst:
        return jsonify({
            "error": f"Unknown symbol: {symbol}",
            "hint": "Use /pairs to see available symbols",
        }), 404

    active_pair = symbol
    ensure_subscribed(symbol)

    return jsonify({
        "success": True,
        "symbol": symbol,
        "displayName": inst.get("displayName", symbol),
        "payout": get_payout_str(symbol),
        "isOTC": inst.get("isOTC", False),
        "isOpen": inst.get("isOpen", False),
    })


@app.route("/candles", methods=["GET"])
def candles_active():
    """Get rolling 200 candles for the active pair."""
    ensure_subscribed(active_pair)
    candles = get_rolling_candles(active_pair)
    payout = get_payout_str(active_pair)

    return jsonify({
        "symbol": active_pair,
        "OWNER": OWNER,
        "CONTACT": CONTACT,
        "payout": payout,
        "interval": "1m",
        "total_candles": len(candles),
        "candles": candles,
    })


@app.route("/candles/<symbol>", methods=["GET"])
def candles_by_symbol(symbol):
    """Get rolling 200 candles for any pair."""
    symbol = client._normalize_symbol(symbol.strip().upper())
    ensure_subscribed(symbol)

    # Wait briefly if candles not yet available
    for _ in range(20):
        if client._candle_history.get(symbol):
            break
        time.sleep(0.5)

    candles = get_rolling_candles(symbol)
    payout = get_payout_str(symbol)

    return jsonify({
        "symbol": symbol,
        "OWNER": OWNER,
        "CONTACT": CONTACT,
        "payout": payout,
        "interval": "1m",
        "total_candles": len(candles),
        "candles": candles,
    })


@app.route("/pairs", methods=["GET"])
def list_pairs():
    """List all available trading pairs."""
    category = request.args.get("category", "").lower()
    otc_only = request.args.get("otc", "").lower() in ("true", "1", "yes")

    pairs = []
    for inst in client.instruments:
        if category and inst.get("category", "").lower() != category:
            continue
        if otc_only and not inst.get("isOTC", False):
            continue
        pairs.append({
            "symbol": inst["symbol"],
            "displayName": inst.get("displayName", inst["symbol"]),
            "category": inst.get("category", ""),
            "isOTC": inst.get("isOTC", False),
            "isOpen": inst.get("isOpen", False),
            "payout": f"{int(inst.get('effectiveTurboPayoutRate', 0) * 100)}%",
        })

    return jsonify({"total": len(pairs), "pairs": pairs})


# ─── Startup ───
def start_client():
    """Initialize TradoWix client in background."""
    global client

    if not EMAIL or not PASSWORD:
        logger.error("Set TRADOWIX_EMAIL and TRADOWIX_PASSWORD environment variables!")
        logger.info("Example: TRADOWIX_EMAIL=you@email.com TRADOWIX_PASSWORD=pass python tradowix_api.py")
        return

    try:
        logger.info("Logging in as %s...", EMAIL)
        client.login(EMAIL, PASSWORD)
        logger.info("Logged in! Connecting WebSocket...")
        client.connect()
        logger.info("Connected! %d instruments available", len(client.instruments))

        # Subscribe to default pair
        ensure_subscribed(active_pair)
        logger.info("Ready! Serving candles for %s", active_pair)

    except Exception as e:
        logger.error("Startup error: %s", e)


if __name__ == "__main__":
    # Start client in background thread
    threading.Thread(target=start_client, daemon=True).start()

    # Give client a moment to connect
    time.sleep(3)

    logger.info("Starting Flask server on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
