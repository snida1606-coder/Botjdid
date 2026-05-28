#!/bin/bash
# =============================================
# TradoWix Bot - Termux Setup Script
# =============================================

echo "🚀 Setting up TradoWix Bot for Termux..."
echo ""

# Check Python
echo "📌 Checking Python..."
python3 --version

# Update Termux packages
echo ""
echo "📌 Updating Termux packages..."
pkg update && pkg upgrade -y

# Install required packages
echo ""
echo "📌 Installing required packages..."
pkg install -y python git clang openssl libffi libjpeg-turbo libwebp zlib

# Upgrade pip
echo ""
echo "📌 Upgrading pip..."
python3 -m pip install --upgrade pip setuptools wheel

# Install requirements
echo ""
echo "📌 Installing Python packages..."
pip install requests colorama python-telegram-bot==20.7 telethon Pillow websockets flask

echo ""
echo "============================================="
echo "✅ SETUP COMPLETE!"
echo "============================================="
echo ""
echo "📋 Next Steps:"
echo "1. cd to your bot folder"
echo "2. python3 aimode4\\ \\(1\\).py"
echo ""
echo "Or use this command:"
echo "   python3 \"aimode4 (1).py\""
echo ""