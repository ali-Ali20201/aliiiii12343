import sqlite3
import logging
import re
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.constants import ParseMode

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------- الثوابت والمتغيرات ---------------------

# تم وضع توكن البوت الخاص بك هنا
BOT_TOKEN = "8439068545:AAFe_SlJuLJp7-ue4rZQljN6WVl_GFPT_l4"
DB_PATH = "bot_data.db"
user_states = {}
# تم وضع آيدي الأدمن الخاص بك هنا
ADMIN_IDS = {7509255483}
ADMIN_GROUP_ID = -4947085075 # استبدل هذا الآيدي بالآيدي الفعلي لمجموعة المدير

# مفاتيح الإعدادات
SETTING_SUPPORT = "support_user"
SETTING_SHAM_CODE = "sham_code"
SETTING_SHAM_ADDR = "sham_address"
SETTING_GROUP_TOPUP = "group_topup"
SETTING_GROUP_ORDERS = "group_orders"
SETTING_ADMINS = "admins"
SETTING_GROUP_SUBS = "group_subscriptions"
SETTING_GROUP_EXPIRE = "group_subscription_expire"

# --------------------- وظائف مساعدة ---------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            is_admin BOOLEAN DEFAULT 0
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            op_number TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            contact TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
    """)
    conn.commit()
    conn.close()
    update_admins_list()

def update_admins_list():
    global ADMIN_IDS
    admins_str = get_setting(SETTING_ADMINS)
    if admins_str:
        try:
            ADMIN_IDS.update(int(uid.strip()) for uid in admins_str.split(',') if uid.strip())
        except ValueError:
            logger.error("Invalid ADMINS setting format. Please use comma-separated integers.")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def ensure_user(user):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # التحقق من وجود المستخدم في قاعدة البيانات
    cur.execute("SELECT * FROM users WHERE user_id=?", (user.id,))
    existing_user = cur.fetchone()

    if existing_user is None:
        # إذا كان المستخدم جديداً، يتم إضافته
        cur.execute("INSERT INTO users(user_id, username) VALUES(?,?)",
                    (user.id, user.username))
        conn.commit()
    elif existing_user['username'] != user.username:
        # إذا كان المستخدم موجوداً واسم المستخدم مختلف، يتم تحديثه
        cur.execute("UPDATE users SET username=? WHERE user_id=?",
                    (user.username, user.id))
        conn.commit()

    conn.close()

def get_user(user_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_balance(user_id):
    user = get_user(user_id)
    return user['balance'] if user else 0.0
    

def change_balance(user_id: int, amount: float) -> float:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?",
                (amount, user_id))
    conn.commit()
    conn.close()
    u = get_user(user_id)
    return u['balance'] if u else 0.0

def get_setting(key: str) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row['value'] if row else None

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)",
                (key, value))
    conn.commit()
    conn.close()
    if key == SETTING_ADMINS:
        update_admins_list()

def money(amount):
    return f"{amount} $"

def get_categories() -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM categories ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_products_by_cat(cat_id: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE category_id=?", (cat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_product(prod_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id=?", (prod_id,))
    row = cur.fetchone()
    conn.close()
    return row


# --------------------- لوحات الأزرار ---------------------
MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🛍️ شراء منتج", callback_data="BUY")],
    [InlineKeyboardButton("💳 شحن شام كاش", callback_data="TOPUP_MENU")],
    [InlineKeyboardButton("🆘 التواصل مع الدعم", callback_data="SUPPORT")],
    [InlineKeyboardButton("👤 معلومات الحساب", callback_data="ACCOUNT")],
    [InlineKeyboardButton("🗞️ الأخبار", callback_data="NEWS")],
])

def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 إدارة القوائم", callback_data="ADM_CATS")],
        [InlineKeyboardButton("🛒 إدارة المنتجات", callback_data="ADM_PRODS")],
        [InlineKeyboardButton("👤 إدارة المستخدمين", callback_data="ADM_USERS")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="ADM_SETTINGS")],
        [InlineKeyboardButton("📜 إدارة الاشتراكات", callback_data="ADM_SUBS")],
    ])

def subs_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ آيدي مجموعة الاشتراكات", callback_data="SET_GROUP_SUBS")],
        [InlineKeyboardButton("🗓️ آيدي مجموعة انتهاء الاشتراكات", callback_data="SET_GROUP_EXPIRE")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="ADM_BACK")],
    ])

def cats_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة قائمة", callback_data="CAT_ADD")],
        [InlineKeyboardButton("✏️ تعديل اسم قائمة", callback_data="CAT_EDIT_LIST")],
        [InlineKeyboardButton("🗑️ حذف قائمة", callback_data="CAT_DEL_LIST")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="ADM_BACK")],
    ])

def prods_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة منتج", callback_data="PROD_ADD")],
        [InlineKeyboardButton("✏️ تعديل اسم منتج", callback_data="PROD_EDIT_NAME_LIST")],
        [InlineKeyboardButton("💲 تعديل سعر منتج", callback_data="PROD_EDIT_PRICE_LIST")],
        [InlineKeyboardButton("📂 نقل منتج لقائمة أخرى", callback_data="PROD_MOVE_LIST")],
        [InlineKeyboardButton("🗑️ حذف منتج", callback_data="PROD_DEL_LIST")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="ADM_BACK")],
    ])

def users_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شحن رصيد", callback_data="USR_CREDIT")],
        [InlineKeyboardButton("➖ سحب رصيد", callback_data="USR_DEBIT")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="ADM_BACK")],
    ])

def settings_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆘 يوزر الدعم", callback_data="SET_SUPPORT")],
        [InlineKeyboardButton("📮 كود شام كاش", callback_data="SET_SHAM_CODE")],
        [InlineKeyboardButton("📍 عنوان شام كاش", callback_data="SET_SHAM_ADDR")],
        [InlineKeyboardButton("💬 آيدي مجموعة الشحن", callback_data="SET_GROUP_TOPUP")],
        [InlineKeyboardButton("🧾 آيدي مجموعة الطلبات", callback_data="SET_GROUP_ORDERS")],
        [InlineKeyboardButton("👑 آيديات الأدمن", callback_data="SET_ADMINS")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="ADM_BACK")],
    ])


# --------------------- نصوص مساعدة ---------------------
def account_text(u_row: sqlite3.Row) -> str:
    return (f"👤 معلومات حسابك:\n"
            f"• الآيدي: <code>{u_row['user_id']}</code>\n"
            f"• اليوزر: @{u_row['username'] if u_row['username'] else '—'}\n"
            f"• الرصيد: <b>{money(u_row['balance'])}</b>\n")

def start_text(u_row: sqlite3.Row) -> str:
    return ("أهلًا بك في متجرنا!\n" + "\nاختر من القائمة بالأسفل.")

# --------------------- Handlers أساسية ---------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        start_text(u),
        reply_markup=MAIN_MENU,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

async def show_account(update: Update, context: ContextTypes.DEFAULT_TYPE, as_new: bool = True):
    ensure_user(update.effective_user)
    u = get_user(update.effective_user.id)
    if as_new:
        await update.effective_chat.send_message(account_text(u), parse_mode=ParseMode.HTML)
    else:
        await update.callback_query.edit_message_text(account_text(u), parse_mode=ParseMode.HTML)

# --------------------- القوائم العامة (شراء/شحن/دعم) ---------------------
async def on_main_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "ACCOUNT":
        await show_account(update, context, as_new=True)
        return

    if data == "SUPPORT":
        sup = get_setting(SETTING_SUPPORT)
        if sup:
            await q.message.chat.send_message(f"للتواصل مع الدعم: @{sup}")
        else:
            await q.message.chat.send_message("لم يتم ضبط يوزر الدعم بعد. الرجاء إبلاغ الأدمن.")
        return

    if data == "TOPUP_MENU":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📮 كود شام كاش", callback_data="SHOW_SHAM_CODE")],
            [InlineKeyboardButton("📍 عنوان شام كاش", callback_data="SHOW_SHAM_ADDR")],
            [InlineKeyboardButton("➕ شحن الحساب", callback_data="TOPUP_START")],
        ])
        await q.message.chat.send_message("اختر من خيارات الشحن:", reply_markup=kb)
        return

    if data == "BUY":
        cats = get_categories()
        if not cats:
            await q.message.chat.send_message("لا توجد قوائم بعد. الرجاء مراجعة الأدمن.")
            return
        rows = [[InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"BUY_CAT:{c['id']}")] for c in cats]
        await q.message.chat.send_message("اختر قائمة:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data == "CHECK_SUB":
        user_id = q.from_user.id
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT p.name, s.end_date FROM subscriptions s JOIN products p ON s.product_id = p.id WHERE s.user_id = ? AND s.end_date > ? ORDER BY s.end_date DESC LIMIT 1",
            (user_id, datetime.utcnow().isoformat()))
        sub = cur.fetchone()
        conn.close()

        if sub:
            end_date = datetime.fromisoformat(sub['end_date'])
            remaining_days = (end_date - datetime.utcnow()).days
            await q.message.reply_text(
                f"✅ لديك اشتراك فعال لـ **{sub['name']}**.\n\n"
                f"يتبقى على انتهائه: **{remaining_days}** يومًا.",
                parse_mode=ParseMode.MARKDOWN)
        else:
            await q.message.reply_text("❌ ليس لديك أي اشتراك فعال حاليًا.")
        return

    if data == "NEWS":
        await on_news_button(update, context)
        return

# ----------- إظهار كود/عنوان الشام كاش + بدء الشحن -----------
async def on_topup_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "SHOW_SHAM_CODE":
        # ضع مُعرّف الصورة الذي حصلت عليه في الخطوة 1 هنا
        photo_id = "AgACAgQAAxkBAYkui2ixsUvmCDPQVMDpOvFzFISV2TEIAAKeyjEbDEyQUc4oaicsvccZAQADAgADcwADNgQ" 

        # يمكنك إضافة نص يظهر أسفل الصورة (اختياري)
        caption_text = f"عنوان شام كاش:\n \n 9cd65bde642da2496b407f8941dc01"

        # تأكد من أن هناك صورة أو كود ليرسل
        if not photo_id:
            await q.message.chat.send_message("لم يتم ضبط صورة كود شام كاش بعد. أخبر الأدمن.")
            return

        # إرسال الصورة مع النص (إذا كان هناك نص)
        await q.message.chat.send_photo(
            photo=photo_id,
            caption=caption_text,
            parse_mode=ParseMode.HTML
        )
        return

    if data == "SHOW_SHAM_ADDR":
        addr = get_setting(SETTING_SHAM_ADDR)
        if addr:
            await q.message.chat.send_message(f"عنوان شام كاش:\n<code>{addr}</code>", parse_mode=ParseMode.HTML)
        else:
            await q.message.chat.send_message("لم يتم ضبط العنوان بعد. أخبر الأدمن.")
        return

    if data == "TOPUP_START":
        context.user_data.clear()
        context.user_data["flow"] = "topup"
        await q.message.chat.send_message("🔢 أرسل رقم العملية:")
        return

# ----------- معالجة أزرار الشراء -----------
async def on_buy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data.startswith("BUY_CAT:"):
        cat_id = int(data.split(":", 1)[1])
        prods = get_products_by_cat(cat_id)
        if not prods:
            await q.message.chat.send_message("لا توجد منتجات في هذه القائمة حالياً.")
            return
        rows = [[InlineKeyboardButton(f"🛒 {p['name']} — {money(p['price'])}", callback_data=f"BUY_PROD:{p['id']}")] for p in prods]
        await q.message.chat.send_message("اختر منتجاً:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("BUY_PROD:"):
        prod_id = int(data.split(":", 1)[1])
        context.user_data.clear()
        context.user_data["flow"] = "buy_contact"
        context.user_data["buy_prod_id"] = prod_id
        await q.message.chat.send_message("أرسل الآيدي أو رقم الهاتف المطلوب ربطه بالطلب:")
        return

    if data == "BUY_CANCEL":
        msg_id = context.user_data.get("confirm_msg_id")
        if msg_id:
            try:
                await q.message.chat.delete_message(msg_id)
            except Exception:
                pass
        context.user_data.clear()
        await q.message.chat.send_message("تم إلغاء الطلب.")
        return

    if data == "BUY_EDIT":
        await q.message.chat.send_message("أعد إرسال الآيدي/رقم الهاتف الجديد:")
        context.user_data["flow"] = "buy_contact"
        return

    if data == "BUY_CONFIRM":
        urow = get_user(q.from_user.id)
        prod_id = int(context.user_data.get("buy_prod_id", 0))
        contact = context.user_data.get("buy_contact")
        if not (prod_id and contact):
            await q.message.chat.send_message("الطلب غير مكتمل. أعد المحاولة.")
            context.user_data.clear()
            return
        prow = get_product(prod_id)
        if not prow:
            await q.message.chat.send_message("تعذر إيجاد المنتج.")
            context.user_data.clear()
            return
        price = float(prow["price"])
        bal = float(urow["balance"]) if urow else 0.0
        if bal < price:
            await q.message.chat.send_message("رصيدك غير كافٍ لهذا الطلب.")
            context.user_data.clear()
            return

        new_bal = change_balance(q.from_user.id, -price)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders(user_id, product_id, price, contact, status, created_at) VALUES(?,?,?,?,?,?)",
            (q.from_user.id, prod_id, price, contact, "pending", datetime.utcnow().isoformat()),
        )
        oid = cur.lastrowid
        conn.commit()

        if "اشتراك" in prow['name'].lower():
            duration_days = 30 # مثال: مدة الاشتراك 30 يوم
            end_date = datetime.utcnow() + timedelta(days=duration_days)
            cur.execute(
                "INSERT INTO subscriptions(user_id, product_id, start_date, end_date) VALUES(?,?,?,?)",
                (q.from_user.id, prod_id, datetime.utcnow().isoformat(), end_date.isoformat())
            )
            conn.commit()
            await q.message.chat.send_message("تم تسجيل اشتراكك بنجاح!")

        conn.close()

        await q.message.chat.send_message("⏳ تم تقديم طلبك. الرجاء الانتظار ريثما يتم التحقق منه.")

        gid = get_setting(SETTING_GROUP_ORDERS)
        if gid:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ قبول", callback_data=f"ORD_ACCEPT:{oid}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"ORD_REJECT:{oid}"),
            ]])
            urow = get_user(q.from_user.id)
            text = (
                "🧾 تأكيد طلب شراء\n"
                f"• المنتج: <b>{prow['name']}</b>\n"
                f"• السعر: <b>{money(price)}</b>\n"
                f"• الآيدي/الهاتف: <code>{contact}</code>\n"
                f"• اليوزر: @{urow['username'] if urow['username'] else '—'}\n"
                f"• آيدي المستخدم: <code>{urow['user_id']}</code>\n")
            try:
                await context.bot.send_message(int(gid), text, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception as e:
                logger.error(f"Failed to send order to group: {e}")
        else:
            await q.message.chat.send_message("⚠️ لم يتم ضبط آيدي مجموعة الطلبات. تواصل مع الأدمن.")

        context.user_data.clear()
        return


# ----------- استقبال رسائل المستخدم لحالات متعددة ----------
async def on_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or '').strip()
    user_id = update.effective_user.id
    current_flow = context.user_data.get("flow")

    # ------------------- الأولوية الأولى: أوامر المدير (جميع الحالات) -------------------
    if is_admin(user_id):
        # تأكد من أن تدفق المدير الحالي يبدأ بـ "adm_"
        if current_flow and current_flow.startswith("adm_"):
            # حالة إضافة قائمة جديدة
            if current_flow == "adm_cat_add":
                cat_name = text
                if not cat_name:
                    await update.message.reply_text("الاسم لا يمكن أن يكون فارغاً، يرجى المحاولة مرة أخرى.")
                    return
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("INSERT INTO categories(name) VALUES(?)", (cat_name,))
                conn.commit()
                conn.close()
                del context.user_data["flow"]
                await update.message.reply_text(f"✅ تم إضافة الفئة '{cat_name}' بنجاح.")
                return

            # حالة إعادة تسمية قائمة
            elif current_flow == "adm_cat_rename":
                cid = context.user_data.get("cid")
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE categories SET name=? WHERE id=?", (text, cid))
                conn.commit()
                conn.close()
                del context.user_data["flow"]
                del context.user_data["cid"]
                await update.message.reply_text("✅ تم تعديل اسم القائمة.")
                return

            # حالة إضافة منتج جديد: إدخال الاسم
            elif current_flow == "adm_prod_add_name":
                prod_name = text
                context.user_data["prod_name"] = prod_name
                context.user_data["flow"] = "adm_prod_add_price"
                await update.message.reply_text("أدخل سعر المنتج (رقماً):")
                return

            # حالة إضافة منتج جديد: إدخال السعر
            elif current_flow == "adm_prod_add_price":
                try:
                    prod_price = float(text)
                except ValueError:
                    await update.message.reply_text("السعر يجب أن يكون رقماً، يرجى المحاولة مرة أخرى.")
                    return
                prod_name = context.user_data.get("prod_name")
                cid = context.user_data.get("cid")
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO products(name, price, category_id) VALUES(?,?,?)",
                    (prod_name, prod_price, cid)
                )
                conn.commit()
                conn.close()
                del context.user_data["flow"]
                del context.user_data["prod_name"]
                del context.user_data["cid"]
                await update.message.reply_text(f"✅ تم إضافة المنتج '{prod_name}' بنجاح.")
                return

            # حالة إعادة تسعير منتج
            elif current_flow == "adm_prod_reprice":
                try:
                    prod_price = float(text)
                except ValueError:
                    await update.message.reply_text("السعر يجب أن يكون رقماً، يرجى المحاولة مرة أخرى.")
                    return
                pid = context.user_data.get("pid")
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE products SET price=? WHERE id=?", (prod_price, pid))
                conn.commit()
                conn.close()
                del context.user_data["flow"]
                del context.user_data["pid"]
                await update.message.reply_text("✅ تم تعديل سعر المنتج.")
                return

            # حالة شحن رصيد لمستخدم
            elif current_flow == "adm_usr_credit_id":
                context.user_data["credit_uid"] = text
                context.user_data["flow"] = "adm_usr_credit_amount"
                await update.message.reply_text("أدخل المبلغ المراد شحنه (رقماً):")
                return

            elif current_flow == "adm_usr_credit_amount":
                try:
                    amount = float(text)
                except ValueError:
                    await update.message.reply_text("المبلغ يجب أن يكون رقماً، يرجى المحاولة مرة أخرى.")
                    return
                credit_uid = context.user_data.get("credit_uid")
                change_balance(int(credit_uid), amount)
                await update.message.reply_text("✅ تم شحن رصيد المستخدم بنجاح.")
                del context.user_data["flow"]
                del context.user_data["credit_uid"]
                return

            # حالة سحب رصيد من مستخدم
            elif current_flow == "adm_usr_debit_id":
                context.user_data["debit_uid"] = text
                context.user_data["flow"] = "adm_usr_debit_amount"
                await update.message.reply_text("أدخل المبلغ المراد سحبه (رقماً):")
                return

            elif current_flow == "adm_usr_debit_amount":
                try:
                    amount = float(text)
                except ValueError:
                    await update.message.reply_text("المبلغ يجب أن يكون رقماً، يرجى المحاولة مرة أخرى.")
                    return
                debit_uid = context.user_data.get("debit_uid")
                change_balance(int(debit_uid), -amount)
                await update.message.reply_text("✅ تم سحب الرصيد من المستخدم بنجاح.")
                del context.user_data["flow"]
                del context.user_data["debit_uid"]
                return

            # حالات الإعدادات
            elif current_flow == "adm_set_support":
                set_setting(SETTING_SUPPORT, text)
                await update.message.reply_text("✅ تم حفظ يوزر الدعم.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_sham_code":
                set_setting(SETTING_SHAM_CODE, text)
                await update.message.reply_text("✅ تم حفظ كود شام كاش.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_sham_addr":
                set_setting(SETTING_SHAM_ADDR, text)
                await update.message.reply_text("✅ تم حفظ عنوان شام كاش.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_group_topup":
                set_setting(SETTING_GROUP_TOPUP, text)
                await update.message.reply_text("✅ تم حفظ آيدي مجموعة الشحن.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_group_orders":
                set_setting(SETTING_GROUP_ORDERS, text)
                await update.message.reply_text("✅ تم حفظ آيدي مجموعة الطلبات.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_admins":
                admin_ids = [int(i.strip()) for i in text.split(",")]
                set_setting(SETTING_ADMINS, ",".join(map(str, admin_ids)))
                await update.message.reply_text("✅ تم حفظ آيديات الأدمن.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_group_subs":
                set_setting(SETTING_GROUP_SUBS, text)
                await update.message.reply_text("✅ تم حفظ آيدي مجموعة الاشتراكات.")
                del context.user_data["flow"]
                return

            elif current_flow == "adm_set_group_expire":
                set_setting(SETTING_GROUP_EXPIRE, text)
                await update.message.reply_text("✅ تم حفظ آيدي مجموعة انتهاء الاشتراكات.")
                del context.user_data["flow"]
                return

    # ------------------- الأولوية الثانية: عملية الشحن -------------------
    if current_flow == "topup":
        stage = context.user_data.get("stage")
        if stage is None:
            context.user_data["topup_op"] = text
            context.user_data["stage"] = "amount"
            await update.message.reply_text("💰 الآن أرسل المبلغ (رقماً مثل 1000 أو 10.5):")
            return
        elif stage == "amount":
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text("الرجاء إرسال المبلغ كرقم صحيح أو عشري.")
                return
            op = context.user_data.get("topup_op")
            user = update.effective_user
            ensure_user(user)

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO topups(user_id, op_number, amount, status, created_at) VALUES(?,?,?,?,?)",
                (user.id, op, amount, "pending", datetime.utcnow().isoformat()),
            )
            tid = cur.lastrowid
            conn.commit()
            conn.close()

            await update.message.reply_text("⏳ تم إرسال طلب الشحن. الرجاء الانتظار ريثما يتم التحقق منه.")
            gid = get_setting(SETTING_GROUP_TOPUP)
            if gid:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ قبول", callback_data=f"TP_ACCEPT:{tid}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"TP_REJECT:{tid}"),
                ]])
                urow = get_user(user.id)
                message_text = (
                    "📩 طلب شحن جديد\n"
                    f"• اليوزر: @{urow['username'] if urow['username'] else '—'}\n"
                    f"• الآيدي: <code>{urow['user_id']}</code>\n"
                    f"• رقم العملية: <code>{op}</code>\n"
                    f"• المبلغ: <b>{money(amount)}</b>\n"
                )
                try:
                    await context.bot.send_message(int(gid), message_text, parse_mode=ParseMode.HTML, reply_markup=kb)
                except Exception as e:
                    logger.error(f"Failed to send topup to group: {e}")
            else:
                await update.message.reply_text("⚠️ لم يتم ضبط آيدي مجموعة الشحن. تواصل مع الأدمن.")
            context.user_data.clear()
            return

    # ------------------- الأولوية الثالثة: عملية الشراء -------------------
    if current_flow == "buy_contact":
        contact = text
        context.user_data["buy_contact"] = contact
        prod_id = context.user_data.get("buy_prod_id")
        prow = get_product(prod_id)
        if not prow:
            await update.message.reply_text("تعذر إيجاد المنتج. الرجاء المحاولة مرة أخرى.")
            context.user_data.clear()
            return

        current_balance = get_balance(user_id)
        new_balance = current_balance - prow['price']

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="BUY_CONFIRM")],
            [InlineKeyboardButton("✏️ تعديل الآيدي/الهاتف", callback_data="BUY_EDIT")],
            [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="BUY_CANCEL")]
        ])

        msg_text = (f"❓هل أنت متأكد من معلومات الطلب\n"
                    f"• المنتج: {prow['name']}\n"
                    f"• السعر: {money(prow['price'])}\n"
                    f"• الآيدي/الهاتف: {contact}\n"
                    f"• الرصيد قبل: {money(current_balance)}\n"
                    f"• الرصيد بعد: {money(new_balance)}\n")

        msg = await update.message.reply_text(msg_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        context.user_data["confirm_msg_id"] = msg.message_id
        context.user_data["flow"] = None
        return

    # ------------------- الرسالة الافتراضية -------------------
    await update.message.reply_text("اختر إجراءً من الأزرار.", reply_markup=main_menu_kb())

    # ------------------- الأولوية الثالثة: عملية الشراء -------------------
    if current_flow == "buy_contact":
        contact = text
        context.user_data["buy_contact"] = contact
        prod_id = context.user_data.get("buy_prod_id")
        prow = get_product(prod_id)
        if not prow:
            await update.message.reply_text("تعذر إيجاد المنتج. الرجاء المحاولة مرة أخرى.")
            context.user_data.clear()
            return

        current_balance = get_balance(user_id)
        new_balance = current_balance - prow['price']

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="BUY_CONFIRM")],
            [InlineKeyboardButton("✏️ تعديل الآيدي/الهاتف", callback_data="BUY_EDIT")],
            [InlineKeyboardButton("❌ إلغاء الطلب", callback_data="BUY_CANCEL")]
        ])

        msg_text = (f"❓هل أنت متأكد من معلومات الطلب\n"
                    f"• المنتج: {prow['name']}\n"
                    f"• السعر: {money(prow['price'])}\n"
                    f"• الآيدي/الهاتف: {contact}\n"
                    f"• الرصيد قبل: {money(current_balance)}\n"
                    f"• الرصيد بعد:* {money(new_balance)}\n")

        msg = await update.message.reply_text(msg_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        context.user_data["confirm_msg_id"] = msg.message_id
        context.user_data["flow"] = None
        return # هذا السطر ينهي الدالة هنا ويمنع الرسالة الافتراضية

    # ------------------- الرسالة الافتراضية -------------------
    await update.message.reply_text("اختر إجراءً من الأزرار.", reply_markup=main_menu_kb())
    await update.message.reply_text("اختر إجراءً من الأزرار.", reply_markup=main_menu_kb())

# ----------- أزرار مجموعة الشحن/الطلبات (للأدمن فقط) ---------
async def on_group_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # ❗ التأكد من أن المستخدم مدير قبل معالجة أي شيء
    if not is_admin(q.from_user.id):
        await q.message.reply_text("هذا الإجراء للأدمن فقط.")
        return

    # --- معالجة طلبات الشحن (TP_ACCEPT/REJECT) ---
    if data.startswith("TP_ACCEPT:") or data.startswith("TP_REJECT:"):
        # استخراج ID طلب الشحن من البيانات
        tid = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM topups WHERE id=?", (tid,))
        row = cur.fetchone()

        if not row:
            await q.message.reply_text("لم يتم العثور على هذا الطلب.")
            conn.close()
            return

        # منع معالجة الطلبات المكررة
        if row["status"] != "pending":
            await q.message.reply_text("تمت معالجته مسبقًا.")
            conn.close()
            return

        # قبول الطلب
        if data.startswith("TP_ACCEPT"):
            # تحديث رصيد المستخدم
            new_bal = change_balance(row["user_id"], float(row["amount"]))
            cur.execute("UPDATE topups SET status='approved' WHERE id=?", (tid,))
            conn.commit()
            conn.close()

            # إزالة الأزرار من رسالة المجموعة
            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

            await q.message.reply_text("✅ تم قبول الشحن.")

            # إرسال إشعار للمستخدم
            try:
                await context.bot.send_message(
                    row["user_id"],
                    f"✅ تم شحن حسابك بمبلغ {money(row['amount'])}. رصيدك الحالي: {money(new_bal)}"
                )
            except Exception:
                pass
            return

        # رفض الطلب
        else:
            cur.execute("UPDATE topups SET status='rejected' WHERE id=?", (tid,))
            conn.commit()
            conn.close()

            # إزالة الأزرار من رسالة المجموعة
            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

            await q.message.reply_text("❌ تم رفض الشحن.")

            # إرسال إشعار للمستخدم
            try:
                await context.bot.send_message(row["user_id"], "❌ تم رفض طلب الشحن.")
            except Exception:
                pass
            return

    # --- معالجة طلبات الأوامر (ORD_ACCEPT/REJECT) ---
    if data.startswith("ORD_ACCEPT:") or data.startswith("ORD_REJECT:"):
        oid = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE id=?", (oid,))
        row = cur.fetchone()

        if not row:
            await q.message.reply_text("لم يتم العثور على الطلب.")
            conn.close()
            return

        if row["status"] != "pending":
            await q.message.reply_text("تمت معالجته مسبقًا.")
            conn.close()
            return

        # قبول الطلب
        if data.startswith("ORD_ACCEPT"):
            cur.execute("UPDATE orders SET status='approved' WHERE id=?", (oid,))
            conn.commit()
            conn.close()

            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

            await q.message.reply_text("✅ تم قبول الطلب.")

            try:
                await context.bot.send_message(row["user_id"], "✅ تم تنفيذ طلبك.")
            except Exception:
                pass
            return

        # رفض الطلب
        else:
            change_balance(row["user_id"], float(row["price"]))
            cur.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
            conn.commit()
            conn.close()

            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

            await q.message.reply_text("❌ تم رفض الطلب.")

            try:
                await context.bot.send_message(row["user_id"], "❌ تم رفض طلبك وتم إرجاع الرصيد.")
            except Exception:
                pass
            return

# --------------------- لوحة الأدمن ---------------------
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("لوحة الأدمن: الوصول مرفوض.")
        return
    await update.message.reply_text("لوحة الأدمن:", reply_markup=admin_menu_kb())

async def on_admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.message.reply_text("لوحة الأدمن: الوصول مرفوض.")
        return

    data = q.data
    if data == "ADM_BACK":
        await q.message.edit_text("لوحة الأدمن:", reply_markup=admin_menu_kb())
        return

    if data == "ADM_CATS":
        await q.message.edit_text("إدارة القوائم:", reply_markup=cats_menu_kb())
        return
    if data == "ADM_PRODS":
        await q.message.edit_text("إدارة المنتجات:", reply_markup=prods_menu_kb())
        return
    if data == "ADM_USERS":
        await q.message.edit_text("إدارة المستخدمين:", reply_markup=users_menu_kb())
        return
    if data == "ADM_SETTINGS":
        await q.message.edit_text("الإعدادات:", reply_markup=settings_menu_kb())
        return
    if data == "ADM_SUBS":
        await q.message.edit_text("إدارة الاشتراكات:", reply_markup=subs_menu_kb())
        return

    # القوائم
    if data == "CAT_ADD":
        context.user_data.clear()
        context.user_data["flow"] = "adm_cat_add"
        await q.message.reply_text("أرسل اسم القائمة الجديدة:")
        return
    if data == "CAT_EDIT_LIST":
        cats = get_categories()
        if not cats:
            await q.message.reply_text("لا توجد قوائم.")
            return
        rows = [[InlineKeyboardButton(f"✏️ {c['name']}", callback_data=f"CAT_EDIT:{c['id']}")] for c in cats]
        await q.message.reply_text("اختر قائمة لتعديل اسمها:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("CAT_EDIT:"):
        cid = int(data.split(":", 1)[1])
        context.user_data.clear()
        context.user_data["flow"] = "adm_cat_rename"
        context.user_data["cid"] = cid
        await q.message.reply_text("أرسل الاسم الجديد للقائمة:")
        return
    if data == "CAT_DEL_LIST":
        cats = get_categories()
        if not cats:
            await q.message.reply_text("لا توجد قوائم.")
            return
        rows = [[InlineKeyboardButton(f"🗑️ {c['name']}", callback_data=f"CAT_DEL:{c['id']}")] for c in cats]
        await q.message.reply_text("اختر قائمة لحذفها:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("CAT_DEL:"):
        cid = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM products WHERE category_id=?", (cid,))
        if cur.fetchone()["n"] > 0:
            await q.message.reply_text("لا يمكن حذف قائمة تحتوي منتجات. انقل/احذف المنتجات أولاً.")
            conn.close()
            return
        cur.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
        conn.close()
        await q.message.reply_text("تم حذف القائمة.")
        return

    # المنتجات
    if data == "PROD_ADD":
        cats = get_categories()
        if not cats:
            await q.message.reply_text("أضف قائمة أولاً.")
            return
        rows = [[InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"PROD_ADD_IN:{c['id']}")] for c in cats]
        await q.message.reply_text("اختر القائمة التي سيضاف فيها المنتج:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_ADD_IN:"):
        cid = int(data.split(":", 1)[1])
        context.user_data.clear()
        context.user_data["flow"] = "adm_prod_add_name"
        context.user_data["cid"] = cid
        await q.message.reply_text("أدخل اسم المنتج:")
        return

    if data == "PROD_EDIT_NAME_LIST":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT p.id, p.name, c.name AS cname FROM products p JOIN categories c ON p.category_id=c.id ORDER BY p.id DESC"
        )
        items = cur.fetchall()
        conn.close()
        if not items:
            await q.message.reply_text("لا توجد منتجات.")
            return
        rows = [[InlineKeyboardButton(f"✏️ {i['name']} (\u2192 {i['cname']})", callback_data=f"PROD_EDIT_NAME:{i['id']}")] for i in items]
        await q.message.reply_text("اختر المنتج لتعديل اسمه:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_EDIT_NAME:"):
        pid = int(data.split(":", 1)[1])
        # لا تقم بمسح البيانات هنا
        context.user_data["flow"] = "adm_prod_rename"
        context.user_data["pid"] = pid
        print(f"DEBUG: Product ID saved in context: {context.user_data.get('pid')}") # أمر طباعة للفحص
        await q.message.reply_text("أدخل الاسم الجديد:")
        return

    if data == "PROD_EDIT_PRICE_LIST":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT p.id, p.name, p.price FROM products p ORDER BY p.id DESC")
        items = cur.fetchall()
        conn.close()
        if not items:
            await q.message.reply_text("لا توجد منتجات.")
            return
        rows = [[InlineKeyboardButton(f"💲 {i['name']} — {money(i['price'])}", callback_data=f"PROD_EDIT_PRICE:{i['id']}")] for i in items]
        await q.message.reply_text("اختر المنتج لتعديل سعره:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_EDIT_PRICE:"):
        pid = int(data.split(":", 1)[1])
        context.user_data.clear()
        context.user_data["flow"] = "adm_prod_reprice"
        context.user_data["pid"] = pid
        await q.message.reply_text("أدخل السعر الجديد (رقماً):")
        return

    if data == "PROD_MOVE_LIST":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM products ORDER BY id DESC")
        items = cur.fetchall()
        conn.close()
        if not items:
            await q.message.reply_text("لا توجد منتجات.")
            return
        rows = [[InlineKeyboardButton(f"📦 {i['name']}", callback_data=f"PROD_MOVE_PICK:{i['id']}")] for i in items]
        await q.message.reply_text("اختر المنتج المراد نقله:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_MOVE_PICK:"):
        pid = int(data.split(":", 1)[1])
        cats = get_categories()
        if not cats:
            await q.message.reply_text("لا توجد قوائم.")
            return
        rows = [[InlineKeyboardButton(f"➡️ {c['name']}", callback_data=f"PROD_MOVE_TO:{pid}:{c['id']}")] for c in cats]
        await q.message.reply_text("اختر القائمة الجديدة:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_MOVE_TO:"):
        _, pid, cid = data.split(":")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("UPDATE products SET category_id=? WHERE id=?", (int(cid), int(pid)))
        conn.commit()
        conn.close()
        await q.message.reply_text("تم نقل المنتج.")
        return

    if data == "PROD_DEL_LIST":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM products ORDER BY id DESC")
        items = cur.fetchall()
        conn.close()
        if not items:
            await q.message.reply_text("لا توجد منتجات.")
            return
        rows = [[InlineKeyboardButton(f"🗑️ {i['name']}", callback_data=f"PROD_DEL:{i['id']}")] for i in items]
        await q.message.reply_text("اختر المنتج لحذفه:", reply_markup=InlineKeyboardMarkup(rows))
        return
    if data.startswith("PROD_DEL:"):
        pid = int(data.split(":", 1)[1])
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        await q.message.reply_text("تم حذف المنتج.")
        return

    # المستخدمون
    if data == "USR_CREDIT":
        context.user_data.clear()
        context.user_data["flow"] = "adm_usr_credit_id"
        await q.message.reply_text("أدخل آيدي المستخدم المطلوب شحنه:")
        return
    if data == "USR_DEBIT":
        context.user_data.clear()
        context.user_data["flow"] = "adm_usr_debit_id"
        await q.message.reply_text("أدخل آيدي المستخدم المطلوب سحب رصيد منه:")
        return

    # الإعدادات
    if data == "SET_SUPPORT":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_support"
        await q.message.reply_text("أدخل يوزر الدعم بدون @ :")
        return
    if data == "SET_SHAM_CODE":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_sham_code"
        await q.message.reply_text("أدخل كود شام كاش:")
        return
    if data == "SET_SHAM_ADDR":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_sham_addr"
        await q.message.reply_text("أدخل عنوان شام كاش:")
        return
    if data == "SET_GROUP_TOPUP":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_group_topup"
        await q.message.reply_text("أدخل آيدي مجموعة الشحن (رقم):")
        return
    if data == "SET_GROUP_ORDERS":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_group_orders"
        await q.message.reply_text("أدخل آيدي مجموعة الطلبات (رقم):")
        return
    if data == "SET_ADMINS":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_admins"
        await q.message.reply_text(
            "أدخل آيديات الأدمن مفصولة بفواصل (مثال: 123,456):")
        return

    # الاشتراكات
    if data == "SET_GROUP_SUBS":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_group_subs"
        await q.message.reply_text("أدخل آيدي مجموعة إشعارات الاشتراكات (رقم):")
        return
    if data == "SET_GROUP_EXPIRE":
        context.user_data.clear()
        context.user_data["flow"] = "adm_set_group_expire"
        await q.message.reply_text("أدخل آيدي مجموعة انتهاء الاشتراكات (رقم):")
        return

# ----------- استقبال نصوص الأدمن حسب التدفق -----------
async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, flow: str, txt: str):
    # القوائم
    if flow == "adm_cat_add":
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("INSERT INTO categories(name) VALUES(?)", (txt,))
        conn.commit()
        conn.close()
        await update.message.reply_text("تمت إضافة القائمة.")
        context.user_data.clear()
        return
    if flow == "adm_cat_rename":
        cid = context.user_data.get("cid")
        if not cid:
            await update.message.reply_text("انتهت الجلسة. أعد المحاولة.")
            context.user_data.clear()
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("UPDATE categories SET name=? WHERE id=?", (txt, int(cid)))
        conn.commit()
        conn.close()
        await update.message.reply_text("تم تعديل الاسم.")
        context.user_data.clear()
        return

    # إضافة منتج
    if flow == "adm_prod_add_name":
        context.user_data["new_prod_name"] = txt
        context.user_data["flow"] = "adm_prod_add_price"
        await update.message.reply_text("أدخل السعر (رقماً):")
        return
    if flow == "adm_prod_add_price":
        try:
            price = float(txt)
        except Exception:
            await update.message.reply_text("الرجاء إدخال سعر صحيح.")
            return
        cid = int(context.user_data.get("cid"))
        name = context.user_data.get("new_prod_name")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("INSERT INTO products(name, price, category_id) VALUES(?,?,?)", (name, price, cid))
        conn.commit()
        conn.close()
        await update.message.reply_text("تم حفظ المنتج.")
        context.user_data.clear()
        return

    # تعديل اسم منتج
    if flow == "adm_prod_rename":
        pid = int(context.user_data.get("pid"))
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("UPDATE products SET name=? WHERE id=?", (txt, pid))
        conn.commit()
        conn.close()
        await update.message.reply_text("تم تعديل الاسم.")
        context.user_data.clear()
        return

    # تعديل سعر منتج
    if flow == "adm_prod_reprice":
        pid = int(context.user_data.get("pid"))
        try:
            price = float(txt)
        except Exception:
            await update.message.reply_text("الرجاء إدخال سعر صحيح.")
            return
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("UPDATE products SET price=? WHERE id=?", (price, pid))
        conn.commit()
        conn.close()
        await update.message.reply_text("تم تعديل السعر.")
        context.user_data.clear()
        return

    # شحن يدوي
    if flow == "adm_usr_credit_id":
        try:
            uid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي رقمي صحيح.")
            return
        context.user_data["flow"] = "adm_usr_credit_amount"
        context.user_data["uid"] = uid
        await update.message.reply_text("أدخل المبلغ المراد شحنه:")
        return
    if flow == "adm_usr_credit_amount":
        try:
            amount = float(txt)
        except Exception:
            await update.message.reply_text("أدخل مبلغاً صحيحاً.")
            return
        uid = int(context.user_data.get("uid"))
        ensure_user(update.effective_user)
        new_bal = change_balance(uid, amount)
        await update.message.reply_text(
            f"✅ تم الشحن. الرصيد الحالي للمستخدم {uid}: {money(new_bal)}")
        try:
            await context.bot.send_message(
                uid,
                f"تم شحن حسابك بـ {money(amount)}. رصيدك الحالي هو: {money(new_bal)}"
            )
        except Exception:
            pass
        context.user_data.clear()
        return

    # سحب رصيد
    if flow == "adm_usr_debit_id":
        try:
            uid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي رقمي صحيح.")
            return
        context.user_data["flow"] = "adm_usr_debit_amount"
        context.user_data["uid"] = uid
        await update.message.reply_text("أدخل مبلغ السحب:")
        return
    if flow == "adm_usr_debit_amount":
        try:
            amount = float(txt)
        except Exception:
            await update.message.reply_text("أدخل مبلغاً صحيحاً.")
            return
        uid = int(context.user_data.get("uid"))
        u = get_user(uid)
        if not u:
            await update.message.reply_text("المستخدم غير موجود.")
            context.user_data.clear()
            return
        if float(u["balance"]) < amount:
            await update.message.reply_text(
                "لا تستطيع السحب: الرصيد أقل من المحدد.")
            context.user_data.clear()
            return
        new_bal = change_balance(uid, -amount)
        await update.message.reply_text(
            f"✅ تم السحب. الرصيد الحالي للمستخدم {uid}: {money(new_bal)}")
        try:
            await context.bot.send_message(
                uid,
                f"تم سحب {money(amount)} من حسابك. رصيدك الحالي هو: {money(new_bal)}"
            )
        except Exception:
            pass
        context.user_data.clear()
        return

    # الإعدادات
    if flow == "adm_set_support":
        set_setting(SETTING_SUPPORT, txt.replace("@", "").strip())
        await update.message.reply_text("تم حفظ يوزر الدعم.")
        context.user_data.clear()
        return

    if flow == "adm_set_sham_code":
        set_setting(SETTING_SHAM_CODE, txt)
        await update.message.reply_text("تم حفظ كود شام كاش.")
        context.user_data.clear()
        return

    if flow == "adm_set_sham_addr":
        set_setting(SETTING_SHAM_ADDR, txt)
        await update.message.reply_text("تم حفظ عنوان شام كاش.")
        context.user_data.clear()
        return

    if flow == "adm_set_group_topup":
        try:
            gid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي مجموعة كرقم.")
            return
        set_setting(SETTING_GROUP_TOPUP, str(gid))
        await update.message.reply_text("تم حفظ آيدي مجموعة الشحن.")
        context.user_data.clear()
        return

    if flow == "adm_set_group_orders":
        try:
            gid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي مجموعة كرقم.")
            return
        set_setting(SETTING_GROUP_ORDERS, str(gid))
        await update.message.reply_text("تم حفظ آيدي مجموعة الطلبات.")
        context.user_data.clear()
        return

    if flow == "adm_set_admins":
        set_setting(SETTING_ADMINS, txt)
        await update.message.reply_text("تم حفظ آيديات الأدمن.")
        context.user_data.clear()
        return

    # الاشتراكات
    if flow == "adm_set_group_subs":
        try:
            gid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي مجموعة كرقم.")
            return
        set_setting(SETTING_GROUP_SUBS, str(gid))
        await update.message.reply_text("تم حفظ آيدي مجموعة الاشتراكات.")
        context.user_data.clear()
        return

    if flow == "adm_set_group_expire":
        try:
            gid = int(txt)
        except Exception:
            await update.message.reply_text("أدخل آيدي مجموعة كرقم.")
            return
        set_setting(SETTING_GROUP_EXPIRE, str(gid))
        await update.message.reply_text("تم حفظ آيدي مجموعة انتهاء الاشتراكات.")
        context.user_data.clear()
        return

    if flow and flow.startswith("adm_"):
        await update.message.reply_text("هذا الأمر غير مدعوم أو غير مكتمل. الرجاء المحاولة مرة أخرى.")
        context.user_data.clear()
        return

# ----------- دالة جديدة لمعالجة زر الأخبار -----------
async def on_news_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    news_text = "<b>تابع آخر تحديثات الكود </b>\n" \
                "• التحديثات\n" \
                "• الإضافات\n" \
                "• التعديلات\n" \
                "• آخر معلوامت البوت\n" \
                   "تابع الآن لن تندم"

    news_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("قناتنا الرسمية", url="https://t.me/rox_stor_group")],
        [InlineKeyboardButton("القناة الاحتياطية", url="https://t.me/rox_stor_group2")],
        [InlineKeyboardButton("رجوع للقائمة الرئيسية", callback_data="BACK_TO_MAIN")]
    ])

    await query.edit_message_text(
        text=news_text,
        reply_markup=news_keyboard,
        parse_mode=ParseMode.HTML
    )

async def handle_topup_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if not str(query.from_user.id) == str(ADMIN_ID):
        await query.edit_message_text("عذراً، أنت لست مسؤولاً للقيام بهذا الإجراء.")
        return

    action_parts = data.split('_')
    action = action_parts[0]
    target_user_id = int(action_parts[2])

    if action == "ACCEPT":
        amount = float(action_parts[3])
        add_balance(target_user_id, amount)
        balance = get_balance(target_user_id)

        await context.bot.send_message(target_user_id, f"✅ تم قبول طلبك وإضافة {money(amount)} إلى رصيدك. رصيدك الحالي: {money(balance)}")

        await query.edit_message_text(f"✅ تم قبول الطلب بنجاح. المبلغ: {money(amount)}. المستخدم: {target_user_id}")

    elif action == "REJECT":
        await context.bot.send_message(target_user_id, "❌ تم رفض طلب الشحن الخاص بك.")

        await query.edit_message_text(f"❌ تم رفض الطلب بنجاح. المستخدم: {target_user_id}")
# --------------------- نقاط الدخول ---------------------
async def on_any_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "REQUEST_SHAM_TOPUP":
        context.user_data['flow'] = "topup"
        context.user_data['stage'] = None
        await query.edit_message_text("أرسل رقم العملية (كود الشحن).")
        return


    if data == "REQUEST_SHAM_TOPUP":
        user_states[query.from_user.id] = "AWAITING_TOPUP_CODE"
        await query.edit_message_text(
            "أرسل لي رقم العملية (كود الشحن).",
            parse_mode=ParseMode.HTML
        )
        return

    if data == "BACK_TO_MAIN":
        user_states.pop(query.from_user.id, None)  # إزالة حالة المستخدم عند الرجوع للقائمة الرئيسية
        u = get_user(update.effective_user.id)
        await query.message.edit_text(start_text(u), reply_markup=MAIN_MENU, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "NEWS":
        await on_news_button(update, context)
        return

    if data in {"ACCOUNT", "SUPPORT", "TOPUP_MENU", "BUY", "CHECK_SUB"}:
        await on_main_buttons(update, context)
        return

    if data == "BACK_TO_MAIN":
        u = get_user(update.effective_user.id)
        await query.message.edit_text(start_text(u), reply_markup=MAIN_MENU, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if data in {"SHOW_SHAM_CODE", "SHOW_SHAM_ADDR", "TOPUP_START"}:
        await on_topup_buttons(update, context)
        return

    if data.startswith("BUY_"):
        await on_buy_flow(update, context)
        return

    if data.startswith("TP_") or data.startswith("ORD_"):
        await on_group_actions(update, context)
        return

    if data.startswith("ADM_") or data.startswith("CAT_") or data.startswith("PROD_") or data.startswith("USR_") or data.startswith("SET_"):
        await on_admin_buttons(update, context)
        return

    await update.callback_query.answer("أمر غير معروف")



def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # الأوامر: /start و /admin
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # معالجة رسائل المستخدم (النصوص)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_user_message))

    # معالجة جميع أزرار الـ Callback
    app.add_handler(CallbackQueryHandler(on_any_callback, pattern=r"^(REQUEST_SHAM_TOPUP|MENU|BACK_TO_HOME|...)"))

    # ❗ تم تعديل هذا السطر لحل المشكلة
    app.add_handler(CallbackQueryHandler(on_group_actions, pattern=r"^(TP_|ORD_).*"))

    

    logger.info("Bot is up.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()



