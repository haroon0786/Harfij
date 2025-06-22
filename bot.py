import json
import os
import logging
from threading import Thread
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ChatJoinRequestHandler,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Configuration
BOT_TOKEN = '7822722074:AAEKmQYZL9kUQJuQ9Bz_4Wy1tsPYZASgt5E'
OWNER_USERNAME = '@OGxCODEX'
DATA_DIR = 'pending_requests'
PORT = int(os.environ.get('PORT', 8000))

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask app for keeping the service alive
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "active",
        "bot": "Professional Telegram Join Request Bot",
        "owner": OWNER_USERNAME,
        "message": "Bot is running successfully!"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "uptime": "running"})

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

def save_request(chat_id, user_data):
    """Save join request with user details"""
    file_path = os.path.join(DATA_DIR, f'{chat_id}.json')
    
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = []
    
    # Check if user already exists
    if not any(req['user_id'] == user_data['user_id'] for req in data):
        data.append(user_data)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    return False

def get_pending_count(chat_id):
    """Get count of pending requests for a channel"""
    file_path = os.path.join(DATA_DIR, f'{chat_id}.json')
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return len(data)
    return 0

def create_main_keyboard():
    """Create inline keyboard for bot features"""
    keyboard = [
        [
            InlineKeyboardButton("📊 Channel Stats", callback_data="stats"),
            InlineKeyboardButton("➕ Add to Channel", url=f"https://t.me/TeleApproveUserBot?startchannel=new&admin=invite_users+restrict_members+manage_chat+post_messages+delete_messages+edit_messages")
        ],
        [
            InlineKeyboardButton("👤 Owner", url=f"https://t.me/{OWNER_USERNAME[1:]}")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
            InlineKeyboardButton("ℹ️ About", callback_data="about")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = f"""
🤖 **Professional Join Request Manager**

Welcome! I'm a professional bot designed to manage channel join requests efficiently.

**Key Features:**
• 📥 Auto-log all join requests
• ✅ Bulk approve with /approve command
• 📊 Real-time statistics
• 🔄 Always active and reliable

**Owner:** {OWNER_USERNAME}

Use the buttons below to explore my features!
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=create_main_keyboard(),
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = f"""
📚 **How to Use This Bot**

**For Channel Admins:**
1. Add me to your channel as admin
2. Give me permission to manage join requests
3. Users' join requests will be auto-logged
4. Send `/approve` in your channel to approve all pending requests

**Commands:**
• `/start` - Show main menu
• `/help` - Show this help message
• `/stats` - Show channel statistics
• `/approve` - Approve all pending requests (channel only)

**Owner:** {OWNER_USERNAME}
**Status:** Always Active 🟢
    """
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    total_channels = len([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])
    total_pending = 0
    
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            chat_id = filename.replace('.json', '')
            total_pending += get_pending_count(chat_id)
    
    stats_text = f"""
📊 **Bot Statistics**

🤖 **Status:** Online & Active
🔄 **Uptime:** 24/7

**Owner:** {OWNER_USERNAME}
    """
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
    
    await update.message.reply_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def log_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log join requests with detailed info"""
    user = update.chat_join_request.from_user
    chat = update.chat_join_request.chat
    
    user_data = {
        'user_id': user.id,
        'full_name': user.full_name,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_bot': user.is_bot,
        'language_code': user.language_code,
        'timestamp': update.chat_join_request.date.isoformat()
    }
    
    if save_request(chat.id, user_data):
        logger.info(f"📥 New join request in {chat.title} (ID: {chat.id})")
        logger.info(f"👤 {user.full_name} | @{user.username or 'No username'} | ID: {user.id}")
        
        # Send notification to channel (optional)
        pending_count = get_pending_count(chat.id)
        notification = f""
        
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=notification,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Could not send notification: {e}")

async def approve_all_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command in channels"""
    if not update.channel_post or update.channel_post.text.strip() != "/approve":
        return
    
    chat_id = update.channel_post.chat.id
    file_path = os.path.join(DATA_DIR, f'{chat_id}.json')
    
    if not os.path.exists(file_path):
        await context.bot.send_message(
            chat_id=chat_id, 
            text="⚠️ No pending join requests found for this channel."
        )
        return
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not data:
        await context.bot.send_message(
            chat_id=chat_id, 
            text="⚠️ No pending requests to approve."
        )
        return
    
    approved = 0
    failed = 0
    
    for req in data:
        try:
            await context.bot.approve_chat_join_request(
                chat_id=chat_id, 
                user_id=req['user_id']
            )
            approved += 1
            logger.info(f"✅ Approved user {req['full_name']} (ID: {req['user_id']})")
        except Exception as e:
            failed += 1
            logger.error(f"❌ Failed to approve {req['user_id']}: {e}")
    
    # Remove the file after processing
    os.remove(file_path)
    
    result_text = f"""
🎉 **Approval Complete!**

✅ **Successfully Approved:** {approved}
❌ **Failed:** {failed}
📊 **Total Processed:** {len(data)}

**Channel:** {update.channel_post.chat.title}
**Processed by:** {OWNER_USERNAME}'s Bot
    """
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text=result_text,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        welcome_text = f"""
🤖 **ᴘʀᴏꜰᴇꜱꜱɪᴏɴᴀʟ ᴊᴏɪɴ ʀᴇQᴜᴇꜱᴛ ᴍᴀɴᴀɢᴇʀ**

 ᴡᴇʟᴄᴏᴍᴇ! ɪ'ᴍ ᴀ ᴘʀᴏꜰᴇꜱꜱɪᴏɴᴀʟ ʙᴏᴛ ᴅᴇꜱɪɢɴᴇᴅ ᴛᴏ ᴍᴀɴᴀɢᴇ ᴄʜᴀɴɴᴇʟ ᴊᴏɪɴ ʀᴇQᴜᴇꜱᴛꜱ ᴇꜰꜰɪᴄɪᴇɴᴛʟʏ.  **ᴋᴇʏ ꜰᴇᴀᴛᴜʀᴇꜱ:** 
 • 📥 ᴀᴜᴛᴏ-ʟᴏɢ ᴀʟʟ ᴊᴏɪɴ ʀᴇQᴜᴇꜱᴛꜱ 
 • ✅ ʙᴜʟᴋ ᴀᴘᴘʀᴏᴠᴇ ᴡɪᴛʜ /ᴀᴘᴘʀᴏᴠᴇ ᴄᴏᴍᴍᴀɴᴅ • 📊 ʀᴇᴀʟ-ᴛɪᴍᴇ ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ 
 • 🔄 ᴀʟᴡᴀʏꜱ ᴀᴄᴛɪᴠᴇ ᴀɴᴅ ʀᴇʟɪᴀʙʟᴇ  
 **ᴏᴡɴᴇʀ:** {ᴏᴡɴᴇʀ_ᴜꜱᴇʀɴᴀᴍᴇ}  ᴜꜱᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴꜱ ʙᴇʟᴏᴡ ᴛᴏ ᴇxᴘʟᴏʀᴇ ᴍʏ ꜰᴇᴀᴛᴜʀᴇꜱ!
        """
        await query.edit_message_text(
            welcome_text,
            reply_markup=create_main_keyboard(),
            parse_mode='Markdown'
        )
    
    elif query.data == "stats":
        total_channels = len([f for f in os.listdir(DATA_DIR) if f.endswith('.json')])
        total_pending = sum(get_pending_count(f.replace('.json', '')) 
                          for f in os.listdir(DATA_DIR) if f.endswith('.json'))
        
        stats_text = f"""
📊 **Bot Statistics**

🏢 **Active Channels:** {total_channels}
⏳ **Total Pending Requests:** {total_pending}
🤖 **Status:** Online & Active
🔄 **Uptime:** 24/7

**Owner:** {OWNER_USERNAME}
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "help":
        help_text = f"""
📚 **How to Use This Bot**

**For Channel Admins:**
1. Add me to your channel as admin
2. Give me permission to manage join requests
3. Users' join requests will be auto-logged
4. Send `/approve` in your channel to approve all pending requests

**Commands:**
• `/start` - Show main menu
• `/help` - Show this help message
• `/stats` - Show channel statistics
• `/approve` - Approve all pending requests (channel only)

**Owner:** {OWNER_USERNAME}
**Status:** Always Active 🟢
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "about":
        about_text = f"""
ℹ️ **About This Bot**

🤖 **Name:** Professional Join Request Manager
👨‍💻 **Developer:** {OWNER_USERNAME}
🚀 **Version:** 2.0 Professional
🌐 **Hosting:** 24/7 Cloud Deployment

**Features:**
• Professional interface with inline buttons
• Real-time join request logging
• Bulk approval system
• Statistics tracking
• Always active deployment
• Error handling & logging
• Multi-channel support

**Built with:** Python, python-telegram-bot, Flask
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(
            about_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

def run_flask():
    """Run Flask server in a separate thread"""
    app.run(host='0.0.0.0', port=PORT, debug=False)

def main():
    """Main function to run the bot"""
    # Start Flask server in background
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    logger.info(f"🚀 Flask server started on port {PORT}")
    logger.info(f"🤖 Starting Telegram Bot...")
    logger.info(f"👤 Owner: {OWNER_USERNAME}")
    
    # Build application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(ChatJoinRequestHandler(log_join_request))
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, approve_all_channel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start bot
    logger.info("✅ Bot is now running and ready to serve!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
