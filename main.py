import os
import requests
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import json
import psycopg

# ================= LOAD ENV =================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg.connect(DATABASE_URL, autocommit=True)

# ================= DATABASE SETUP =================

with conn.cursor() as cur:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE NOT NULL,
            subscribed BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id SERIAL PRIMARY KEY,
            word TEXT UNIQUE NOT NULL,
            meaning TEXT NOT NULL,
            example TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

# ================= USER FUNCTIONS =================

def subscribe_user(chat_id):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (chat_id)
            VALUES (%s)
            ON CONFLICT (chat_id)
            DO UPDATE SET subscribed = TRUE;
        """, (chat_id,))

def unsubscribe_user(chat_id):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET subscribed = FALSE WHERE chat_id = %s;
        """, (chat_id,))

def get_subscribed_users():
    with conn.cursor() as cur:
        cur.execute("""
            SELECT chat_id FROM users WHERE subscribed = TRUE;
        """)
        return [row[0] for row in cur.fetchall()]

# ================= WORD FUNCTIONS =================

def word_exists(word):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1 FROM content WHERE LOWER(word) = LOWER(%s);
        """, (word,))
        return cur.fetchone() is not None

def save_content(word, meaning, example):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO content (word, meaning, example)
            VALUES (%s, %s, %s);
        """, (word, meaning, example))

# ================= OPENROUTER WORD GENERATION =================

def generate_word():
    prompt = """
    Generate ONE advanced English vocabulary word.

    Format exactly like this:

    Word: <word>

    Meaning: <simple meaning in easy English>

    Example: <real life short example sentence>

    Do not add anything else.
    """

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "model": "google/gemma-3n-e4b-it:free",
            "messages": [{"role": "user", "content": prompt}],
        })
    )

    if response.status_code == 200:
        content = response.json()["choices"][0]["message"]["content"].strip()

        try:
            parts = content.split("\n\n")
            word = parts[0].replace("Word: ", "").strip()
            meaning = parts[1].replace("Meaning: ", "").strip()
            example = parts[2].replace("Example: ", "").strip()
            return word, meaning, example
        except:
            return None, None, None
    else:
        print(response.text)
        return None, None, None

# ================= GENERATE NEW UNIQUE WORD =================

def get_new_unique_word():
    for _ in range(5):  # try 5 times to avoid duplicates
        word, meaning, example = generate_word()

        if not word:
            continue

        if not word_exists(word):
            save_content(word, meaning, example)
            return word, meaning, example

    return None, None, None

# ================= SEND DAILY WORD (SAME FOR ALL USERS) =================

async def send_daily_word(application):
    word, meaning, example = get_new_unique_word()

    if not word:
        print("Failed to generate unique word.")
        return

    message = f"""
📘 Word of the Day

🔤 Word: {word}

📖 Meaning: {meaning}

📝 Example: {example}
"""

    users = get_subscribed_users()

    for chat_id in users:
        try:
            await application.bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            print(f"Failed to send to {chat_id}: {e}")

# ================= /IKNOW HANDLER =================

async def regenerate_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    word, meaning, example = get_new_unique_word()

    if not word:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Couldn't generate a new word. Try again."
        )
        return

    message = f"""
📘 New Word For You

🔤 Word: {word}

📖 Meaning: {meaning}

📝 Example: {example}
"""

    await context.bot.send_message(chat_id=chat_id, text=message)

# ================= COMMAND HANDLERS =================

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribe_user(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ Subscribed to Word of the Day!"
    )

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    unsubscribe_user(chat_id)
    await context.bot.send_message(
        chat_id=chat_id,
        text="❌ Unsubscribed successfully."
    )

# ================= MAIN =================

if __name__ == "__main__":
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("iknow", regenerate_word))

    # Run bot normally
    print("Running....")
    # application.run_polling()

    # If you want to send word immediately (optional)
    asyncio.run(send_daily_word(application))
