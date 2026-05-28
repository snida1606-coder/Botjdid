"""
TradoWix Live Candle Data — Flask API Server
=============================================
Uses SEPARATE WebSocket connection per pair for maximum reliability.

Usage:
    python tradowix_api.py

Endpoints:
    GET  /                       → Health check
    POST /set-pair               → Set active pair {"symbol": "EURUSD-OTC"}
    GET  /candles                → Get rolling 200 candles for active pair
    GET  /candles/<SYMBOL>       → Get rolling 200 candles for any pair
    GET  /pairs                  → List all available pairs
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
EMAIL = "snida1606@gmail.com"
PASSWORD = "Rohailcoolz@41"
DEFAULT_PAIR = "EURUSD-OTC"
# Pairs to monitor with dedicated connections
MONITORED_PAIRS = [
    "EURUSD-OTC",
    "USDEGP-OTC",
    "USDBRL-OTC",
]
PORT = int(os.environ.get("PORT", 5000))
MAX_CANDLES = 200

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("tradowix_api")

# ─── One client PER pair (dedicated connection) ───
pair_clients: dict = {}  # symbol -> TradoWixClient
candle_locks: dict = {}  # symbol -> threading.Lock
active_pair = DEFAULT_PAIR
master_client = None  # For getting instruments list

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


def get_client(symbol: str) -> TradoWixClient:
    """Get or create a dedicated client for a symbol."""
    symbol = symbol.upper()
    if symbol not in pair_clients:
        logger.info("Creating new dedicated client for %s", symbol)
        client = TradoWixClient()
        pair_clients[symbol] = client
        candle_locks[symbol] = threading.Lock()
        
        # Start client in background
        def start_client():
            try:
                client.login(EMAIL, PASSWORD)
                client.connect()
                client.subscribe(symbol, lookback_minutes=300, timeframe=60)
                logger.info("Dedicated client for %s started", symbol)
            except Exception as e:
                logger.error("Client %s error: %s", symbol, e)
        
        threading.Thread(target=start_client, daemon=True).start()
    
    return pair_clients[symbol]


def get_rolling_candles(symbol: str) -> list:
    """Get the latest MAX_CANDLES candles for a symbol."""
    symbol = symbol.upper()
    client = get_client(symbol)
    
    # Wait for data
    for _ in range(30):
        if client._candle_history.get(symbol):
            break
        time.sleep(1)
    
    candles_data = client._candle_history.get(symbol, [])
    
    # Fill gaps
    if len(candles_data) >= 2:
        filled = [candles_data[0]]
        for i in range(1, len(candles_data)):
            prev = filled[-1]
            curr = candles_data[i]
            expected = prev["time"] + 60000
            while expected < curr["time"]:
                filled.append({
                    "time": expected,
                    "open": prev["close"],
                    "high": prev["close"],
                    "low": prev["close"],
                    "close": prev["close"],
                    "volume": 0,
                })
                prev = filled[-1]
                expected += 60000
            filled.append(curr)
        candles_data = filled

    if len(candles_data) > MAX_CANDLES:
        candles_data = candles_data[-MAX_CANDLES:]
    
    return [format_candle(c) for c in candles_data]


def get_instruments():
    """Get instruments from any available client."""
    if master_client:
        return master_client.instruments
    for client in pair_clients.values():
        if client.instruments:
            return client.instruments
    return []


# ─── Flask App ───
app = Flask(__name__)


@app.route("/", methods=["GET"])
def health():
    connected = []
    for sym, client in pair_clients.items():
        if client.is_connected:
            connected.append(sym)
    return jsonify({
        "status": "running",
        "active_pair": active_pair,
        "connections": len(connected),
        "pairs": list(pair_clients.keys()),
        "connected_pairs": connected,
    })


@app.route("/set-pair", methods=["POST"])
def set_pair():
    """Set the active trading pair."""
    global active_pair
    data = request.get_json(force=True, silent=True) or {}
    symbol = data.get("symbol", "").strip().upper()

    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    # Verify instrument exists
    inst = None
    for i in get_instruments():
        if i.get("symbol", "").upper() == symbol:
            inst = i
            break
    
    if not inst:
        return jsonify({
            "error": f"Unknown symbol: {symbol}",
            "hint": "Use /pairs to see available symbols",
        }), 404

    active_pair = symbol
    # Ensure client exists
    get_client(symbol)
    
    # Wait for data
    time.sleep(5)

    return jsonify({
        "success": True,
        "symbol": symbol,
        "displayName": inst.get("displayName", symbol),
        "payout": f"{int(inst.get('effectiveTurboPayoutRate', 0) * 100)}%",
        "isOTC": inst.get("isOTC", False),
        "isOpen": inst.get("isOpen", False),
        "message": "Pair set with dedicated connection"
    })


@app.route("/candles", methods=["GET"])
def candles_active():
    """Get rolling 200 candles for the active pair."""
    candles = get_rolling_candles(active_pair)
    inst = None
    for i in get_instruments():
        if i.get("symbol", "").upper() == active_pair:
            inst = i
            break
    payout = f"{int(inst.get('effectiveTurboPayoutRate', 0) * 100)}%" if inst else "?"

    return jsonify({
        "symbol": active_pair,
        "payout": payout,
        "interval": "1m",
        "total_candles": len(candles),
        "candles": candles,
    })


@app.route("/candles/<symbol>", methods=["GET"])
def candles_by_symbol(symbol):
    """Get rolling 200 candles for any pair."""
    symbol = symbol.strip().upper()
    candles = get_rolling_candles(symbol)
    
    inst = None
    for i in get_instruments():
        if i.get("symbol", "").upper() == symbol:
            inst = i
            break
    payout = f"{int(inst.get('effectiveTurboPayoutRate', 0) * 100)}%" if inst else "?"

    return jsonify({
        "symbol": symbol,
        "payout": payout,
        "interval": "1m",
        "total_candles": len(candles),
        "candles": candles,
    })


@app.route("/pairs", methods=["GET"])
def list_pairs():
    """List all available trading pairs."""
    pairs = []
    for inst in get_instruments():
        pairs.append({
            "symbol": inst.get("symbol", ""),
            "displayName": inst.get("displayName", inst.get("symbol", "")),
            "isOTC": inst.get("isOTC", False),
            "isOpen": inst.get("isOpen", False),
            "payout": f"{int(inst.get('effectiveTurboPayoutRate', 0) * 100)}%",
        })
    return jsonify({"total": len(pairs), "pairs": pairs})


# ─── Startup ───
def start_master_client():
    """Start master client to get instruments list."""
    global master_client
    try:
        master_client = TradoWixClient()
        master_client.login(EMAIL, PASSWORD)
        master_client.connect()
        logger.info("Master client connected with %d instruments", len(master_client.instruments))
    except Exception as e:
        logger.error("Master client error: %s", e)


if __name__ == "__main__":
    # Start master client for instruments
    threading.Thread(target=start_master_client, daemon=True).start()
    time.sleep(3)

    # Pre-start monitored pairs
    logger.info("Pre-starting %d monitored pairs...", len(MONITORED_PAIRS))
    for pair in MONITORED_PAIRS:
        get_client(pair)
        time.sleep(1)
    
    # Give clients time to connect
    time.sleep(5)
    
    logger.info("Starting Flask server on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
