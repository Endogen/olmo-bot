"""OLMo Telegram Bot — chat with Allen AI models via web2api."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import tempfile
import textwrap
from collections import defaultdict
from contextlib import asynccontextmanager

import httpx
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
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
    TOOL_MODELS,
    VISION_MODELS,
    WEB2API_URL,
)
from formatting import md_to_telegram_html
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
# Typing indicator
# ---------------------------------------------------------------------------

async def send_formatted(msg, text: str) -> None:
    """Send a message with markdown→HTML conversion, falling back to plain text."""
    formatted = md_to_telegram_html(text)
    chunks = [formatted[i:i + 4096] for i in range(0, len(formatted), 4096)]
    for chunk in chunks:
        try:
            await msg.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            # If HTML parsing fails, send as plain text
            plain = text[chunks.index(chunk) * 4096:(chunks.index(chunk) + 1) * 4096] if len(chunks) > 1 else text
            await msg.reply_text(plain[:4096])


@asynccontextmanager
async def keep_typing(chat):
    """Send typing indicator every 4 seconds until the block exits."""
    stop = asyncio.Event()

    async def _loop():
        while not stop.is_set():
            try:
                await chat.send_action(ChatAction.TYPING)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=4)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop.set()
        await task


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
    use_tools: bool = False,
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

    # Build query params — tools_url only when explicitly requested
    params: dict[str, str] = {"q": full_prompt}
    if use_tools and DEFAULT_TOOLS_URL and model not in VISION_MODELS:
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

    # OLMo sometimes generates fake follow-up conversations — truncate at first
    # occurrence of a role marker that indicates hallucinated multi-turn output.
    for marker in ("\nuser\n", "\nassistant\n", "\n<function_calls>"):
        idx = answer.find(marker)
        if idx > 0:
            answer = answer[:idx].rstrip()
            break

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
        f"/search — web search (e.g. /search latest AI news)\n"
        f"/memory — toggle conversation memory\n"
        f"/clear — clear memory history\n"
        f"/status — current settings\n\n"
        f"📷 <b>Vision:</b> Send a photo or video with a caption to analyze it with Molmo 2.\n"
        f"🎯 <b>Pointing:</b> Use captions like \"Point to the eyes\" to get annotated images.",
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

    tmp_path = None
    pointed_path = None
    try:
        # Download to temp file
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
            await file_obj.download_to_drive(tmp_path)

        mem_on = user_memory_enabled.get(uid, False)
        history = user_history[uid] if mem_on else None
        async with keep_typing(msg.chat):
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
                    # Only send extra text if there's substantial content
                    # beyond the point labels themselves
                    clean_text = strip_points(answer)
                    all_labels = {
                        g.label.lower() for g in groups
                    }
                    if clean_text and clean_text.lower().strip() not in all_labels:
                        await msg.reply_text(clean_text)
            except Exception:
                logger.exception("Point overlay failed, sending text only")
                pointed_path = None

        if not pointed_path:
            await send_formatted(msg, answer)

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


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search the web via OLMo with tool calling enabled."""
    if not await check_access(update):
        return

    uid = update.effective_user.id
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /search <your question>")
        return

    model = user_model[uid]
    if model not in TOOL_MODELS:
        model = DEFAULT_MODEL  # only certain models support tool calling

    mem_on = user_memory_enabled.get(uid, False)

    try:
        async with keep_typing(update.message.chat):
            history = user_history[uid] if mem_on else None
            answer = await query_model(model, query, history, use_tools=True)

        if mem_on:
            user_history[uid].append({"role": "user", "text": query})
            user_history[uid].append({"role": "assistant", "text": answer})
            if len(user_history[uid]) > MAX_HISTORY * 2:
                user_history[uid] = user_history[uid][-(MAX_HISTORY * 2):]

        await send_formatted(update.message, answer)

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error: %s", e)
        await update.message.reply_text(f"❌ API error: {e.response.status_code}")
    except httpx.ReadTimeout:
        await update.message.reply_text("⏳ Search timed out — try again.")
    except Exception as e:
        logger.exception("Search error")
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_access(update):
        return

    uid = update.effective_user.id
    prompt = update.message.text
    if not prompt:
        return

    model = user_model[uid]
    mem_on = user_memory_enabled.get(uid, False)

    try:
        async with keep_typing(update.message.chat):
            history = user_history[uid] if mem_on else None
            answer = await query_model(model, prompt, history)

        # Store in history if memory enabled
        if mem_on:
            user_history[uid].append({"role": "user", "text": prompt})
            user_history[uid].append({"role": "assistant", "text": answer})
            # Trim to max
            if len(user_history[uid]) > MAX_HISTORY * 2:
                user_history[uid] = user_history[uid][-(MAX_HISTORY * 2):]

        await send_formatted(update.message, answer)

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error: %s", e)
        await update.message.reply_text(f"❌ API error: {e.response.status_code}")
    except httpx.ReadTimeout:
        await update.message.reply_text("⏳ Request timed out. The model might be slow — try again.")
    except Exception as e:
        logger.exception("Unexpected error")
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


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
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | (filters.Document.IMAGE | filters.Document.VIDEO), handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting OLMo bot (allowed users: %s)", ALLOWED_USERS or "all")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
