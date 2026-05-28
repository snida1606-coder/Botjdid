#!/usr/bin/env python3
"""
TradoWix Auto Trade Bot
=======================
Auto Trading System with Strategy Selection

Flow:
1. User clicks "Auto Trade" button
2. Enter TradoWix Email & Password
3. Select Strategy (1-6)
4. Enter TP, SL, MTG settings
5. Bot scans pairs and places trades automatically

Author: Auto Trade System
"""

import asyncio
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tradowix_client import TradoWixClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)

# ══════════════ CONFIG ══════════════
BOT_TOKEN = "7623409497:AAECia8u02Vwj4QOdBweRDwMlihn3n3RW38"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("autotrade")

# ══════════════ CONVERSATION STATES ══════════════
(STATE_EMAIL, STATE_PASSWORD, STATE_STRATEGY, STATE_TP, STATE_SL, STATE_MTG, STATE_TRADING) = range(7)

# ══════════════ STRATEGIES ══════════════
STRATEGIES = {
    1: {"name": "RSI Divergence", "desc": "RSI overbought/oversold with divergence"},
    2: {"name": "MA Crossover", "desc": "Moving Average crossover signals"},
    3: {"name": "Bollinger Bands", "desc": "Bollinger Bands breakout/mean-reversion"},
    4: {"name": "Candle Pattern", "desc": "Japanese candle patterns"},
    5: {"name": "Volume Analysis", "desc": "Volume-based signals"},
    6: {"name": "Multi-Timeframe", "desc": "Multiple timeframe confirmation"},
}

# PAIRS TO SCAN
SCAN_PAIRS = [
    "EURUSD-OTC",
    "USDBRL-OTC",
    "USDCOP-OTC",
    "USDJPY-OTC",
    "GBPUSD-OTC",
    "AUDUSD-OTC",
]

# ══════════════ USER STATE ══════════════
class TraderState:
    def __init__(self, uid: int):
        self.uid = uid
        self.email = None
        self.password = None
        self.client: Optional[TradoWixClient] = None
        self.strategy = 1
        self.tp_percent = 80
        self.sl_percent = 70
        self.mtg = 1  # 1 = 1 min, 2 = 5 min (default 1)
        self.running = False
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.scan_interval = 60  # seconds between scans
        self.trade_lock = threading.Lock()

user_traders: Dict[int, TraderState] = {}

def get_trader(uid: int) -> TraderState:
    if uid not in user_traders:
        user_traders[uid] = TraderState(uid)
    return user_traders[uid]

# ══════════════ STRATEGY FUNCTIONS ══════════════

def calculate_rsi(candles: List[Dict], period: int = 14) -> float:
    """Calculate RSI indicator"""
    if len(candles) < period + 1:
        return 50.0
    
    gains = []
    losses = []
    
    for i in range(1, min(len(candles), period + 10)):
        change = candles[i]['close'] - candles[i-1]['close']
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    if not gains:
        return 50.0
    
    avg_gain = sum(gains[-period:]) / period if len(gains) >= period else sum(gains) / len(gains)
    avg_loss = sum(losses[-period:]) / period if len(losses) >= period else sum(losses) / len(losses)
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ma(candles: List[Dict], period: int) -> float:
    """Calculate Simple Moving Average"""
    if len(candles) < period:
        return candles[-1]['close']
    return sum(c['close'] for c in candles[-period:]) / period

def calculate_bollinger_bands(candles: List[Dict], period: int = 20, std_dev: int = 2):
    """Calculate Bollinger Bands"""
    if len(candles) < period:
        return None, None, None
    
    prices = [c['close'] for c in candles[-period:]]
    sma = sum(prices) / period
    
    variance = sum((p - sma) ** 2 for p in prices) / period
    std = variance ** 0.5
    
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    
    return upper, sma, lower

def apply_strategy(candles: List[Dict], strategy: int) -> Dict[str, Any]:
    """
    Apply selected strategy and return signal
    
    Returns:
        {
            "signal": "BUY" | "SELL" | "HOLD",
            "confidence": 0-100,
            "reason": str,
            "rsi": float,
            "price": float
        }
    """
    if not candles or len(candles) < 20:
        return {"signal": "HOLD", "confidence": 0, "reason": "Insufficient data", "rsi": 50, "price": 0}
    
    current_price = candles[-1]['close']
    rsi = calculate_rsi(candles)
    
    if strategy == 1:  # RSI Divergence
        if rsi < 30:
            return {
                "signal": "BUY",
                "confidence": min(100, 100 - rsi + 20),
                "reason": f"RSI Oversold ({rsi:.1f})",
                "rsi": rsi,
                "price": current_price
            }
        elif rsi > 70:
            return {
                "signal": "SELL",
                "confidence": min(100, rsi - 20),
                "reason": f"RSI Overbought ({rsi:.1f})",
                "rsi": rsi,
                "price": current_price
            }
        return {"signal": "HOLD", "confidence": 50, "reason": f"RSI Neutral ({rsi:.1f})", "rsi": rsi, "price": current_price}
    
    elif strategy == 2:  # MA Crossover
        ma9 = calculate_ma(candles, 9)
        ma21 = calculate_ma(candles, 21)
        
        if ma9 > ma21 and candles[-1]['close'] > ma9:
            return {
                "signal": "BUY",
                "confidence": 75,
                "reason": "MA9 crossed above MA21",
                "rsi": rsi,
                "price": current_price
            }
        elif ma9 < ma21 and candles[-1]['close'] < ma9:
            return {
                "signal": "SELL",
                "confidence": 75,
                "reason": "MA9 crossed below MA21",
                "rsi": rsi,
                "price": current_price
            }
        return {"signal": "HOLD", "confidence": 50, "reason": "MA neutral", "rsi": rsi, "price": current_price}
    
    elif strategy == 3:  # Bollinger Bands
        upper, middle, lower = calculate_bollinger_bands(candles)
        if not upper:
            return {"signal": "HOLD", "confidence": 0, "reason": "Calculating...", "rsi": rsi, "price": current_price}
        
        if current_price <= lower:
            return {
                "signal": "BUY",
                "confidence": 80,
                "reason": "Price at lower band",
                "rsi": rsi,
                "price": current_price
            }
        elif current_price >= upper:
            return {
                "signal": "SELL",
                "confidence": 80,
                "reason": "Price at upper band",
                "rsi": rsi,
                "price": current_price
            }
        return {"signal": "HOLD", "confidence": 50, "reason": "Price in bands", "rsi": rsi, "price": current_price}
    
    elif strategy == 4:  # Candle Pattern
        if len(candles) < 3:
            return {"signal": "HOLD", "confidence": 0, "reason": "Need more candles", "rsi": rsi, "price": current_price}
        
        last = candles[-1]
        prev = candles[-2]
        
        # Bullish Engulfing
        if prev['close'] < prev['open'] and last['close'] > last['open']:
            if last['close'] > prev['open'] and last['open'] < prev['close']:
                return {
                    "signal": "BUY",
                    "confidence": 70,
                    "reason": "Bullish Engulfing",
                    "rsi": rsi,
                    "price": current_price
                }
        
        # Bearish Engulfing
        if prev['close'] > prev['open'] and last['close'] < last['open']:
            if last['open'] > prev['close'] and last['close'] < prev['open']:
                return {
                    "signal": "SELL",
                    "confidence": 70,
                    "reason": "Bearish Engulfing",
                    "rsi": rsi,
                    "price": current_price
                }
        
        return {"signal": "HOLD", "confidence": 50, "reason": "No pattern", "rsi": rsi, "price": current_price}
    
    elif strategy == 5:  # Volume Analysis
        if len(candles) < 10:
            return {"signal": "HOLD", "confidence": 0, "reason": "Need more data", "rsi": rsi, "price": current_price}
        
        avg_volume = sum(c.get('volume', 1) for c in candles[-10:]) / 10
        current_volume = candles[-1].get('volume', 1)
        
        if current_volume > avg_volume * 1.5:
            if rsi < 50:
                return {
                    "signal": "BUY",
                    "confidence": 75,
                    "reason": f"High volume + RSI {rsi:.1f}",
                    "rsi": rsi,
                    "price": current_price
                }
            else:
                return {
                    "signal": "SELL",
                    "confidence": 75,
                    "reason": f"High volume + RSI {rsi:.1f}",
                    "rsi": rsi,
                    "price": current_price
                }
        return {"signal": "HOLD", "confidence": 50, "reason": f"Normal volume", "rsi": rsi, "price": current_price}
    
    elif strategy == 6:  # Multi-Timeframe
        # Uses RSI on multiple timeframes concept
        rsi_14 = calculate_rsi(candles, 14)
        rsi_28 = calculate_rsi(candles, 28)
        
        if rsi_14 < 30 and rsi_28 < 40:
            return {
                "signal": "BUY",
                "confidence": 85,
                "reason": f"Multi-TF oversold (RSI14={rsi_14:.1f}, RSI28={rsi_28:.1f})",
                "rsi": rsi,
                "price": current_price
            }
        elif rsi_14 > 70 and rsi_28 > 60:
            return {
                "signal": "SELL",
                "confidence": 85,
                "reason": f"Multi-TF overbought (RSI14={rsi_14:.1f}, RSI28={rsi_28:.1f})",
                "rsi": rsi,
                "price": current_price
            }
        return {"signal": "HOLD", "confidence": 50, "reason": "Multi-TF neutral", "rsi": rsi, "price": current_price}
    
    return {"signal": "HOLD", "confidence": 50, "reason": "Unknown strategy", "rsi": rsi, "price": current_price}

# ══════════════ TELEGRAM HANDLERS ══════════════

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu with Auto Trade button"""
    uid = update.effective_user.id
    
    keyboard = [
        [InlineKeyboardButton("🤖 Auto Trade", callback_data="autotrade_start")],
        [InlineKeyboardButton("📊 Status", callback_data="autotrade_status")],
        [InlineKeyboardButton("🛑 Stop Trading", callback_data="autotrade_stop")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 *AUTO TRADE BOT*\n\n"
        "Select an option below:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def autotrade_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Auto Trade - Ask for email"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📧 *Step 1/5: TradoWix Login*\n\n"
        "Enter your TradoWix *Email*:"
    )
    return STATE_EMAIL

async def email_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store email and ask for password"""
    trader = get_trader(update.effective_user.id)
    trader.email = update.message.text.strip()
    
    await update.message.reply_text(
        "🔐 *Step 2/5: Password*\n\n"
        "Enter your TradoWix *Password*:"
    )
    return STATE_PASSWORD

async def password_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store password and show strategy options"""
    trader = get_trader(update.effective_user.id)
    trader.password = update.message.text.strip()
    
    # Build strategy buttons
    keyboard = []
    for i in range(1, 7):
        strategy = STRATEGIES[i]
        keyboard.append([InlineKeyboardButton(
            f"{i}. {strategy['name']}",
            callback_data=f"strat_{i}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📈 *Step 3/5: Select Strategy*\n\n"
        "Choose a trading strategy:\n\n"
        "1️⃣ RSI Divergence - Overbought/Oversold\n"
        "2️⃣ MA Crossover - Moving Average signals\n"
        "3️⃣ Bollinger Bands - Band breakout\n"
        "4️⃣ Candle Pattern - Pattern recognition\n"
        "5️⃣ Volume Analysis - Volume based\n"
        "6️⃣ Multi-Timeframe - Multiple confirmation",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return STATE_STRATEGY

async def strategy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store strategy and ask for TP"""
    query = update.callback_query
    await query.answer()
    
    trader = get_trader(update.effective_user.id)
    strategy_id = int(query.data.split("_")[1])
    trader.strategy = strategy_id
    
    await query.edit_message_text(
        f"✅ *Strategy Selected: {STRATEGIES[strategy_id]['name']}*\n\n"
        "📈 *Step 4/5: Take Profit %*\n\n"
        "Enter TP percentage (50-95):"
    )
    return STATE_TP

async def tp_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store TP and ask for SL"""
    trader = get_trader(update.effective_user.id)
    
    try:
        tp = int(update.message.text.strip())
        if tp < 50 or tp > 95:
            await update.message.reply_text("❌ TP must be between 50-95. Try again:")
            return STATE_TP
        trader.tp_percent = tp
    except:
        await update.message.reply_text("❌ Invalid number. Enter TP (50-95):")
        return STATE_TP
    
    await update.message.reply_text(
        f"📉 *Step 5/5: Stop Loss %*\n\n"
        "Enter SL percentage (50-95):"
    )
    return STATE_SL

async def sl_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store SL and ask for MTG"""
    trader = get_trader(update.effective_user.id)
    
    try:
        sl = int(update.message.text.strip())
        if sl < 50 or sl > 95:
            await update.message.reply_text("❌ SL must be between 50-95. Try again:")
            return STATE_SL
        trader.sl_percent = sl
    except:
        await update.message.reply_text("❌ Invalid number. Enter SL (50-95):")
        return STATE_SL
    
    keyboard = [
        [InlineKeyboardButton("1️⃣ 1 Minute", callback_data="mtg_1")],
        [InlineKeyboardButton("2️⃣ 5 Minutes", callback_data="mtg_2")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⏱️ *Maturity Time (MTG)*\n\n"
        "Select trade duration:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return STATE_MTG

async def mtg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store MTG and start trading"""
    query = update.callback_query
    await query.answer()
    
    trader = get_trader(update.effective_user.id)
    trader.mtg = int(query.data.split("_")[1])
    
    # Connect to TradoWix
    await query.edit_message_text("🔌 *Connecting to TradoWix...*")
    
    try:
        trader.client = TradoWixClient()
        trader.client.login(trader.email, trader.password)
        trader.client.connect()
        
        # Wait for connection
        for _ in range(30):
            if trader.client.is_connected:
                break
            time.sleep(0.5)
        
        if not trader.client.is_connected:
            await context.bot.send_message(
                chat_id=trader.uid,
                text="❌ *Connection Failed!* Could not connect to TradoWix."
            )
            return ConversationHandler.END
        
        # Start trading thread
        trader.running = True
        threading.Thread(target=trading_loop, args=(trader, context), daemon=True).start()
        
        await context.bot.send_message(
            chat_id=trader.uid,
            text=
            f"✅ *Connected & Trading Started!*\n\n"
            f"📧 Account: `{trader.email}`\n"
            f"📈 Strategy: {STRATEGIES[trader.strategy]['name']}\n"
            f"🎯 TP: {trader.tp_percent}% | SL: {trader.sl_percent}%\n"
            f"⏱️ MTG: {trader.mtg} minute(s)\n\n"
            f"🔍 Scanning pairs..."
        )
        
    except Exception as e:
        await context.bot.send_message(
            chat_id=trader.uid,
            text=f"❌ *Login Failed!*\n\nError: {str(e)}"
        )
        return ConversationHandler.END
    
    return ConversationHandler.END

# ══════════════ TRADING LOOP ══════════════

def trading_loop(trader: TraderState, context: ContextTypes.DEFAULT_TYPE):
    """Main trading loop - runs in background"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def send_msg(text: str):
        try:
            await context.bot.send_message(chat_id=trader.uid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    async def run():
        await send_msg("🔄 *Trading Loop Started*\n" + "─"*30)
        
        while trader.running:
            try:
                # Subscribe to all pairs one by one
                for pair in SCAN_PAIRS:
                    if not trader.running:
                        break
                    
                    # Subscribe
                    trader.client.subscribe(pair, lookback_minutes=300, timeframe=60)
                    
                    # Wait for data
                    for _ in range(15):
                        if trader.client._candle_history.get(pair):
                            break
                        time.sleep(0.5)
                    
                    # Get candles
                    candles = trader.client._candle_history.get(pair, [])
                    
                    if candles and len(candles) >= 20:
                        # Apply strategy
                        signal = apply_strategy(candles, trader.strategy)
                        
                        await send_msg(
                            f"📊 *{pair}*\n"
                            f"├ Signal: {signal['signal']}\n"
                            f"├ RSI: {signal['rsi']:.1f}\n"
                            f"├ Price: {signal['price']:.5f}\n"
                            f"├ Confidence: {signal['confidence']:.0f}%\n"
                            f"└ Reason: {signal['reason']}"
                        )
                        
                        # Place trade if signal is BUY or SELL with high confidence
                        if signal['signal'] != "HOLD" and signal['confidence'] >= 70:
                            direction = "higher" if signal['signal'] == "BUY" else "lower"
                            amount = calculate_trade_amount(trader)
                            
                            try:
                                trade_result = trader.client.place_trade(
                                    symbol=pair,
                                    direction=direction,
                                    amount=amount,
                                    duration_minutes=trader.mtg,
                                    is_demo=True
                                )
                                
                                if trade_result and not trade_result.get("error"):
                                    trader.trade_count += 1
                                    trade_id = trade_result.get("tradeId", "N/A")
                                    
                                    await send_msg(
                                        f"✅ *Trade Placed!*\n"
                                        f"├ Pair: {pair}\n"
                                        f"├ Direction: {direction.upper()}\n"
                                        f"├ Amount: ${amount}\n"
                                        f"├ Trade ID: `{trade_id}`\n"
                                        f"└ Waiting for result..."
                                    )
                                else:
                                    error = trade_result.get("error", "Unknown error") if trade_result else "No response"
                                    await send_msg(f"⚠️ Trade failed: {error}")
                                    
                            except Exception as trade_err:
                                await send_msg(f"⚠️ Trade error: {str(trade_err)}")
                        
                        # Small delay between pairs
                        time.sleep(2)
                
                # Wait before next scan cycle
                for _ in range(trader.scan_interval):
                    if not trader.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await send_msg(f"⚠️ Error in trading loop: {str(e)}")
                time.sleep(10)
        
        await send_msg("🛑 *Trading Stopped*")
    
    loop.run_until_complete(run())

def calculate_trade_amount(trader: TraderState) -> float:
    """Calculate trade amount based on balance and risk"""
    # Default amount - can be enhanced with MM
    base_amount = 5.0  # Minimum trade
    return base_amount

async def autotrade_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trading status"""
    query = update.callback_query
    await query.answer()
    
    trader = get_trader(update.effective_user.id)
    
    if not trader.client or not trader.client.is_connected:
        status_text = "❌ Not connected to TradoWix"
    else:
        status_text = (
            f"✅ *Auto Trade Status*\n\n"
            f"📧 Account: `{trader.email}`\n"
            f"📈 Strategy: {STRATEGIES[trader.strategy]['name']}\n"
            f"🎯 TP: {trader.tp_percent}% | SL: {trader.sl_percent}%\n"
            f"⏱️ MTG: {trader.mtg} minute(s)\n"
            f"🔄 Status: {'Running' if trader.running else 'Stopped'}\n"
            f"📊 Trades: {trader.trade_count}"
        )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="autotrade_status")],
        [InlineKeyboardButton("🛑 Stop", callback_data="autotrade_stop")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        status_text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def autotrade_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop trading"""
    query = update.callback_query
    await query.answer()
    
    trader = get_trader(update.effective_user.id)
    trader.running = False
    
    if trader.client:
        trader.client.disconnect()
    
    await query.edit_message_text(
        "🛑 *Trading Stopped*\n\n"
        f"Total trades: {trader.trade_count}\n\n"
        "Use /start to begin again."
    )

# ══════════════ MAIN ══════════════

def main():
    """Start the bot"""
    print("🤖 Auto Trade Bot Starting...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Main menu
    app.add_handler(CommandHandler("start", start_cmd))
    
    # Auto trade conversation
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(autotrade_start_callback, pattern="^autotrade_start$")],
        states={
            STATE_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_received)],
            STATE_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password_received)],
            STATE_STRATEGY: [CallbackQueryHandler(strategy_callback, pattern=r"^strat_\d+$")],
            STATE_TP: [MessageHandler(filters.TEXT & ~filters.COMMAND, tp_received)],
            STATE_SL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sl_received)],
            STATE_MTG: [CallbackQueryHandler(mtg_callback, pattern=r"^mtg_\d+$")],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    )
    app.add_handler(conv_handler)
    
    # Status and stop
    app.add_handler(CallbackQueryHandler(autotrade_status_callback, pattern="^autotrade_status$"))
    app.add_handler(CallbackQueryHandler(autotrade_stop_callback, pattern="^autotrade_stop$"))
    
    print("✅ Bot Ready! Starting polling...")
    app.run_polling()

if __name__ == "__main__":
    main()