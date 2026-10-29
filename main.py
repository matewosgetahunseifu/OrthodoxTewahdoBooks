import os
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from supabase import create_client, Client

# ==========================================
# 1. ማዋቀሪያ (Configuration)
# ==========================================
# Keep the fallback for your token, but prefer environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE"))
ADMIN_IDS = [7480368503]
ADMIN_USERNAME = "@Sealilenemariyammsle12we19"
ADMIN_EMAIL = "matewosgetahunseifu@gmail.com"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logger = logging.getLogger(__name__)
    logger.error("⚠️ SUPABASE_URL or SUPABASE_KEY is missing from Environment Variables!")
    supabase = None

# --- RENDER DUMMY SERVER ---
# Render requires a web server to be running on a port, otherwise it kills the bot.
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), BaseHTTPRequestHandler)
    server.serve_forever()

# Start the dummy server in a background thread
threading.Thread(target=run_dummy_server, daemon=True).start()

# ሎግ ማዋቀሪያ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ካታጎሪዎች
ALL_CATEGORIES = [
    'geez_law','geez_hist','geez_gdsl','geez_ot','geez_nt',
    'ga_law','ga_hist','ga_gdsl','ga_ot','ga_nt',
    'geez_edu',
    'amh_law','amh_hist','amh_gdsl','amh_eth','amh_ot','amh_nt',
    'amh_std','amh_chr','amh_mry','amh_snt','amh_thl',
    'eng_law','eng_hist','eng_eth','eng_ot','eng_gdsl',
    'eng_nt','eng_std','eng_chr','eng_mry','eng_snt','eng_thl'
]

# የአስተዳዳሪ ማከማቻ
add_book_sessions = {}

# ==========================================
# 2. የውሂብ ቤት (Database helpers)
# ==========================================
def is_admin(user_id):
    return user_id in ADMIN_IDS

async def get_books(category):
    """ሁሉንም መጽሐፍች በአንድ ካታጎሪ አመጣ"""
    if not supabase: return []
    try:
        result = supabase.table('books').select('*').eq('category', category).order('order', desc=False).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"get_books error: {e}")
        return []

async def get_book(book_id):
    """አንድ መጽሐፍ በID አመጣ"""
    if not supabase: return None
    try:
        result = supabase.table('books').select('*').eq('id', book_id).single().execute()
        return result.data
    except Exception:
        return None

async def add_book_to_db(book):
    """አዲስ መጽሐፍ ወደ DB ጨምር"""
    if not supabase: return None
    try:
        existing = supabase.table('books').select('order').eq('category', book['category']).order('order', desc=True).limit(1).execute()
        next_order = (existing.data[0]['order'] + 1) if existing.data else 1
        book['order'] = next_order
        result = supabase.table('books').insert(book).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"add_book error: {e}")
        return None

async def remove_book_from_db(book_id):
    if not supabase: return None
    try:
        result = supabase.table('books').delete().eq('id', book_id).execute()
        return result.data
    except Exception as e:
        logger.error(f"remove_book error: {e}")
        return None

async def reorder_books_in_db(category, ordered_ids):
    if not supabase: return False
    try:
        for i, book_id in enumerate(ordered_ids):
            supabase.table('books').update({'order': i + 1}).eq('id', book_id).execute()
        return True
    except Exception as e:
        logger.error(f"reorder error: {e}")
        return False

async def register_user(from_user):
    """ተጠቃሚ መዝግብ (ነጻ - ሁሉም ተጠቃሚዎች እኩል ናቸው)"""
    if not supabase: return
    try:
        supabase.table('users').upsert({
            'id': from_user.id,
            'username': f"@{from_user.username}" if from_user.username else "No Username",
            'is_paid': True,
            'registration_date': datetime.utcnow().isoformat(),
            'preferred_language': None,
            'total_downloads': 0,
            'books_downloaded': []
        }, on_conflict='id').execute()
    except Exception as e:
        logger.error(f"register_user error: {e}")

async def track_download(user_id, cat_key, book_id):
    """የማውረድ ቆጠራ መዝግብ"""
    if not supabase: return
    try:
        user_res = supabase.table('users').select('*').eq('id', user_id).single().execute()
        if user_res.data:
            user = user_res.data
            total = (user.get('total_downloads') or 0) + 1
            books = user.get('books_downloaded') or []
            book_key = f"{cat_key}_{book_id}"
            if book_key not in books:
                books.append(book_key)
            supabase.table('users').update({
                'total_downloads': total,
                'books_downloaded': books
            }).eq('id', user_id).execute()

        book_key = f"{cat_key}_{book_id}"
        stat_res = supabase.table('book_stats').select('*').eq('book_key', book_key).execute()
        if stat_res.data:
            new_count = (stat_res.data[0]['count'] or 0) + 1
            supabase.table('book_stats').update({'count': new_count, 'updated_at': datetime.utcnow().isoformat()}).eq('book_key', book_key).execute()
        else:
            supabase.table('book_stats').insert({'book_key': book_key, 'count': 1, 'updated_at': datetime.utcnow().isoformat()}).execute()
    except Exception as e:
        logger.error(f"track_download error: {e}")

# ==========================================
# 3. ዋና ምናሌ (Main keyboard)
# ==========================================
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 መጽሐፍት", callback_data="menu_books"),
         InlineKeyboardButton("🔍 መጽሐፍ ፈልግ", callback_data="menu_search")],
        [InlineKeyboardButton("📞 አግኙኝ", callback_data="menu_contact"),
         InlineKeyboardButton("💬 አስተያየት", callback_data="menu_feedback")],
        [InlineKeyboardButton("📊 ስታቲስቲክስ", callback_data="menu_stats"),
         InlineKeyboardButton("🔄 ዳግም ጀምር", callback_data="menu_restart")]
    ])

# ==========================================
# 4. /start
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await register_user(user)
    msg = (
        "እንኳን ወደ ታላቁ ዲጂታል መጽሐፍ ቦት በሰላም መጡ! 📚✨\n\n"
        "ይህ ቦት የኢትዮጵያ ኦርቶዶክስ ተዋሕዶ ቤተ ክርስቲያን መንፈሳዊ መጽሐፍትን በዲጂታል መልክ ያቀርባል።\n\n"
        "🎁 **ሁሉም መጽሐፍት ሙሉ በሙሉ ነጻ ናቸው!**\n\n"
        "📖 ከስር ያሉትን ቁልፎች በመጫን መጽሐፍትን ያስሱ።\n\n"
        "👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን"
    )
    await update.message.reply_text(msg, reply_markup=main_keyboard())

# ==========================================
# 5. ዋና ምናሌ አያያዥ
# ==========================================
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_books":
        keyboard = [
            [InlineKeyboardButton("በግዕዝ", callback_data="lang_geez"),
             InlineKeyboardButton("በግዕዝ አማርኛ", callback_data="lang_ga")],
            [InlineKeyboardButton("የግዕዝ ቋንቋ መማሪያ", callback_data="cat_geez_edu")],
            [InlineKeyboardButton("በአማርኛ", callback_data="lang_amh"),
             InlineKeyboardButton("In English", callback_data="lang_eng")]
        ]
        await query.edit_message_text("እባክዎን ቋንቋ ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "menu_contact":
        await query.edit_message_text(
            f"📞 **የአስተዳዳሪ መረጃ**\n\n"
            f"➖ ቴሌግራም: {ADMIN_USERNAME}\n"
            f"➖ ኢሜይል: {ADMIN_EMAIL}\n\n"
            f"ማንኛውንም ጥያቄ ወይም ችግር በላይኛው አድራሻ ያናግሩን።\n\n"
            f"👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን",
            parse_mode='Markdown'
        )

    elif data == "menu_feedback":
        await query.edit_message_text(
            f"💬 **አስተያየት ወይም ሀሳብ**\n\n"
            f"ሀሳብዎን ወይም ማሻሻያ ሀሳብዎን በሚከተሉት አድራሻዎች ያሳውቁን።\n\n"
            f"➖ ቴሌግራም: {ADMIN_USERNAME}\n"
            f"➖ ኢሜይል: {ADMIN_EMAIL}\n\n"
            f"አስተያየትዎ ውድ ነው! 🙏",
            parse_mode='Markdown'
        )

    elif data == "menu_stats":
        if not supabase:
            await query.edit_message_text("❌ የውሂብ ቤት ግንኙነት አልተሳካም።")
            return
        try:
            res = supabase.table('users').select('*').eq('id', update.effective_user.id).single().execute()
            user = res.data
            if not user:
                await query.edit_message_text("❌ መረጃ አልተገኘም።")
                return
            await query.edit_message_text(
                f"📊 **የእርስዎ መረጃ**\n\n"
                f"👤 ስም: {user.get('username', 'N/A')}\n"
                f"🎁 ነጻ ተጠቃሚ: ✅\n"
                f"📚 የወረዱ መጽሐፍት: {user.get('total_downloads', 0)}\n"
                f"📖 የተለያዩ መጽሐፍት: {len(user.get('books_downloaded', []))}\n\n"
                f"👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"stats error: {e}")
            await query.edit_message_text("❌ መረጃ ማግኘት አልተሳካም።")

    elif data == "menu_restart":
        await query.edit_message_text(
            "👋 እንኳን ወደ ቦቱ በሰላም ተመለሱ!\n\n"
            "🎁 ሁሉም መጽሐፍት ነጻ ናቸው!\n\n"
            "👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን",
            reply_markup=main_keyboard()
        )

# ==========================================
# 6. የቋንቋ ምናሌ
# ==========================================
async def language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "lang_geez":
        keyboard = [
            [InlineKeyboardButton("ሕግና ሥርዓት", callback_data="cat_geez_law")],
            [InlineKeyboardButton("ታሪክና ድርሳናት", callback_data="sub_geez_hist")],
            [InlineKeyboardButton("የመጽሐፍ ቅዱስ ክፍል", callback_data="sub_geez_bible")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="menu_books")]
        ]
        await query.edit_message_text("በግዕዝ ምድብ ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "lang_ga":
        keyboard = [
            [InlineKeyboardButton("ሕግና ሥርዓት", callback_data="cat_ga_law")],
            [InlineKeyboardButton("ታሪክና ድርሳናት", callback_data="sub_ga_hist")],
            [InlineKeyboardButton("የመጽሐፍ ቅዱስ ክፍል", callback_data="sub_ga_bible")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="menu_books")]
        ]
        await query.edit_message_text("በግዕዝ አማርኛ ምድብ ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "lang_amh":
        keyboard = [
            [InlineKeyboardButton("ሕግና ሥርዓት", callback_data="cat_amh_law")],
            [InlineKeyboardButton("ታሪክና ድርሳናት", callback_data="sub_amh_hist")],
            [InlineKeyboardButton("ክርስቲያናዊ ሥነ ምግባር", callback_data="cat_amh_eth")],
            [InlineKeyboardButton("የመጽሐፍ ቅዱስ ጥናት", callback_data="sub_amh_bible")],
            [InlineKeyboardButton("ነገረ ሃይማኖት", callback_data="sub_amh_theology")],
            [InlineKeyboardButton("⬅️ ተመለስ", callback_data="menu_books")]
        ]
        await query.edit_message_text("በአማርኛ ምድብ ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "lang_eng":
        keyboard = [
            [InlineKeyboardButton("Law & Order", callback_data="cat_eng_law")],
            [InlineKeyboardButton("History & Discourse", callback_data="sub_eng_hist")],
            [InlineKeyboardButton("Christian Ethics", callback_data="cat_eng_eth")],
            [InlineKeyboardButton("Bible Study", callback_data="sub_eng_bible")],
            [InlineKeyboardButton("Theology & Dogma", callback_data="sub_eng_theology")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu_books")]
        ]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(keyboard))

    # Sub-menus
    elif data == "sub_geez_hist":
        kb = [[InlineKeyboardButton("ታሪክ", callback_data="cat_geez_hist")],
              [InlineKeyboardButton("ገድል ተአምር ድርሳን", callback_data="cat_geez_gdsl")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_geez")]]
        await query.edit_message_text("ከታሪክና ድርሳናት ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_geez_bible":
        kb = [[InlineKeyboardButton("ብሉይ ኪዳን", callback_data="cat_geez_ot")],
              [InlineKeyboardButton("ሐዲስ ኪዳን", callback_data="cat_geez_nt")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_geez")]]
        await query.edit_message_text("ከመጽሐፍ ቅዱስ ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_ga_hist":
        kb = [[InlineKeyboardButton("ታሪክ", callback_data="cat_ga_hist")],
              [InlineKeyboardButton("ገድል ተአምር ድርሳን", callback_data="cat_ga_gdsl")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_ga")]]
        await query.edit_message_text("ከታሪክና ድርሳናት ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_ga_bible":
        kb = [[InlineKeyboardButton("ብሉይ ኪዳን", callback_data="cat_ga_ot")],
              [InlineKeyboardButton("ሐዲስ ኪዳን", callback_data="cat_ga_nt")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_ga")]]
        await query.edit_message_text("ከመጽሐፍ ቅዱስ ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_amh_hist":
        kb = [[InlineKeyboardButton("ታሪክ", callback_data="cat_amh_hist")],
              [InlineKeyboardButton("ድርሳን ተአምር ገድላት", callback_data="cat_amh_gdsl")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_amh")]]
        await query.edit_message_text("ከታሪክና ድርሳናት ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_amh_bible":
        kb = [[InlineKeyboardButton("ብሉይ ኪዳን", callback_data="cat_amh_ot")],
              [InlineKeyboardButton("ሐዲስ ኪዳን", callback_data="cat_amh_nt")],
              [InlineKeyboardButton("መጽሐፍ ቅዱስ ጥናት", callback_data="cat_amh_std")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_amh")]]
        await query.edit_message_text("ከመጽሐፍ ቅዱስ ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_amh_theology":
        kb = [[InlineKeyboardButton("ነገረ ክርስቶስ", callback_data="cat_amh_chr")],
              [InlineKeyboardButton("ነገረ ማርያም", callback_data="cat_amh_mry")],
              [InlineKeyboardButton("ነገረ ቅዱሳን", callback_data="cat_amh_snt")],
              [InlineKeyboardButton("ነገረ ሃይማኖት", callback_data="cat_amh_thl")],
              [InlineKeyboardButton("⬅️ ተመለስ", callback_data="lang_amh")]]
        await query.edit_message_text("ከነገረ ሃይማኖት ይምረጡ:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_eng_hist":
        kb = [[InlineKeyboardButton("History", callback_data="cat_eng_hist")],
              [InlineKeyboardButton("Discourse & Miracles", callback_data="cat_eng_gdsl")],
              [InlineKeyboardButton("⬅️ Back", callback_data="lang_eng")]]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_eng_bible":
        kb = [[InlineKeyboardButton("Old Testament", callback_data="cat_eng_ot")],
              [InlineKeyboardButton("New Testament", callback_data="cat_eng_nt")],
              [InlineKeyboardButton("General Bible Study", callback_data="cat_eng_std")],
              [InlineKeyboardButton("⬅️ Back", callback_data="lang_eng")]]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "sub_eng_theology":
        kb = [[InlineKeyboardButton("Christology", callback_data="cat_eng_chr")],
              [InlineKeyboardButton("Mariology", callback_data="cat_eng_mry")],
              [InlineKeyboardButton("Hagiography", callback_data="cat_eng_snt")],
              [InlineKeyboardButton("Theology", callback_data="cat_eng_thl")],
              [InlineKeyboardButton("⬅️ Back", callback_data="lang_eng")]]
        await query.edit_message_text("Select category:", reply_markup=InlineKeyboardMarkup(kb))

# ==========================================
# 7. የካታጎሪ መጽሐፍት ዝርዝር
# ==========================================
async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_key = query.data.replace("cat_", "", 1)
    books = await get_books(cat_key)
    if not books:
        await query.edit_message_text(
            "ምንም መጽሐፍ የለም።",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ ተመለስ", callback_data="menu_books")]])
        )
        return
    buttons = []
    for i, book in enumerate(books, start=1):
        buttons.append([InlineKeyboardButton(f"{i}. {book['title']}", callback_data=f"gb_{cat_key}_{book['id']}")])
    buttons.append([InlineKeyboardButton("⬅️ ተመለስ", callback_data="menu_books")])
    await query.edit_message_text("መጽሐፍ ይምረጡ:", reply_markup=InlineKeyboardMarkup(buttons))

# ==========================================
# 8. መጽሐፍ ማውረድ (ሁሉም ነጻ!)
# ==========================================
async def book_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace("gb_", "", 1).rsplit("_", 1)
    cat_key, book_id = parts[0], parts[1]
    book = await get_book(book_id)
    if not book:
        await query.edit_message_text("❌ መጽሐፉ አልተገኘም።")
        return

    try:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=book['file_id'],
            caption=f"📖 {book['title']}\n\n🎁 ሙሉ በሙሉ ነጻ! መልካም ንባብ! 📚✨\n\n👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን",
            protect_content=True
        )
        await track_download(query.from_user.id, cat_key, book_id)
    except Exception as e:
        logger.error(f"send book error: {e}")
        await query.message.reply_text(f"❌ መጽሐፉን መላክ አልተሳካም። ({str(e)})")

# ==========================================
# 9. ፍለጋ (Search)
# ==========================================
async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔍 እባክዎትን የመጽሐፍ ስም ያስገቡ:",
    )

async def text_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if not text:
        return
    results = []
    for cat in ALL_CATEGORIES:
        books = await get_books(cat)
        for b in books:
            if text in b['title'].lower():
                results.append((cat, b))
    if not results:
        await update.message.reply_text(f'🔍 "{text}" ምንም ውጤት አልተገኘም።')
        return
    buttons = []
    for i, (cat, b) in enumerate(results[:20], start=1):
        buttons.append([InlineKeyboardButton(f"{i}. {b['title']}", callback_data=f"gb_{cat}_{b['id']}")])
    await update.message.reply_text(
        f"🔍 {len(results)} ውጤቶች:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ==========================================
# 10. /addbook (ብዙ መጽሐፍት በአንድ ጊዜ!)
# ==========================================
async def add_book_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ ይህ ትዕዛዝ ለአስተዳዳሪ ብቻ ነው!")
        return

    if user_id in add_book_sessions:
        await update.message.reply_text("⚠️ አሁን መጽሐፍ እየጨመሩ ነው! /canceladd ይጠቀሙ።")
        return

    add_book_sessions[user_id] = {'step': 'category', 'category': None, 'titles': [], 'files': []}

    kb = []
    row = []
    for i, cat in enumerate(ALL_CATEGORIES):
        row.append(InlineKeyboardButton(cat, callback_data=f"addcat_{cat}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    await update.message.reply_text(
        "📚 **አዲስ መጽሐፍት መጨመር**\n\n"
        "1️⃣ **ካታጎሪ ምረጥ**\n\n"
        "ካታጎሪ ከስር ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode='Markdown'
    )

async def addcat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in add_book_sessions:
        await query.edit_message_text("⚠️ እባክዎትን /addbook ይጠቀሙ።")
        return

    category = query.data.replace("addcat_", "", 1)
    add_book_sessions[user_id]['category'] = category
    add_book_sessions[user_id]['step'] = 'titles'

    await query.edit_message_text(
        f"✅ ካታጎሪ: `{category}`\n\n"
        f"2️⃣ **ርዕሶችን አስገባ**\n\n"
        f"የመጽሐፎቹን ርዕሶች አንድ በአንድ ይጻፉ (እያንዳንዱን በአዲስ መስመር):\n\n"
        f"ለምሳሌ:\n"
        f"`ድርሳነ ሚካኤል`\n"
        f"`ድርሳነ ገብርኤል`\n"
        f"`መዝሙረ ዳዊት`\n\n"
        f"ሲጨርሱ `/done` ይጻፉ።",
        parse_mode='Markdown'
    )

async def add_titles_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in add_book_sessions:
        return
    if add_book_sessions[user_id]['step'] != 'titles':
        return

    text = update.message.text.strip()

    if text == '/done':
        titles = add_book_sessions[user_id]['titles']
        if not titles:
            await update.message.reply_text("⚠️ ምንም ርዕስ አልገቡም። እባክዎትን ቢያንስ አንድ ርዕስ ይጻፉ።")
            return
        add_book_sessions[user_id]['step'] = 'files'
        add_book_sessions[user_id]['files'] = []
        await update.message.reply_text(
            f"✅ {len(titles)} ርዕሶች ተቀምጠዋል!\n\n"
            f"3️⃣ **ፋይሎችን ላክ**\n\n"
            f"አሁን {len(titles)} ፋይሎችን በተመሳሳይ ቅደም ተከተል ላኩ፦\n\n"
            f"`1. {titles[0]}`\n" +
            "\n".join([f"`{i+1}. {t}`" for i, t in enumerate(titles[1:], start=1)]) +
            f"\n\n📎 ፋይል 1 → ርዕስ 1\n"
            f"📎 ፋይል 2 → ርዕስ 2\n"
            f"....\n\n"
            f"⚠️ በትክክል {len(titles)} ፋይሎች መላክ አለብዎት።\n"
            f"📤 ፋይሎችን አሁን ይላኩ:",
            parse_mode='Markdown'
        )
        return

    add_book_sessions[user_id]['titles'].append(text)
    count = len(add_book_sessions[user_id]['titles'])
    await update.message.reply_text(
        f"✅ ርዕስ #{count} ተጨምሯል: `{text}`\n\n"
        f"ሌላ ርዕስ ይጻፉ ወይም `/done` ይጻፉ።",
        parse_mode='Markdown'
    )

async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in add_book_sessions:
        return
    if add_book_sessions[user_id]['step'] != 'files':
        return

    session = add_book_sessions[user_id]
    file_id = None
    if update.message.document:
        file_id = update.message.document.file_id
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.video:
        file_id = update.message.video.file_id
    elif update.message.audio:
        file_id = update.message.audio.file_id
    elif update.message.voice:
        file_id = update.message.voice.file_id

    if not file_id:
        await update.message.reply_text("⚠️ ይህ ፋይል አልተቀበለም። እባክዎትን ሌላ ይላኩ።")
        return

    session['files'].append(file_id)
    received = len(session['files'])
    total = len(session['titles'])

    await update.message.reply_text(f"📎 ፋይል #{received}/{total} ተቀብለናል።")

    if received == total:
        await update.message.reply_text("⏳ እያስቀመጥን ነው...")
        added = 0
        for i, title in enumerate(session['titles']):
            book = {
                'category': session['category'],
                'file_id': session['files'][i],
                'title': title,
                'preview': 'Preview not available',
                'preview_files': []
            }
            result = await add_book_to_db(book)
            if result:
                added += 1

        await update.message.reply_text(
            f"✅ **{added} መጽሐፍት በተሳካ ሁኔታ ተመዝግበዋል!**\n\n"
            f"📂 ካታጎሪ: `{session['category']}`\n\n"
            f"📄 ርዕሶች:\n" +
            "\n".join([f"   {i+1}. {t}" for i, t in enumerate(session['titles'])]) +
            f"\n\n🎁 ሁሉም መጽሐፍት ለሁሉም ተጠቃሚዎች ነጻ ናቸው!\n\n"
            f"👨‍💻 የቦቱ አዘጋጅ ዲያቆን ማቴዎስ ጌታሁን",
            parse_mode='Markdown'
        )
        del add_book_sessions[user_id]

async def cancel_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in add_book_sessions:
        del add_book_sessions[user_id]
        await update.message.reply_text("❌ መጽሐፍ መጨመር ተሰርዟል።")
    else:
        await update.message.reply_text("⚠️ ምንም እየተጨመረ ያለ መጽሐፍ የለም።")

# ==========================================
# 11. /removebook
# ==========================================
async def remove_book_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ለአስተዳዳሪ ብቻ!")
        return
    await update.message.reply_text(
        "🗑️ የሚሰረዘውን መጽሐፍ ID ይላኩ:\n"
        "ለምሳሌ: `amh_law_1`",
        parse_mode='Markdown'
    )
    add_book_sessions[update.effective_user.id] = {'step': 'remove'}

async def remove_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in add_book_sessions:
        return
    if add_book_sessions[user_id]['step'] != 'remove':
        return
    book_id = update.message.text.strip()
    book = await get_book(book_id)
    if not book:
        await update.message.reply_text(f"❌ ID `{book_id}` ያለው መጽሐፍ አልተገኘም።")
        del add_book_sessions[user_id]
        return
    await remove_book_from_db(book_id)
    await update.message.reply_text(f"✅ `{book_id}` ተሰርዟል።")
    del add_book_sessions[user_id]

# ==========================================
# 12. /orderbook
# ==========================================
async def order_book_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ለአስተዳዳሪ ብቻ!")
        return
    await update.message.reply_text(
        "🔄 ካታጎሪ እና አዲስ ቅደም ተከተል ይላኩ:\n"
        "ለምሳሌ: `amh_law 3 1 5 2 4`",
        parse_mode='Markdown'
    )
    add_book_sessions[update.effective_user.id] = {'step': 'order'}

async def order_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in add_book_sessions:
        return
    if add_book_sessions[user_id]['step'] != 'order':
        return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("⚠️ ምሳሌ: `amh_law 3 1 5 2 4`", parse_mode='Markdown')
        del add_book_sessions[user_id]
        return
    category, ordered_ids = parts[0], parts[1:]
    ok = await reorder_books_in_db(category, ordered_ids)
    if ok:
        await update.message.reply_text(f"✅ በ `{category}` ቅደም ተከተል ተደራጅቷል።")
    else:
        await update.message.reply_text("❌ ማደራጀት አልተሳካም።")
    del add_book_sessions[user_id]

# ==========================================
# 13. ትዕዛዞች: /bookcount, /random, /stats, /backup
# ==========================================
async def book_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = 0
    msg = "📚 **የመጽሐፍ ብዛት**\n\n"
    any_books = False
    for cat in ALL_CATEGORIES:
        books = await get_books(cat)
        valid = [b for b in books if b.get('title') and b['title'].strip()]
        if valid:
            any_books = True
            total += len(valid)
            msg += f"• {cat}: {len(valid)}\n"
    if not any_books:
        await update.message.reply_text("📚 ምንም መጽሐፍ አልተገኘም።")
        return
    msg += f"\n*ጠቅላላ: {total}*"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def random_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_books = []
    for cat in ALL_CATEGORIES:
        books = await get_books(cat)
        all_books.extend([(cat, b) for b in books if b.get('title')])
    if not all_books:
        await update.message.reply_text("📚 ምንም መጽሐፍ የለም።")
        return
    import random
    cat, book = random.choice(all_books)
    await update.message.reply_text(
        f"📖 **የዘፈቀደ መጽሐፍ**\n\n📕 {book['title']}\n📂 {cat}\n🆔 {book['id']}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📖 አንብብ", callback_data=f"gb_{cat}_{book['id']}")]])
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not supabase: return
    try:
        res = supabase.table('users').select('*').execute()
        total = len(res.data or [])
    except Exception:
        total = 0
    await update.message.reply_text(f"📊 **የቦት መረጃ**\n\n👤 ጠቅላላ ተጠቃሚዎች: {total}\n🎁 ሁሉም ነጻ ናቸው!", parse_mode='Markdown')

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not supabase: return
    await update.message.reply_text("💾 ምትኬ በመስራት ላይ...")
    try:
        users = supabase.table('users').select('*').execute().data or []
        books = supabase.table('books').select('*').execute().data or []
        stats = supabase.table('book_stats').select('*').execute().data or []
        data = {'users': users, 'books': books, 'book_stats': stats}
        file_path = f"backup_{int(datetime.utcnow().timestamp())}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open(file_path, 'rb') as f:
            await update.message.reply_document(document=f, caption="📦 የውሂብ ምትኬ")
        os.remove(file_path)
    except Exception as e:
        logger.error(f"backup error: {e}")
        await update.message.reply_text(f"❌ ምትኬ አልተሳካም: {e}")

# ==========================================
# 14. ዋና ማስጀመሪያ (Main)
# ==========================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in add_book_sessions:
        step = add_book_sessions[user_id]['step']
        if step == 'titles':
            await add_titles_handler(update, context)
            return
        if step == 'remove':
            await remove_text(update, context)
            return
        if step == 'order':
            await order_text(update, context)
            return
        if step == 'files':
            await update.message.reply_text("📤 እባክዎትን ፋይሎችን ይላኩ (ጽሑፍ አይቀበልም)።")
            return
    # ፍለጋ
    await text_search(update, context)

def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("⚠️ BOT_TOKEN is missing! Please set it in Render Environment Variables.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("addbook", add_book_command))
    app.add_handler(CommandHandler("canceladd", cancel_add_command))
    app.add_handler(CommandHandler("removebook", remove_book_command))
    app.add_handler(CommandHandler("orderbook", order_book_command))
    app.add_handler(CommandHandler("bookcount", book_count))
    app.add_handler(CommandHandler("random", random_book))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("backup", backup_command))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(language_handler, pattern="^(lang_|sub_)"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(book_handler, pattern="^gb_"))
    app.add_handler(CallbackQueryHandler(addcat_handler, pattern="^addcat_"))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
        file_handler
    ))

    logger.info("🤖 Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()