#!/usr/bin/env python3
"""
Telegram Earning Bot - Complete Production System
Single-file backend with Telegram bot, FastAPI, database, and admin logic
"""

import os
import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qs

# Database
import aiosqlite
from contextlib import asynccontextmanager

# FastAPI for Web App backend
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Telegram Bot
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    WebAppInfo, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import uvicorn

# ============================================================================
# CONFIGURATION & ENVIRONMENT
# ============================================================================

# Security: Load from environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "8502536019:AAFcuwfD_tDnlMGNwP0jQapNsakJIRjaSfc")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

ADMIN_IDS = [633765043, 6375918223]  # Admin Telegram IDs
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-render-app.onrender.com")
DATABASE_URL = "earn_bot.db"

# Admin Information (Editable)
ADMIN_INFO = {
    "names": ["XT Maim !!", "XT Hunter !!"],
    "telegram": ["@cr_maim", "@Huntervai1k"],
    "whatsapp": "01833515655",
    "support_group": "https://t.me/+OXFzYPTSQXQ3NjVl"
}

# Earning Configuration (Admin editable)
EARNING_CONFIG = {
    "ad_reward": 5.0,  # 5৳ per ad
    "ad_daily_limit": 10,
    "ad_cooldown": 60,  # seconds
    "referral_bonus": 10.0,  # 10৳ per active referral
    "min_withdraw": 100.0,
    "daily_login_bonus": 5.0,
    "streak_bonus": [5, 10, 15, 20, 25]  # Day 1-5 bonuses
}

# ============================================================================
# DATABASE MODELS & SCHEMA
# ============================================================================

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    @asynccontextmanager
    async def get_connection(self):
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn
    
    async def init_db(self):
        """Initialize database with PostgreSQL-ready schema"""
        async with self.get_connection() as conn:
            # Users table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    balance REAL DEFAULT 0,
                    total_earned REAL DEFAULT 0,
                    total_withdrawn REAL DEFAULT 0,
                    ads_watched_today INTEGER DEFAULT 0,
                    ads_watched_total INTEGER DEFAULT 0,
                    referral_id TEXT UNIQUE,
                    referred_by INTEGER,
                    referral_count INTEGER DEFAULT 0,
                    active_referrals INTEGER DEFAULT 0,
                    last_ad_watch TIMESTAMP,
                    last_login TIMESTAMP,
                    login_streak INTEGER DEFAULT 0,
                    last_login_date DATE,
                    is_banned BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Earnings table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS earnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL, -- 'ad', 'task', 'referral', 'bonus'
                    description TEXT,
                    task_id INTEGER,
                    referral_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Tasks table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reward REAL NOT NULL,
                    redirect_url TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    daily_limit INTEGER DEFAULT 1,
                    total_completions INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User tasks (track completions)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id),
                    UNIQUE(user_id, task_id, DATE(completed_at))
                )
            ''')
            
            # Referrals table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    bonus_paid BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users(id),
                    FOREIGN KEY (referred_id) REFERENCES users(id),
                    UNIQUE(referred_id)
                )
            ''')
            
            # Withdrawals table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    method TEXT NOT NULL, -- 'bkash', 'nagad', 'rocket'
                    account_number TEXT NOT NULL,
                    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
                    admin_notes TEXT,
                    approved_by INTEGER,
                    approved_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Bonuses table (system bonuses)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bonuses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    type TEXT NOT NULL, -- 'daily_login', 'streak', 'weekly'
                    streak_days INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            
            # Admin settings table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admin_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Insert default admin settings
            await conn.execute('''
                INSERT OR IGNORE INTO admin_settings (key, value) 
                VALUES (?, ?)
            ''', ('admin_info', json.dumps(ADMIN_INFO)))
            
            await conn.execute('''
                INSERT OR IGNORE INTO admin_settings (key, value) 
                VALUES (?, ?)
            ''', ('earning_config', json.dumps(EARNING_CONFIG)))
            
            # Insert sample tasks
            sample_tasks = [
                ("YouTube Subscribe", "Subscribe to our YouTube channel", 10.0, "https://youtube.com"),
                ("Telegram Join", "Join our Telegram channel", 15.0, "https://t.me/example"),
                ("Facebook Like", "Like our Facebook page", 8.0, "https://facebook.com"),
            ]
            
            for title, desc, reward, url in sample_tasks:
                await conn.execute('''
                    INSERT OR IGNORE INTO tasks (title, description, reward, redirect_url)
                    VALUES (?, ?, ?, ?)
                ''', (title, desc, reward, url))
            
            await conn.commit()

# Initialize database
db = Database(DATABASE_URL)

# ============================================================================
# SECURITY: TELEGRAM WEB APP HASH VERIFICATION
# ============================================================================

def verify_telegram_hash(init_data: str, bot_token: str) -> bool:
    """Verify Telegram WebApp initData hash"""
    try:
        # Parse init data
        parsed = parse_qs(init_data)
        
        # Get hash and remove it from data
        hash_str = parsed.get('hash', [''])[0]
        if not hash_str:
            return False
        
        # Create data check string
        data_check = []
        for key in sorted(parsed.keys()):
            if key != 'hash':
                data_check.append(f"{key}={parsed[key][0]}")
        data_check_string = "\n".join(data_check)
        
        # Calculate secret key
        secret_key = hmac.new(
            key=b"WebAppData",
            msg=bot_token.encode(),
            digestmod=hashlib.sha256
        ).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(
            key=secret_key,
            msg=data_check_string.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        return calculated_hash == hash_str
    except:
        return False

def parse_init_data(init_data: str) -> Dict:
    """Parse Telegram WebApp initData to get user info"""
    parsed = parse_qs(init_data)
    user_data = parsed.get('user', ['{}'])[0]
    try:
        return json.loads(user_data)
    except:
        return {}

# ============================================================================
# BOT & FASTAPI SETUP
# ============================================================================

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Initialize FastAPI with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan for FastAPI app"""
    # Initialize database
    await db.init_db()
    
    # Start bot polling in background
    asyncio.create_task(start_bot())
    
    yield
    
    # Cleanup
    await bot.session.close()

app = FastAPI(lifespan=lifespan, title="EarnMoney BD Bot")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# DATABASE OPERATIONS
# ============================================================================

async def get_or_create_user(telegram_id: int, username: str = None, 
                           first_name: str = None, last_name: str = None,
                           referral_code: str = None) -> Dict:
    """Get or create user in database"""
    async with db.get_connection() as conn:
        # Check if user exists
        cursor = await conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        user = await cursor.fetchone()
        
        if user:
            # Update last login and check streak
            today = datetime.now().date()
            last_login = datetime.fromisoformat(user['last_login_date']) if user['last_login_date'] else None
            
            if last_login and last_login.date() == today:
                # Already logged in today
                streak = user['login_streak']
            elif last_login and (today - last_login.date()).days == 1:
                # Consecutive day
                streak = user['login_streak'] + 1
            else:
                # Streak broken
                streak = 1
            
            await conn.execute('''
                UPDATE users 
                SET last_login = CURRENT_TIMESTAMP,
                    last_login_date = DATE('now'),
                    login_streak = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            ''', (streak, telegram_id))
            
            # Add daily login bonus if it's a new day
            if last_login is None or last_login.date() != today:
                bonus_amount = EARNING_CONFIG['daily_login_bonus']
                await add_earning(telegram_id, bonus_amount, 'bonus', 'Daily Login Bonus')
            
            await conn.commit()
            
            # Return user as dict
            return dict(user)
        else:
            # Generate referral ID
            referral_id = secrets.token_urlsafe(8)[:8]
            
            # Check if referred by someone
            referred_by = None
            if referral_code:
                cursor = await conn.execute(
                    "SELECT id FROM users WHERE referral_id = ?",
                    (referral_code,)
                )
                referrer = await cursor.fetchone()
                if referrer:
                    referred_by = referrer['id']
            
            # Create new user
            await conn.execute('''
                INSERT INTO users 
                (telegram_id, username, first_name, last_name, referral_id, referred_by, last_login, last_login_date, login_streak)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, DATE('now'), 1)
            ''', (telegram_id, username, first_name, last_name, referral_id, referred_by))
            
            # If referred, add to referrals table
            if referred_by:
                await conn.execute('''
                    INSERT INTO referrals (referrer_id, referred_id)
                    VALUES (?, ?)
                ''', (referred_by, telegram_id))
                
                # Update referrer's count
                await conn.execute('''
                    UPDATE users 
                    SET referral_count = referral_count + 1,
                        active_referrals = active_referrals + 1
                    WHERE id = ?
                ''', (referred_by,))
            
            await conn.commit()
            
            # Get the newly created user
            cursor = await conn.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            new_user = await cursor.fetchone()
            return dict(new_user)

async def add_earning(user_id: int, amount: float, 
                     earning_type: str, description: str = None,
                     task_id: int = None, referral_id: int = None) -> bool:
    """Add earning record and update user balance"""
    async with db.get_connection() as conn:
        try:
            # Add earning record
            await conn.execute('''
                INSERT INTO earnings (user_id, amount, type, description, task_id, referral_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, amount, earning_type, description, task_id, referral_id))
            
            # Update user balance and total earned
            await conn.execute('''
                UPDATE users 
                SET balance = balance + ?,
                    total_earned = total_earned + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (amount, amount, user_id))
            
            # If referral earning, mark as paid
            if earning_type == 'referral' and referral_id:
                await conn.execute('''
                    UPDATE referrals 
                    SET bonus_paid = TRUE 
                    WHERE id = ?
                ''', (referral_id,))
            
            await conn.commit()
            return True
        except:
            await conn.rollback()
            return False

async def watch_ad(user_id: int) -> Dict:
    """Process ad watching with cooldown and limits"""
    async with db.get_connection() as conn:
        # Get user's ad status
        cursor = await conn.execute('''
            SELECT ads_watched_today, last_ad_watch 
            FROM users 
            WHERE id = ? AND is_banned = FALSE
        ''', (user_id,))
        user = await cursor.fetchone()
        
        if not user:
            return {"success": False, "message": "User not found or banned"}
        
        # Check daily limit
        if user['ads_watched_today'] >= EARNING_CONFIG['ad_daily_limit']:
            return {"success": False, "message": "Daily ad limit reached"}
        
        # Check cooldown
        if user['last_ad_watch']:
            last_watch = datetime.fromisoformat(user['last_ad_watch'])
            cooldown = timedelta(seconds=EARNING_CONFIG['ad_cooldown'])
            if datetime.now() - last_watch < cooldown:
                remaining = cooldown - (datetime.now() - last_watch)
                return {
                    "success": False, 
                    "message": f"Please wait {int(remaining.total_seconds())} seconds"
                }
        
        # Update user
        reward = EARNING_CONFIG['ad_reward']
        await conn.execute('''
            UPDATE users 
            SET balance = balance + ?,
                total_earned = total_earned + ?,
                ads_watched_today = ads_watched_today + 1,
                ads_watched_total = ads_watched_total + 1,
                last_ad_watch = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (reward, reward, user_id))
        
        # Add earning record
        await conn.execute('''
            INSERT INTO earnings (user_id, amount, type, description)
            VALUES (?, ?, 'ad', 'Ad Watching')
        ''', (user_id, reward))
        
        await conn.commit()
        
        return {
            "success": True,
            "reward": reward,
            "ads_watched": user['ads_watched_today'] + 1,
            "balance": await get_user_balance(user_id)
        }

async def get_user_balance(user_id: int) -> float:
    """Get user's current balance"""
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user_id,)
        )
        result = await cursor.fetchone()
        return result['balance'] if result else 0.0

async def get_user_stats(user_id: int) -> Dict:
    """Get comprehensive user statistics"""
    async with db.get_connection() as conn:
        # User info
        cursor = await conn.execute('''
            SELECT u.*, 
                   (SELECT COUNT(*) FROM referrals WHERE referrer_id = u.id) as total_refs,
                   (SELECT COUNT(*) FROM referrals WHERE referrer_id = u.id AND is_active = TRUE) as active_refs
            FROM users u
            WHERE u.id = ?
        ''', (user_id,))
        user = await cursor.fetchone()
        
        if not user:
            return {}
        
        # Today's earnings
        cursor = await conn.execute('''
            SELECT COALESCE(SUM(amount), 0) as today_earnings 
            FROM earnings 
            WHERE user_id = ? AND DATE(created_at) = DATE('now')
        ''', (user_id,))
        today = await cursor.fetchone()
        
        # Withdrawal stats
        cursor = await conn.execute('''
            SELECT COALESCE(SUM(amount), 0) as total_withdrawn,
                   COUNT(*) as total_withdrawals
            FROM withdrawals 
            WHERE user_id = ? AND status = 'approved'
        ''', (user_id,))
        withdraw = await cursor.fetchone()
        
        return {
            "balance": user['balance'],
            "total_earned": user['total_earned'],
            "today_earnings": today['today_earnings'],
            "ads_watched_today": user['ads_watched_today'],
            "ads_watched_total": user['ads_watched_total'],
            "referral_count": user['referral_count'],
            "active_referrals": user['active_referrals'],
            "total_withdrawn": withdraw['total_withdrawn'],
            "total_withdrawals": withdraw['total_withdrawals'],
            "login_streak": user['login_streak'],
            "referral_id": user['referral_id']
        }

# ============================================================================
# ADMIN FUNCTIONS
# ============================================================================

async def is_admin(telegram_id: int) -> bool:
    """Check if user is admin"""
    return telegram_id in ADMIN_IDS

async def get_all_users(page: int = 1, limit: int = 20) -> List[Dict]:
    """Get all users for admin panel"""
    offset = (page - 1) * limit
    async with db.get_connection() as conn:
        cursor = await conn.execute('''
            SELECT u.*, 
                   (SELECT COUNT(*) FROM referrals WHERE referrer_id = u.id) as ref_count,
                   (SELECT COUNT(*) FROM withdrawals WHERE user_id = u.id) as withdraw_count
            FROM users u
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def get_pending_withdrawals() -> List[Dict]:
    """Get pending withdrawals for admin approval"""
    async with db.get_connection() as conn:
        cursor = await conn.execute('''
            SELECT w.*, u.telegram_id, u.username, u.first_name
            FROM withdrawals w
            JOIN users u ON w.user_id = u.id
            WHERE w.status = 'pending'
            ORDER BY w.created_at DESC
        ''')
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def update_withdrawal_status(withdrawal_id: int, status: str, 
                                  admin_id: int, notes: str = None) -> bool:
    """Approve or reject withdrawal"""
    async with db.get_connection() as conn:
        try:
            if status == 'approved':
                await conn.execute('''
                    UPDATE withdrawals 
                    SET status = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP, admin_notes = ?
                    WHERE id = ?
                ''', (status, admin_id, notes, withdrawal_id))
                
                # Deduct from user balance
                cursor = await conn.execute(
                    "SELECT user_id, amount FROM withdrawals WHERE id = ?",
                    (withdrawal_id,)
                )
                wd = await cursor.fetchone()
                
                if wd:
                    await conn.execute('''
                        UPDATE users 
                        SET balance = balance - ?,
                            total_withdrawn = total_withdrawn + ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (wd['amount'], wd['amount'], wd['user_id']))
                    
                    # Notify user via bot
                    user_cursor = await conn.execute(
                        "SELECT telegram_id FROM users WHERE id = ?",
                        (wd['user_id'],)
                    )
                    user = await user_cursor.fetchone()
                    if user:
                        try:
                            await bot.send_message(
                                user['telegram_id'],
                                f"✅ আপনার {wd['amount']}৳ উত্তোলন অনুমোদিত হয়েছে!\n\n"
                                f"টাকা ২৪ ঘন্টার মধ্যে আপনার একাউন্টে জমা হবে।"
                            )
                        except:
                            pass
            
            elif status == 'rejected':
                await conn.execute('''
                    UPDATE withdrawals 
                    SET status = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP, admin_notes = ?
                    WHERE id = ?
                ''', (status, admin_id, notes, withdrawal_id))
                
                # Notify user
                cursor = await conn.execute(
                    "SELECT w.amount, u.telegram_id FROM withdrawals w JOIN users u ON w.user_id = u.id WHERE w.id = ?",
                    (withdrawal_id,)
                )
                wd = await cursor.fetchone()
                
                if wd:
                    try:
                        await bot.send_message(
                            wd['telegram_id'],
                            f"❌ আপনার {wd['amount']}৳ উত্তোলন প্রত্যাখ্যান হয়েছে।\n\n"
                            f"কারণ: {notes or 'অনির্দিষ্ট'}"
                        )
                    except:
                        pass
            
            await conn.commit()
            return True
        except Exception as e:
            await conn.rollback()
            print(f"Error updating withdrawal: {e}")
            return False

# ============================================================================
# TELEGRAM BOT HANDLERS
# ============================================================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    # Extract referral code from deep link
    referral_code = None
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
    
    # Register user
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        referral_code=referral_code
    )
    
    # Create keyboard with Web App button
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=f"{WEBAPP_URL}/app"))]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    
    # Send welcome message
    welcome_text = f"""
🎉 *স্বাগতম {message.from_user.first_name}!*

*EarnMoney BD* এ আপনাকে স্বাগতম! টাকা আয় করুন সহজেই:
✅ বিজ্ঞাপন দেখে আয় করুন
✅ টাস্ক সম্পূর্ণ করুন
✅ বন্ধুদের রেফার করুন
✅ উত্তোলন করুন সহজেই

*🎯 শুরু করতে নিচের বাটনে ক্লিক করুন:* 🚀 Open App

💰 *প্রথম উত্তোলন:* ১০০৳ (ন্যূনতম)
👥 *রেফারেল বোনাস:* ১০৳ প্রতি সক্রিয় রেফারেল
📱 *সাপোর্ট:* @cr_maim, @Huntervai1k
    """
    
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Admin command for admin panel"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ আপনি অ্যাডমিন নন!")
        return
    
    # Create admin keyboard
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👑 Admin Panel", web_app=WebAppInfo(url=f"{WEBAPP_URL}/admin"))],
            [KeyboardButton(text="🚀 User App", web_app=WebAppInfo(url=f"{WEBAPP_URL}/app"))]
        ],
        resize_keyboard=True
    )
    
    await message.answer(
        "👑 *অ্যাডমিন প্যানেল*\n\n"
        "নিচের বাটনে ক্লিক করে অ্যাডমিন প্যানেলে প্রবেশ করুন:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ============================================================================
# FASTAPI ROUTES - WEB APP BACKEND
# ============================================================================

# Dependency for Telegram WebApp authentication
async def verify_webapp(request: Request):
    """Verify Telegram WebApp initData"""
    init_data = request.headers.get("X-Telegram-Init-Data")
    if not init_data or not verify_telegram_hash(init_data, BOT_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid Telegram hash")
    return parse_init_data(init_data)

@app.get("/app")
async def serve_webapp():
    """Serve the main Web App HTML"""
    with open("webapp.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/admin")
async def serve_admin_panel():
    """Serve admin panel HTML"""
    with open("webapp.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

# ============================================================================
# API ENDPOINTS FOR WEB APP
# ============================================================================

@app.get("/api/user")
async def get_user_data(user_data: Dict = Depends(verify_webapp)):
    """Get user data for Web App"""
    telegram_id = user_data.get("id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="User ID not found")
    
    user = await get_or_create_user(
        telegram_id=telegram_id,
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name")
    )
    
    stats = await get_user_stats(user['id'])
    
    return {
        "success": True,
        "user": {
            "id": user['id'],
            "telegram_id": user['telegram_id'],
            "username": user['username'],
            "first_name": user['first_name'],
            "balance": user['balance'],
            "referral_id": user['referral_id'],
            "created_at": user['created_at']
        },
        "stats": stats,
        "config": EARNING_CONFIG,
        "admin_info": ADMIN_INFO
    }

@app.post("/api/watch-ad")
async def api_watch_ad(user_data: Dict = Depends(verify_webapp)):
    """Watch ad endpoint"""
    telegram_id = user_data.get("id")
    user = await get_or_create_user(telegram_id=telegram_id)
    
    result = await watch_ad(user['id'])
    return result

@app.get("/api/tasks")
async def api_get_tasks(user_data: Dict = Depends(verify_webapp)):
    """Get available tasks"""
    telegram_id = user_data.get("id")
    user = await get_or_create_user(telegram_id=telegram_id)
    
    async with db.get_connection() as conn:
        # Get all active tasks
        cursor = await conn.execute('''
            SELECT * FROM tasks WHERE is_active = TRUE
        ''')
        tasks = await cursor.fetchall()
        
        # Get user's completed tasks today
        cursor = await conn.execute('''
            SELECT task_id FROM user_tasks 
            WHERE user_id = ? AND DATE(completed_at) = DATE('now')
        ''', (user['id'],))
        completed = await cursor.fetchall()
        completed_ids = [row['task_id'] for row in completed]
        
        tasks_list = []
        for task in tasks:
            tasks_list.append({
                "id": task['id'],
                "title": task['title'],
                "description": task['description'],
                "reward": task['reward'],
                "redirect_url": task['redirect_url'],
                "completed": task['id'] in completed_ids
            })
        
        return {"success": True, "tasks": tasks_list}

@app.post("/api/complete-task/{task_id}")
async def api_complete_task(task_id: int, user_data: Dict = Depends(verify_webapp)):
    """Complete a task"""
    telegram_id = user_data.get("id")
    user = await get_or_create_user(telegram_id=telegram_id)
    
    async with db.get_connection() as conn:
        # Check if task exists and is active
        cursor = await conn.execute('''
            SELECT * FROM tasks WHERE id = ? AND is_active = TRUE
        ''', (task_id,))
        task = await cursor.fetchone()
        
        if not task:
            return {"success": False, "message": "Task not found"}
        
        # Check if already completed today
        cursor = await conn.execute('''
            SELECT * FROM user_tasks 
            WHERE user_id = ? AND task_id = ? AND DATE(completed_at) = DATE('now')
        ''', (user['id'], task_id))
        existing = await cursor.fetchone()
        
        if existing:
            return {"success": False, "message": "Already completed today"}
        
        # Check daily limit
        cursor = await conn.execute('''
            SELECT COUNT(*) as count FROM user_tasks 
            WHERE user_id = ? AND task_id = ? 
            AND DATE(completed_at) = DATE('now')
        ''', (user['id'], task_id))
        count = await cursor.fetchone()
        
        if count['count'] >= task['daily_limit']:
            return {"success": False, "message": "Daily limit reached"}
        
        # Add task completion
        await conn.execute('''
            INSERT INTO user_tasks (user_id, task_id)
            VALUES (?, ?)
        ''', (user['id'], task_id))
        
        # Add earning
        await add_earning(user['id'], task['reward'], 'task', task['title'], task_id)
        
        # Update task completion count
        await conn.execute('''
            UPDATE tasks 
            SET total_completions = total_completions + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (task_id,))
        
        await conn.commit()
        
        return {
            "success": True,
            "reward": task['reward'],
            "message": f"Task completed! {task['reward']}৳ added to your balance"
        }

@app.post("/api/withdraw")
async def api_withdraw(request: Request, user_data: Dict = Depends(verify_webapp)):
    """Create withdrawal request"""
    data = await request.json()
    method = data.get("method")
    amount = float(data.get("amount", 0))
    account = data.get("account_number")
    
    telegram_id = user_data.get("id")
    user = await get_or_create_user(telegram_id=telegram_id)
    
    # Validation
    if amount < EARNING_CONFIG['min_withdraw']:
        return {
            "success": False,
            "message": f"Minimum withdrawal is {EARNING_CONFIG['min_withdraw']}৳"
        }
    
    if user['balance'] < amount:
        return {"success": False, "message": "Insufficient balance"}
    
    if method not in ['bkash', 'nagad', 'rocket']:
        return {"success": False, "message": "Invalid method"}
    
    async with db.get_connection() as conn:
        # Create withdrawal request
        await conn.execute('''
            INSERT INTO withdrawals (user_id, amount, method, account_number)
            VALUES (?, ?, ?, ?)
        ''', (user['id'], amount, method, account))
        
        await conn.commit()
        
        # Notify admins
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🔄 নতুন উত্তোলন রিকুয়েস্ট!\n\n"
                    f"User: {user['first_name']} (@{user['username']})\n"
                    f"Amount: {amount}৳\n"
                    f"Method: {method}\n"
                    f"Account: {account}"
                )
            except:
                pass
        
        return {
            "success": True,
            "message": "Withdrawal request submitted. Admin approval required."
        }

@app.get("/api/history/{type}")
async def api_get_history(type: str, user_data: Dict = Depends(verify_webapp)):
    """Get user history"""
    telegram_id = user_data.get("id")
    user = await get_or_create_user(telegram_id=telegram_id)
    
    async with db.get_connection() as conn:
        if type == "earnings":
            cursor = await conn.execute('''
                SELECT * FROM earnings 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 50
            ''', (user['id'],))
        elif type == "withdrawals":
            cursor = await conn.execute('''
                SELECT * FROM withdrawals 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 50
            ''', (user['id'],))
        else:
            return {"success": False, "message": "Invalid history type"}
        
        rows = await cursor.fetchall()
        history = [dict(row) for row in rows]
        
        return {"success": True, "history": history}

# ============================================================================
# ADMIN API ENDPOINTS
# ============================================================================

@app.get("/api/admin/users")
async def admin_get_users(user_data: Dict = Depends(verify_webapp)):
    """Get all users (admin only)"""
    telegram_id = user_data.get("id")
    if not await is_admin(telegram_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    page = 1
    limit = 50
    users = await get_all_users(page, limit)
    
    return {"success": True, "users": users}

@app.get("/api/admin/withdrawals/pending")
async def admin_pending_withdrawals(user_data: Dict = Depends(verify_webapp)):
    """Get pending withdrawals (admin only)"""
    telegram_id = user_data.get("id")
    if not await is_admin(telegram_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    withdrawals = await get_pending_withdrawals()
    return {"success": True, "withdrawals": withdrawals}

@app.post("/api/admin/withdrawals/{withdrawal_id}/{action}")
async def admin_process_withdrawal(
    withdrawal_id: int, 
    action: str,
    request: Request,
    user_data: Dict = Depends(verify_webapp)
):
    """Approve or reject withdrawal (admin only)"""
    telegram_id = user_data.get("id")
    if not await is_admin(telegram_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    data = await request.json()
    notes = data.get("notes", "")
    
    # Get admin user ID
    user = await get_or_create_user(telegram_id=telegram_id)
    
    if action not in ["approve", "reject"]:
        return {"success": False, "message": "Invalid action"}
    
    status = "approved" if action == "approve" else "rejected"
    success = await update_withdrawal_status(withdrawal_id, status, user['id'], notes)
    
    if success:
        return {"success": True, "message": f"Withdrawal {status} successfully"}
    else:
        return {"success": False, "message": "Failed to process withdrawal"}

@app.post("/api/admin/user/{user_id}/ban")
async def admin_ban_user(user_id: int, user_data: Dict = Depends(verify_webapp)):
    """Ban/unban user (admin only)"""
    telegram_id = user_data.get("id")
    if not await is_admin(telegram_id):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    async with db.get_connection() as conn:
        # Toggle ban status
        await conn.execute('''
            UPDATE users 
            SET is_banned = NOT is_banned,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (user_id,))
        
        await conn.commit()
        
        # Get new status
        cursor = await conn.execute(
            "SELECT is_banned FROM users WHERE id = ?",
            (user_id,)
        )
        user = await cursor.fetchone()
        
        status = "banned" if user['is_banned'] else "unbanned"
        return {"success": True, "message": f"User {status} successfully"}

# ============================================================================
# STARTUP AND MAIN FUNCTION
# ============================================================================

async def start_bot():
    """Start Telegram bot polling"""
    print("🤖 Starting Telegram bot...")
    await dp.start_polling(bot)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"status": "online", "service": "EarnMoney BD Bot"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    # Run with uvicorn for production
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False
    )
