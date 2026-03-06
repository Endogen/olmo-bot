"""OLMo Telegram Bot — chat with Allen AI models via web2api."""

from __future__ import annotations

import html
import hashlib
import logging
import textwrap
from collections import defaultdict

import httpx
from telegram import InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from config import (
    ALLOWED_USERS,
    BOT_TOKEN,
    DEFAULT_MODEL,
    MODELS,
    REQUEST_TIMEOUT,
    WEB2API_URL,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-user state
user_model: dict[int, str] = defaultdict(lambda: DEFAULT_MODEL)
user_memory_enabled: dict[int, bool] = {}
user_history: dict[int, list[dict]] = defaultdict(list)

MAX_HISTORY = 20  # max turns to keep


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def is_allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


async def check_access(update: Update) -> bool:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Access denied.")
        return False
    return True


# ---------------------------------------------------------------------------
# Web2API query
# ---------------------------------------------------------------------------

async def query_model(model: str, prompt: str, history: list[dict] | None = None) -> str:
    """Send a prompt to web2api and return the response text."""
    endpoint = MODELS.get(model)
    if not endpoint:
        return f"Unknown model: {model}"

    # Build the full prompt with history context
    full_prompt = prompt
    if history:
        parts = []
        for msg in history:
            role = msg["role"]
            text = msg["text"]
            if role == "user":
                parts.append(f"User: {text}")
            else:
                parts.append(f"Assistant: {text}")
        parts.append(f"User: {prompt}")
        full_prompt = "\n\n".join(parts)

    url = f"{WEB2API_URL}{endpoint}"
    params = {"q": full_prompt}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    # web2api returns {"items": [{"fields": {"response": "..."}}]}
    items = data.get("items", [])
    if not items:
        return "No response from model."

    fields = items[0].get("fields", {})
    answer = fields.get("response") or fields.get("answer") or fields.get("text") or str(fields)
    return answer


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    model = user_model[uid]
    mem = "on" if user_memory_enabled.get(uid) else "off"
    await update.message.reply_text(
        f"🤖 <b>OLMo AI Bot</b>\n\n"
        f"Current model: <code>{model}</code>\n"
        f"Memory: <code>{mem}</code>\n\n"
        f"<b>Commands:</b>\n"
        f"/olmo32b — OLMo 3.1 32B Instruct\n"
        f"/think — OLMo 3.1 32B Think (reasoning)\n"
        f"/olmo7b — OLMo 3 7B Instruct\n"
        f"/tulu8b — Tülu 3 8B\n"
        f"/tulu70b — Tülu 3 70B\n"
        f"/models — list available models\n"
        f"/memory — toggle conversation memory\n"
        f"/clear — clear memory history\n"
        f"/status — current settings",
        parse_mode=ParseMode.HTML,
    )


async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    current = user_model[uid]
    lines = []
    for name in MODELS:
        marker = " ✅" if name == current else ""
        lines.append(f"• <code>{name}</code>{marker}")
    await update.message.reply_text(
        "<b>Available models:</b>\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def cmd_set_model(model: str, update: Update) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    user_model[uid] = model
    await update.message.reply_text(f"Switched to <code>{model}</code>", parse_mode=ParseMode.HTML)


async def cmd_olmo32b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("olmo-32b", update)

async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("olmo-32b-think", update)

async def cmd_olmo7b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("olmo-7b", update)

async def cmd_tulu8b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("tulu-8b", update)

async def cmd_tulu70b(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("tulu-70b", update)


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    args = context.args
    if args and args[0].lower() == "enable":
        user_memory_enabled[uid] = True
        await update.message.reply_text("🧠 Memory <b>enabled</b>", parse_mode=ParseMode.HTML)
    elif args and args[0].lower() == "disable":
        user_memory_enabled[uid] = False
        user_history[uid].clear()
        await update.message.reply_text("🧠 Memory <b>disabled</b> (history cleared)", parse_mode=ParseMode.HTML)
    else:
        # Toggle
        current = user_memory_enabled.get(uid, False)
        user_memory_enabled[uid] = not current
        if not user_memory_enabled[uid]:
            user_history[uid].clear()
        state = "enabled" if user_memory_enabled[uid] else "disabled"
        await update.message.reply_text(f"🧠 Memory <b>{state}</b>", parse_mode=ParseMode.HTML)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    user_history[uid].clear()
    await update.message.reply_text("🗑 History cleared.")



async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return
    uid = update.effective_user.id
    model = user_model[uid]
    mem = user_memory_enabled.get(uid, False)
    hist_len = len(user_history[uid])
    await update.message.reply_text(
        f"<b>Status:</b>\n"
        f"Model: <code>{model}</code>\n"
        f"Memory: <code>{'on' if mem else 'off'}</code>\n"
        f"History: <code>{hist_len} turns</code>",
        parse_mode=ParseMode.HTML,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return

    uid = update.effective_user.id
    prompt = update.message.text
    if not prompt:
        return

    model = user_model[uid]
    mem_on = user_memory_enabled.get(uid, False)

    # Send typing indicator
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        history = user_history[uid] if mem_on else None
        answer = await query_model(model, prompt, history)

        # Store in history if memory enabled
        if mem_on:
            user_history[uid].append({"role": "user", "text": prompt})
            user_history[uid].append({"role": "assistant", "text": answer})
            # Trim to max
            if len(user_history[uid]) > MAX_HISTORY * 2:
                user_history[uid] = user_history[uid][-(MAX_HISTORY * 2):]

        # Telegram has a 4096 char limit
        if len(answer) <= 4096:
            await update.message.reply_text(answer)
        else:
            # Split into chunks
            for i in range(0, len(answer), 4096):
                chunk = answer[i:i + 4096]
                await update.message.reply_text(chunk)

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error: %s", e)
        await update.message.reply_text(f"❌ API error: {e.response.status_code}")
    except httpx.ReadTimeout:
        await update.message.reply_text("⏳ Request timed out. The model might be slow — try again.")
    except Exception as e:
        logger.exception("Unexpected error")
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


# ---------------------------------------------------------------------------
# Inline mode
# ---------------------------------------------------------------------------

async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    if not is_allowed(query.from_user.id):
        return

    prompt = query.query.strip()
    if not prompt:
        return

    uid = query.from_user.id
    model = user_model[uid]

    try:
        answer = await query_model(model, prompt)
    except Exception as e:
        logger.exception("Inline query error")
        answer = f"Error: {e}"

    # Truncate for inline result description
    description = answer[:200] + "…" if len(answer) > 200 else answer
    result_id = hashlib.md5(f"{prompt}:{answer[:100]}".encode()).hexdigest()

    results = [
        InlineQueryResultArticle(
            id=result_id,
            title=f"OLMo ({model})",
            description=description,
            input_message_content=InputTextMessageContent(
                message_text=answer[:4096],
            ),
        )
    ]

    await query.answer(results, cache_time=0, is_personal=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("models", cmd_models))
    app.add_handler(CommandHandler("olmo32b", cmd_olmo32b))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(CommandHandler("olmo7b", cmd_olmo7b))
    app.add_handler(CommandHandler("tulu8b", cmd_tulu8b))
    app.add_handler(CommandHandler("tulu70b", cmd_tulu70b))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(InlineQueryHandler(handle_inline))

    logger.info("Starting OLMo bot (allowed users: %s)", ALLOWED_USERS or "all")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
