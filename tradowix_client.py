"""
TradoWix Unofficial Python Client Library
==========================================
Auto-trade bot integration for TradoWix binary options broker.
Supports email/password login (no manual session token needed),
real-time OHLC candle data, tick streaming, and trade execution.

Usage:
    from tradowix_client import TradoWixClient

    client = TradoWixClient()
    client.login("email@example.com", "password")
    client.connect()

    # Get OHLC candles (gap-filled)
    candles = client.get_candles("EURUSD-OTC", timeframe=60, count=200)

    # Place a trade
    trade_id = client.place_trade(
        symbol="EURUSD-OTC",
        direction="higher",
        amount=10,
        duration_minutes=1,
        is_demo=True
    )

    # Stream live ticks
    client.on_tick("EURUSD-OTC", callback=my_handler)

    client.disconnect()
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

try:
    import websockets
    import websockets.sync.client as ws_sync
except ImportError:
    websockets = None

logger = logging.getLogger("tradowix")

API_BASE = "https://api.tradowix.com"
WS_URL = "wss://api.tradowix.com/ws"
FRONTEND_BASE = "https://tradowix.com"
ORIGIN = "https://tradowix.com"


class TradoWixError(Exception):
    pass


class AuthenticationError(TradoWixError):
    pass


class TradeError(TradoWixError):
    pass


class TradoWixClient:
    """
    TradoWix trading client.

    Students only need to provide email + password.
    Session token is obtained automatically via login.
    """

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None):
        self.email = email
        self.password = password
        self.session_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.trader_id: Optional[int] = None
        self.user_info: Optional[Dict] = None

        # WebSocket state
        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        self._authenticated = False
        self._stop_event = threading.Event()

        # Data storage
        self.instruments: List[Dict] = []
        self.balance: Dict = {}
        self._candle_history: Dict[str, List] = {}
        self._tick_buffers: Dict[str, List] = {}
        self._subscribed_symbols: set = set()

        # Callbacks
        self._tick_callbacks: Dict[str, List[Callable]] = {}
        self._trade_opened_callbacks: List[Callable] = []
        self._trade_result_callbacks: List[Callable] = []
        self._balance_callbacks: List[Callable] = []
        self._candle_callbacks: Dict[str, List[Callable]] = {}

        # Pending RPC/trade responses
        self._pending_responses: Dict[str, asyncio.Future] = {}
        self._candle_events: Dict[str, threading.Event] = {}

        # HTTP session
        self._http = requests.Session()
        self._http.headers.update({
            "Content-Type": "application/json",
            "Origin": ORIGIN,
            "Referer": f"{FRONTEND_BASE}/trading",
        })

    # ─────────────────────────────────────────────
    #  1. AUTHENTICATION (email/password → token)
    # ─────────────────────────────────────────────

    def login(self, email: Optional[str] = None, password: Optional[str] = None) -> Dict:
        """
        Login with email/password. Returns user info dict.
        Session token is stored internally — no need to copy-paste tokens.
        """
        email = email or self.email
        password = password or self.password
        if not email or not password:
            raise AuthenticationError("Email and password are required")

        self.email = email
        self.password = password

        resp = self._http.post(
            f"{FRONTEND_BASE}/api/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )

        if resp.status_code != 200:
            raise AuthenticationError(f"Login failed: HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("success"):
            msg = data.get("message") or data.get("error") or "Login failed"
            raise AuthenticationError(msg)

        self.session_token = data["sessionToken"]
        self.user_info = data.get("user", {})
        self.user_id = self.user_info.get("id")
        self.trader_id = self.user_info.get("traderId")

        # Set cookie for future REST calls
        self._http.cookies.set("session-token", self.session_token, domain=".tradowix.com")

        logger.info("Logged in as %s (trader %s)", self.user_info.get("displayName"), self.trader_id)
        return self.user_info

    def login_with_token(self, session_token: str) -> Dict:
        """Login using an existing session token (for advanced users)."""
        self.session_token = session_token
        self._http.cookies.set("session-token", session_token, domain=".tradowix.com")

        resp = self._http.get(f"{API_BASE}/api/auth/me", timeout=10)
        if resp.status_code != 200:
            raise AuthenticationError(f"Token invalid: HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("success"):
            raise AuthenticationError("Token validation failed")

        self.user_info = data.get("user", {})
        self.user_id = self.user_info.get("id")
        self.trader_id = self.user_info.get("traderId")

        logger.info("Token login: %s (trader %s)", self.user_info.get("displayName"), self.trader_id)
        return self.user_info

    # ─────────────────────────────────────────────
    #  2. WEBSOCKET CONNECTION
    # ─────────────────────────────────────────────

    def connect(self, blocking: bool = False):
        """
        Connect to TradoWix WebSocket.
        If blocking=False (default), runs in background thread.
        If blocking=True, blocks the current thread.
        """
        if not self.session_token:
            raise AuthenticationError("Login first before connecting")

        if websockets is None:
            raise ImportError("Install websockets: pip install websockets")

        if blocking:
            asyncio.run(self._ws_main_loop())
        else:
            self._stop_event.clear()
            self._ws_thread = threading.Thread(target=self._run_ws_thread, daemon=True)
            self._ws_thread.start()
            # Wait for connection + auth + instruments
            for _ in range(150):
                if self._authenticated and self.instruments:
                    break
                time.sleep(0.1)
            if not self._authenticated:
                raise ConnectionError("WebSocket authentication timed out")

    def _run_ws_thread(self):
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)
        try:
            self._ws_loop.run_until_complete(self._ws_main_loop())
        except Exception as e:
            logger.error("WebSocket thread error: %s", e)
        finally:
            self._connected = False
            self._authenticated = False

    async def _ws_main_loop(self):
        url = f"{WS_URL}?token={self.session_token}"
        retry_delay = 1

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, origin=ORIGIN, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._connected = True
                    retry_delay = 1
                    logger.info("WebSocket connected")

                    await self._handle_messages(ws)

            except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError) as e:
                logger.warning("WebSocket disconnected: %s. Reconnecting in %ds...", e, retry_delay)
                self._connected = False
                self._authenticated = False
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)
            except asyncio.CancelledError:
                break

    async def _handle_messages(self, ws):
        async for raw in ws:
            if self._stop_event.is_set():
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            data = msg.get("data")

            if msg_type == "authRequired":
                await ws.send(json.dumps({"type": "authenticate", "token": self.session_token}))

            elif msg_type == "authenticated":
                self._authenticated = True
                logger.info("WebSocket authenticated")
                # Resubscribe
                for sym in list(self._subscribed_symbols):
                    await self._send_subscribe_ticks(ws, sym)

            elif msg_type == "instruments":
                self.instruments = data if isinstance(data, list) else []
                logger.info("Received %d instruments", len(self.instruments))

            elif msg_type == "balanceUpdate":
                self.balance = data.get("balance", {}) if data else {}
                for cb in self._balance_callbacks:
                    self._safe_call(cb, self.balance)

            elif msg_type == "candleHistory":
                if data:
                    symbol = (data.get("symbol") or "").upper()
                    candles_raw = data.get("candles", [])
                    timeframe = data.get("timeframe", 60)
                    current_ticks = data.get("currentPeriodTicks", [])
                    candles = self._parse_candles(candles_raw, timeframe)
                    candles = self._fill_missing_candles(candles, timeframe)
                    self._candle_history[symbol] = candles
                    if symbol in self._candle_events:
                        self._candle_events[symbol].set()
                    for cb in self._candle_callbacks.get(symbol, []):
                        self._safe_call(cb, candles, symbol)

            elif msg_type == "tickUpdate":
                if data:
                    symbol = (data.get("symbol") or "").upper()
                    tick = data.get("tick", [])
                    if len(tick) >= 2:
                        price, ts = tick[0], tick[1]
                        if symbol not in self._tick_buffers:
                            self._tick_buffers[symbol] = []
                        self._tick_buffers[symbol].append({"price": price, "timestamp": ts})
                        # Keep buffer reasonable
                        if len(self._tick_buffers[symbol]) > 5000:
                            self._tick_buffers[symbol] = self._tick_buffers[symbol][-3000:]
                        for cb in self._tick_callbacks.get(symbol, []):
                            self._safe_call(cb, price, ts, symbol)
                        # Update last candle in history
                        self._update_live_candle(symbol, price, ts)

            elif msg_type == "tickSubscribed":
                if data:
                    sym = (data.get("symbol") or "").upper()
                    logger.info("Subscribed to ticks: %s", sym)

            elif msg_type == "quote":
                pass  # Lightweight quote, handled via tickUpdate

            elif msg_type == "tradeOpened":
                if data:
                    for cb in self._trade_opened_callbacks:
                        self._safe_call(cb, data)

            elif msg_type == "tradeResult":
                if data:
                    for cb in self._trade_result_callbacks:
                        self._safe_call(cb, data)

            elif msg_type == "tradeFailed":
                error = data.get("error", "Trade failed") if data else "Trade failed"
                req_id = msg.get("requestId")
                if req_id and req_id in self._pending_responses:
                    self._pending_responses[req_id] = {"error": error}
                logger.warning("Trade failed: %s", error)

            elif msg_type == "tradeCancelled":
                if data:
                    trade_id = data.get("tradeId")
                    logger.info("Trade cancelled: %s", trade_id)

            elif msg_type == "openTrades":
                pass  # Can be handled via callbacks

            elif msg_type == "tradeHistory":
                pass

            elif msg_type == "pong":
                pass

            elif msg_type == "error":
                error = data.get("error", "Unknown error") if data else "Unknown error"
                req_id = msg.get("requestId")
                if req_id and req_id in self._pending_responses:
                    self._pending_responses[req_id] = {"error": error}
                logger.warning("WS error: %s", error)

    async def _send_subscribe_ticks(self, ws, symbol: str, lookback: int = 300, timeframe: int = 60):
        await ws.send(json.dumps({
            "type": "subscribeTicks",
            "symbol": symbol.upper(),
            "lookbackMinutes": lookback,
            "timeframe": timeframe,
            "chartType": "candle",
        }))

    def _send_ws_message(self, msg: dict):
        if self._ws_loop and self._ws and self._connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._ws.send(json.dumps(msg)),
                    self._ws_loop,
                ).result(timeout=5)  # Wait for message to be sent
            except Exception as e:
                logger.error("WS send error: %s", e)

    @staticmethod
    def _safe_call(cb, *args):
        try:
            cb(*args)
        except Exception as e:
            logger.error("Callback error: %s", e)

    # ─────────────────────────────────────────────
    #  3. OHLC CANDLE DATA (gap-filled)
    # ─────────────────────────────────────────────

    @staticmethod
    def _parse_candles(raw_candles: list, timeframe: int = 60) -> List[Dict]:
        """
        Convert raw candle arrays [timestamp, O, H, L, C] → list of dicts.
        Compatible with aimode3.py candle format: {open, high, low, close, volume, time}
        """
        candles = []
        for c in raw_candles:
            if isinstance(c, list) and len(c) >= 5:
                candles.append({
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": int(c[5]) if len(c) > 5 else 1,
                })
        return candles

    @staticmethod
    def _fill_missing_candles(candles: List[Dict], timeframe: int = 60) -> List[Dict]:
        """
        Fill gaps in candle data. If consecutive candles have timestamp gap > timeframe,
        insert synthetic candles using the previous close as OHLC values.
        This fixes the 4-5 missing candle issue on 1m timeframes.
        """
        if not candles or len(candles) < 2:
            return candles

        timeframe_ms = timeframe * 1000
        filled = [candles[0]]

        for i in range(1, len(candles)):
            prev = filled[-1]
            curr = candles[i]
            expected_ts = prev["time"] + timeframe_ms

            # Fill gaps
            while expected_ts < curr["time"] - (timeframe_ms // 2):
                filled.append({
                    "time": expected_ts,
                    "open": prev["close"],
                    "high": prev["close"],
                    "low": prev["close"],
                    "close": prev["close"],
                    "volume": 0,
                })
                prev = filled[-1]
                expected_ts = prev["time"] + timeframe_ms

            filled.append(curr)

        return filled

    def _update_live_candle(self, symbol: str, price: float, timestamp: int):
        """Update the latest candle or create a new one from live ticks."""
        candles = self._candle_history.get(symbol)
        if not candles:
            return

        last = candles[-1]
        timeframe_ms = 60000  # default 1m

        if timestamp >= last["time"] + timeframe_ms:
            new_ts = (timestamp // timeframe_ms) * timeframe_ms
            # Fill any gap between last candle and new one
            expected_ts = last["time"] + timeframe_ms
            while expected_ts < new_ts:
                candles.append({
                    "time": expected_ts,
                    "open": last["close"],
                    "high": last["close"],
                    "low": last["close"],
                    "close": last["close"],
                    "volume": 0,
                })
                last = candles[-1]
                expected_ts += timeframe_ms

            # New candle with actual tick
            new_candle = {
                "time": new_ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1,
            }
            candles.append(new_candle)
        else:
            # Update existing candle
            last["close"] = price
            if price > last["high"]:
                last["high"] = price
            if price < last["low"]:
                last["low"] = price
            last["volume"] += 1

    def subscribe(self, symbol: str, lookback_minutes: int = 300, timeframe: int = 60):
        """Subscribe to a symbol's tick stream and candle history."""
        symbol = symbol.upper()
        self._subscribed_symbols.add(symbol)
        self._candle_events[symbol] = threading.Event()
        self._send_ws_message({
            "type": "subscribeTicks",
            "symbol": symbol,
            "lookbackMinutes": lookback_minutes,
            "timeframe": timeframe,
            "chartType": "candle",
        })

    def unsubscribe(self, symbol: str):
        """Unsubscribe from a symbol's tick stream."""
        symbol = symbol.upper()
        self._subscribed_symbols.discard(symbol)
        self._send_ws_message({"type": "unsubscribeTicks", "symbol": symbol})

    def get_candles(self, symbol: str, timeframe: int = 60, count: int = 200,
                    lookback_minutes: int = 0, timeout: float = 10.0) -> List[Dict]:
        """
        Get OHLC candle data for a symbol.
        Returns list of dicts: [{time, open, high, low, close, volume}, ...]
        Automatically fills missing candles.
        If not already subscribed, subscribes and waits for data.

        Args:
            symbol: Instrument symbol (e.g., "EURUSD-OTC")
            timeframe: Candle period in seconds (60 = 1min, 300 = 5min)
            count: Number of candles desired
            lookback_minutes: How many minutes of history (0 = auto-calculate)
            timeout: Max seconds to wait for data
        """
        symbol = symbol.upper()

        if lookback_minutes <= 0:
            lookback_minutes = max((count * timeframe) // 60 + 30, 200)

        if symbol not in self._subscribed_symbols:
            self.subscribe(symbol, lookback_minutes, timeframe)

        # Wait for candle data
        event = self._candle_events.get(symbol)
        if event:
            event.wait(timeout=timeout)

        candles = self._candle_history.get(symbol, [])
        if count and len(candles) > count:
            candles = candles[-count:]

        return candles

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get the latest price for a symbol."""
        symbol = symbol.upper()
        ticks = self._tick_buffers.get(symbol, [])
        if ticks:
            return ticks[-1]["price"]
        candles = self._candle_history.get(symbol, [])
        if candles:
            return candles[-1]["close"]
        return None

    # ─────────────────────────────────────────────
    #  4. TRADING
    # ─────────────────────────────────────────────

    def place_trade(self, symbol: str, direction: str, amount: float,
                    duration_minutes: int = 1, is_demo: bool = True,
                    mode: str = "turbo", duration_seconds: int = 0,
                    tournament_id: Optional[str] = None) -> str:
        """
        Place a binary options trade.

        Args:
            symbol: e.g., "EURUSD-OTC"
            direction: "higher" or "lower" (also accepts "call"/"put")
            amount: Trade amount in USD
            duration_minutes: Expiry in minutes (for turbo mode: 1,2,3,4,5,10,15,30)
            is_demo: True for demo account
            mode: "turbo" (minutes) or "blitz" (seconds)
            duration_seconds: Expiry in seconds (for blitz mode: 60,90,120,150,300)
            tournament_id: Optional tournament ID

        Returns:
            requestId string for tracking
        """
        direction = direction.lower()
        if direction in ("higher", "up", "buy"):
            direction = "call"
        elif direction in ("lower", "down", "sell"):
            direction = "put"

        if direction not in ("call", "put"):
            raise TradeError(f"Invalid direction: {direction}. Use 'call'/'put' or 'higher'/'lower'")

        request_id = f"trade-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

        msg = {
            "type": "placeTrade",
            "requestId": request_id,
            "symbol": symbol.upper(),
            "direction": direction,
            "amount": amount,
            "expirationMode": mode,
            "isDemo": is_demo,
        }

        if mode == "turbo":
            msg["turboMinutes"] = duration_minutes
        elif mode == "blitz":
            msg["duration"] = duration_seconds or (duration_minutes * 60)

        if tournament_id:
            msg["tournamentId"] = tournament_id

        self._send_ws_message(msg)
        logger.info("Trade placed: %s %s %s $%s (%s)", request_id, symbol, direction, amount, mode)
        return request_id

    def cancel_trade(self, trade_id: str):
        """Cancel an active trade by ID."""
        self._send_ws_message({
            "type": "cancelTrade",
            "requestId": f"cancel-{int(time.time() * 1000)}",
            "tradeId": trade_id,
        })

    def get_open_trades(self, is_demo: bool = True):
        """Request the list of currently open trades."""
        self._send_ws_message({"type": "getOpenTrades", "isDemo": is_demo})

    def get_trade_history(self, is_demo: bool = True, page: int = 1, page_size: int = 50):
        """Request trade history via WebSocket."""
        self._send_ws_message({
            "type": "getTradeHistory",
            "isDemo": is_demo,
            "page": page,
            "pageSize": page_size,
        })

    # ─────────────────────────────────────────────
    #  5. EVENT CALLBACKS
    # ─────────────────────────────────────────────

    def on_tick(self, symbol: str, callback: Callable):
        """
        Register a callback for live tick updates.
        callback(price: float, timestamp: int, symbol: str)
        """
        symbol = symbol.upper()
        if symbol not in self._tick_callbacks:
            self._tick_callbacks[symbol] = []
        self._tick_callbacks[symbol].append(callback)
        if symbol not in self._subscribed_symbols:
            self.subscribe(symbol)

    def on_candle(self, symbol: str, callback: Callable):
        """
        Register a callback for candle history updates.
        callback(candles: list, symbol: str)
        """
        symbol = symbol.upper()
        if symbol not in self._candle_callbacks:
            self._candle_callbacks[symbol] = []
        self._candle_callbacks[symbol].append(callback)

    def on_trade_opened(self, callback: Callable):
        """callback(trade_data: dict)"""
        self._trade_opened_callbacks.append(callback)

    def on_trade_result(self, callback: Callable):
        """callback(result_data: dict)"""
        self._trade_result_callbacks.append(callback)

    def on_balance_update(self, callback: Callable):
        """callback(balance: dict)"""
        self._balance_callbacks.append(callback)

    # ─────────────────────────────────────────────
    #  6. REST API HELPERS
    # ─────────────────────────────────────────────

    def get_balance(self) -> Dict:
        """Fetch current balance via REST API."""
        resp = self._http.get(f"{API_BASE}/api/user/balance", timeout=10)
        if resp.status_code == 200:
            self.balance = resp.json()
            return self.balance
        return {}

    def get_user_info(self) -> Dict:
        """Fetch current user profile."""
        resp = self._http.get(f"{API_BASE}/api/auth/me", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            self.user_info = data.get("user", {})
            return self.user_info
        return {}

    def reset_demo(self) -> bool:
        """Reset demo account balance to default."""
        resp = self._http.get(f"{API_BASE}/api/user/demo/reset", timeout=10)
        return resp.status_code == 200

    def get_payment_methods(self) -> Dict:
        """Get available payment/withdrawal methods."""
        resp = self._http.get(f"{API_BASE}/api/payment/methods", timeout=10)
        return resp.json() if resp.status_code == 200 else {}

    def get_user_settings(self) -> Dict:
        """Get user settings (default amounts, favorites, etc.)."""
        resp = self._http.get(f"{API_BASE}/api/user-settings", timeout=10)
        return resp.json() if resp.status_code == 200 else {}

    def get_instruments_list(self) -> List[Dict]:
        """Return cached instruments list (from WebSocket)."""
        return self.instruments

    def find_instrument(self, symbol: str) -> Optional[Dict]:
        """Find an instrument by symbol name."""
        symbol = symbol.upper()
        for inst in self.instruments:
            if inst.get("symbol", "").upper() == symbol:
                return inst
        return None

    def get_payout(self, symbol: str) -> float:
        """Get the turbo payout rate for a symbol (e.g., 0.92 = 92%)."""
        inst = self.find_instrument(symbol)
        if inst:
            return inst.get("effectiveTurboPayoutRate", inst.get("turboPayoutRate", 0))
        return 0

    # ─────────────────────────────────────────────
    #  7. DISCONNECT
    # ─────────────────────────────────────────────

    def disconnect(self):
        """Close WebSocket connection and stop background thread."""
        self._stop_event.set()
        if self._ws and self._ws_loop:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._ws_loop)
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=5)
        self._connected = False
        self._authenticated = False
        logger.info("Disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._authenticated

    # ─────────────────────────────────────────────
    #  8. CONVENIENCE — fetch_data() compatible
    # ─────────────────────────────────────────────

    def fetch_data(self, pair: str, limit: int = 600) -> Tuple[Optional[List[Dict]], Optional[float], str]:
        """
        Drop-in replacement for SMZXBot.fetch_data().
        Returns (candles, current_price, payout_str) — same format as quotex proxy.

        Example:
            candles, price, payout = client.fetch_data("EURUSD-OTC", 600)
        """
        symbol = self._normalize_symbol(pair)
        candles = self.get_candles(symbol, timeframe=60, count=limit)
        if not candles:
            return None, None, "0"

        current_price = candles[-1]["close"]
        payout_rate = self.get_payout(symbol)
        payout_str = str(int(payout_rate * 100)) if payout_rate else "92"

        return candles, current_price, payout_str

    @staticmethod
    def _normalize_symbol(pair: str) -> str:
        """
        Convert various pair formats to TradoWix symbol format.
        EURUSD_OTC → EURUSD-OTC
        EURUSD → EURUSD
        EUR/USD (OTC) → EURUSD-OTC
        """
        pair = pair.strip().upper()
        pair = pair.replace("/", "").replace(" ", "")
        pair = pair.replace("(OTC)", "-OTC")
        pair = pair.replace("_OTC", "-OTC")
        pair = pair.replace("_", "")
        return pair


# ─────────────────────────────────────────────
#  EXAMPLE USAGE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python tradowix_client.py <email> <password>")
        print("Example: python tradowix_client.py user@email.com mypassword")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    client = TradoWixClient()

    # 1. Login (students just give email + password)
    print("Logging in...")
    user = client.login(email, password)
    print(f"  Logged in: {user.get('displayName')} | Demo: ${user.get('demoBalance')}")

    # 2. Connect WebSocket
    print("Connecting WebSocket...")
    client.connect()
    print(f"  Connected! {len(client.instruments)} instruments available")

    # 3. Get OHLC candle data (gap-filled)
    symbol = "EURUSD-OTC"
    print(f"\nFetching {symbol} candles...")
    candles = client.get_candles(symbol, timeframe=60, count=50)
    print(f"  Got {len(candles)} candles (gap-filled)")
    if candles:
        last = candles[-1]
        print(f"  Last candle: O={last['open']} H={last['high']} L={last['low']} C={last['close']}")

    # 4. Get payout
    payout = client.get_payout(symbol)
    print(f"  Payout: {int(payout * 100)}%")

    # 5. fetch_data() compatible (same as quotex proxy)
    candles2, price, payout_str = client.fetch_data(symbol, 200)
    print(f"\nfetch_data() → {len(candles2)} candles, price={price}, payout={payout_str}%")

    # 6. Live tick stream
    tick_count = [0]
    def on_tick(price, ts, sym):
        tick_count[0] += 1
        if tick_count[0] <= 5:
            print(f"  Tick #{tick_count[0]}: {sym} = {price}")
        elif tick_count[0] == 6:
            print("  (more ticks streaming...)")

    client.on_tick(symbol, on_tick)

    # 7. Demo trade
    print(f"\nPlacing demo trade: {symbol} CALL $1 (1min)...")
    req_id = client.place_trade(symbol, "call", amount=1, duration_minutes=1, is_demo=True)
    print(f"  Trade request: {req_id}")

    # Track result
    def on_result(data):
        print(f"  Trade result: {data.get('result')} | Profit: ${data.get('profit', 0)}")

    client.on_trade_result(on_result)

    # Wait a bit for ticks
    print("\nStreaming for 15 seconds...")
    time.sleep(15)

    print(f"\nTotal ticks received: {tick_count[0]}")
    print(f"Balance: ${client.balance.get('currentBalance', 'N/A')}")

    client.disconnect()
    print("Done!")
