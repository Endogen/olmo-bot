"""OLMo Telegram Bot — chat with Allen AI models via web2api."""

from __future__ import annotations

import html
import hashlib
import logging
import os
import tempfile
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
    DEFAULT_TOOLS_URL,
    MODELS,
    REQUEST_TIMEOUT,
    VISION_MODELS,
    WEB2API_URL,
)
from pointing import draw_points_on_image, has_points, parse_points, strip_points

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

async def query_model(
    model: str,
    prompt: str,
    history: list[dict] | None = None,
    file_path: str | None = None,
) -> str:
    """Send a prompt to web2api and return the response text.

    If *file_path* is given the request is sent as multipart POST so the
    scraper can forward the file to vision models like Molmo 2.
    """
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

    # Build query params — always include tools_url for web search access
    params: dict[str, str] = {"q": full_prompt}
    if DEFAULT_TOOLS_URL and model not in VISION_MODELS:
        params["tools_url"] = DEFAULT_TOOLS_URL

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if file_path:
            # POST multipart with file (vision models don't need tools)
            import mimetypes
            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            with open(file_path, "rb") as f:
                files = [("files", (file_path.split("/")[-1], f, mime))]
                resp = await client.post(url, params=params, files=files)
        else:
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
        f"/molmo2 — Molmo 2 8B (vision: images & video)\n"
        f"/molmo2track — Molmo 2 8B 8fps tracking\n"
        f"/models — list available models\n"
        f"/memory — toggle conversation memory\n"
        f"/clear — clear memory history\n"
        f"/status — current settings\n\n"
        f"📷 <b>Vision:</b> Send a photo or video with a caption to analyze it with Molmo 2.",
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

async def cmd_molmo2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("molmo2", update)

async def cmd_molmo2track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_set_model("molmo2-track", update)


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


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photos and videos — forward to Molmo 2 vision model."""
    if not await check_access(update):
        return

    uid = update.effective_user.id
    model = user_model[uid]
    msg = update.message

    # Auto-switch to molmo2 if current model doesn't support vision
    if model not in VISION_MODELS:
        model = "molmo2"

    # Get the caption as the prompt, or use a default
    prompt = msg.caption or "Describe this image in detail."

    # Determine the file to download
    if msg.photo:
        file_obj = await msg.photo[-1].get_file()  # highest resolution
        ext = ".jpg"
    elif msg.video:
        file_obj = await msg.video.get_file()
        ext = ".mp4"
    elif msg.document and msg.document.mime_type and (
        msg.document.mime_type.startswith("image/") or
        msg.document.mime_type.startswith("video/")
    ):
        file_obj = await msg.document.get_file()
        ext = os.path.splitext(msg.document.file_name or "file")[1] or ".bin"
    else:
        await msg.reply_text("⚠️ Unsupported file type. Send an image or video.")
        return

    await msg.chat.send_action(ChatAction.TYPING)

    tmp_path = None
    pointed_path = None
    try:
        # Download to temp file
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            await file_obj.download_to_drive(tmp_path)

        mem_on = user_memory_enabled.get(uid, False)
        history = user_history[uid] if mem_on else None
        answer = await query_model(model, prompt, history, file_path=tmp_path)

        if mem_on:
            user_history[uid].append({"role": "user", "text": f"[image/video] {prompt}"})
            user_history[uid].append({"role": "assistant", "text": answer})
            if len(user_history[uid]) > MAX_HISTORY * 2:
                user_history[uid] = user_history[uid][-(MAX_HISTORY * 2):]

        # Check if the response contains pointing data
        pointed_path = None
        if has_points(answer) and tmp_path and ext in (".jpg", ".jpeg", ".png", ".webp"):
            try:
                groups = parse_points(answer)
                if groups:
                    pointed_path = tmp_path.rsplit(".", 1)[0] + "_pointed.jpg"
                    pointed_path, caption = draw_points_on_image(
                        tmp_path, groups, output_path=pointed_path,
                    )
                    # Send annotated image with caption
                    with open(pointed_path, "rb") as photo:
                        await msg.reply_photo(
                            photo=photo,
                            caption=caption[:1024] if caption else None,
                        )
                    # Also send the text response with tags stripped
                    clean_text = strip_points(answer)
                    if clean_text and clean_text != caption:
                        await msg.reply_text(clean_text)
            except Exception:
                logger.exception("Point overlay failed, sending text only")
                pointed_path = None

        if not pointed_path:
            if len(answer) <= 4096:
                await msg.reply_text(answer)
            else:
                for i in range(0, len(answer), 4096):
                    await msg.reply_text(answer[i:i + 4096])

    except httpx.ReadTimeout:
        await msg.reply_text("⏳ Request timed out. Vision analysis can be slow — try again.")
    except Exception as e:
        logger.exception("Media handling error")
        await msg.reply_text(f"❌ Error: {html.escape(str(e))}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if pointed_path and os.path.exists(pointed_path):
            os.unlink(pointed_path)


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
    app.add_handler(CommandHandler("molmo2", cmd_molmo2))
    app.add_handler(CommandHandler("molmo2track", cmd_molmo2track))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | (filters.Document.IMAGE | filters.Document.VIDEO), handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(InlineQueryHandler(handle_inline))

    logger.info("Starting OLMo bot (allowed users: %s)", ALLOWED_USERS or "all")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
