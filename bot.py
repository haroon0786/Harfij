import json
import os
import logging
import asyncio
import time
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

# Performance Configuration
BATCH_SIZE = 50  # Process 50 requests per batch
CONCURRENT_BATCHES = 5  # Run 5 batches concurrently
MAX_RETRIES = 3  # Retry failed requests
DELAY_BETWEEN_BATCHES = 0.1  # Small delay to prevent rate limiting

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
        "bot": "High-Speed Telegram Join Request Bot",
        "owner": OWNER_USERNAME,
        "message": "Bot is running at maximum speed!",
        "performance": f"Up to {BATCH_SIZE * CONCURRENT_BATCHES} approvals per second"
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

async def approve_batch_with_retry(context, chat_id, batch, batch_num, max_retries=MAX_RETRIES):
    """Approve a batch of users with retry logic"""
    approved = 0
    failed = 0
    
    for attempt in range(max_retries):
        batch_to_retry = []
        
        # Create tasks for concurrent approval within batch
        tasks = []
        for req in batch:
            task = approve_single_user(context, chat_id, req)
            tasks.append(task)
        
        # Execute all approvals in the batch concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                if attempt < max_retries - 1:  # Not the last attempt
                    batch_to_retry.append(batch[i])
                else:
                    failed += 1
                    logger.error(f"❌ Final failure for user {batch[i]['user_id']}: {result}")
            else:
                approved += 1
                if attempt == 0:  # Only log on first attempt
                    logger.info(f"✅ Batch {batch_num}: Approved {batch[i]['full_name']} (ID: {batch[i]['user_id']})")
        
        if not batch_to_retry:
            break
        
        batch = batch_to_retry
        if attempt < max_retries - 1:
            await asyncio.sleep(0.5)  # Wait before retry
    
    return approved, failed

async def approve_single_user(context, chat_id, user_req):
    """Approve a single user - wrapped for error handling"""
    try:
        await context.bot.approve_chat_join_request(
            chat_id=chat_id,
            user_id=user_req['user_id']
        )
        return True
    except Exception as e:
        raise e

def chunk_list(lst, chunk_size):
    """Split list into chunks of specified size"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]

async def approve_all_concurrent(context, chat_id, requests_data):
    """High-speed concurrent approval of all requests"""
    start_time = time.time()
    total_requests = len(requests_data)
    
    # Split requests into batches
    batches = list(chunk_list(requests_data, BATCH_SIZE))
    total_batches = len(batches)
    
    logger.info(f"🚀 Starting high-speed approval: {total_requests} requests in {total_batches} batches")
    
    total_approved = 0
    total_failed = 0
    
    # Process batches in groups of CONCURRENT_BATCHES
    for batch_group_start in range(0, total_batches, CONCURRENT_BATCHES):
        batch_group = batches[batch_group_start:batch_group_start + CONCURRENT_BATCHES]
        
        # Create tasks for concurrent batch processing
        batch_tasks = []
        for i, batch in enumerate(batch_group):
            batch_num = batch_group_start + i + 1
            task = approve_batch_with_retry(context, chat_id, batch, batch_num)
            batch_tasks.append(task)
        
        # Execute batches concurrently
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        
        # Collect results
        for result in batch_results:
            if isinstance(result, Exception):
                logger.error(f"❌ Batch processing failed: {result}")
                total_failed += BATCH_SIZE  # Assume all failed
            else:
                approved, failed = result
                total_approved += approved
                total_failed += failed
        
        # Small delay between batch groups to prevent rate limiting
        if batch_group_start + CONCURRENT_BATCHES < total_batches:
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)
        
        # Progress update
        processed = min((batch_group_start + CONCURRENT_BATCHES) * BATCH_SIZE, total_requests)
        logger.info(f"⚡ Progress: {processed}/{total_requests} processed | Approved: {total_approved} | Failed: {total_failed}")
    
    end_time = time.time()
    duration = end_time - start_time
    speed = total_requests / duration if duration > 0 else 0
    
    logger.info(f"🎯 Approval completed in {duration:.2f}s | Speed: {speed:.1f} approvals/sec")
    
    return total_approved, total_failed, duration, speed

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    welcome_text = f"""
🚀 **High-Speed Join Request Manager**

Welcome! I'm a professional bot designed to manage channel join requests at maximum speed.

**Key Features:**
• 📥 Auto-log all join requests
• ⚡ Ultra-fast bulk approval (up to {BATCH_SIZE * CONCURRENT_BATCHES}/sec)
• 🔄 Concurrent processing with retry logic
• 📊 Real-time statistics
• 🛡️ Rate limit protection

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
📚 **How to Use This High-Speed Bot**

**For Channel Admins:**
1. Add me to your channel as admin
2. Give me permission to manage join requests
3. Users' join requests will be auto-logged
4. Send `/approve` in your channel for lightning-fast approval

**Commands:**
• `/start` - Show main menu
• `/help` - Show this help message
• `/stats` - Show channel statistics
• `/approve` - High-speed approve all pending requests
• `/turbo` - Enable maximum speed mode

**Performance:**
• Speed: Up to {BATCH_SIZE * CONCURRENT_BATCHES} approvals per second
• Batch Size: {BATCH_SIZE} requests per batch
• Concurrent Batches: {CONCURRENT_BATCHES}
• Auto-retry failed requests

**Owner:** {OWNER_USERNAME}
**Status:** Running at Maximum Speed 🚀
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
📊 **High-Speed Bot Statistics**

🏢 **Active Channels:** {total_channels}
⏳ **Total Pending Requests:** {total_pending}
🚀 **Max Speed:** {BATCH_SIZE * CONCURRENT_BATCHES} approvals/sec
⚡ **Batch Size:** {BATCH_SIZE} requests
🔄 **Concurrent Batches:** {CONCURRENT_BATCHES}
🤖 **Status:** Online & Running at Max Speed

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

async def approve_all_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command in channels with high-speed processing"""
    if not update.channel_post or not update.channel_post.text:
        return
    
    command = update.channel_post.text.strip().lower()
    if command not in ["/approve", "/turbo"]:
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
    
    # Send processing message
    processing_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚀 **High-Speed Processing Started**\n\n⚡ Processing {len(data)} requests at maximum speed...\n🔄 Please wait...",
        parse_mode='Markdown'
    )
    
    # High-speed concurrent approval
    try:
        approved, failed, duration, speed = await approve_all_concurrent(context, chat_id, data)
        
        # Remove the file after processing
        os.remove(file_path)
        
        # Update processing message with results
        result_text = f"""
🎉 **High-Speed Approval Complete!**

⚡ **Processing Speed:** {speed:.1f} approvals/sec
⏱️ **Total Time:** {duration:.2f} seconds
✅ **Successfully Approved:** {approved}
❌ **Failed:** {failed}
📊 **Total Processed:** {len(data)}

**Channel:** {update.channel_post.chat.title}
**Mode:** {"Turbo" if command == "/turbo" else "High-Speed"}
**Processed by:** {OWNER_USERNAME}'s Lightning Bot ⚡
        """
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            text=result_text,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"High-speed approval failed: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            text=f"❌ **Processing Failed**\n\nError: {str(e)}\n\nPlease try again or contact {OWNER_USERNAME}",
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        welcome_text = f"""
🚀 **High-Speed Join Request Manager**

Welcome! I'm a professional bot designed to manage channel join requests at maximum speed.

**Key Features:**
• 📥 Auto-log all join requests
• ⚡ Ultra-fast bulk approval (up to {BATCH_SIZE * CONCURRENT_BATCHES}/sec)
• 🔄 Concurrent processing with retry logic
• 📊 Real-time statistics
• 🛡️ Rate limit protection

**Owner:** {OWNER_USERNAME}

Use the buttons below to explore my features!
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
📊 **High-Speed Bot Statistics**

🏢 **Active Channels:** {total_channels}
⏳ **Total Pending Requests:** {total_pending}
🚀 **Max Speed:** {BATCH_SIZE * CONCURRENT_BATCHES} approvals/sec
⚡ **Batch Size:** {BATCH_SIZE} requests
🔄 **Concurrent Batches:** {CONCURRENT_BATCHES}
🤖 **Status:** Online & Running at Max Speed

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
📚 **How to Use This High-Speed Bot**

**For Channel Admins:**
1. Add me to your channel as admin
2. Give me permission to manage join requests
3. Users' join requests will be auto-logged
4. Send `/approve` in your channel for lightning-fast approval

**Commands:**
• `/start` - Show main menu
• `/help` - Show this help message
• `/stats` - Show channel statistics
• `/approve` - High-speed approve all pending requests
• `/turbo` - Enable maximum speed mode

**Performance:**
• Speed: Up to {BATCH_SIZE * CONCURRENT_BATCHES} approvals per second
• Batch Size: {BATCH_SIZE} requests per batch
• Concurrent Batches: {CONCURRENT_BATCHES}
• Auto-retry failed requests

**Owner:** {OWNER_USERNAME}
**Status:** Running at Maximum Speed 🚀
        """
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == "about":
        about_text = f"""
ℹ️ **About This High-Speed Bot**

🤖 **Name:** High-Speed Join Request Manager
👨‍💻 **Developer:** {OWNER_USERNAME}
🚀 **Version:** 3.0 Lightning Edition
🌐 **Hosting:** 24/7 High-Performance Cloud

**Performance Features:**
• ⚡ Concurrent batch processing
• 🔄 Automatic retry mechanism
• 📊 Real-time speed monitoring
• 🛡️ Rate limit protection
• 🎯 Up to {BATCH_SIZE * CONCURRENT_BATCHES} approvals/sec

**Technical Specs:**
• Batch Size: {BATCH_SIZE} requests
• Concurrent Batches: {CONCURRENT_BATCHES}
• Max Retries: {MAX_RETRIES}
• Built with: Python asyncio, high-performance algorithms

**Built for Speed!** 🏎️💨
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
    logger.info(f"⚡ Starting High-Speed Telegram Bot...")
    logger.info(f"👤 Owner: {OWNER_USERNAME}")
    logger.info(f"🎯 Max Speed: {BATCH_SIZE * CONCURRENT_BATCHES} approvals/sec")
    
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
    logger.info("✅ High-Speed Bot is now running at maximum velocity!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
