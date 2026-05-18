#!/usr/bin/env python3
import asyncio, json, os, signal, sys, time, base64, hashlib, socket, uuid, threading, math, re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import requests
from colorama import init, Fore, Style
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telethon import TelegramClient, Button
from telethon.tl.types import MessageEntityCustomEmoji as TelethonCustomEmoji, MessageEntityBold as TelethonBold
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    MessageEntity
)
from telegram.constants import KeyboardButtonStyle
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)

# ══════════════ CONFIG ══════════════
BOT_TOKEN = "8261301090:AAHM2JRXTsflqkksuCk9n-kwcoB_XZT2zyw"
SUPABASE_URL = "https://jklibjyjzimcjlpvskvw.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImprbGlianlqemltY2pscHZza3Z3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQxMTE0NzEsImV4cCI6MjA4OTY4NzQ3MX0.aPMtnplXCpMenfdpDAPFcdMd4ccptM2L3C5oCWWC4X4"

def is_authorized(uid: int) -> bool:
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json"
    }
    url = f"{SUPABASE_URL}/rest/v1/bot_access"
    params = {"telegram_id": f"eq.{uid}", "is_active": "eq.true", "select": "id"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return len(data) > 0
    except:
        pass
    return False

# ══════════════ MULTI‑USER STATE ══════════════
class UserState:
    def __init__(self):
        self.strategy = 1
        self.market_type = "OTC"
        self.pairs = []
        self.telegram_format = 1
        self.running = False
        self.stop_requested = False
        self.stats = {"wins":0, "losses":0}
        self.signal_history = []
        self.last_signal_pair = None
        self.same_pair_count = 0
        self.last_loss = {}
        self.loss_cooldown_minutes = 3
        self.strategy2_filters = None
        self.strategy3_min_accuracy = 75
        self.strategy3_lookback = 20
        self.strategy4_min_accuracy = 60
        self.strategy5_min_score = 80
        self.strategy6_min_score = 85          # minimum confluence score for Strategy 6
        self.strategy6_min_candles = 50        # minimum candles required before analysis

user_states: Dict[int, UserState] = {}
def get_state(uid: int) -> UserState:
    if uid not in user_states:
        user_states[uid] = UserState()
    return user_states[uid]

# ══════════════ PREMIUM EMOJI IDs ══════════════
PREMIUM_EMOJI_IDS = {
    "👑": 5217822164362739968, "📊": 6145248943807667330,
    "⏳": 6062063510412599114, "🔰": 6147725220087077904,
    "📉": 6064347140228912866, "📈": 6062085844242537125,
    "💎": 6104975752732612597, "😈": 6062153953833917531,
    "✅": 6147440218942218700, "✨": 6145352194821462834,
    "🏆": 6145546134069714639, "❌": 6145317070578916456,
    "📳": 5321305265306348161, "🐲": 5319156849650441091,
    "🤖": 5314391089514291948, "🔥": 5424972470023104089,
    "⬇️": 5260651934720740549, "⏰": 6145553439809084250,
    "🤭": 6062294201696000196, "🔍": 5212985021870123409,
    "⚠️": 6147840110462245787, "🗓": 5413879192267805083,
    "💲": 6145449239607515472, "🔅": 6102445273965926934,
    "📋": 6147840110462245787,   # backtest
    # New mode emojis
    "🕐": 5215484787325676090,   # UTC Converter
    "📝": 6145248943807667330,   # Text Formatter (reuse 📊)
    "🎨": 5314391089514291948,   # Font Changer (reuse 🤖)
    "📉": 6064347140228912866,   # Trend Filter
    "➡️": 5260651934720740549,   # arrow
    "🟢": 6102581171026140784,   # green circle (use ❌ ID temporarily, will fix later)
    "🔴": 6102581171026140784,   # red circle (same, we'll use standard emojis for these)
    "💪": 5316681209026191987,
    "🚀": 6147654280112248427,
    "🏐": 5217911744495624141,
    "🖥": 5282843764451195532,
    "🎥": 6264778055454036969,
    "🎇": 5229228004068057251,
    "⛈": 6102795674577803992,
    "⚙️": 5316977664848837418,
    "📺":5314406675950608695,
    "🐶": 5319301933645707826,
}

FORMAT2_EMOJI_IDS = {
    "📊": 5231200819986047254, "⏰": 6285240160120477644,
    "⏳": 5212985021870123409, "🇵🇰": 5269660289321679111,
    "💀": 6204172639523572930, "👿": 6104776659523607556,
    "📺": 4927197721900614739, "🏆": 6145546134069714639,
    "🤔": 5370919202796348364, "🕐": 5215484787325676090,
    "📉": 6064347140228912866, "📈": 6062085844242537125,
    "🦇": 6136515548718045689, "✅": 6147440218942218700,
    "❌": 6102581171026140784,
}

# ══════════════ FANCY FONT ══════════════
def fancy_font(text):
    mapping = {
        'A':'𝙰','B':'𝙱','C':'𝙲','D':'𝙳','E':'𝙴','F':'𝙵','G':'𝙶','H':'𝙷','I':'𝙸','J':'𝙹',
        'K':'𝙺','L':'𝙻','M':'𝙼','N':'𝙽','O':'𝙾','P':'𝙿','Q':'𝚀','R':'𝚁','S':'𝚂','T':'𝚃',
        'U':'𝚄','V':'𝚅','W':'𝚆','X':'𝚇','Y':'𝚈','Z':'𝚉','a':'𝚊','b':'𝚋','c':'𝚌','d':'𝚍',
        'e':'𝚎','f':'𝚏','g':'𝚐','h':'𝚑','i':'𝚒','j':'𝚓','k':'𝚔','l':'𝚕','m':'𝚖','n':'𝚗',
        'o':'𝚘','p':'𝚙','q':'𝚚','r':'𝚛','s':'𝚜','t':'𝚝','u':'𝚞','v':'𝚟','w':'𝚠','x':'𝚡',
        'y':'𝚢','z':'𝚣','0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽',
        '8':'𝟾','9':'𝟿',':':'：','.':'．','/':'╱','-':'—','_':'＿','@':'＠','!':'！','?':'？',
        '(':'（',')':'）','[':'【',']':'】','{':'｛','}':'｝','<':'＜','>':'＞','=':'＝','+':'＋',
        '*':'＊','&':'＆','^':'＾','$':'＄','#':'＃','~':'～'
    }
    return "".join(mapping.get(c, c) for c in str(text))

# ══════════════ MESSAGE BUILDERS ══════════════
def build_signal_message(pair, entry_time, direction, payout, trend_text):
    dir_emoji = "📉" if direction == "CALL" else "📈"
    return (
        f"❀° ┄────────=─────────╮\n"
        f"   👑 𝚂𝙼𝚉𝚇-𝙰𝙸 𝚅𝟺.𝟹 👑\n"
        f"╰────────=───=─────┄ °❀\n"
        f"┏───♡─────────── ⊹˚───┓\n"
        f"📊 Pair∶— {fancy_font(pair)}\n"
        f"⏳ TimeFrame∶— 𝙼𝟷\n"
        f"🔰 TradeTime∶— {fancy_font(entry_time)}\n"
        f"{dir_emoji} Direction∶— {fancy_font(direction)}\n"
        f"┗─── ⊹˚───────────♡───┛\n"
        f"💎 Payout∶— {fancy_font(payout)}% 📊 Trend∶— 📈 {fancy_font(trend_text)}\n"
        f"•❅✦──────✧❅✦❅✧──────✦❅•\n"
        f"😈 𝚂𝙼𝚉𝚇 𝚅𝟺.𝟹 - 𝙰𝙸 𝚃𝚁𝙰𝙳𝙸𝙽𝙶 𝚂𝙾𝙵𝚃𝚆𝙰𝚁𝙴"
    )

def build_result_message_first_win(pair, entry_time, payout, wins, losses):
    win_rate = int((wins/(wins+losses))*100) if (wins+losses)>0 else 100
    return (
        f"•❅✦─𝚂𝙼𝚉𝚇 𝚁𝙴𝚂𝚄𝙻𝚃𝚂 𝚅𝟺.𝟹─✦❅•\n\n"
        f"┏━⋅━⋅━━⋅༻  ᵔᴗᵔ  ༺⋅━━⋅━⋅━┓\n"
        f"  {fancy_font(pair)} ➛ {fancy_font(entry_time)} ➛ {fancy_font(payout)}%\n"
        f"✅✅✅ 𝚂𝚄𝚁𝙴𝚂𝙷𝙾𝚃!! ✅✅✅\n"
        f"┗━⋅━⋅━━⋅༻ıllıʬıllı༺⋅━━⋅━⋅━┛\n"
        f"✅ 𝚆𝚒𝚗: {fancy_font(str(wins))} | |✨ 𝙻𝚘𝚜𝚜: {fancy_font(str(losses))} |🏆 ({fancy_font(str(win_rate))}%)\n\n"
        f"💎Developer∶— @Rohailtrader"
    )

def build_result_message_second_win(pair, entry_time, payout, wins, losses):
    win_rate = int((wins/(wins+losses))*100) if (wins+losses)>0 else 100
    return (
        f"•❅✦─𝚂𝙼𝚉𝚇 𝚁𝙴𝚂𝚄𝙻𝚃𝚂 𝚅𝟺.𝟹─✦❅•\n\n"
        f"┏━⋅━⋅━━⋅༻  ᵔᴗᵔ  ༺⋅━━⋅━⋅━┓\n"
        f"  {fancy_font(pair)} ➛ {fancy_font(entry_time)} ➛ {fancy_font(payout)}%\n"
        f"✅✅✅ 𝚆𝙸𝙽 — 𝙶𝟷 ✅✅✅\n"
        f"┗━⋅━⋅━━⋅༻ıllıʬıllı༺⋅━━⋅━⋅━┛\n"
        f"✅ 𝚆𝚒𝚗: {fancy_font(str(wins))} | |✨ 𝙻𝚘𝚜𝚜: {fancy_font(str(losses))} |🏆 ({fancy_font(str(win_rate))}%)\n\n"
        f"💎Developer∶— @Rohailtrader"
    )

def build_result_message_loss(pair, entry_time, payout, wins, losses):
    win_rate = int((wins/(wins+losses))*100) if (wins+losses)>0 else 100
    return (
        f"•❅✦─𝚂𝙼𝚉𝚇 𝚁𝙴𝚂𝚄𝙻𝚃𝚂 𝚅𝟺.𝟹─✦❅•\n\n"
        f"┏━⋅━⋅━━⋅༻  ᵔᴗᵔ  ༺⋅━━⋅━⋅━┓\n"
        f"  {fancy_font(pair)} ➛ {fancy_font(entry_time)} ➛ {fancy_font(payout)}%\n"
        f"❌❌❌ 𝙻𝙾𝚂𝚂 ❌❌❌\n"
        f"┗━⋅━⋅━━⋅༻ıllıʬıllı༺⋅━━⋅━⋅━┛\n"
        f"✅ 𝚆𝚒𝚗: {fancy_font(str(wins))} | |✨ 𝙻𝚘𝚜𝚜: {fancy_font(str(losses))} |🏆 ({fancy_font(str(win_rate))}%)\n\n"
        f"💎Developer∶— @Rohailtrader"
    )

def build_future_signal_header(signal_list):
    lines = [
        "📊 UTC +6",
        "💎 MAX MARTINGALE： 01",
        "🔅 1 MINUTE",
        "     🤖 Software： SMZX4.3 🏆",
        ""
    ]
    for sig in signal_list:
        dir_text = "𝙲𝙰𝙻𝙻" if sig['dir'] == "CALL" else "𝙿𝚄𝚃"
        lines.append(f"❒ {fancy_font(sig['pair'])} ➪ {fancy_font(sig['time'])} ➪ {dir_text}")
    return "\n".join(lines)

# ══════════════ CUSTOM EMOJI ENTITY BUILDER ══════════════
def build_custom_emoji_entities(text: str) -> list:
    entities = []
    offset = 0
    for ch in text:
        clen = len(ch.encode('utf-16-le')) // 2
        eid = PREMIUM_EMOJI_IDS.get(ch) or FORMAT2_EMOJI_IDS.get(ch)
        if eid:
            entities.append(
                MessageEntity(
                    type='custom_emoji',
                    offset=offset,
                    length=clen,
                    custom_emoji_id=eid
                )
            )
        offset += clen
    return entities

# ══════════════ INDICATORS (full) ══════════════
def calculate_ema(prices, period):
    if len(prices) < period: return None
    alpha = 2.0/(period+1.0)
    ema_val = sum(prices[-period:])/period
    for i in range(-period+1, 0): ema_val = prices[i]*alpha + ema_val*(1-alpha)
    return ema_val

def calculate_rsi(prices, period=14):
    if len(prices) < period+1: return 50.0
    gains, losses = [], []
    for i in range(len(prices)-period, len(prices)-1):
        change = prices[i+1] - prices[i]
        if change > 0: gains.append(change); losses.append(0)
        else: gains.append(0); losses.append(abs(change))
    if not gains or not losses: return 50.0
    avg_gain = sum(gains)/period; avg_loss = sum(losses)/period
    if avg_loss == 0: return 100.0
    rs = avg_gain/avg_loss; return 100.0 - (100.0/(1.0+rs))

def calculate_williams_r(prices, period=14):
    if len(prices) < period: return -50
    highest = max(prices[-period:]); lowest = min(prices[-period:])
    if highest == lowest: return -50
    return -100 * (highest - prices[-1]) / (highest - lowest)

def calculate_bollinger(prices, period=20, std_dev=2):
    if len(prices) < period: return None, None, None
    ma = sum(prices[-period:])/period
    variance = sum((p - ma)**2 for p in prices[-period:])/period
    std = variance**0.5
    upper = ma + std_dev*std; lower = ma - std_dev*std
    return ma, upper, lower

def calculate_atr(candles, period=14):
    if len(candles) < period+1: return 0
    highs = [c['high'] for c in candles]; lows = [c['low'] for c in candles]; closes = [c['close'] for c in candles]
    tr = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1,len(candles))]
    return sum(tr[-period:])/period

def calculate_adx(candles, period=14):
    if len(candles) < period+1: return 0,0,0
    highs=[c['high'] for c in candles]; lows=[c['low'] for c in candles]; closes=[c['close'] for c in candles]
    tr, plus_dm, minus_dm = [], [], []
    for i in range(1,len(candles)):
        hl = highs[i]-lows[i]; hc = abs(highs[i]-closes[i-1]); lc = abs(lows[i]-closes[i-1])
        tr.append(max(hl, hc, lc))
        up_move = highs[i] - highs[i-1]; down_move = lows[i-1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
    atr_val = sum(tr[:period])/period
    plus_di = (sum(plus_dm[:period])/period)/atr_val*100 if atr_val>0 else 0
    minus_di = (sum(minus_dm[:period])/period)/atr_val*100 if atr_val>0 else 0
    dx = abs(plus_di - minus_di)/(plus_di + minus_di)*100 if (plus_di+minus_di)>0 else 0
    adx_vals = [dx]
    for i in range(period, len(tr)):
        atr_val = (atr_val*(period-1) + tr[i])/period
        plus_di = (plus_di*(period-1) + plus_dm[i])/period
        minus_di = (minus_di*(period-1) + minus_dm[i])/period
        plus_di = (plus_di/atr_val*100) if atr_val>0 else 0
        minus_di = (minus_di/atr_val*100) if atr_val>0 else 0
        dx = abs(plus_di - minus_di)/(plus_di + minus_di)*100 if (plus_di+minus_di)>0 else 0
        adx_vals.append(dx)
    return adx_vals[-1], plus_di, minus_di

def calculate_stochastic(candles, k_period=8, d_period=3):
    if len(candles) < k_period: return 50,50
    recent = candles[-k_period:]
    highest = max(c['high'] for c in recent); lowest = min(c['low'] for c in recent)
    current_close = candles[-1]['close']
    raw_k = 50 if highest==lowest else (current_close - lowest)/(highest - lowest)*100
    k_vals = []
    for i in range(len(candles)-k_period+1):
        window = candles[i:i+k_period]
        h = max(c['high'] for c in window); l = min(c['low'] for c in window)
        c_close = window[-1]['close']
        k_vals.append(50 if h==l else (c_close - l)/(h - l)*100)
    d_val = sum(k_vals[-d_period:])/d_period if len(k_vals)>=d_period else raw_k
    return raw_k, d_val

def calculate_support_resistance_levels(prices, lookback=20):
    if len(prices) < lookback: return None, None
    recent = prices[-lookback:]; return min(recent), max(recent)

def detect_price_action_patterns(candles):
    if len(candles) < 5: return []
    patterns = []
    for i in range(2, len(candles)-2):
        c = candles[i]; p1 = candles[i-1]; p2 = candles[i-2] if i>=2 else None
        o, cl, h, l = float(c['open']), float(c['close']), float(c['high']), float(c['low'])
        po, pc1 = float(p1['open']), float(p1['close'])
        body = abs(cl - o)
        lower_wick = min(o, cl) - l
        upper_wick = h - max(o, cl)
        if pc1 < po and cl > o and o <= pc1 and cl >= po:
            patterns.append({'type':'BULLISH_ENGULFING','candle_index':i,'strength':0.9})
        elif pc1 > po and cl < o and o >= pc1 and cl <= po:
            patterns.append({'type':'BEARISH_ENGULFING','candle_index':i,'strength':0.9})
        elif po < pc1 and o > pc1 and cl < po:
            patterns.append({'type':'BULLISH_HARAMI','candle_index':i,'strength':0.7})
        elif po > pc1 and o < pc1 and cl > po:
            patterns.append({'type':'BEARISH_HARAMI','candle_index':i,'strength':0.7})
        if body > 0 and lower_wick >= 2*body and upper_wick <= 0.3*body:
            patterns.append({'type':'HAMMER','candle_index':i,'strength':0.8})
        if body > 0 and upper_wick >= 2*body and lower_wick <= 0.3*body:
            patterns.append({'type':'SHOOTING_STAR','candle_index':i,'strength':0.8})
        if p2:
            p2o, p2c = float(p2['open']), float(p2['close'])
            doji_p1 = abs(pc1 - po) <= (float(p1['high'])-float(p1['low']))*0.3
            if p2c < p2o and doji_p1 and cl > o and cl > (p2o+p2c)/2:
                patterns.append({'type':'MORNING_STAR','candle_index':i,'strength':0.95})
            if p2c > p2o and doji_p1 and cl < o and cl < (p2o+p2c)/2:
                patterns.append({'type':'EVENING_STAR','candle_index':i,'strength':0.95})
        if i >= 3:
            c3=candles[i-2]; c2=candles[i-1]; c1=candles[i]
            if (float(c1['close'])>float(c1['open']) and float(c2['close'])>float(c2['open']) and float(c3['close'])>float(c3['open']) and float(c1['close'])>float(c2['close'])>float(c3['close'])):
                patterns.append({'type':'THREE_WHITE_SOLDIERS','candle_index':i,'strength':0.9})
            if (float(c1['close'])<float(c1['open']) and float(c2['close'])<float(c2['open']) and float(c3['close'])<float(c3['open']) and float(c1['close'])<float(c2['close'])<float(c3['close'])):
                patterns.append({'type':'THREE_BLACK_CROWS','candle_index':i,'strength':0.9})
    return patterns

def calculate_supertrend(candles, period=10, multiplier=3):
    if len(candles) < period: return [], []
    high = [c['high'] for c in candles]; low = [c['low'] for c in candles]; close = [c['close'] for c in candles]
    tr = [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1])) for i in range(1,len(high))]
    atr_val = sum(tr[:period])/period
    atr = [atr_val]
    for i in range(period, len(tr)): atr_val = (atr_val*(period-1)+tr[i])/period; atr.append(atr_val)
    supertrend, trend = [], []
    for i in range(len(candles)):
        if i < period: supertrend.append(None); trend.append(None); continue
        hl2 = (high[i]+low[i])/2
        upper_band = hl2 + multiplier*atr[i-period]; lower_band = hl2 - multiplier*atr[i-period]
        if i == period: supertrend.append(upper_band); trend.append(1)
        else:
            if close[i] > supertrend[-1]:
                current_trend = 1
                supertrend.append(max(lower_band, supertrend[-1]) if trend[-1]==1 else lower_band)
            else:
                current_trend = -1
                supertrend.append(min(upper_band, supertrend[-1]) if trend[-1]==-1 else upper_band)
            trend.append(current_trend)
    return supertrend, trend

def detect_fvg_gaps(candles, threshold=0.001):
    if len(candles) < 3: return []
    fvg_gaps = []
    for i in range(1, len(candles)-1):
        prev = candles[i-1]; curr = candles[i]; nxt = candles[i+1]
        if (curr['high'] > prev['low'] and nxt['low'] > curr['low'] and abs(curr['high'] - prev['low'])/prev['low'] > threshold):
            fvg_gaps.append({'type':'BULLISH_FVG','start_price':prev['low'],'end_price':curr['high'],'candle_index':i,'strength':(curr['high']-prev['low'])/prev['low']})
        if (curr['low'] < prev['high'] and nxt['high'] < curr['high'] and abs(prev['high'] - curr['low'])/prev['high'] > threshold):
            fvg_gaps.append({'type':'BEARISH_FVG','start_price':prev['high'],'end_price':curr['low'],'candle_index':i,'strength':(prev['high']-curr['low'])/prev['high']})
    return fvg_gaps

def check_trend_reverse(candles, direction):
    if len(candles) < 30: return True
    closes = [c['close'] for c in candles]; cur = closes[-1]
    ema20 = calculate_ema(closes, 20) if len(closes)>=20 else None
    ema50 = calculate_ema(closes, 50) if len(closes)>=50 else None
    rsi = calculate_rsi(closes, 14)
    support, resistance = calculate_support_resistance_levels(closes, 20)
    if ema20 and ema50:
        if cur > ema20 and ema20 > ema50:
            if rsi > 70 and resistance and abs(cur - resistance)/resistance < 0.005: return direction == "PUT"
        elif cur < ema20 and ema20 < ema50:
            if rsi < 30 and support and abs(cur - support)/support < 0.005: return direction == "CALL"
    return True

class Strategy2Filters:
    def __init__(self):
        self.use_trend = False; self.use_bollinger = False; self.use_support_resistance = False
        self.use_price_action = False; self.use_supertrend = False; self.use_fvg = False
        self.use_trend_reverse = False; self.min_accuracy = 75
    def check_trend(self, candles, direction):
        if len(candles) < 5: return True
        closes = [c['close'] for c in candles[-5:]]
        trend_score = sum(1 if closes[i] > closes[i-1] else -1 for i in range(1,5))
        if trend_score >= 3: return direction == "CALL"
        elif trend_score <= -3: return direction == "PUT"
        return True
    def check_bollinger(self, candles, direction):
        if len(candles) < 20: return True
        closes = [c['close'] for c in candles]; ma, upper, lower = calculate_bollinger(closes)
        if ma is None: return True
        cur, prev = closes[-1], closes[-2] if len(closes) >= 2 else cur
        if direction == "CALL": return cur < lower and prev >= lower
        else: return cur > upper and prev <= upper
    def check_support_resistance(self, candles, direction):
        if len(candles) < 20: return True
        closes = [c['close'] for c in candles]; sup, res = calculate_support_resistance_levels(closes)
        if sup is None or res is None: return True
        cur, prev = closes[-1], closes[-2] if len(closes) >= 2 else cur
        if direction == "CALL":
            if cur > res and prev <= res: return True
            if abs(cur - sup)/sup < 0.001 and cur > prev: return True
        else:
            if cur < sup and prev >= sup: return True
            if abs(cur - res)/res < 0.001 and cur < prev: return True
        return False
    def check_price_action(self, candles, direction):
        if len(candles) < 5: return True
        patterns = detect_price_action_patterns(candles)
        recent = [p for p in patterns if p['candle_index'] >= len(candles)-3]
        for p in recent:
            if p['type'] in ['BULLISH_ENGULFING','HAMMER','BULLISH_HARAMI','MORNING_STAR','THREE_WHITE_SOLDIERS']: return direction == "CALL"
            if p['type'] in ['BEARISH_ENGULFING','SHOOTING_STAR','BEARISH_HARAMI','EVENING_STAR','THREE_BLACK_CROWS']: return direction == "PUT"
        return True
    def check_supertrend(self, candles, direction):
        if len(candles) < 20: return True
        st, tr = calculate_supertrend(candles, 10, 3)
        if st[-1] is None or tr[-1] is None: return True
        cur = candles[-1]['close']
        if direction == "CALL": return tr[-1] == 1 and cur > st[-1]
        else: return tr[-1] == -1 and cur < st[-1]
    def check_fvg(self, candles, direction):
        if len(candles) < 10: return True
        fvg = detect_fvg_gaps(candles)
        cur = candles[-1]['close']
        for f in fvg:
            if f['candle_index'] >= len(candles)-5:
                if f['type'] == 'BULLISH_FVG' and cur > f['end_price']: return direction == "CALL"
                if f['type'] == 'BEARISH_FVG' and cur < f['end_price']: return direction == "PUT"
        return True
    def check_trend_reverse(self, candles, direction):
        return check_trend_reverse(candles, direction)

def analyze_strategy1(candles, min_accuracy=75):
    if not candles or len(candles) < 20: return None, None, None
    closes = [c['close'] for c in candles]; cur = closes[-1]; prev = closes[-2] if len(closes)>1 else cur
    rsi = calculate_rsi(closes, 14)
    direction, conf = None, 0
    if cur > prev and rsi < 70: direction = "CALL"; conf = 70 + (rsi/2)
    elif cur < prev and rsi > 30: direction = "PUT"; conf = 70 + ((100-rsi)/2)
    if direction and conf >= min_accuracy:
        entry_dt = datetime.now(timezone.utc) + timedelta(hours=5)
        entry_dt = entry_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return direction, entry_dt, conf
    return None, None, None

def analyze_strategy2(candles, filters):
    if not candles or len(candles) < max(10,14)+5: return None, None, None
    closes=[c['close'] for c in candles]; cur=closes[-1]
    ema=calculate_ema(closes, 10)
    if ema is None: return None, None, None
    rsi=calculate_rsi(closes, 14)
    direction, score = None, 0
    if cur>ema and 50<rsi<70: direction="CALL"; score=5
    elif cur<ema and 30<rsi<50: direction="PUT"; score=5
    elif rsi>80: direction="PUT"; score=4
    elif rsi<20: direction="CALL"; score=4
    if direction is None: return None, None, None
    if len(closes)>=3:
        recent_up = sum(1 for i in range(-3,0) if closes[i]>closes[i-1])
        if direction=="CALL" and recent_up<2: score-=1
        elif direction=="PUT" and recent_up>1: score-=1
    if score<4: return None, None, None
    if filters.use_trend and not filters.check_trend(candles,direction): return None,None,None
    if filters.use_bollinger and not filters.check_bollinger(candles,direction): return None,None,None
    if filters.use_support_resistance and not filters.check_support_resistance(candles,direction): return None,None,None
    if filters.use_price_action and not filters.check_price_action(candles,direction): return None,None,None
    if filters.use_supertrend and not filters.check_supertrend(candles,direction): return None,None,None
    if filters.use_fvg and not filters.check_fvg(candles,direction): return None,None,None
    if filters.use_trend_reverse and not filters.check_trend_reverse(candles,direction): return None,None,None
    confidence = (score/5)*100
    if confidence < filters.min_accuracy: return None, None, None
    entry_dt = datetime.now(timezone.utc)+timedelta(hours=5)
    entry_dt = entry_dt.replace(second=0, microsecond=0)+timedelta(minutes=1)
    return direction, entry_dt, confidence

def analyze_strategy3(candles, min_accuracy=75, lookback=20):
    if not candles or len(candles) < lookback+5: return None, None, None
    closes=[c['close'] for c in candles]; highs=[c['high'] for c in candles]; lows=[c['low'] for c in candles]
    n=len(closes); wr_vals=[]
    for i in range(n):
        if i<14: wr_vals.append(-50)
        else:
            window=closes[i-13:i+1]; highest=max(window); lowest=min(window)
            wr_vals.append(-50 if highest==lowest else -100*(highest-closes[i])/(highest-lowest))
    start_idx = max(0, n-lookback-2)
    price_highs, price_lows, wr_highs, wr_lows = [], [], [], []
    for i in range(start_idx+2, n-2):
        if highs[i]>highs[i-1] and highs[i]>highs[i-2] and highs[i]>highs[i+1] and highs[i]>highs[i+2]:
            price_highs.append((i,highs[i])); wr_highs.append((i,wr_vals[i]))
        if lows[i]<lows[i-1] and lows[i]<lows[i-2] and lows[i]<lows[i+1] and lows[i]<lows[i+2]:
            price_lows.append((i,lows[i])); wr_lows.append((i,wr_vals[i]))
    direction, confidence = None, 75
    if len(price_lows)>=2 and len(wr_lows)>=2:
        last_pl=price_lows[-1][1]; prev_pl=price_lows[-2][1]; last_wrl=wr_lows[-1][1]; prev_wrl=wr_lows[-2][1]
        if last_pl<prev_pl and last_wrl>prev_wrl: direction="CALL"; confidence+=10 if wr_vals[-1]<-80 else 0
    if len(price_highs)>=2 and len(wr_highs)>=2:
        last_ph=price_highs[-1][1]; prev_ph=price_highs[-2][1]; last_wrh=wr_highs[-1][1]; prev_wrh=wr_highs[-2][1]
        if last_ph>prev_ph and last_wrh<prev_wrh: direction="PUT"; confidence+=10 if wr_vals[-1]>-20 else 0
    if direction is None: return None, None, None
    confidence = min(100, max(50, confidence))
    if confidence < min_accuracy: return None, None, None
    entry_dt = datetime.now(timezone.utc)+timedelta(hours=5)
    entry_dt = entry_dt.replace(second=0, microsecond=0)+timedelta(minutes=1)
    return direction, entry_dt, confidence

def analyze_strategy4(candles, min_accuracy=60):
    if not candles or len(candles) < max(14,8)+5: return None, None, None
    adx, plus_di, minus_di = calculate_adx(candles, 14)
    if adx < 15: return None, None, None
    current_k, current_d = calculate_stochastic(candles, 8, 3)
    prev_k, prev_d = calculate_stochastic(candles[:-1], 8, 3)
    crossover_up = (prev_k <= prev_d and current_k > current_d)
    crossover_down = (prev_k >= prev_d and current_k < current_d)
    is_green = candles[-1]['close'] > candles[-1]['open']; is_red = not is_green
    direction, confidence = None, 65
    if crossover_up and current_k < 30 and is_green: direction = "CALL"; confidence += 10
    elif crossover_down and current_k > 70 and is_red: direction = "PUT"; confidence += 10
    else: return None, None, None
    if adx >= 25: confidence += 5
    confidence = min(95, confidence)
    if confidence < min_accuracy: return None, None, None
    entry_dt = datetime.now(timezone.utc)+timedelta(hours=5)
    entry_dt = entry_dt.replace(second=0, microsecond=0)+timedelta(minutes=1)
    return direction, entry_dt, confidence

# ══════════════ TELEGRAM SENDER (Telethon, for all non‑button messages) ══════════════
class TelegramSender:
    def __init__(self):
        self.client = None
        self.loop = None
        self.ready = False

    def start_with_bot_token(self, api_id, api_hash, bot_token):
        async def init():
            self.client = TelegramClient('finorix_session', api_id, api_hash)
            await self.client.start(bot_token=bot_token)
            self.ready = True
            print(f"{Fore.GREEN}[✓] Telethon ready.{Style.RESET_ALL}")
            while True:
                await asyncio.sleep(60)

        def run_loop():
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(init())
            self.loop.run_forever()

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()
        timeout = 30
        start_time = time.time()
        while not self.ready and time.time() - start_time < timeout:
            time.sleep(0.5)
        if not self.ready:
            raise RuntimeError("Telethon init timeout")

    def _run_async(self, coro, timeout=30):
        if not self.ready:
            return None
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def _build_entities(self, text):
        entities = []
        offset = 0
        for ch in text:
            clen = len(ch.encode('utf-16-le')) // 2
            if ch in PREMIUM_EMOJI_IDS:
                entities.append(TelethonCustomEmoji(offset=offset, length=clen, document_id=PREMIUM_EMOJI_IDS[ch]))
            elif ch in FORMAT2_EMOJI_IDS:
                entities.append(TelethonCustomEmoji(offset=offset, length=clen, document_id=FORMAT2_EMOJI_IDS[ch]))
            offset += clen
        return entities

    def send_message(self, chat_id, text, buttons=None):
        async def _send():
            entities = self._build_entities(text)
            if buttons:
                return await self.client.send_message(chat_id, text, formatting_entities=entities, buttons=buttons)
            return await self.client.send_message(chat_id, text, formatting_entities=entities)
        return self._run_async(_send())

    def edit_message(self, chat_id, msg_id, text, buttons=None):
        async def _edit():
            entities = self._build_entities(text)
            if buttons:
                return await self.client.edit_message(chat_id, msg_id, text, formatting_entities=entities, buttons=buttons)
            return await self.client.edit_message(chat_id, msg_id, text, formatting_entities=entities)
        return self._run_async(_edit())

    def send_file(self, chat_id, file_path, caption):
        async def _send():
            entities = self._build_entities(caption)
            return await self.client.send_file(chat_id, file_path, caption=caption, formatting_entities=entities, force_document=False, supports_streaming=True)
        return self._run_async(_send())

sender = TelegramSender()

# ══════════════ ANIMATED PROGRESS BAR HELPER ══════════════
def progress_bar_text(pct: int) -> str:
    """Return a text progress bar like [████████░░] 75%"""
    filled = int(pct / 10)  # 0‑10 scale for a 10‑block bar
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {pct}%"

# ══════════════ CONFLUENCE ENGINE (Strategy 5) ══════════════
BULL_PATTERNS = {'BULLISH_ENGULFING','HAMMER','BULLISH_HARAMI','MORNING_STAR','THREE_WHITE_SOLDIERS',
                 'BULLISH_PINBAR','TWEEZER_BOTTOM','BULLISH_MARUBOZU'}
BEAR_PATTERNS = {'BEARISH_ENGULFING','SHOOTING_STAR','BEARISH_HARAMI','EVENING_STAR',
                 'THREE_BLACK_CROWS','BEARISH_PINBAR','TWEEZER_TOP','BEARISH_MARUBOZU'}

def cf_calc_ema(prices, period):
    if len(prices) < period: return [None]*len(prices)
    alpha = 2.0/(period+1)
    ema_series = [None]*len(prices)
    ema_series[period-1] = sum(prices[:period])/period
    for i in range(period, len(prices)): ema_series[i] = prices[i]*alpha + ema_series[i-1]*(1-alpha)
    return ema_series

def cf_last_ema(prices, period):
    series = cf_calc_ema(prices, period)
    for v in reversed(series):
        if v is not None: return v
    return None

def cf_calc_rsi(prices, period=14):
    if len(prices) < period+1: return 50.0
    deltas = [prices[i]-prices[i-1] for i in range(1,len(prices))]
    gains = [max(d,0) for d in deltas]; losses = [max(-d,0) for d in deltas]
    avg_g = sum(gains[:period])/period; avg_l = sum(losses[:period])/period
    for i in range(period, len(gains)):
        avg_g = (avg_g*(period-1)+gains[i])/period; avg_l = (avg_l*(period-1)+losses[i])/period
    if avg_l == 0: return 100.0
    rs = avg_g/avg_l; return 100.0 - 100.0/(1+rs)

def cf_calc_macd(prices, fast=12, slow=26, signal=9):
    if len(prices) < slow+signal: return None, None, None
    ema_fast = cf_calc_ema(prices, fast); ema_slow = cf_calc_ema(prices, slow)
    macd_line = []
    for f,s in zip(ema_fast, ema_slow):
        if f is not None and s is not None: macd_line.append(f - s)
        else: macd_line.append(None)
    valid_macd = [v for v in macd_line if v is not None]
    if len(valid_macd) < signal: return None, None, None
    sig_series = cf_calc_ema(valid_macd, signal)
    sig_val = next((v for v in reversed(sig_series) if v is not None), None)
    macd_val = valid_macd[-1]
    if sig_val is None: return None, None, None
    return macd_val, sig_val, macd_val - sig_val

def cf_calc_stoch_rsi(prices, rsi_period=14, stoch_period=14, k=3, d=3):
    needed = rsi_period + stoch_period + max(k,d) + 5
    if len(prices) < needed: return None, None
    rsi_series = [cf_calc_rsi(prices[:i+1], rsi_period) for i in range(rsi_period, len(prices))]
    if len(rsi_series) < stoch_period: return None, None
    k_vals = []
    for i in range(stoch_period-1, len(rsi_series)):
        window = rsi_series[i-stoch_period+1:i+1]; lo, hi = min(window), max(window)
        k_vals.append(50.0 if hi==lo else (rsi_series[i]-lo)/(hi-lo)*100)
    if len(k_vals) < max(k,d): return None, None
    return sum(k_vals[-k:])/k, sum(k_vals[-d:])/d

def cf_calc_bb(prices, period=20, std_mult=2.0):
    if len(prices) < period: return None, None, None, None, None
    window = prices[-period:]; mid = sum(window)/period
    variance = sum((p-mid)**2 for p in window)/period; std = math.sqrt(variance)
    upper = mid + std_mult*std; lower = mid - std_mult*std
    cur = prices[-1]
    pct_b = (cur - lower)/(upper - lower) if (upper-lower) > 0 else 0.5
    bw = (upper-lower)/mid if mid != 0 else 0
    return upper, mid, lower, pct_b, bw

def cf_calc_atr(candles, period=14):
    if len(candles) < period+1: return 0.0
    trs = [max(c['high']-c['low'], abs(c['high']-candles[i-1]['close']), abs(c['low']-candles[i-1]['close']))
           for i in range(1,len(candles))]
    return sum(trs[-period:])/period if len(trs) >= period else sum(trs)/len(trs)

def cf_calc_adx(candles, period=14):
    if len(candles) < period*2: return None, None, None
    asc = sorted(candles, key=lambda x: x['time'])
    plus_dm_list, minus_dm_list, tr_list = [], [], []
    for i in range(1, len(asc)):
        h=float(asc[i]['high']); l=float(asc[i]['low']); ph=float(asc[i-1]['high']); pl=float(asc[i-1]['low']); pc=float(asc[i-1]['close'])
        up_move=h-ph; down_move=pl-l
        plus_dm  = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0
        tr = max(h-l, abs(h-pc), abs(l-pc))
        plus_dm_list.append(plus_dm); minus_dm_list.append(minus_dm); tr_list.append(tr)
    tr14 = sum(tr_list[:period]); pdm14 = sum(plus_dm_list[:period]); mdm14 = sum(minus_dm_list[:period])
    dx_list = []
    plus_di  = 100 * pdm14 / tr14 if tr14 else 0
    minus_di = 100 * mdm14 / tr14 if tr14 else 0
    if plus_di + minus_di: dx_list.append(100 * abs(plus_di - minus_di) / (plus_di + minus_di))
    for i in range(period, len(tr_list)):
        tr14  = tr14  - tr14 /period + tr_list[i]
        pdm14 = pdm14 - pdm14/period + plus_dm_list[i]
        mdm14 = mdm14 - mdm14/period + minus_dm_list[i]
        plus_di  = 100 * pdm14 / tr14 if tr14 else 0
        minus_di = 100 * mdm14 / tr14 if tr14 else 0
        if plus_di + minus_di: dx_list.append(100 * abs(plus_di - minus_di) / (plus_di + minus_di))
    if not dx_list: return None, None, None
    adx = sum(dx_list[-period:]) / min(len(dx_list), period)
    return adx, plus_di, minus_di

def cf_detect_patterns(candles):
    if len(candles) < 5: return []
    patterns = []
    for i in range(2, len(candles)):
        c  = candles[i]; p1 = candles[i-1]; p2 = candles[i-2] if i >= 2 else None
        o, cl, h, l = float(c['open']), float(c['close']), float(c['high']), float(c['low'])
        po, pc1 = float(p1['open']), float(p1['close'])
        body = abs(cl - o); candle_range = h - l
        lower_wick = min(o, cl) - l; upper_wick = h - max(o, cl)
        if body > 0 and candle_range > 0 and body / candle_range > 0.85:
            t = 'BULLISH_MARUBOZU' if cl > o else 'BEARISH_MARUBOZU'
            patterns.append({'type': t, 'index': i, 'strength': 0.85})
        if body > 0 and lower_wick >= 2.5 * body and upper_wick <= 0.4 * body:
            patterns.append({'type': 'HAMMER', 'index': i, 'strength': 0.80})
        if body > 0 and lower_wick >= 3 * body:
            patterns.append({'type': 'BULLISH_PINBAR', 'index': i, 'strength': 0.85})
        if body > 0 and upper_wick >= 2.5 * body and lower_wick <= 0.4 * body:
            patterns.append({'type': 'SHOOTING_STAR', 'index': i, 'strength': 0.80})
        if body > 0 and upper_wick >= 3 * body:
            patterns.append({'type': 'BEARISH_PINBAR', 'index': i, 'strength': 0.85})
        if pc1 < po and cl > o and o <= pc1 and cl >= po:
            patterns.append({'type': 'BULLISH_ENGULFING', 'index': i, 'strength': 0.90})
        if pc1 > po and cl < o and o >= pc1 and cl <= po:
            patterns.append({'type': 'BEARISH_ENGULFING', 'index': i, 'strength': 0.90})
        if po < pc1 and o > pc1 and cl < po:
            patterns.append({'type': 'BULLISH_HARAMI', 'index': i, 'strength': 0.70})
        if po > pc1 and o < pc1 and cl > po:
            patterns.append({'type': 'BEARISH_HARAMI', 'index': i, 'strength': 0.70})
        if p2 and abs(float(p1['high']) - h) < candle_range * 0.05 and cl < o and pc1 > po:
            patterns.append({'type': 'TWEEZER_TOP', 'index': i, 'strength': 0.75})
        if p2 and abs(float(p1['low']) - l) < candle_range * 0.05 and cl > o and pc1 < po:
            patterns.append({'type': 'TWEEZER_BOTTOM', 'index': i, 'strength': 0.75})
        if p2:
            p2o, p2c = float(p2['open']), float(p2['close'])
            doji_p1 = abs(pc1 - po) <= (float(p1['high']) - float(p1['low'])) * 0.3
            if p2c < p2o and doji_p1 and cl > o and cl > (p2o + p2c) / 2:
                patterns.append({'type': 'MORNING_STAR', 'index': i, 'strength': 0.95})
            if p2c > p2o and doji_p1 and cl < o and cl < (p2o + p2c) / 2:
                patterns.append({'type': 'EVENING_STAR', 'index': i, 'strength': 0.95})
        if i >= 2:
            c3 = candles[i-2]; c2 = candles[i-1]; c1 = candles[i]
            if (float(c1['close']) > float(c1['open']) and float(c2['close']) > float(c2['open']) and
                float(c3['close']) > float(c3['open']) and float(c1['close']) > float(c2['close']) > float(c3['close'])):
                patterns.append({'type': 'THREE_WHITE_SOLDIERS', 'index': i, 'strength': 0.90})
            if (float(c1['close']) < float(c1['open']) and float(c2['close']) < float(c2['open']) and
                float(c3['close']) < float(c3['open']) and float(c1['close']) < float(c2['close']) < float(c3['close'])):
                patterns.append({'type': 'THREE_BLACK_CROWS', 'index': i, 'strength': 0.90})
    return patterns

def cf_aggregate_candles(candles, minutes):
    if not candles: return []
    asc = sorted(candles, key=lambda x: x['time'])
    result, group = [], []
    base_time = None
    for c in asc:
        ct = datetime.fromtimestamp(c['time'])
        if base_time is None: base_time = ct; group = [c]
        elif (ct - base_time).total_seconds() < minutes * 60: group.append(c)
        else:
            result.append({'time': group[0]['time'], 'open': float(group[0]['open']),
                           'high': max(float(c['high']) for c in group), 'low': min(float(c['low']) for c in group),
                           'close': float(group[-1]['close'])})
            base_time = ct; group = [c]
    if group:
        result.append({'time': group[0]['time'], 'open': float(group[0]['open']),
                       'high': max(float(c['high']) for c in group), 'low': min(float(c['low']) for c in group),
                       'close': float(group[-1]['close'])})
    return sorted(result, key=lambda x: x['time'], reverse=True)

def cf_htf_direction(candles_htf):
    if not candles_htf or len(candles_htf) < 25: return None
    asc = sorted(candles_htf, key=lambda x: x['time'])
    closes = [float(c['close']) for c in asc]
    e9  = cf_last_ema(closes, 9); e21 = cf_last_ema(closes, 21)
    return "CALL" if (e9 and e21 and e9 > e21) else ("PUT" if e9 and e21 else None)

def cf_run_confluence_engine(candles_1m, candles_5m, candles_15m):
    if len(candles_1m) < 50: return None, 0, {}
    asc = sorted(candles_1m, key=lambda x: x['time'])
    closes = [float(c['close']) for c in asc]
    details = {}; votes_call, votes_put = 0, 0

    e9 = cf_last_ema(closes, 9); e21 = cf_last_ema(closes, 21); e50 = cf_last_ema(closes, 50); e200 = cf_last_ema(closes, 200)
    cur = closes[-1]
    ema_score, ema_dir = 0, None
    if e9 and e21 and e50:
        if cur > e9 > e21 > e50: ema_score, ema_dir = 18, "CALL"
        elif cur < e9 < e21 < e50: ema_score, ema_dir = 18, "PUT"
        elif cur > e21 and e9 > e21: ema_score, ema_dir = 10, "CALL"
        elif cur < e21 and e9 < e21: ema_score, ema_dir = 10, "PUT"
    if ema_dir == "CALL": votes_call += ema_score
    elif ema_dir == "PUT": votes_put += ema_score
    details['EMA_stack'] = {'dir': ema_dir, 'score': ema_score}

    e200_dir = None
    if e200:
        if cur > e200: e200_dir = "CALL"; votes_call += 8
        else: e200_dir = "PUT"; votes_put += 8
    details['EMA200'] = {'dir': e200_dir}

    macd_val, sig_val, hist = cf_calc_macd(closes)
    macd_dir, macd_score = None, 0
    if macd_val is not None:
        if macd_val > sig_val and hist > 0: macd_dir, macd_score = "CALL", 16 if macd_val > 0 else 10
        elif macd_val < sig_val and hist < 0: macd_dir, macd_score = "PUT", 16 if macd_val < 0 else 10
    if macd_dir == "CALL": votes_call += macd_score
    elif macd_dir == "PUT": votes_put += macd_score
    details['MACD'] = {'dir': macd_dir, 'score': macd_score}

    rsi = cf_calc_rsi(closes, 14)
    rsi_dir, rsi_score = None, 0
    if rsi < 35: rsi_dir, rsi_score = "CALL", 12
    elif rsi > 65: rsi_dir, rsi_score = "PUT", 12
    elif 40 <= rsi <= 50: rsi_dir, rsi_score = "CALL", 6
    elif 50 < rsi <= 60: rsi_dir, rsi_score = "PUT", 6
    if rsi_dir == "CALL": votes_call += rsi_score
    elif rsi_dir == "PUT": votes_put += rsi_score
    details['RSI'] = {'dir': rsi_dir, 'rsi': round(rsi,2)}

    k_val, d_val = cf_calc_stoch_rsi(closes)
    stoch_dir, stoch_score = None, 0
    if k_val is not None:
        if k_val < 20 and d_val < 20 and k_val > d_val: stoch_dir, stoch_score = "CALL", 10
        elif k_val > 80 and d_val > 80 and k_val < d_val: stoch_dir, stoch_score = "PUT", 10
        elif k_val < 50 and k_val > d_val: stoch_dir, stoch_score = "CALL", 5
        elif k_val > 50 and k_val < d_val: stoch_dir, stoch_score = "PUT", 5
    if stoch_dir == "CALL": votes_call += stoch_score
    elif stoch_dir == "PUT": votes_put += stoch_score
    details['StochRSI'] = {'dir': stoch_dir, 'K': round(k_val,2) if k_val else None, 'D': round(d_val,2) if d_val else None}

    bb_upper, bb_mid, bb_lower, pct_b, bw = cf_calc_bb(closes, 20, 2.0)
    bb_dir, bb_score = None, 0
    if pct_b is not None:
        if pct_b < 0.05: bb_dir, bb_score = "CALL", 10
        elif pct_b > 0.95: bb_dir, bb_score = "PUT", 10
        elif pct_b < 0.30: bb_dir, bb_score = "CALL", 5
        elif pct_b > 0.70: bb_dir, bb_score = "PUT", 5
    if bw is None or bw < 0.0015: bb_dir, bb_score = None, 0
    if bb_dir == "CALL": votes_call += bb_score
    elif bb_dir == "PUT": votes_put += bb_score
    details['BB'] = {'dir': bb_dir, 'pct_b': round(pct_b,3) if pct_b else None}

    adx_val, plus_di, minus_di = cf_calc_adx(asc, 14)
    adx_dir, adx_score = None, 0
    if adx_val is not None and adx_val >= 18:
        if plus_di > minus_di: adx_dir, adx_score = "CALL", 8
        else: adx_dir, adx_score = "PUT", 8
    if adx_dir == "CALL": votes_call += adx_score
    elif adx_dir == "PUT": votes_put += adx_score
    details['ADX'] = {'dir': adx_dir, 'adx': round(adx_val,2) if adx_val else None}

    patterns = cf_detect_patterns(asc[-15:])
    recent_patterns = [p for p in patterns if p['index'] >= len(asc[-15:]) - 3]
    pat_dir, pat_score, best_strength = None, 0, 0
    for p in recent_patterns:
        if p['strength'] > best_strength:
            if p['type'] in BULL_PATTERNS: pat_dir, best_strength = "CALL", p['strength']
            elif p['type'] in BEAR_PATTERNS: pat_dir, best_strength = "PUT", p['strength']
    if pat_dir: pat_score = int(best_strength * 12)
    if pat_dir == "CALL": votes_call += pat_score
    elif pat_dir == "PUT": votes_put += pat_score
    details['Pattern'] = {'dir': pat_dir, 'score': pat_score, 'patterns': [p['type'] for p in recent_patterns]}

    htf_dir, htf_score = None, 0
    results_5m = cf_htf_direction(candles_5m); results_15m = cf_htf_direction(candles_15m)
    if results_5m and results_15m:
        htf_dir, htf_score = (results_5m, 10) if results_5m == results_15m else (results_5m, 5)
    elif results_5m: htf_dir, htf_score = results_5m, 5
    if htf_dir == "CALL": votes_call += htf_score
    elif htf_dir == "PUT": votes_put += htf_score
    details['HTF'] = {'dir': htf_dir, 'score': htf_score}

    mom_dir, mom_score = None, 0
    if len(asc) >= 5:
        last5 = asc[-5:]
        bull_count = sum(1 for c in last5 if float(c['close']) > float(c['open']))
        if bull_count >= 4: mom_dir, mom_score = "CALL", 6
        elif bull_count <= 1: mom_dir, mom_score = "PUT", 6
        elif bull_count == 3: mom_dir, mom_score = "CALL", 3
        elif bull_count == 2: mom_dir, mom_score = "PUT", 3
    if mom_dir == "CALL": votes_call += mom_score
    elif mom_dir == "PUT": votes_put += mom_score
    details['Momentum'] = {'dir': mom_dir, 'score': mom_score}

    total = votes_call + votes_put
    if total == 0: return None, 0, details
    dominant, raw_score = ("CALL", (votes_call / total) * 100) if votes_call >= votes_put else ("PUT", (votes_put / total) * 100)
    details['votes_call'] = votes_call; details['votes_put'] = votes_put; details['raw_score'] = round(raw_score, 1)

    if dominant == "CALL" and rsi > 75: return None, 0, {**details, 'reject': 'RSI_OVERBOUGHT'}
    if dominant == "PUT" and rsi < 35: return None, 0, {**details, 'reject': 'RSI_OVERSOLD'}
    if adx_val is not None and adx_val < 18 * 0.7: return None, 0, {**details, 'reject': 'ADX_WEAK_MARKET'}
    return dominant, raw_score, details

def analyze_strategy5(candles, min_accuracy=72):
    if not candles or len(candles) < 50: return None, None, None
    candles_5m = cf_aggregate_candles(candles, 5); candles_15m = cf_aggregate_candles(candles, 15)
    direction, score, details = cf_run_confluence_engine(candles, candles_5m, candles_15m)
    if direction is None or score < min_accuracy: return None, None, None
    entry_dt = datetime.now(timezone.utc) + timedelta(hours=5)
    entry_dt = entry_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return direction, entry_dt, score
    return direction, entry_dt, conf

# ══════════════ INSTITUTIONAL REJECTION & ORDER FLOW (IROF) – STRATEGY 6 ══════════════
def detect_liquidity_sweep(candles, lookback=20):
    if len(candles) < lookback + 1:
        return False, False, None, None
    highs = [c['high'] for c in candles[-lookback-1:]]
    lows  = [c['low'] for c in candles[-lookback-1:]]
    closes = [c['close'] for c in candles[-lookback-1:]]
    recent_high = max(highs[:-1])
    recent_low  = min(lows[:-1])
    cur_high, cur_low, cur_close = highs[-1], lows[-1], closes[-1]
    bearish_sweep = (cur_high > recent_high) and (cur_close < recent_high)
    bullish_sweep = (cur_low < recent_low) and (cur_close > recent_low)
    return bearish_sweep, bullish_sweep, recent_high if bearish_sweep else None, recent_low if bullish_sweep else None

def detect_order_block(candles, sweep_type='BEARISH'):
    """Find the last opposite candle before a sweep (Order Block)."""
    if len(candles) < 3:
        return None
    if sweep_type == 'BEARISH':
        # Last bullish candle before the sweep
        for i in range(-2, -len(candles), -1):
            if candles[i]['close'] > candles[i]['open']:
                return {'high': candles[i]['high'], 'low': candles[i]['low']}
    else:
        # Last bearish candle before the sweep
        for i in range(-2, -len(candles), -1):
            if candles[i]['close'] < candles[i]['open']:
                return {'high': candles[i]['high'], 'low': candles[i]['low']}
    return None

def wick_rejection_strength(candle, sweep_type='BEARISH'):
    """Return how strong the rejection wick is (ratio of wick to body)."""
    body = abs(candle['close'] - candle['open'])
    if body == 0:
        return 0
    if sweep_type == 'BEARISH':
        upper_wick = candle['high'] - max(candle['open'], candle['close'])
        return upper_wick / body
    else:
        lower_wick = min(candle['open'], candle['close']) - candle['low']
        return lower_wick / body

def detect_fvg(candles):
    if len(candles) < 3:
        return False, False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    bullish = (c2['low'] > c1['high']) and (c3['close'] < c2['low'])
    bearish = (c2['high'] < c1['low']) and (c3['close'] > c2['high'])
    return bullish, bearish

def analyze_strategy6(candles, min_score=20, min_candles=10):
    if len(candles) < min_candles:
        return None, None, None

    closes = [c['close'] for c in candles]

    # Trend bias (last 2 candles)
    trend_bias = "BULLISH" if closes[-1] > closes[-2] else "BEARISH"

    # Sweep detection
    bear_sweep, bull_sweep, _, _ = detect_liquidity_sweep(candles)

    call_score = 0
    put_score  = 0

    # Sweep alone gives 40 points
    if bear_sweep:
        put_score += 40
    if bull_sweep:
        call_score += 40

    # Any wick (ratio ≥ 1.2) adds points
    candle = candles[-1]
    body = abs(candle['close'] - candle['open'])
    if body > 0:
        upper_wick = candle['high'] - max(candle['open'], candle['close'])
        lower_wick = min(candle['open'], candle['close']) - candle['low']
        if upper_wick / body >= 1.2:
            put_score += 30
        if lower_wick / body >= 1.2:
            call_score += 30

    # Trend bias (small bonus)
    if trend_bias == "BEARISH":
        put_score += 10
    else:
        call_score += 10

    # FVG bonus
    bull_fvg, bear_fvg = detect_fvg(candles)
    if bear_fvg:
        put_score += 15
    if bull_fvg:
        call_score += 15

    if call_score >= min_score and call_score > put_score:
        direction = "CALL"
        conf = call_score
    elif put_score >= min_score and put_score > call_score:
        direction = "PUT"
        conf = put_score
    else:
        return None, None, None

    entry_dt = datetime.now(timezone.utc) + timedelta(hours=5)
    entry_dt = entry_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return direction, entry_dt, conf

# ══════════════ CHART DRAWING (SMZX PRO) ══════════════
STRATEGY_NAMES = {1:"RSI basic",2:"EMA filtered",3:"WR divergence",
                  4:"ADX stochastic",5:"ultra accurate",6:"IROF pro"}

def get_system_font(size, bold=False):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/system/fonts/Roboto-Bold.ttf" if bold else "/system/fonts/Roboto-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path): return ImageFont.truetype(path, size)
    try: return ImageFont.truetype("arial.ttf", size) if os.path.exists("arial.ttf") else ImageFont.load_default()
    except: return ImageFont.load_default()

def _fmt_pair(pair):
    return pair.replace("_OTC"," (OTC)").replace("_"," ")

def _chart_base(W, H):
    C = dict(
        BG=(13,17,23), SIDEBAR_BG=(15,19,27), HEADER_BG=(10,13,18),
        CANDLE_GREEN=(0,210,130), CANDLE_RED=(234,57,67),
        WICK_GREEN=(0,170,105), WICK_RED=(200,50,58),
        EMA9=(0,215,255), EMA21=(105,155,255), EMA56=(155,115,215),
        GRID=(28,36,48), TXT_GRAY=(120,130,148), TXT_WHITE=(228,233,242),
        GREEN=(0,235,110), RED=(255,70,90), CYAN=(0,215,255),
        YGREEN=(175,255,55), SEC_HDR=(95,108,128), SB_BORDER=(35,48,62),
        BRAND_CYAN=(0,225,255),
    )
    img = Image.new('RGB', (W, H), C['BG'])
    return img, C

def _draw_pro_body(img, draw, candles, pair, W, H, C, wins, losses, strategy, martingale_steps,
                   header_extra="", sidebar_top_section=None, entry_idx=None, second_idx=None,
                   result_type=None, direction=None, confidence=80, entry_time_str=""):
    SIDEBAR_W = 310; HEADER_H = 44; CHART_LEFT = 80
    CHART_RIGHT = W - SIDEBAR_W - 20; CHART_TOP = 70; CHART_BOTTOM = H - 225
    EMA_LEGEND_Y = CHART_BOTTOM + 15; VOLUME_TOP = CHART_BOTTOM + 45
    VOLUME_BOTTOM = H - 40; TIME_Y = H - 30

    f_header = get_system_font(18, True); f_price = get_system_font(13)
    f_small = get_system_font(11); f_sidebar_ttl = get_system_font(13)
    f_sidebar_lbl = get_system_font(14); f_sidebar_val = get_system_font(14, True)
    f_ema = get_system_font(12, True); f_vol = get_system_font(12)
    f_time = get_system_font(11); f_brand = get_system_font(22, True)
    f_brand_sm = get_system_font(12); f_badge = get_system_font(14, True)
    f_hl = get_system_font(11); f_conf = get_system_font(18, True)
    f_marker = get_system_font(12, True)

    n_disp = min(50, len(candles)); display = candles[-n_disp:]; n = len(display)
    closes = [float(c['close']) for c in display]
    opens  = [float(c['open'])  for c in display]
    highs  = [float(c['high'])  for c in display]
    lows   = [float(c['low'])   for c in display]
    vols   = [float(c.get('volume',1)) for c in display]

    p_min = min(lows); p_max = max(highs); p_rng = p_max - p_min or 0.0001
    pad = p_rng * 0.08; p_min -= pad; p_max += pad; p_rng = p_max - p_min

    all_cl = [float(c['close']) for c in candles]
    si = len(candles) - n
    ema9  = cf_calc_ema(all_cl, 9)[si:]
    ema21 = cf_calc_ema(all_cl, 21)[si:]
    ema56 = cf_calc_ema(all_cl, 56)[si:]

    sample = f"{p_max:.10f}".rstrip('0')
    dp = max(2, min(len(sample.split('.')[1]) if '.' in sample else 2, 5))

    chart_w = CHART_RIGHT - CHART_LEFT; chart_h = CHART_BOTTOM - CHART_TOP
    def p2y(p): return int(CHART_TOP + chart_h - ((p - p_min) / p_rng) * chart_h)
    ctw = chart_w / n; cbw = max(4, int(ctw * 0.55)); cgap = (ctw - cbw) / 2
    def cx(i):  return int(CHART_LEFT + i * ctw + cgap)
    def ccx(i): return int(CHART_LEFT + i * ctw + ctw / 2)

    current_price = closes[-1]

    # HEADER
    draw.rectangle([0, 0, W, HEADER_H], fill=C['HEADER_BG'])
    draw.line([(0, HEADER_H), (W, HEADER_H)], fill=C['SB_BORDER'], width=1)
    now_pk = datetime.now(timezone.utc) + timedelta(hours=5)
    hdr_pair = _fmt_pair(pair)
    hdr_txt = f"SMZX PRO    {hdr_pair}    {header_extra}    {now_pk.strftime('%Y.%m.%d')}    {entry_time_str}:00"
    hw = draw.textlength(hdr_txt, font=f_header)
    draw.text(((W - hw) / 2, 12), hdr_txt, fill=C['TXT_WHITE'], font=f_header)

    # GRID
    mag = 10 ** (-dp); raw_step = p_rng / 8
    p_step = max(mag, round(raw_step / mag) * mag)
    gp = math.floor(p_min / p_step) * p_step
    while gp <= p_max + p_step:
        if p_min <= gp <= p_max:
            y = p2y(gp)
            if CHART_TOP < y < CHART_BOTTOM:
                for xx in range(CHART_LEFT, CHART_RIGHT, 8):
                    draw.line([(xx, y), (min(xx+4, CHART_RIGHT), y)], fill=C['GRID'], width=1)
                draw.text((8, y-7), f"{gp:.{dp}f}", fill=C['TXT_GRAY'], font=f_price)
        gp += p_step

    real_hi = max(highs); real_lo = min(lows)
    draw.text((CHART_LEFT+5, CHART_TOP+2), f"H: {real_hi:.{min(2,dp)}f}", fill=C['TXT_GRAY'], font=f_hl)
    draw.text((CHART_LEFT+5, CHART_BOTTOM-18), f"L: {real_lo:.{min(2,dp)}f}", fill=C['TXT_GRAY'], font=f_hl)

    # CANDLESTICKS
    for i in range(n):
        x = cx(i); cxx = ccx(i)
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        green = c >= o
        bcol = C['CANDLE_GREEN'] if green else C['CANDLE_RED']
        wcol = C['WICK_GREEN'] if green else C['WICK_RED']
        bt = p2y(max(o,c)); bb = p2y(min(o,c)); wt = p2y(h); wb = p2y(l)
        if bb - bt < 1: bb = bt + 1
        draw.line([(cxx, wt), (cxx, wb)], fill=wcol, width=2)
        draw.rectangle([x, bt, x+cbw, bb], fill=bcol)

    # EMA LINES
    def draw_ema(vals, color, w=2):
        pts = [(ccx(i), p2y(vals[i])) for i in range(n) if vals[i] is not None and p_min <= vals[i] <= p_max]
        for j in range(len(pts)-1): draw.line([pts[j], pts[j+1]], fill=color, width=w)
    draw_ema(ema56, C['EMA56']); draw_ema(ema21, C['EMA21']); draw_ema(ema9, C['EMA9'])

    # ENTRY GLOW (signal chart) or RESULT MARKERS
    if result_type is None and direction:
        last_cxv = ccx(n-1); glow_half = 25
        glow_img = Image.new('RGBA', (W, H), (0,0,0,0)); gd = ImageDraw.Draw(glow_img)
        for dx in range(-glow_half, glow_half+1):
            a = int(55 * (1 - abs(dx)/glow_half)**2)
            gd.line([(last_cxv+dx, CHART_TOP), (last_cxv+dx, CHART_BOTTOM)], fill=(0,220,180,a), width=1)
        img.paste(Image.alpha_composite(Image.new('RGBA',(W,H),(0,0,0,0)), glow_img).convert('RGB'), (0,0), glow_img.split()[3])
        draw = ImageDraw.Draw(img)
        i = n-1; x = cx(i); cxx = ccx(i)
        o,h,l,c = opens[i],highs[i],lows[i],closes[i]; green = c>=o
        bcol = C['CANDLE_GREEN'] if green else C['CANDLE_RED']
        wcol = C['WICK_GREEN'] if green else C['WICK_RED']
        bt = p2y(max(o,c)); bb = p2y(min(o,c))
        if bb-bt<1: bb=bt+1
        draw.line([(cxx,p2y(h)),(cxx,p2y(l))],fill=wcol,width=2)
        draw.rectangle([x,bt,x+cbw,bb],fill=bcol)
        btxt = direction; btw = draw.textlength(btxt, font=f_badge)+24; bh=30
        if direction=="CALL":
            by = p2y(lows[n-1])+15; bcl=(0,185,85)
            draw.polygon([(last_cxv,by-22),(last_cxv-7,by-12),(last_cxv+7,by-12)],fill=C['TXT_WHITE'])
        else:
            by = p2y(highs[n-1])-bh-15; bcl=(220,55,65)
            draw.polygon([(last_cxv,by+bh+22),(last_cxv-7,by+bh+12),(last_cxv+7,by+bh+12)],fill=C['TXT_WHITE'])
        bx = int(last_cxv - btw/2)
        draw.rounded_rectangle([bx,by,bx+int(btw),by+bh], radius=6, fill=bcl)
        tw_i = draw.textlength(btxt, font=f_badge)
        draw.text((bx+(int(btw)-tw_i)/2, by+6), btxt, fill=C['TXT_WHITE'], font=f_badge)

    # RESULT MARKERS
    if result_type is not None and entry_idx is not None:
        def _mark(idx, mtype):
            x = cx(idx); cxx = ccx(idx)
            h_v = highs[idx]; l_v = lows[idx]
            yt = p2y(h_v); yb = p2y(l_v)
            oc = C['GREEN'] if mtype=='win' else C['RED']
            sym = "W" if mtype=='win' else "L"
            gw = 15
            gi = Image.new('RGBA',(W,H),(0,0,0,0)); gdraw = ImageDraw.Draw(gi)
            for dx in range(-gw, gw+1):
                a = int(40*(1-abs(dx)/gw)**2)
                gc = (0,200,100,a) if mtype=='win' else (200,50,50,a)
                gdraw.line([(cxx+dx,yt-5),(cxx+dx,yb+5)],fill=gc,width=1)
            img.paste(Image.alpha_composite(Image.new('RGBA',(W,H),(0,0,0,0)),gi).convert('RGB'),(0,0),gi.split()[3])
            draw_fresh = ImageDraw.Draw(img)
            draw_fresh.text((cxx-5, yt-20), sym, fill=oc, font=f_marker)
            return draw_fresh
        if result_type == "WIN":
            draw = _mark(entry_idx, 'win')
        elif result_type == "LOSS":
            draw = _mark(entry_idx, 'loss')
        elif result_type == "MTG WIN":
            draw = _mark(entry_idx, 'loss')
            if second_idx is not None:
                draw = _mark(second_idx, 'win')
                x1 = ccx(entry_idx); x2 = ccx(second_idx)
                ya = p2y(max(highs[entry_idx],highs[second_idx]))-28
                draw.line([(x1,ya),(x2,ya)],fill=(255,215,0),width=2)
                draw.polygon([(x2,ya),(x2-6,ya-5),(x2-6,ya+5)],fill=(255,215,0))
                mtw = draw.textlength("MTG",font=f_small)
                draw.text(((x1+x2)/2-mtw/2, ya-16),"MTG",fill=(255,215,0),font=f_small)

    # CURRENT PRICE LINE
    cp_y = p2y(current_price)
    for xx in range(CHART_LEFT, CHART_RIGHT, 12):
        draw.line([(xx,cp_y),(min(xx+6,CHART_RIGHT),cp_y)],fill=(85,95,115),width=1)
    cp_txt = f"{current_price:.{dp}f}"
    cp_tw = draw.textlength(cp_txt, font=f_price)+14
    tag_x = CHART_RIGHT - int(cp_tw) - 2
    draw.rounded_rectangle([tag_x, cp_y-11, tag_x+int(cp_tw), cp_y+11],
                           radius=3, fill=(18,28,45), outline=C['CYAN'], width=1)
    draw.text((tag_x+7, cp_y-7), cp_txt, fill=C['CYAN'], font=f_price)

    # EMA LEGEND
    draw.text((CHART_LEFT, EMA_LEGEND_Y), "EMA 9", fill=C['EMA9'], font=f_ema)
    draw.text((CHART_LEFT+85, EMA_LEGEND_Y), "EMA 21", fill=C['EMA21'], font=f_ema)
    draw.text((CHART_LEFT+180, EMA_LEGEND_Y), "EMA 56", fill=C['EMA56'], font=f_ema)

    # VOLUME
    draw.line([(CHART_LEFT, VOLUME_TOP-8),(CHART_RIGHT, VOLUME_TOP-8)],fill=C['GRID'],width=1)
    draw.text((20, VOLUME_TOP-4),"VOL",fill=C['TXT_GRAY'],font=f_vol)
    vol_h = VOLUME_BOTTOM - VOLUME_TOP; mx_vol = max(vols) if vols else 1
    for i in range(n):
        x = cx(i); v = vols[i]; bh = max(2, int((v/mx_vol)*vol_h*0.8))
        green = closes[i] >= opens[i]
        out_c = C['CANDLE_GREEN'] if green else C['CANDLE_RED']
        fill_c = (0,100,65) if green else (120,35,42)
        bt = VOLUME_BOTTOM - bh
        draw.rectangle([x, bt, x+cbw, VOLUME_BOTTOM], outline=out_c, width=1)
        if bh > 2: draw.rectangle([x+1, bt+1, x+cbw-1, VOLUME_BOTTOM-1], fill=fill_c)

    # TIME LABELS
    step = max(1, n // 9)
    for i in range(0, n, step):
        ts = ""
        if 'time' in display[i]:
            try: ts = (datetime.fromtimestamp(display[i]['time'])+timedelta(hours=5)).strftime("%H:%M")
            except: pass
        if ts:
            tw_t = draw.textlength(ts, font=f_time)
            draw.text((ccx(i)-tw_t/2, TIME_Y), ts, fill=C['TXT_GRAY'], font=f_time)

    # VOL % LABEL
    vol_chg = abs((vols[-1]-vols[-2])/vols[-2]*100) if len(vols)>=2 and vols[-2]>0 else 0
    draw.text((CHART_LEFT+5, CHART_TOP-15), f"VOL {vol_chg:.2f}%", fill=C['GREEN'], font=f_small)

    # CONFIDENCE BADGE
    cb_txt = f"{confidence:.0f}%"; cb_x = CHART_RIGHT-65; cb_y = CHART_TOP-8
    draw.polygon([(cb_x+18,cb_y),(cb_x+6,cb_y+20),(cb_x+30,cb_y+20)],fill=C['YGREEN'])
    draw.text((cb_x+36, cb_y+1), cb_txt, fill=C['YGREEN'], font=f_conf)

    # RIGHT SIDEBAR
    sb_x = W - SIDEBAR_W
    draw.rectangle([sb_x, HEADER_H, W, H], fill=C['SIDEBAR_BG'])
    draw.line([(sb_x, HEADER_H),(sb_x, H)], fill=C['SB_BORDER'], width=1)
    lbl_x = sb_x+22; val_x = W-22
    sb_cx = sb_x + SIDEBAR_W//2
    dir_color = C['GREEN'] if direction == "CALL" else C['RED']

    def sb_row(y, label, value, vcol=C['TXT_WHITE']):
        draw.text((lbl_x, y), label, fill=C['TXT_GRAY'], font=f_sidebar_lbl)
        vw = draw.textlength(str(value), font=f_sidebar_val)
        draw.text((val_x-vw, y), str(value), fill=vcol, font=f_sidebar_val)

    # Top section (SIGNAL or RESULT)
    rh = 30
    if sidebar_top_section:
        sy = HEADER_H + 28
        shdr = sidebar_top_section['title']
        shw = draw.textlength(shdr, font=f_sidebar_ttl)
        draw.text((sb_cx-shw/2, sy), shdr, fill=C['SEC_HDR'], font=f_sidebar_ttl)
        draw.line([(sb_x+18, sy+22),(W-18, sy+22)], fill=C['SB_BORDER'], width=1)
        ry = sy + 38
        for i, (lbl, val, col) in enumerate(sidebar_top_section['rows']):
            sb_row(ry + i*rh, lbl, val, col)
    else:
        sy = HEADER_H + 28
        shdr = "\u2014 SIGNAL \u2014"
        shw = draw.textlength(shdr, font=f_sidebar_ttl)
        draw.text((sb_cx-shw/2, sy), shdr, fill=C['SEC_HDR'], font=f_sidebar_ttl)
        draw.line([(sb_x+18, sy+22),(W-18, sy+22)], fill=C['SB_BORDER'], width=1)
        ry = sy + 38
        sb_row(ry, "Direction", direction or "", dir_color)
        sb_row(ry+rh, "Confidence", f"{confidence:.1f}%", C['TXT_WHITE'])
        sb_row(ry+rh*2, "Price", f"{current_price:.{min(4,dp)}f}", C['TXT_WHITE'])
        sb_row(ry+rh*3, "Time", entry_time_str, C['TXT_WHITE'])

    # PERFORMANCE
    py = sy + rh*4 + 56
    phdr = "\u2014 PERFORMANCE \u2014"
    phw = draw.textlength(phdr, font=f_sidebar_ttl)
    draw.text((sb_cx-phw/2, py), phdr, fill=C['SEC_HDR'], font=f_sidebar_ttl)
    draw.line([(sb_x+18, py+22),(W-18, py+22)], fill=C['SB_BORDER'], width=1)
    total = wins + losses; wr = (wins/total*100) if total>0 else 0
    pry = py + 38
    sb_row(pry, "Win Rate", f"{wr:.1f}%", C['GREEN'])
    bar_x = lbl_x; bar_y = pry+rh; bar_w = SIDEBAR_W-44; bar_h = 14
    draw.rounded_rectangle([bar_x, bar_y, bar_x+bar_w, bar_y+bar_h], radius=4, fill=(28,38,52))
    filled = int(bar_w * wr / 100)
    if filled > 0:
        draw.rounded_rectangle([bar_x, bar_y, bar_x+filled, bar_y+bar_h], radius=4, fill=C['GREEN'])
    sb_row(pry+rh+22, "Wins", str(wins), C['GREEN'])
    sb_row(pry+rh*2+22, "Losses", str(losses), C['RED'])
    sb_row(pry+rh*3+22, "Streak", f"{wins}W/{losses}L", C['TXT_WHITE'])

    # SESSION
    ssy = pry + rh*4 + 52
    ss_hdr = "\u2014 SESSION \u2014"
    ssw = draw.textlength(ss_hdr, font=f_sidebar_ttl)
    draw.text((sb_cx-ssw/2, ssy), ss_hdr, fill=C['SEC_HDR'], font=f_sidebar_ttl)
    draw.line([(sb_x+18, ssy+22),(W-18, ssy+22)], fill=C['SB_BORDER'], width=1)
    sry = ssy + 38
    sb_row(sry, "Signals", str(max(1, total)), C['TXT_WHITE'])
    sb_row(sry+rh, "Pair", _fmt_pair(pair), C['CYAN'])
    sb_row(sry+rh*2, "Mode", STRATEGY_NAMES.get(strategy, "auto"), C['GREEN'])
    sb_row(sry+rh*3, "Martingale", f"{martingale_steps} Step(s)", C['TXT_WHITE'])

    # BRANDING
    br_w, br_h = 260, 68; br_x = W-br_w-28; br_y = H-br_h-18
    draw.rounded_rectangle([br_x, br_y, br_x+br_w, br_y+br_h],
                           radius=8, fill=(11,15,21), outline=(38,52,72), width=1)
    bt_txt = "SMZX PRO"; btw2 = draw.textlength(bt_txt, font=f_brand)
    draw.text((br_x+(br_w-btw2)/2, br_y+12), bt_txt, fill=C['BRAND_CYAN'], font=f_brand)
    cr_txt = "\u2666 @Rohailtrader \u2666"; ctw2 = draw.textlength(cr_txt, font=f_brand_sm)
    draw.text((br_x+(br_w-ctw2)/2, br_y+42), cr_txt, fill=C['TXT_GRAY'], font=f_brand_sm)


def draw_neon_chart(candles, pair, trade_time, direction, payout,
                    confidence=80, wins=0, losses=0, strategy=1, martingale_steps=1):
    W, H = 1560, 780
    img, C = _chart_base(W, H)
    draw = ImageDraw.Draw(img)
    arrow = "\u25b2" if direction == "CALL" else "\u25bc"
    hdr_extra = f"{arrow} {direction} {confidence:.1f}%"
    _draw_pro_body(img, draw, candles, pair, W, H, C,
                   wins=wins, losses=losses, strategy=strategy,
                   martingale_steps=martingale_steps,
                   header_extra=hdr_extra, direction=direction,
                   confidence=confidence, entry_time_str=trade_time)
    path = f"smzx_chart_{uuid.uuid4().hex[:8]}.png"
    img.save(path, quality=100, subsampling=0)
    return path


def draw_result_chart(candles, pair, payout, result_type, entry_candle, second_candle=None,
                      wins=0, losses=0, strategy=1, confidence=80, direction=None, entry_time_str=""):
    W, H = 1560, 780
    img, C = _chart_base(W, H)
    draw = ImageDraw.Draw(img)

    result_display = "WIN" if "WIN" in result_type else "LOSS"
    result_color = C['GREEN'] if "WIN" in result_type else C['RED']
    hdr_extra = f"RESULT: {result_display}    PAYOUT: {payout}%"

    n_disp = min(50, len(candles)); display = candles[-n_disp:]
    entry_idx = None; second_idx = None
    for i, c in enumerate(display):
        if 'time' in c and 'time' in entry_candle and c['time'] == entry_candle['time']:
            entry_idx = i
        if second_candle and 'time' in c and 'time' in second_candle and c['time'] == second_candle['time']:
            second_idx = i
    if entry_idx is None:
        entry_idx = len(display) - 1

    sidebar_top = {
        'title': "\u2014 RESULT \u2014",
        'rows': [
            ("Result", result_display, result_color),
            ("Direction", direction or "", C['GREEN'] if direction == "CALL" else C['RED']),
            ("Payout", f"{payout}%", C['TXT_WHITE']),
            ("Time", entry_time_str, C['TXT_WHITE']),
        ]
    }

    _draw_pro_body(img, draw, candles, pair, W, H, C,
                   wins=wins, losses=losses, strategy=strategy,
                   martingale_steps=1, header_extra=hdr_extra,
                   sidebar_top_section=sidebar_top,
                   entry_idx=entry_idx, second_idx=second_idx,
                   result_type=result_type, direction=direction,
                   confidence=confidence, entry_time_str=entry_time_str)
    path = f"smzx_result_{uuid.uuid4().hex[:8]}.png"
    img.save(path, quality=100, subsampling=0)
    return path

# ══════════════ SMZXBot (animated progress, premium emojis, Telethon for all) ══════════════
LIVE_PAIRS = ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","EURJPY","GBPJPY","EURAUD","GBPCAD","AUDJPY","NZDJPY","EURCHF","GBPCHF"]
DEFAULT_OTC_PAIRS = ["USDBDT_OTC","USDARS_OTC","USDINR_OTC","USDMXN_OTC","USDNGN_OTC","USDEGP_OTC",
                     "USDPKR_OTC","USDIDR_OTC","BRLUSD_OTC","NZDUSD_OTC","EURNZD_OTC","FB_OTC",
                     "NZDCAD_OTC","CADCHF_OTC","NZDCHF_OTC","AUDNZD_OTC","BTCUSD_OTC","MSFT_OTC",
                     "XAUUSD_OTC","JNJ_OTC","MCD_OTC","USDCHF_OTC","EURCHF_OTC","EURCAD_OTC","USDDZD_OTC"]

class SMZXBot:
    def __init__(self, uid):
        self.uid = uid
        st = get_state(uid)
        self.market_type = st.market_type
        self.pairs = st.pairs if st.pairs else DEFAULT_OTC_PAIRS.copy()
        self.base_url = "https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={}&interval=1m&limit=600:qx_vzwz3wsu54chx8zmxpt0vp1yfk9gkxv0"
        self.telegram_format = st.telegram_format
        self.strategy = st.strategy
        self.strategy2_filters = st.strategy2_filters if st.strategy2_filters else Strategy2Filters()
        self.strategy3_min_accuracy = st.strategy3_min_accuracy
        self.strategy3_lookback = st.strategy3_lookback
        self.strategy4_min_accuracy = st.strategy4_min_accuracy
        self.strategy5_min_score = st.strategy5_min_score
        # Strategy 6 additions
        self.strategy6_min_score = st.strategy6_min_score
        self.strategy6_min_candles = st.strategy6_min_candles
        # ------
        self.stats = st.stats
        self.signal_history = st.signal_history
        self.last_signal_pair = None
        self.same_pair_count = 0
        self.last_loss = st.last_loss

    def format_pair_for_api(self, pair):
        return pair.upper() if self.market_type == "LIVE" else pair.replace("_", "-") + "q"

    def fetch_data(self, pair, limit=600):
        url = f"https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={self.format_pair_for_api(pair)}&interval=1m&limit={limit}:qx_fxbd1pmgumxe8xo8j9mgz8nbeiabq3p3"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                payout = str(data.get("payout","92")).replace("%","")
                if 'candles' in data and data['candles']:
                    for c in data['candles']:
                        if 'volume' not in c: c['volume'] = 1
                    return data['candles'], data['candles'][-1]['close'], payout
        except: pass
        return None, None, "92"

    def analyze(self, candles):
        if self.strategy == 1:
            return analyze_strategy1(candles, 75)
        elif self.strategy == 2:
            return analyze_strategy2(candles, self.strategy2_filters)
        elif self.strategy == 3:
            return analyze_strategy3(candles, self.strategy3_min_accuracy, self.strategy3_lookback)
        elif self.strategy == 4:
            return analyze_strategy4(candles, self.strategy4_min_accuracy)
        elif self.strategy == 5:
            return analyze_strategy5(candles, self.strategy5_min_score)
        elif self.strategy == 6:
            return analyze_strategy6(candles, self.strategy6_min_score, self.strategy6_min_candles)
        else:
            # Fallback to Strategy 3 (default parameters 75 / 20)
            return analyze_strategy3(candles, 75, 20)

    def get_trend_text(self, candles, direction):
        if len(candles) >= 10:
            closes = [c['close'] for c in candles]
            ema = calculate_ema(closes, 10)
            if ema: return "Bullish" if closes[-1] > ema else "Bearish"
        return "Bullish" if direction == "CALL" else "Bearish"

    def send_signal_with_chart(self, pair, price, bias, entry_t, candles, payout, confidence=80):
        direction = "CALL" if bias == "CALL" else "PUT"
        trend_text = self.get_trend_text(candles, direction)
        signal_text = build_signal_message(pair, entry_t, direction, payout, trend_text)
        st = get_state(self.uid)
        chart_path = draw_neon_chart(candles, pair, entry_t, direction, payout,
                                    confidence=confidence,
                                    wins=st.stats['wins'], losses=st.stats['losses'],
                                    strategy=self.strategy, martingale_steps=1)
        if chart_path and os.path.exists(chart_path):
            sender.send_file(self.uid, chart_path, signal_text)
            try: os.remove(chart_path)
            except: pass
        else:
            sender.send_message(self.uid, signal_text)

    def send_result_with_chart(self, pair, entry_time, entry_candle, second_candle, payout, result_type, candles, direction=None):
        if result_type == "WIN":
            msg = build_result_message_first_win(pair, entry_time, payout, self.stats['wins'], self.stats['losses'])
        elif result_type == "MTG WIN":
            msg = build_result_message_second_win(pair, entry_time, payout, self.stats['wins'], self.stats['losses'])
        else:
            msg = build_result_message_loss(pair, entry_time, payout, self.stats['wins'], self.stats['losses'])
        st = get_state(self.uid)
        chart_path = draw_result_chart(candles, pair, payout, result_type, entry_candle, second_candle,
                                       wins=st.stats['wins'], losses=st.stats['losses'],
                                       strategy=self.strategy, direction=direction,
                                       entry_time_str=entry_time)
        if chart_path and os.path.exists(chart_path):
            sender.send_file(self.uid, chart_path, msg)
            try: os.remove(chart_path)
            except: pass
        else:
            sender.send_message(self.uid, msg)

    def sleep_until(self, target_utc5):
        while not get_state(self.uid).stop_requested:
            if (datetime.now(timezone.utc) + timedelta(hours=5)) >= target_utc5: break
            time.sleep(0.2)

    def get_candle_at_time(self, candles, target_dt_utc5):
        target = int((target_dt_utc5 - timedelta(hours=5)).timestamp())
        for c in candles:
            if 'time' in c and abs(c['time'] - target) < 30: return c
        return None

    def run_single_signal(self):
        uid = self.uid
        st = get_state(uid)
        st.running = True
        st.stop_requested = False

        # Animated progress bar using Telethon (premium emojis work)
        progress_msg = sender.send_message(uid, "⏳ Scanning for a signal... 0%")
        if not progress_msg:
            return
        progress_id = progress_msg.id

        signal_found = False
        try:
            for idx, pair in enumerate(self.pairs):
                if st.stop_requested:
                    break
                pct = int((idx + 1) / len(self.pairs) * 100)
                bar_text = f"⏳ Scanning {pair}... {progress_bar_text(pct)}"
                sender.edit_message(uid, progress_id, bar_text)

                candles, price, payout = self.fetch_data(pair, limit=200)
                if not candles:
                    continue
                try:
                    payout_num = int(payout) if payout != "!" else 77
                except:
                    payout_num = 0
                if self.market_type == "OTC" and payout_num < 77:
                    continue
                now = datetime.now(timezone.utc) + timedelta(hours=5)
                if pair in st.last_loss:
                    if (now - st.last_loss[pair]).total_seconds() < st.loss_cooldown_minutes * 60:
                        continue
                bias, entry_dt, score = self.analyze(candles)
                if bias:
                    if pair == self.last_signal_pair:
                        self.same_pair_count += 1
                    else:
                        self.last_signal_pair = pair
                        self.same_pair_count = 1
                    if self.same_pair_count > 2:
                        continue
                    entry_t = entry_dt.strftime("%H:%M")
                    sender.edit_message(uid, progress_id, "✅ Signal found! Sending...")
                    self.send_signal_with_chart(pair, price, bias, entry_t, candles, payout, confidence=score)
                    sender.edit_message(uid, progress_id, "⏳ Monitoring result...")
                    self.handle_signal_result(pair, entry_dt, bias, payout, candles)
                    signal_found = True
                    break

            if signal_found:
                sender.edit_message(uid, progress_id, "✅ Scanning complete.")
                sender.send_message(uid, "✅ Signal completed.\nUse /continue for next signal, or /stop to return to main menu.")
            else:
                sender.edit_message(uid, progress_id, "❌ No signal found.")
        finally:
            st.running = False

    def handle_signal_result(self, pair, entry_dt_utc5, direction, payout, initial_candles):
        st = get_state(self.uid)
        close_time_1 = entry_dt_utc5 + timedelta(minutes=1)
        self.sleep_until(close_time_1)
        if st.stop_requested: return
        candles, _, _ = self.fetch_data(pair, limit=750)
        if not candles: return
        first = self.get_candle_at_time(candles, entry_dt_utc5)
        if not first: return
        win1 = (first['close'] > first['open']) if direction == "CALL" else (first['close'] < first['open'])
        trade_type = "NON-MTG"
        st.signal_history.append({'pair':pair, 'direction':direction, 'time':entry_dt_utc5.strftime('%H:%M'),
                                  'result':"WIN" if win1 else "LOSS", 'type':trade_type})
        if not win1: st.last_loss[pair] = datetime.now(timezone.utc) + timedelta(hours=5)
        if win1:
            st.stats['wins'] += 1
            self.send_result_with_chart(pair, entry_dt_utc5.strftime('%H:%M'), first, None, payout, "WIN", candles, direction=direction)
            return
        close_time_2 = entry_dt_utc5 + timedelta(minutes=2)
        self.sleep_until(close_time_2)
        if st.stop_requested: return
        candles2, _, _ = self.fetch_data(pair, limit=750)
        if not candles2: return
        second = self.get_candle_at_time(candles2, entry_dt_utc5 + timedelta(minutes=1))
        if not second: return
        win2 = (second['close'] > second['open']) if direction == "CALL" else (second['close'] < second['open'])
        if win2:
            st.signal_history[-1]['result'] = "WIN"
            st.signal_history[-1]['type'] = "MTG"
            st.stats['wins'] += 1
            self.send_result_with_chart(pair, entry_dt_utc5.strftime('%H:%M'), first, second, payout, "MTG WIN", candles2, direction=direction)
        else:
            st.stats['losses'] += 1
            self.send_result_with_chart(pair, entry_dt_utc5.strftime('%H:%M'), first, None, payout, "LOSS", candles2, direction=direction)

# ══════════════ LIVE CHECKER (flexible format parser + readable_time matching) ══════════════
def clean_int_input(text: str) -> str:
    return text.strip().replace('\n', '').replace('\r', '').replace(' ', '').replace('\u200b', '')

def parse_signal_line(line: str):
    line = line.strip()
    if not line:
        return None, None, None
    line = re.sub(r'^(M\d+\s+)', '', line)
    time_match = re.search(r'(\d{2}:\d{2})', line)
    if not time_match:
        return None, None, None
    time_str = time_match.group(1)
    dir_match = re.search(r'\b(CALL|PUT)\b', line, re.IGNORECASE)
    if not dir_match:
        return None, None, None
    direction = dir_match.group(1).upper()
    rest = line.replace(time_str, '').replace(dir_match.group(1), '').replace(dir_match.group(1).upper(), '').replace(dir_match.group(1).lower(), '')
    rest = re.sub(r'[;,_\-\.]', ' ', rest)
    rest = ' '.join(rest.split())
    pair = rest.strip()
    if not pair:
        return None, None, None
    if not re.search(r'(OTC|otc)', pair):
        pair += "_OTC"
    pair = pair.replace('-OTC', '_OTC').replace(' ', '_').upper()
    return pair, time_str, direction

def run_checker_sio(uid, date_str, signals_text):
    BASE_URL = "https://sio.tools"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Referer": "https://sio.tools/",
    }
    USER_TZ = 5
    API_TZ = -3
    TZ_OFFSET = USER_TZ - API_TZ

    def user_time_to_api_local(time_str):
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            user_dt = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
            api_dt = user_dt - timedelta(hours=TZ_OFFSET)
            return api_dt.strftime("%H:%M")
        except:
            return time_str

    def api_time_to_user_local(time_str):
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            api_dt = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
            user_dt = api_dt + timedelta(hours=TZ_OFFSET)
            return user_dt.strftime("%H:%M")
        except:
            return time_str

    lines = [l.strip() for l in signals_text.strip().split('\n') if l.strip()]
    if not lines:
        return "❌ No signals provided."
    if len(lines) == 1 and "," in lines[0]:
        signals_user = [s.strip() for s in lines[0].split(",") if s.strip()]
    else:
        signals_user = lines

    # Normalise to "M1;PAIR;TIME;DIRECTION"
    signals_api = []
    for sig in signals_user:
        parts = sig.split(";")
        parts = [p.strip() for p in parts]
        if len(parts) == 4:
            tf, asset, time_user, direction = parts
        elif len(parts) == 3:
            asset, time_user, direction = parts
            tf = "M1"
        else:
            signals_api.append(sig)
            continue
        time_api = user_time_to_api_local(time_user)
        signals_api.append(f"{tf};{asset};{time_api};{direction}")

    # Send progress bar
    progress_msg = sender.send_message(uid, "⏳ Checking signals... [░░░░░░░░░░] 0%")
    if not progress_msg:
        return
    progress_id = progress_msg.id

    info = {"broker": "quotex", "date": date_str, "gale": 1, "time": 1}
    try:
        resp = requests.post(BASE_URL + "/quotex/check", json={"info": info, "signals": signals_api}, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            sender.edit_message(uid, progress_id, "❌ Check creation failed.")
            return
        check_id = resp.json().get("id")
        if not check_id:
            sender.edit_message(uid, progress_id, "❌ No check ID.")
            return
    except Exception as e:
        sender.edit_message(uid, progress_id, f"❌ Network error: {e}")
        return

    # Poll with animated progress
    for attempt in range(1, 41):
        time.sleep(3)
        pct = int(attempt / 40 * 100)
        filled = int(pct / 10)
        bar = "█" * filled + "░" * (10 - filled)
        sender.edit_message(uid, progress_id, f"⏳ Checking... [{bar}] {pct}%")
        try:
            resp = requests.get(BASE_URL + f"/quotex/check/{check_id}", headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "finished":
                    break
        except:
            pass
    else:
        sender.edit_message(uid, progress_id, "❌ Timeout waiting for check result.")
        return

    sender.edit_message(uid, progress_id, "✅ Check complete!")

    signals_res = data.get("signals", [])
    output_lines = []
    for sig in signals_res:
        if sig.startswith("\n"):
            output_lines.append(sig.strip())
        else:
            parts = sig.split(";")
            if len(parts) >= 4:
                tf = parts[0]
                asset = parts[1]
                time_api = parts[2]
                rest = ";".join(parts[3:])
                time_user = api_time_to_user_local(time_api)
                output_lines.append(f"M1 {asset} {time_user} {rest}")
            else:
                output_lines.append(sig)

    # Build premium‑formatted header
    win_count = sum(1 for l in output_lines if "WIN" in l or "G1" in l)
    mtg_count = sum(1 for l in output_lines if "G1" in l)
    loss_count = sum(1 for l in output_lines if "LOSS" in l)

    header = (
        f"=========== 𝙲𝙷𝙴𝙲𝙺𝙴𝚁 ===========\n"
        f"SMZ CHECKER🏆\n"
        f"━━━━━━━━━・━━━━━━━━━\n"
        f"          📆 - {date_str}\n"
        f"━━━━━━━━━・━━━━━━━━━\n\n"
    )
    body = "\n".join(output_lines)
    summary = (
        f"\n━━━━━━━━━・━━━━━━━━━\n"
        f"✅ 𝚆𝙸𝙽 :{win_count}  (MTG: {mtg_count})\n"
        f"❌ 𝙻𝙾𝚂𝚂 :{loss_count}\n"
        f"━━━━━━━━━・━━━━━━━━━"
    )
    final = header + body + summary
    sender.send_message(uid, final)

# ══════════════ FUTURE SIGNAL FUNCTIONS ══════════════
FUT_PAIRS = [
    "AUDCAD_OTC", "AUDJPY_OTC", "AUDNZD_OTC", "AUDUSD_OTC", "BRLUSD_OTC",
    "CADCHF_OTC", "CADJPY_OTC", "CHFJPY_OTC", "EURAUD_OTC", "EURCAD_OTC",
    "EURCHF_OTC", "EURGBP_OTC", "EURJPY_OTC", "EURNZD_OTC", "EURSGD_OTC",
    "EURUSD_OTC", "GBPAUD_OTC", "GBPCAD_OTC", "GBPCHF_OTC", "GBPJPY_OTC",
    "GBPUSD_OTC", "NZDUSD_OTC", "USDARS_OTC", "USDBDT_OTC", "USDCAD_OTC",
    "USDCHF_OTC", "USDEGP_OTC", "USDGBP_OTC", "USDIDR_OTC", "USDINR_OTC",
    "USDJPY_OTC", "USDMXN_OTC", "USDNGN_OTC", "USDPKR_OTC", "USDTRY_OTC",
    "USDZAR_OTC", "USDPHP_OTC"
]

SUPPORTED_LIVE_PAIRS = [
    "USDBDT_OTC", "USDARS_OTC", "USDINR_OTC", "USDMXN_OTC", "USDNGN_OTC",
    "USDEGP_OTC", "USDPKR_OTC", "USDIDR_OTC", "BRLUSD_OTC", "NZDUSD_OTC",
    "GBPNZD_OTC", "EURNZD_OTC", "NZDCAD_OTC", "CADCHF_OTC", "NZDJPY_OTC",
    "NZDCHF_OTC", "AUDNZD_OTC", "BTCUSD_OTC", "XAUUSD_OTC", "EURUSD_OTC",
    "GBPUSD_OTC", "USDJPY_OTC", "EURJPY_OTC", "AUDUSD_OTC", "USDCAD_OTC",
    "USDCHF_OTC", "EURGBP_OTC", "EURCHF_OTC", "GBPJPY_OTC", "AUDJPY_OTC",
    "GBPCAD_OTC", "EURCAD_OTC", "AUDCAD_OTC", "USDDZD_OTC", "MSFT_OTC",
    "FB_OTC", "MCD_OTC", "INTC_OTC"
]

def generate_future_signals(uid, min_conf=75, start_time="00:00", end_time="23:59", selected_pairs=None):
    if selected_pairs is None:
        selected_pairs = FUT_PAIRS
    all_signals = []
    for pair in selected_pairs:
        pair_api = pair.replace("_OTC", "_otc")
        url = f"https://quotexotc-futureapi.poghen-dx.workers.dev/pairs={pair_api}?start_time={start_time}&end_time={end_time}"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "success": continue
            for sig in data.get("signals", []):
                try: acc = int(sig.get("accuracy","0%").rstrip('%'))
                except: acc = 0
                if acc >= min_conf:
                    all_signals.append({
                        'time': sig.get("time","??:??"),
                        'pair': pair,
                        'dir': sig.get("direction","?").upper(),
                        'acc': acc
                    })
        except: pass
    if not all_signals:
        return None
    all_signals.sort(key=lambda x: time_to_min(x['time']))
    return build_future_signal_header(all_signals)

def time_to_min(t):
    try: h,m = map(int,t.split(':')); return h*60 + m
    except: return 0


# ══════════════ BACKTEST (SMZ HACKING MODE via sio.tools) ══════════════
def run_backtest_sio(uid, start_date, end_date, signals_text):
    BASE_URL = "https://sio.tools"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Referer": "https://sio.tools/",
    }
    USER_TZ = 5
    API_TZ = -3
    TZ_OFFSET = USER_TZ - API_TZ

    def user_time_to_api_local(time_str):
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            user_dt = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
            api_dt = user_dt - timedelta(hours=TZ_OFFSET)
            return api_dt.strftime("%H:%M")
        except:
            return time_str

    def api_time_to_user_local(time_str):
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            api_dt = datetime.strptime(f"{today.date()} {time_str}", "%Y-%m-%d %H:%M")
            user_dt = api_dt + timedelta(hours=TZ_OFFSET)
            return user_dt.strftime("%H:%M")
        except:
            return time_str

    lines = [l.strip() for l in signals_text.strip().split('\n') if l.strip()]
    if not lines:
        return "❌ No signals provided."
    if len(lines) == 1 and "," in lines[0]:
        signals_user = [s.strip() for s in lines[0].split(",") if s.strip()]
    else:
        signals_user = lines

    # ── Normalize signals to "M1;PAIR;TIME;DIRECTION" ──
    signals_api = []
    for sig in signals_user:
        parts = sig.split(";")
        parts = [p.strip() for p in parts]
        if len(parts) == 4:
            tf, asset, time_user, direction = parts
        elif len(parts) == 3:
            asset, time_user, direction = parts
            tf = "M1"
        else:
            signals_api.append(sig)
            continue
        time_api = user_time_to_api_local(time_user)
        signals_api.append(f"{tf};{asset};{time_api};{direction}")

    days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days + 1
    info = {
        "broker": "quotex",
        "brokerLabel": "Quotex",
        "startDate": start_date,
        "endDate": end_date,
        "gale": 1,
        "mode": "geral"
    }

    # ── Send initial progress message ──
    progress_msg = sender.send_message(uid, "⏳ Backtesting... [░░░░░░░░░░] 0%")
    if not progress_msg:
        return "❌ Could not send progress message."
    progress_id = progress_msg.id

    try:
        resp = requests.post(BASE_URL + "/quotex/backtest", json={"info": info, "signals": signals_api, "days": days}, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            sender.edit_message(uid, progress_id, "❌ Backtest creation failed.")
            return ""
        job_id = resp.json().get("id")
        if not job_id:
            sender.edit_message(uid, progress_id, "❌ No job ID returned.")
            return ""
    except Exception as e:
        sender.edit_message(uid, progress_id, f"❌ Network error: {e}")
        return ""

    # ── Poll with animated progress ──
    max_attempts = 60
    for attempt in range(1, max_attempts + 1):
        time.sleep(3)
        # Update progress bar every 3 attempts (every ~9 seconds)
        if attempt % 3 == 0 or attempt == max_attempts:
            pct = int(attempt / max_attempts * 100)
            filled = int(pct / 10)
            bar = "█" * filled + "░" * (10 - filled)
            sender.edit_message(uid, progress_id, f"⏳ Backtesting... [{bar}] {pct}%")
        try:
            resp = requests.get(BASE_URL + f"/quotex/backtest/{job_id}", headers=HEADERS, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "finished":
                    break
        except:
            pass
    else:
        sender.edit_message(uid, progress_id, "❌ Timeout waiting for backtest result.")
        return ""

    # ── Process results ──
    signals_res = data.get("signals", [])
    loss_list = data.get("loss_list", [])
    mode = data.get("mode", "geral")

    # Convert API times back to user local times
    converted_signals = []
    for sig in signals_res:
        parts = sig.split(";")
        if len(parts) >= 5:
            tf = parts[0]
            asset = parts[1]
            time_api = parts[2]
            direction = parts[3]
            res = parts[4]
            time_user = api_time_to_user_local(time_api)
            converted_signals.append(f"{tf};{asset};{time_user};{direction};{res}")
        else:
            converted_signals.append(sig)

    # Build clean loss list (remove G1 signals)
    g1_keys = set()
    for sig in signals_res:
        parts = sig.split(";")
        if len(parts) >= 5 and parts[4] == "G1":
            key = f"{parts[1]};{parts[2]};{parts[3]}"
            g1_keys.add(key)

    converted_loss = []
    for ls in loss_list:
        parts = ls.split(";")
        if len(parts) >= 4:
            tf = parts[0]
            asset = parts[1]
            time_api = parts[2]
            direction = parts[3]
            time_user = api_time_to_user_local(time_api)
            key = f"{asset};{time_user};{direction}"
            if key not in g1_keys:
                converted_loss.append(f"{tf};{asset};{time_user};{direction}")
        else:
            converted_loss.append(ls)

    # Count statistics
    win_count = sum(1 for sig in signals_res if len(sig.split(";")) >= 5 and sig.split(";")[4] == "WIN")
    g1_count = sum(1 for sig in signals_res if len(sig.split(";")) >= 5 and sig.split(";")[4] == "G1")
    loss_count = len(converted_loss)

    # Build result text
    result_text = f"📊 BACKTEST RESULTS (mode: {mode})\n"
    result_text += f"Date range: {start_date} → {end_date}\n\n"
    result_text += f"✅ Direct wins: {win_count}\n"
    result_text += f"🔄 G1 (MTG) wins: {g1_count}\n"
    result_text += f"❌ Losses: {loss_count}\n\n"

    result_text += "✅ WIN / G1 signals (UTC+5):\n"
    for idx, sig in enumerate(converted_signals, 1):
        result_text += f"{idx}. {sig}\n"

    if converted_loss:
        result_text += "\n❌ LOSS signals (UTC+5):\n"
        for idx, ls in enumerate(converted_loss, 1):
            result_text += f"{idx}. {ls}\n"

    # Edit the progress message to show complete, then send the full result
    sender.edit_message(uid, progress_id, "✅ Backtest complete!")
    sender.send_message(uid, result_text)
    return ""  # we already sent the result via sender


# ══════════════ NEW MODES: TREND FILTER, TEXT FORMATTER, FONT CHANGER, ETC. ══════════════

# -- Trend Filter --
def process_trend_filter(uid, signals_text):
    lines = [l.strip() for l in signals_text.strip().split('\n') if l.strip()]
    if not lines:
        return "❌ No signals provided."

    accepted = []
    rejected = []
    supported = SUPPORTED_LIVE_PAIRS

    for line in lines:
        parsed = parse_signal_line(line)
        if not parsed[0]:
            rejected.append(f"⚠️ Invalid format: {line}")
            continue
        pair, time_str, direction = parsed

        # Immediately reject unsupported pairs
        if pair not in supported:
            rejected.append(f"⚠️ Unsupported pair: {pair}")
            continue

        # Use Pakistan date (UTC+5)
        date_str = (datetime.now(timezone.utc) + timedelta(hours=5)).strftime("%Y-%m-%d")

        pair_api = pair.replace("_", "-") + "q"
        url = f"https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={pair_api}&interval=1m&limit=2000:qx_vzwz3wsu54chx8zmxpt0vp1yfk9gkxv0"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                rejected.append(f"❌ No data for {pair}")
                continue
            data = r.json()
            candles = data.get('candles', [])
            if not candles:
                rejected.append(f"❌ No candles for {pair}")
                continue

            try:
                signal_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                signal_dt = signal_dt.replace(tzinfo=timezone(timedelta(hours=5)))
            except:
                rejected.append(f"⚠️ Invalid date/time: {date_str} {time_str}")
                continue

            target_ts = int((signal_dt - timedelta(hours=5)).timestamp())

            # Find the candle at the signal time
            signal_candle = None
            for c in candles:
                if abs(int(c['time']) - target_ts) < 30:
                    signal_candle = c
                    break
            if not signal_candle:
                rejected.append(f"❌ Candle not found for {pair} {time_str}")
                continue

            # Find the candle exactly 1 hour before
            prev_ts = target_ts - 3600
            prev_candle = None
            for c in candles:
                if abs(int(c['time']) - prev_ts) < 30:
                    prev_candle = c
                    break
            if not prev_candle:
                rejected.append(f"❌ Not enough history (1h) for {pair} {time_str}")
                continue

            curr_close = float(signal_candle['close'])
            prev_close = float(prev_candle['close'])
            trend_up = curr_close > prev_close

            signal_emoji = '📉' if direction == 'CALL' else '📈'
            if direction == 'CALL' and trend_up:
                accepted.append(f"✅ {pair} {time_str} {direction} {signal_emoji} (Trend: up)")
            elif direction == 'PUT' and not trend_up:
                accepted.append(f"✅ {pair} {time_str} {direction} {signal_emoji} (Trend: down)")
            else:
                rejected.append(f"❌ {pair} {time_str} {direction} {signal_emoji} (Trend: {'up' if trend_up else 'down'})")

        except Exception as e:
            rejected.append(f"❌ Error: {e}")

    total = len(lines)
    acc_count = len(accepted)
    rej_count = len(rejected)

    result = "📉 **Trend Filter Results**\n\n"
    result += f"🔹 Accepted: {acc_count}/{total}\n"
    result += "\n".join(accepted) if accepted else "None"
    result += f"\n\n🔸 Rejected: {rej_count}/{total}\n"
    result += "\n".join(rejected) if rejected else "None"
    return result

# -- Text Formatter --
def format_signals_with_template(original_lines, template):
    converted = []
    # First try to see if template contains placeholders
    has_placeholders = any(p in template for p in ['<PAIR>','<TIME>','<DIRECTION>','<pair>','<time>','<direction>'])
    # If not, we will try to parse the template's own pair/time/dir to replace them
    example_parsed = None
    if not has_placeholders:
        example_parsed = parse_signal_line(template)   # get (pair, time, dir) from the example

    for line in original_lines:
        parsed = parse_signal_line(line)
        if not parsed[0]:
            converted.append(f"⚠️ Could not parse: {line}")
            continue
        pair, time_str, direction = parsed

        # 1) Replace placeholders if present
        result = template
        result = result.replace('<PAIR>', pair).replace('<pair>', pair)
        result = result.replace('<TIME>', time_str).replace('<time>', time_str)
        result = result.replace('<DIRECTION>', direction).replace('<direction>', direction)
        result = result.replace('<DIR>', direction).replace('<dir>', direction)

        # 2) If no placeholders were found, use the example's own values as templates
        if not has_placeholders and example_parsed[0]:
            ex_pair, ex_time, ex_dir = example_parsed
            # Replace the first occurrence of each
            if ex_pair:
                result = result.replace(ex_pair, pair, 1)
            if ex_time:
                result = result.replace(ex_time, time_str, 1)
            if ex_dir:
                result = result.replace(ex_dir.upper(), direction, 1)
                result = result.replace(ex_dir.lower(), direction, 1)

        converted.append(result)
    return "\n".join(converted)


# -- Pair Payout% (live enriched data) --
def fetch_payout_live(pair):
    """Return the payout percentage from the live trading API for a given pair."""
    pair_api = pair.replace("_", "-") + "q"
    url = f"https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={pair_api}&interval=1m&limit=1:qx_vzwz3wsu54chx8zmxpt0vp1yfk9gkxv0"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            payout = data.get("payout", "!")
            if isinstance(payout, str):
                payout = payout.replace('%', '')
            try:
                return int(payout)
            except:
                return payout
    except:
        pass
    return "!"

def run_pair_payout(uid, context):
    loading_msg = sender.send_message(uid, "⏳ Loading pair payouts...")
    # Only pairs that return a valid number (not "!")
    result_lines = []
    for pair in FUT_PAIRS:
        payout = fetch_payout_live(pair)
        if payout != "!" and isinstance(payout, (int, float)):
            result_lines.append(f"🎥 {pair} : 💲 {payout}%")
        time.sleep(0.3)
    if not result_lines:
        sender.send_message(uid, "❌ No supported pairs found.")
    else:
        text = "📊 **Pair Payout%**\n\n" + "\n".join(result_lines)
        sender.send_message(uid, text)
    try:
        sender.edit_message(uid, loading_msg.id, "✅ Payout list ready.")
    except:
        pass

def get_trend_from_candles(pair):
    """Return 'up', 'down', 'sideways', or None if no data."""
    pair_api = pair.replace("_", "-") + "q"
    url = f"https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={pair_api}&interval=1m&limit=180:qx_vzwz3wsu54chx8zmxpt0vp1yfk9gkxv0"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            candles = data.get("candles", [])
            if len(candles) >= 2:
                first_close = float(candles[0]['close'])
                last_close = float(candles[-1]['close'])
                change_pct = (last_close - first_close) / first_close * 100
                if change_pct > 0.2:
                    return 'up'
                elif change_pct < -0.2:
                    return 'down'
                else:
                    return 'sideways'
    except:
        pass
    return None   # no data

def run_market_trend(uid, context):
    loading_msg = sender.send_message(uid, "⏳ Loading market trends...")
    result_lines = []
    for pair in FUT_PAIRS:
        trend = get_trend_from_candles(pair)
        if trend is None:
            continue   # skip unsupported pairs
        if trend == 'up':
            emoji = '📉'
        elif trend == 'down':
            emoji = '📈'
        else:
            emoji = '➡️'
        result_lines.append(f"🎥 {pair} : {emoji} {trend}")
        time.sleep(0.3)
    if not result_lines:
        sender.send_message(uid, "❌ No supported pairs found.")
    else:
        text = "📈 **Market Trend (last 3 hours)**\n\n" + "\n".join(result_lines)
        sender.send_message(uid, text)
    try:
        sender.edit_message(uid, loading_msg.id, "✅ Trend list ready.")
    except:
        pass

def fetch_recent_candles(pair, limit=6):
    pair_api = pair.replace("_OTC", "-OTC") + "q"
    url = f"https://ikszeynptbmwkaaldfad.supabase.co/functions/v1/quotex-proxy?symbol={pair_api}&interval=1m&limit={limit}:qx_fxbd1pmgumxe8xo8j9mgz8nbeiabq3p3"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get('candles', [])
    except:
        pass
    return None

def run_candle_colors(uid, context):
    loading_msg = sender.send_message(uid, "⏳ Loading candle colors...")
    pairs = FUT_PAIRS
    result_lines = []
    for pair in pairs:
        candles = fetch_recent_candles(pair, limit=6)
        if candles:
            colors = []
            for c in candles:
                if c['close'] >= c['open']:
                    colors.append('🟢')
                else:
                    colors.append('🔴')
            color_str = ''.join(colors)
            result_lines.append(f"➡️ {pair} : {color_str}")
        time.sleep(0.3)
    if not result_lines:
        sender.send_message(uid, "❌ Could not fetch candle data.")
    else:
        text = "🕯️ **Candle Colors (last 6)**\n\n" + "\n".join(result_lines)
        sender.send_message(uid, text)
    try: sender.edit_message(uid, loading_msg.id, "✅ Candle colors ready.")
    except: pass

async def s6_score_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 70 <= val <= 100:
            get_state(uid).strategy6_min_score = val
            await update.message.reply_text("Enter minimum candles for analysis (30‑200):")
            return S6_MIN_CANDLES
        else:
            await update.message.reply_text("❌ Enter between 70‑100:")
            return S6_SCORE
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S6_SCORE

async def s6_candles_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 10 <= val <= 200:
            get_state(uid).strategy6_min_candles = val
            await update.message.reply_text(
                f"✅ Confluence score ≥ {get_state(uid).strategy6_min_score}, "
                f"min candles = {val}. Scanning..."
            )
            bot = SMZXBot(uid)
            threading.Thread(target=bot.run_single_signal, daemon=True).start()
            context.user_data['strategy_active'] = False
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Enter between 30‑200:")
            return S6_MIN_CANDLES
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S6_MIN_CANDLES


# ══════════════ BOT HANDLERS (Inline Buttons + Colored + Premium Icons) ══════════════
(S2_FILTER_CHOICE, S2_FILTER_TOGGLE, S2_ACCURACY,
 S3_ACCURACY, S3_LOOKBACK, S4_ACCURACY, S5_SCORE) = range(7)

# Checker sub‑menu states (2 values)
STATE_CHECKER_CUSTOM_DATE, STATE_CHECKER_SIGNALS = range(7, 9)

# Future signal states (4 values)
STATE_FUT_MIN_CONF, STATE_FUT_START_TIME, STATE_FUT_END_TIME, STATE_FUT_CUSTOM_PAIRS = range(9, 13)

# Backtest states (3 values)
STATE_BACKTEST_START, STATE_BACKTEST_END, STATE_BACKTEST_SIGNALS = range(13, 16)

# UTC converter states (3 values)
STATE_UTC_ORIG_OFFSET, STATE_UTC_TARGET_OFFSET, STATE_UTC_SIGNALS = range(16, 19)

# Text formatter states (2 values)
STATE_FORMATTER_INPUT, STATE_FORMATTER_EXAMPLE = range(19, 21)

# Font changer states (2 values)
STATE_FONT_INPUT, STATE_FONT_STYLE = range(21, 23)

# Trend filter state (1 value)
STATE_TREND_FILTER_INPUT = 23

S6_SCORE, S6_MIN_CANDLES = range(26, 28)

# Helper to build colored button with premium emoji
def colored_button(text, callback_data, style=KeyboardButtonStyle.PRIMARY, emoji_id=None):
    if emoji_id:
        return InlineKeyboardButton(
            text=text,
            callback_data=callback_data,
            style=style,
            icon_custom_emoji_id=emoji_id
        )
    else:
        return InlineKeyboardButton(
            text=text,
            callback_data=callback_data,
            style=style
        )

# UTF‑16 helper for bold text
def utf16_offset(text: str, char_index: int) -> int:
    offset = 0
    for i, ch in enumerate(text):
        if i == char_index:
            break
        offset += len(ch.encode('utf-16-le')) // 2
    return offset

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name

    text = (
        f"👑 Assalamualaikum @{username} 👋\n\n"
        f"🔥 Welcome to SMZXV4.3 AI\n\n"
        f"Quick Guide\n"
        f"1. 📊 Start Trading – live chart analysis\n"
        f"2. 🐶 Signal Checker – verify past signals\n"
        f"3. 🐶 Future Signals – next‑hour signals\n"
        f"4. 🏆 Backtest – multi‑day win‑rate test\n"
        f"5. 🐶 UTC Converter – timezone changer\n"
        f"6. 🐶 Pair Payout% – live payout list\n"
        f"7. 🐶 Market Trend – Current market direction\n"
        f"8. 🐶 Candle Colors – last 6 candle colours\n"
        f"9. 🐶Text Formatter – reformat signal lists\n"
        f"10. 🐶 Font Changer – apply text styles\n"
        f"11. 📺 Trend Filter – Ai trend filter\n"
        f"12. 🤭 Help – contact support\n\n"
        f"💎 Choose an option below to continue.\n\n"
        f"©OWNER @Rohailtrader ✨"
    )

    # Bold entities for feature names and key words
    bold_words = [
        "Start Trading", "Signal Checker", "Future Signals", "Backtest",
        "UTC Converter", "Pair Payout%", "Market Trend", "Candle Colors",
        "Text Formatter", "Font Changer", "Trend Filter", "Help",
        "SMZXV4.3"   # also bold the version number
    ]
    extra_entities = []
    for word in bold_words:
        idx = text.find(word)
        if idx != -1:
            utf16_off = utf16_offset(text, idx)
            extra_entities.append(
                MessageEntity(
                    type='bold',
                    offset=utf16_off,
                    length=len(word.encode('utf-16-le'))//2
                )
            )

    buttons = [
        [colored_button(" Start Trading", "menu_analysis", KeyboardButtonStyle.SUCCESS, "6145248943807667330"),
         colored_button(" Signal Checker", "menu_checker", KeyboardButtonStyle.PRIMARY, "6145553439809084250")],
        [colored_button(" Future Signals", "menu_futuresignal", KeyboardButtonStyle.PRIMARY, "6062153953833917531"),
         colored_button(" Backtest", "menu_backtest", KeyboardButtonStyle.SUCCESS, "6147840110462245787")],   # safe ID
        [colored_button(" UTC Converter", "menu_utc_converter", KeyboardButtonStyle.PRIMARY, "5413879192267805083"),
         colored_button(" Pair Payout%", "menu_pair_payout", KeyboardButtonStyle.PRIMARY, "6145449239607515472")], # safe ID
        [colored_button(" Market Trend", "menu_market_trend", KeyboardButtonStyle.PRIMARY, "6147654280112248427"),
         colored_button(" Candle Colors", "menu_candle_colors", KeyboardButtonStyle.PRIMARY, "5217911744495624141")], # safe ID
        [colored_button(" Text Formatter", "menu_text_formatter", KeyboardButtonStyle.PRIMARY, "5282843764451195532"),
         colored_button(" Font Changer", "menu_font_changer", KeyboardButtonStyle.PRIMARY, "5314391089514291948")],
        [colored_button(" Trend Filter", "menu_trend_filter", KeyboardButtonStyle.SUCCESS, "5316681209026191987")], # safe ID
        [colored_button(" Help", "menu_admin", KeyboardButtonStyle.DANGER, "6062294201696000196")],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    entities = build_custom_emoji_entities(text) + extra_entities
    await context.bot.send_message(chat_id=uid, text=text, entities=entities, reply_markup=reply_markup)
    context.user_data['strategy_active'] = False
    context.user_data['state'] = None

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id

    if not is_authorized(uid):
        await query.answer("⛔ Access denied. Contact Admin to get access.", show_alert=True)
        return

    await query.answer()
    data = query.data
    if data == "menu_analysis":
        await query.answer()
        buttons = [
            [colored_button(" Strategy 1", "strat_1", KeyboardButtonStyle.PRIMARY)],
            [colored_button(" Strategy 2", "strat_2", KeyboardButtonStyle.SUCCESS)],
            [colored_button(" Strategy 3", "strat_3", KeyboardButtonStyle.SUCCESS)],
            [colored_button(" Strategy 4", "strat_4", KeyboardButtonStyle.PRIMARY)],
            [colored_button(" Strategy 5", "strat_5", KeyboardButtonStyle.PRIMARY)],
            [colored_button(" Strategy 6", "strat_6", KeyboardButtonStyle.SUCCESS)],
        ]
        markup = InlineKeyboardMarkup(buttons)
        text = "👑 Select strategy:"
        entities = build_custom_emoji_entities(text)
        # 👇 This sends a NEW message and keeps the main menu visible
        await query.message.reply_text(text, entities=entities, reply_markup=markup)
    elif data == "menu_checker":
        buttons = [
            [colored_button(" Today", "checker_today", KeyboardButtonStyle.SUCCESS, "6102795674577803992")],
            [colored_button(" Yesterday", "checker_yesterday", KeyboardButtonStyle.PRIMARY, "6145553439809084250")],
            [colored_button(" Custom Date", "checker_custom", KeyboardButtonStyle.PRIMARY, "5229228004068057251")],
        ]
        markup = InlineKeyboardMarkup(buttons)
        text = "🔮 **Signal Checker**\nSelect date:"
        entities = build_custom_emoji_entities(text)
        # ✅ Sends a NEW message – keeps the main menu visible
        await query.message.reply_text(text, entities=entities, reply_markup=markup)
    elif data == "menu_futuresignal":
        context.user_data['state'] = STATE_FUT_MIN_CONF
        context.user_data['strategy_active'] = False
        sender.send_message(uid, "😈 Enter minimum confidence % (0-100):")
    elif data == "menu_backtest":
        context.user_data['state'] = STATE_BACKTEST_START
        context.user_data['strategy_active'] = False
        sender.send_message(uid, "📺 Backtest Mode\nEnter start date (YYYY-MM-DD):")
    elif data == "menu_utc_converter":
        context.user_data['state'] = STATE_UTC_ORIG_OFFSET
        sender.send_message(uid, "🕐 Enter original timezone offset (e.g., +0 for UTC, +5 for Pakistan):")
    elif data == "menu_pair_payout":
        threading.Thread(target=run_pair_payout, args=(uid, context), daemon=True).start()
    elif data == "menu_market_trend":
        threading.Thread(target=run_market_trend, args=(uid, context), daemon=True).start()
    elif data == "menu_candle_colors":
        threading.Thread(target=run_candle_colors, args=(uid, context), daemon=True).start()
    elif data == "menu_text_formatter":
        context.user_data['state'] = STATE_FORMATTER_INPUT
        sender.send_message(uid, "📝 **Text Formatter**\n\nSend me your signal list (one per line).\nFormat can be anything – I'll extract pair, time, direction.\nThen send an example of your desired output with placeholders like <PAIR>, <TIME>, <DIRECTION>.")
    elif data == "menu_font_changer":
        context.user_data['state'] = STATE_FONT_INPUT
        sender.send_message(uid, "📱 **TEXT FONT CHANGER**\n\n📝 Please paste your signals or text below:\n\n✨ Premium emojis will be preserved!")
    elif data == "menu_trend_filter":
        context.user_data['state'] = STATE_TREND_FILTER_INPUT
        sender.send_message(uid, "📉 **Trend Filter**\n\nPaste your signal list (one per line).\nFormat: pair;time;direction (or any readable format).\n\nI will check the previous 1‑hour trend and filter accordingly.")
    elif data == "menu_admin":
        sender.send_message(uid, "🤭 Contact @Rohailtrader")

async def strategy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id

    if not is_authorized(uid):
        await query.answer("⛔ Access denied. Contact Admin to get access.", show_alert=True)
        return

    await query.answer()
    data = query.data
    strat = int(data.split("_")[1])
    st = get_state(uid)
    st.strategy = strat
    context.user_data['uid'] = uid
    context.user_data['strategy_active'] = True
    context.user_data['state'] = None

    if strat == 1:
        text = "✅ Strategy 1 selected. Scanning..."
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        bot = SMZXBot(uid)
        threading.Thread(target=bot.run_single_signal, daemon=True).start()
        context.user_data['strategy_active'] = False
        return ConversationHandler.END
    elif strat == 2:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes", callback_data="s2_filters_yes"),
            InlineKeyboardButton("❌ No", callback_data="s2_filters_no")
        ]])
        await query.message.reply_text("🔰 Strategy 2: Enable additional filters?", reply_markup=kb)
        return S2_FILTER_CHOICE
    elif strat == 3:
        text = "✅ Strategy 3 selected. Enter min accuracy % (50-100):"
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        return S3_ACCURACY
    elif strat == 4:
        text = "✅ Strategy 4 selected. Enter min accuracy % (50-100):"
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        return S4_ACCURACY
    elif strat == 5:
        text = "✅ Strategy 5 selected. Enter min score (50-100):"
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        return S5_SCORE
    elif strat == 6:
        text = "✅ Strategy 6 selected. Enter minimum confluence score (70‑100):"
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        return S6_SCORE

async def checker_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()   # acknowledge immediately
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.answer("⛔ Access denied.", show_alert=True)
        return
    data = query.data
    if data == "checker_today":
        context.user_data['checker_date'] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    elif data == "checker_yesterday":
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        context.user_data['checker_date'] = yesterday.strftime("%Y-%m-%d")
    elif data == "checker_custom":
        context.user_data['state'] = STATE_CHECKER_CUSTOM_DATE
        text = "📅 Enter the date (YYYY-MM-DD):"
        entities = build_custom_emoji_entities(text)
        await query.edit_message_text(text, entities=entities)
        return

    context.user_data['state'] = STATE_CHECKER_SIGNALS
    text = "⏰ Now paste your signals (one per line):"
    entities = build_custom_emoji_entities(text)
    await query.edit_message_text(text, entities=entities)

# ── Filter toggles ──
def build_s2_filter_message(filters):
    status = lambda x: "✅" if x else "❌"
    text = (
        f"🎯 Toggle filters:\n\n"
        f"{status(filters.use_trend)} Trend\n"
        f"{status(filters.use_bollinger)} Bollinger\n"
        f"{status(filters.use_support_resistance)} S/R\n"
        f"{status(filters.use_price_action)} Price Action\n"
        f"{status(filters.use_supertrend)} Supertrend\n"
        f"{status(filters.use_fvg)} FVG\n"
        f"{status(filters.use_trend_reverse)} Trend Reverse\n\n"
        "Tap a filter to toggle, then 'Done'."
    )
    buttons = [
        [InlineKeyboardButton(f"{status(filters.use_trend)} Trend", callback_data="s2_trend")],
        [InlineKeyboardButton(f"{status(filters.use_bollinger)} Bollinger", callback_data="s2_bb")],
        [InlineKeyboardButton(f"{status(filters.use_support_resistance)} S/R", callback_data="s2_sr")],
        [InlineKeyboardButton(f"{status(filters.use_price_action)} Price Action", callback_data="s2_pa")],
        [InlineKeyboardButton(f"{status(filters.use_supertrend)} Supertrend", callback_data="s2_st")],
        [InlineKeyboardButton(f"{status(filters.use_fvg)} FVG", callback_data="s2_fvg")],
        [InlineKeyboardButton(f"{status(filters.use_trend_reverse)} Trend Reverse", callback_data="s2_tr")],
        [InlineKeyboardButton("✅ Done", callback_data="s2_done")],
    ]
    return text, InlineKeyboardMarkup(buttons)

async def s2_filter_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.answer("⛔ Access denied.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    data = query.data
    uid = context.user_data['uid']
    st = get_state(uid)
    if data == "s2_filters_no":
        st.strategy2_filters = Strategy2Filters()
        await query.edit_message_text("✅ Filters disabled. Enter min accuracy (50-100):")
        return S2_ACCURACY
    else:
        filters = Strategy2Filters()
        context.user_data['filters'] = filters
        text, markup = build_s2_filter_message(filters)
        await query.edit_message_text(text, reply_markup=markup)
        return S2_FILTER_TOGGLE

async def s2_filter_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.answer("⛔ Access denied.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    data = query.data
    uid = context.user_data['uid']
    filters = context.user_data['filters']
    toggle_map = {
        "s2_trend": "use_trend", "s2_bb": "use_bollinger", "s2_sr": "use_support_resistance",
        "s2_pa": "use_price_action", "s2_st": "use_supertrend", "s2_fvg": "use_fvg",
        "s2_tr": "use_trend_reverse"
    }
    if data in toggle_map:
        attr = toggle_map[data]
        setattr(filters, attr, not getattr(filters, attr))
        text, markup = build_s2_filter_message(filters)
        await query.edit_message_text(text, reply_markup=markup)
        return S2_FILTER_TOGGLE
    elif data == "s2_done":
        get_state(uid).strategy2_filters = filters
        await query.edit_message_text("✅ Filters saved. Enter min accuracy (50-100):")
        return S2_ACCURACY

async def s2_accuracy_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
        return ConversationHandler.END
    st = get_state(uid)
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 50 <= val <= 100:
            st.strategy2_filters.min_accuracy = val
            sender.send_message(uid, f"✅ Min accuracy set to {val}%.\nStarting analysis...")
            bot = SMZXBot(uid)
            threading.Thread(target=bot.run_single_signal, daemon=True).start()
            context.user_data['strategy_active'] = False
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Enter between 50-100:")
            return S2_ACCURACY
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S2_ACCURACY

async def s3_accuracy_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 50 <= val <= 100:
            get_state(uid).strategy3_min_accuracy = val
            await update.message.reply_text("Enter lookback period (10-30):")
            return S3_LOOKBACK
        else:
            await update.message.reply_text("❌ Enter between 50-100:")
            return S3_ACCURACY
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S3_ACCURACY

async def s3_lookback_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 10 <= val <= 30:
            get_state(uid).strategy3_lookback = val
            sender.send_message(uid, f"✅ Lookback set to {val}. Starting analysis...")
            bot = SMZXBot(uid)
            threading.Thread(target=bot.run_single_signal, daemon=True).start()
            context.user_data['strategy_active'] = False
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Enter between 10-30:")
            return S3_LOOKBACK
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Enter a number.")
        return S3_LOOKBACK

async def s4_accuracy_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 50 <= val <= 100:
            get_state(uid).strategy4_min_accuracy = val
            sender.send_message(uid, f"✅ Accuracy set. Starting analysis...")
            bot = SMZXBot(uid)
            threading.Thread(target=bot.run_single_signal, daemon=True).start()
            context.user_data['strategy_active'] = False
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Enter 50-100:")
            return S4_ACCURACY
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S4_ACCURACY

async def s5_score_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = context.user_data['uid']
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    raw = update.message.text
    cleaned = clean_int_input(raw)
    try:
        val = int(cleaned)
        if 50 <= val <= 100:
            get_state(uid).strategy5_min_score = val
            sender.send_message(uid, f"✅ Score set. Starting analysis...")
            bot = SMZXBot(uid)
            threading.Thread(target=bot.run_single_signal, daemon=True).start()
            context.user_data['strategy_active'] = False
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ Enter 50-100:")
            return S5_SCORE
    except ValueError:
        await update.message.reply_text(f"❌ Invalid number: '{cleaned}'. Please enter a number.")
        return S5_SCORE

# ── /continue and /stop ──
async def continue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
        return
    st = get_state(uid)
    if st.running:
        await update.message.reply_text("Already running a signal. Wait for it to finish.")
        return
    bot = SMZXBot(uid)
    threading.Thread(target=bot.run_single_signal, daemon=True).start()
    sender.send_message(uid, "Continuing with next signal...")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
        return

    st = get_state(uid)
    st.stop_requested = True
    st.running = False

    # ✅ Reset stats and history
    st.stats = {"wins": 0, "losses": 0}
    st.signal_history = []

    sender.send_message(uid, "Stopping. Returning to main menu. Use /start to see options.")

# ══════════════ GLOBAL TEXT HANDLER (Checker, Future Signal, Backtest, New Modes) ══════════════
async def global_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_authorized(uid):
        await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
        return

    if context.user_data.get('strategy_active'):
        return

    text = update.message.text.strip()
    state = context.user_data.get('state')

    # ── Checker ──
    if state == STATE_CHECKER_CUSTOM_DATE:
        # User has entered a custom date
        context.user_data['checker_date'] = text
        context.user_data['state'] = STATE_CHECKER_SIGNALS
        sender.send_message(uid, "⏰ Now paste your signals (one per line):")
    elif state == STATE_CHECKER_SIGNALS:
        date_str = context.user_data.get('checker_date')
        run_checker_sio(uid, date_str, text)   # sends result directly
        context.user_data['state'] = None

    # ── Future Signal ──
    elif state == STATE_FUT_MIN_CONF:
        cleaned = clean_int_input(text)
        try:
            val = int(cleaned)
            if 0 <= val <= 100:
                context.user_data['fut_min_conf'] = val
                context.user_data['state'] = STATE_FUT_START_TIME
                sender.send_message(uid, "Enter start time (HH:MM):")
            else:
                sender.send_message(uid, "Enter between 0-100:")
        except ValueError:
            sender.send_message(uid, "Invalid number. Enter min confidence (0-100):")
    elif state == STATE_FUT_START_TIME:
        if re.match(r'^\d{2}:\d{2}$', text):
            context.user_data['fut_start_time'] = text
            context.user_data['state'] = STATE_FUT_END_TIME
            sender.send_message(uid, "Enter end time (HH:MM):")
        else:
            sender.send_message(uid, "Invalid format. Use HH:MM. Enter start time:")
    elif state == STATE_FUT_END_TIME:
        if re.match(r'^\d{2}:\d{2}$', text):
            context.user_data['fut_end_time'] = text
            buttons = [
                [InlineKeyboardButton("🟢 All Supported Pairs", callback_data="pair_all")],
                [InlineKeyboardButton("🟡 Custom Pairs", callback_data="pair_custom")],
            ]
            await update.message.reply_text("📊 Pair selection:", reply_markup=InlineKeyboardMarkup(buttons))
            context.user_data['state'] = 'fut_pair_type'
        else:
            sender.send_message(uid, "Invalid format. Use HH:MM. Enter end time:")

    # ── Backtest ──
    elif state == STATE_BACKTEST_START:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            context.user_data['backtest_start'] = text
            context.user_data['state'] = STATE_BACKTEST_END
            sender.send_message(uid, "Enter end date (YYYY-MM-DD):")
        else:
            sender.send_message(uid, "Invalid date format. Use YYYY-MM-DD:")
    elif state == STATE_BACKTEST_END:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', text):
            context.user_data['backtest_end'] = text
            context.user_data['state'] = STATE_BACKTEST_SIGNALS
            sender.send_message(uid, "📋 Now paste your signals (one per line, format: pair;time;direction):")
        else:
            sender.send_message(uid, "Invalid date format. Use YYYY-MM-DD:")
    elif state == STATE_BACKTEST_SIGNALS:
        start_date = context.user_data.get('backtest_start')
        end_date = context.user_data.get('backtest_end')
        result = run_backtest_sio(uid, start_date, end_date, text)
        sender.send_message(uid, result)
        context.user_data['state'] = None

    # ── UTC Converter ─
    elif state == STATE_UTC_ORIG_OFFSET:
        try:
            orig_off = int(text)
            context.user_data['utc_orig'] = orig_off
            context.user_data['state'] = STATE_UTC_TARGET_OFFSET
            sender.send_message(uid, "Enter target timezone offset (e.g., +5 for Pakistan):")
        except ValueError:
            sender.send_message(uid, "⚠️ Invalid offset. Enter a number (e.g., +5, 0, -3):")
    elif state == STATE_UTC_TARGET_OFFSET:
        try:
            target_off = int(text)
            context.user_data['utc_target'] = target_off
            context.user_data['state'] = STATE_UTC_SIGNALS
            sender.send_message(uid, "📋 Now paste your signal list (one per line).\nType `done` on a new line when you are finished.")
        except ValueError:
            sender.send_message(uid, "⚠️ Invalid offset. Enter a number.")
    elif state == STATE_UTC_SIGNALS:
        # Split the incoming message into lines
        lines_to_add = text.split('\n')
        # Check if any line is exactly "done" (case‑insensitive)
        finish = any(line.strip().lower() == 'done' for line in lines_to_add)
        if finish:
            # Remove the "done" line
            lines_to_add = [l for l in lines_to_add if l.strip().lower() != 'done']
            if 'utc_signals' not in context.user_data:
                context.user_data['utc_signals'] = []
            context.user_data['utc_signals'].extend(lines_to_add)
            orig_off = context.user_data.get('utc_orig', 0)
            target_off = context.user_data.get('utc_target', 0)
            all_lines = context.user_data['utc_signals']
            if not all_lines:
                sender.send_message(uid, "❌ No signals provided.")
            else:
                diff = target_off - orig_off
                converted = []
                for line in all_lines:
                    m = re.search(r'(\d{2}:\d{2})', line)
                    if m:
                        time_str = m.group(1)
                        try:
                            h, minute = map(int, time_str.split(':'))
                            total_min = h * 60 + minute + diff * 60
                            total_min %= 24 * 60
                            new_h, new_m = divmod(total_min, 60)
                            new_time = f"{new_h:02d}:{new_m:02d}"
                            line = line.replace(time_str, new_time, 1)
                        except:
                            pass
                    converted.append(line)
                sender.send_message(uid, "\n".join(converted))
            # Clean up
            context.user_data['utc_signals'] = []
            context.user_data['state'] = None
        else:
            # Just collect the lines
            if 'utc_signals' not in context.user_data:
                context.user_data['utc_signals'] = []
            context.user_data['utc_signals'].extend(lines_to_add)
            sender.send_message(uid, f"✅ Received {len(lines_to_add)} line(s). Continue pasting or type 'done' to finish.")

    # ── Trend Filter ──
    elif state == STATE_TREND_FILTER_INPUT:
        result = process_trend_filter(uid, text)
        sender.send_message(uid, result)
        context.user_data['state'] = None

    # ── Text Formatter ──
    elif state == STATE_FORMATTER_INPUT:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if not lines:
            sender.send_message(uid, "❌ No signals received. Please send your list.")
            return
        context.user_data['formatter_signals'] = lines
        context.user_data['state'] = STATE_FORMATTER_EXAMPLE
        sender.send_message(uid,
            f"✅ Got {len(lines)} signals!\n\n"
            "📋 Now send me an example of your desired output format with placeholders:\n"
            "<PAIR>, <TIME>, <DIRECTION>\n\n"
            "👑 Examples:\n"
            "⧉ <PAIR> - <TIME> - <DIRECTION>\n"
            "❒ <PAIR> ➪ <TIME> ➪ <DIRECTION>\n"
            "| <TIME> = <PAIR> = <DIRECTION> |\n"
            "M1;<PAIR>;<TIME>;<DIRECTION>\n\n"
            "🤖 AI will convert all your signals to this format!🎮")
    elif state == STATE_FORMATTER_EXAMPLE:
        original_lines = context.user_data.get('formatter_signals', [])
        if not original_lines:
            sender.send_message(uid, "❌ No signals stored. Please start again.")
            context.user_data['state'] = None
            return
        template = text.strip()
        result = format_signals_with_template(original_lines, template)
        sender.send_message(uid, result)
        context.user_data['state'] = None

    # ── Font Changer ──
    elif state == STATE_FONT_INPUT:
        context.user_data['font_text'] = text
        context.user_data['state'] = STATE_FONT_STYLE
        keyboard = [
            [InlineKeyboardButton("1️⃣ Monospace (Code)", callback_data="font_mono")],
            [InlineKeyboardButton("2️⃣ Sans‑Serif Bold", callback_data="font_sans_bold")],
            [InlineKeyboardButton("3️⃣ Sans‑Serif Mono", callback_data="font_sans_mono")],
        ]
        await update.message.reply_text("🎨 Choose a font style:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif state == STATE_FONT_STYLE:
        # handled by callback, ignore text here
        pass

    # ── Future custom pairs text ──
    elif state == STATE_FUT_CUSTOM_PAIRS:
        pairs_text = text.upper()
        pairs_list = [p.strip() for p in pairs_text.split(",") if p.strip()]
        min_conf = context.user_data.get('fut_min_conf', 75)
        start = context.user_data.get('fut_start_time', '08:00')
        end = context.user_data.get('fut_end_time', '23:59')
        result = generate_future_signals(uid, min_conf, start, end, selected_pairs=pairs_list)
        if result:
            sender.send_message(uid, result)
        else:
            sender.send_message(uid, "❌ No future signals found.")
        context.user_data['state'] = None

# ── Future signal pair selection callback ──
async def fut_pair_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.answer("⛔ Access denied.", show_alert=True)
        return
    await query.answer()
    data = query.data
    if data == "pair_all":
        min_conf = context.user_data.get('fut_min_conf', 75)
        start = context.user_data.get('fut_start_time', '08:00')
        end = context.user_data.get('fut_end_time', '23:59')
        result = generate_future_signals(uid, min_conf, start, end)
        if result:
            sender.send_message(uid, result)
        else:
            sender.send_message(uid, "❌ No future signals found.")
        context.user_data['state'] = None
    elif data == "pair_custom":
        await query.edit_message_text("📊 Enter pairs (comma-separated), e.g., EURUSD_OTC,GBPUSD_OTC:")
        context.user_data['state'] = STATE_FUT_CUSTOM_PAIRS

# ── Font style callback ──
async def font_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not is_authorized(uid):
        await query.answer("⛔ Access denied.", show_alert=True)
        return
    await query.answer()
    data = query.data
    original_text = context.user_data.get('font_text', '')
    if not original_text:
        await query.edit_message_text("❌ No text found. Please start again.")
        return

    if data == "font_mono":
        formatted_lines = [f"<code>{line}</code>" for line in original_text.split('\n')]
        formatted = "\n".join(formatted_lines)
        await query.edit_message_text("✅ Monospace style applied!")
        await context.bot.send_message(chat_id=uid, text=formatted, parse_mode='HTML')
    elif data == "font_sans_bold":
        formatted_lines = [f"<b>{line}</b>" for line in original_text.split('\n')]
        formatted = "\n".join(formatted_lines)
        await query.edit_message_text("✅ Sans‑Serif Bold applied!")
        await context.bot.send_message(chat_id=uid, text=formatted, parse_mode='HTML')
    elif data == "font_sans_mono":
        formatted_lines = [fancy_font(line) for line in original_text.split('\n')]
        formatted = "\n".join(formatted_lines)
        await query.edit_message_text("✅ Sans‑Serif Mono applied!")
        await context.bot.send_message(chat_id=uid, text=formatted)
    context.user_data['state'] = None

# ══════════════ MAIN ══════════════
def main():
    global bot_instance
    init(autoreset=True)
    print(f"{Fore.CYAN}{'█'*100}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}✅ Access Granted!{Style.RESET_ALL}")

    API_ID = 31504511
    API_HASH = "edbaa34f80c4aedd1ed87f7112f54281"
    BOT_TOKEN_SENDER = "8261301090:AAHM2JRXTsflqkksuCk9n-kwcoB_XZT2zyw"
    sender.start_with_bot_token(API_ID, API_HASH, BOT_TOKEN_SENDER)

    app = Application.builder().token(BOT_TOKEN).build()
    bot_instance = app.bot   # used by SMZXBot for fallback text messages

    # ── start command (Bot API with colored buttons & premium icons) ──
    app.add_handler(CommandHandler("start", start_cmd))

    # ── main menu callbacks ──
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))

    # ── checker sub‑menu callbacks ──
    app.add_handler(CallbackQueryHandler(checker_date_callback, pattern="^checker_"))

    # ── strategy selection conversation ──
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(strategy_callback, pattern=r"^strat_")],
        states={
            S2_FILTER_CHOICE: [CallbackQueryHandler(s2_filter_choice, pattern=r"^s2_filters_")],
            S2_FILTER_TOGGLE: [CallbackQueryHandler(s2_filter_toggle, pattern=r"^s2_")],
            S2_ACCURACY: [MessageHandler(filters.TEXT & ~filters.COMMAND, s2_accuracy_received)],
            S3_ACCURACY: [MessageHandler(filters.TEXT & ~filters.COMMAND, s3_accuracy_received)],
            S3_LOOKBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, s3_lookback_received)],
            S4_ACCURACY: [MessageHandler(filters.TEXT & ~filters.COMMAND, s4_accuracy_received)],
            S5_SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, s5_score_received)],
            S6_SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, s6_score_received)],
            S6_MIN_CANDLES: [MessageHandler(filters.TEXT & ~filters.COMMAND, s6_candles_received)],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(conv_handler)

    # ── /checker and /futuresignal commands ──
    async def checker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not is_authorized(uid):
            await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
            return
        context.user_data['state'] = STATE_CHECKER_DATE
        context.user_data['strategy_active'] = False
        await update.message.reply_text("📅 Enter the date for verification (YYYY-MM-DD) or press Enter for today:")

    async def future_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not is_authorized(uid):
            await update.message.reply_text("⛔ Access denied. Contact Admin to get access.")
            return
        context.user_data['state'] = STATE_FUT_MIN_CONF
        context.user_data['strategy_active'] = False
        await update.message.reply_text("😈 Enter minimum confidence % (0-100):")

    app.add_handler(CommandHandler("checker", checker_cmd))
    app.add_handler(CommandHandler("futuresignal", future_cmd))

    # ── global text handler for all other flows ──
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_handler))

    # ── future signal pair selection callback ──
    app.add_handler(CallbackQueryHandler(fut_pair_callback, pattern="^pair_"))

    # ── font style callback ──
    app.add_handler(CallbackQueryHandler(font_style_callback, pattern="^font_"))

    # ── /continue and /stop commands ──
    app.add_handler(CommandHandler("continue", continue_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    print(f"{Fore.GREEN}[✓] Bot polling...{Style.RESET_ALL}")
    app.run_polling()

if __name__ == "__main__":
    main()
