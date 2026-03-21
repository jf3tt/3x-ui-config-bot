import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import json
import urllib.parse
import qrcode
from io import BytesIO
import uuid
from telegram.helpers import escape_markdown
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# Set up logging
# ---------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ---------------------------
# Load sensitive configuration from environment variables
# ---------------------------
API_HOST = os.getenv("API_HOST")
API_USERNAME = os.getenv("API_USERNAME")
API_PASSWORD = os.getenv("API_PASSWORD")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")  # Optional: channel for registration notifications

if not all([API_HOST, API_USERNAME, API_PASSWORD, TELEGRAM_TOKEN]):
    logger.error("Missing one or more required environment variables: "
                 "API_HOST, API_USERNAME, API_PASSWORD, TELEGRAM_TOKEN")
    exit(1)

# ---------------------------
# Create a session to store cookies (or token) for authentication
# ---------------------------
session = requests.Session()

def api_login() -> bool:
    """
    Performs a POST request to /login to authenticate with the API.
    On successful authentication, the session will store the necessary cookie.
    """
    login_url = f"{API_HOST}/login"
    payload = {"username": API_USERNAME, "password": API_PASSWORD}
    try:
        response = session.post(login_url, json=payload, timeout=10)
        logger.debug("Login response text: %s", response.text)
        if response.status_code == 200:
            # Optionally, parse JSON to confirm success
            try:
                data = response.json()
                if data.get("success"):
                    logger.info("Successfully authenticated with the API")
                    return True
                else:
                    logger.error("API login error: %s", data.get("msg", "No message"))
                    return False
            except json.JSONDecodeError:
                # If 3x-ui doesn't return JSON on success, we assume it's okay if status_code == 200
                logger.info("Successfully authenticated (no JSON in response).")
                return True
        else:
            logger.error(f"Authentication error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.exception("Error during API authentication request:")
        return False

def request_3x_ui(method: str, path: str, **kwargs) -> requests.Response:
    """
    A unified request wrapper that:
      1. Sends the request with the current session.
      2. If the response is HTML (login page), tries to re-login and retries once.
    """
    url = f"{API_HOST}{path}"
    logger.debug("Sending %s request to %s", method, url)
    resp = session.request(method, url, timeout=10, **kwargs)

    content_type = resp.headers.get("Content-Type", "")
    # If we detect HTML or <html in the response, the session might have expired.
    if "text/html" in content_type or "<html" in resp.text.lower():
        logger.warning("Session may have expired (received HTML). Attempting re-login.")
        if api_login():
            resp = session.request(method, url, timeout=10, **kwargs)
        else:
            logger.error("Re-login failed. Returning original response.")
    return resp

def get_inbounds_list() -> list:
    """
    Retrieves a list of inbounds via the API.
    """
    resp = request_3x_ui("GET", "/panel/api/inbounds/list")
    if resp.status_code == 200:
        try:
            data = resp.json()
            if data.get("success") and "obj" in data:
                inbounds = data["obj"]
                logger.info(f"Retrieved {len(inbounds)} inbounds")
                return inbounds
            else:
                logger.error(f"API error: {data.get('msg', 'No message provided')}")
                return []
        except json.JSONDecodeError:
            logger.error("Received non-JSON response: %s", resp.text)
            return []
    else:
        logger.error(f"Error retrieving inbound list: {resp.status_code} - {resp.text}")
        return []

def get_inbound_config(inbound_id: str) -> str:
    """
    Retrieves the configuration for the specified inbound by its ID via GET /panel/api/inbounds/get/:id.
    Returns raw text (JSON or otherwise).
    """
    resp = request_3x_ui("GET", f"/panel/api/inbounds/get/{inbound_id}")
    if resp.status_code == 200:
        return resp.text
    else:
        logger.error(
            f"Error retrieving config for inbound {inbound_id}: "
            f"{resp.status_code} - {resp.text}"
        )
        return None

def create_client(inbound_id: int, email: str) -> dict:
    """
    Creates a new client for the specified inbound via POST /panel/api/inbounds/addClient.
    Returns the data needed to generate the connection link, or None on error.
    """
    client_id = str(uuid.uuid4())
    sub_id = str(uuid.uuid4())
    payload = {
        "id": inbound_id,  # inbound id as an integer
        "settings": json.dumps({
            "clients": [
                {
                    "id": client_id,
                    "flow": "",
                    "email": email,
                    "limitIp": 0,
                    "totalGB": 0,
                    "expiryTime": 0,
                    "enable": True,
                    "tgId": "",
                    "subId": sub_id,
                    "reset": 0
                }
            ]
        })
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    logger.info(f"Client creation request payload: {payload}")
    resp = request_3x_ui("POST", "/panel/api/inbounds/addClient", json=payload, headers=headers)
    logger.info(f"API response: {resp.text}")
    if resp.status_code == 200:
        try:
            data = resp.json()
            if data.get("success"):
                return {"client_id": client_id, "sub_id": sub_id, "email": email}
            else:
                logger.error(f"Client creation error: {data.get('msg', 'No message provided')}")
                return None
        except json.JSONDecodeError:
            logger.error("Expected JSON but got: %s", resp.text)
            return None
    else:
        logger.error(f"Error creating client: {resp.status_code} - {resp.text}")
        return None

def find_client_in_inbound(inbound_id: int, email: str) -> dict:
    """
    Searches for a client by email in a specific inbound.
    Returns the client dict if found, otherwise None.
    """
    config = get_inbound_config(str(inbound_id))
    if not config:
        return None
    try:
        data = json.loads(config) if isinstance(config, str) else config
        if "obj" in data:
            data = data["obj"]
        settings = json.loads(data.get("settings", "{}"))
        for c in settings.get("clients", []):
            if c.get("email") == email:
                logger.info("Found client '%s' in inbound %s", email, inbound_id)
                return c
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return None


def find_client_across_inbounds(email: str) -> dict:
    """
    Searches for a client by email across all inbounds.
    Returns a dict with 'inbound_id' and 'client' data if found, otherwise None.
    """
    inbounds = get_inbounds_list()
    for inbound in inbounds:
        try:
            settings = json.loads(inbound.get("settings", "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        clients = settings.get("clients", [])
        for c in clients:
            if c.get("email") == email:
                logger.info("Found client '%s' in inbound %s", email, inbound.get("id"))
                return {"inbound_id": inbound.get("id"), "client": c}
    return None


def delete_client(inbound_id: int, client_uuid: str) -> bool:
    """
    Deletes a client from the specified inbound via POST /panel/api/inbounds/:id/delClient/:clientId.
    Returns True on success, False on error.
    """
    path = f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}"
    logger.info("Deleting client %s from inbound %s", client_uuid, inbound_id)
    resp = request_3x_ui("POST", path)
    if resp.status_code == 200:
        try:
            data = resp.json()
            if data.get("success"):
                logger.info("Successfully deleted client %s from inbound %s", client_uuid, inbound_id)
                return True
            else:
                logger.error("Delete client error: %s", data.get("msg", "No message"))
                return False
        except json.JSONDecodeError:
            logger.error("Non-JSON response when deleting client: %s", resp.text)
            return False
    else:
        logger.error("Error deleting client: %s - %s", resp.status_code, resp.text)
        return False


def get_client_traffic(email: str) -> dict:
    """
    Retrieves client traffic data via GET /panel/api/inbounds/getClientTraffics/{email}.
    Returns a dict with the JSON response or None on error.
    """
    path = f"/panel/api/inbounds/getClientTraffics/{email}"
    resp = request_3x_ui("GET", path)
    logger.debug("Client traffic response: %s", resp.text)
    if resp.status_code == 200:
        try:
            data = resp.json()
            return data
        except json.JSONDecodeError:
            logger.error("Non-JSON response for client traffic: %s", resp.text)
            return None
    else:
        logger.error("Error retrieving client traffic: %s", resp.text)
        return None

def format_traffic(traffic_bytes: int) -> str:
    """Format traffic in MB if less than 1 GB, otherwise in GB."""
    if traffic_bytes < 1073741824:
        return f"{traffic_bytes / 1048576:.2f} MB"
    else:
        return f"{traffic_bytes / 1073741824:.2f} GB"

async def notify_channel(bot, user, inbound_remark: str, inbound_id) -> None:
    """Send a registration notification to the private channel (if configured)."""
    if not CHANNEL_ID:
        return
    username_str = f"@{user.username}" if user.username else "N/A"
    full_name = user.full_name or "Unknown"
    text = (
        "🆕 New registration\n\n"
        f"👤 User: {full_name} ({username_str})\n"
        f"🆔 ID: {user.id}\n"
        f"🖥 Server: {inbound_remark} (inbound {inbound_id})"
    )
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=text)
    except Exception as e:
        logger.error("Failed to send channel notification: %s", e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = (
        "Hello! 😃 Welcome to our VPN Bot!\n\n"
        "Choose a platform to download the client, generate your config, check your statistics, or view FAQ."
    )
    keyboard = [
        [
            InlineKeyboardButton("Android 📱", url="https://play.google.com/store/apps/details?id=com.v2raytun.android&hl=en&pli=1"),
            InlineKeyboardButton("iOS 🍎", url="https://apps.apple.com/pl/app/v2raytun/id6476628951")
        ],
        [
            InlineKeyboardButton("Generate Config 🔧", callback_data="choose_protocol"),
            InlineKeyboardButton("Statistics 📊", callback_data="stats")
        ],
        [
            InlineKeyboardButton("FAQ ❓", callback_data="faq")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("button_handler invoked")
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.debug("Callback data: %s", data)

    if data == "choose_protocol":
        keyboard = [
            [
                InlineKeyboardButton("Reality (TCP) 🌐", callback_data="config_2"),
                InlineKeyboardButton("Reality (XHTTP) ⚡", callback_data="config_3"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text="Choose a protocol:\n\n"
                 "• *Reality \\(TCP\\)* — standard, proven protocol\n"
                 "• *Reality \\(XHTTP\\)* — newer protocol, better anti\\-censorship",
            reply_markup=reply_markup,
            parse_mode="MarkdownV2"
        )
        return

    if data.startswith("config_"):
        inbound_id = data.split("_", 1)[1]
        logger.debug("Parsed inbound_id: %s", inbound_id)
        await query.edit_message_text(text=f"Processing request...")

        inbound_details = get_inbound_config(inbound_id)
        logger.debug("Received inbound_details: %s", inbound_details)
        if not inbound_details:
            await query.message.reply_text("Error retrieving inbound data. Please try again later.")
            return
        if isinstance(inbound_details, str):
            try:
                inbound_details = json.loads(inbound_details)
                logger.debug("Parsed inbound_details JSON: %s", inbound_details)
            except Exception as e:
                logger.error("Error parsing inbound data: %s", e)
                await query.message.reply_text("Error parsing inbound data.")
                return

        if "obj" in inbound_details:
            inbound_details = inbound_details["obj"]
            logger.debug("Using inbound_details from 'obj': %s", inbound_details)

        port = inbound_details.get("port", 0)
        if not port or port == 0:
            logger.error("Inbound port is 0")
            await query.message.reply_text("Error: Inbound port is 0")
            return
        logger.debug("Inbound port: %s", port)

        remark = inbound_details.get("remark")
        if not remark:
            remark = "vless-ws-tls"
        logger.debug("Remark: %s", remark)

        try:
            stream_settings = json.loads(inbound_details.get("streamSettings", "{}"))
            logger.debug("Stream settings: %s", stream_settings)
        except Exception as e:
            logger.error("Error parsing streamSettings: %s", e)
            stream_settings = {}

        network = stream_settings.get("network", "tcp")
        security = stream_settings.get("security", "reality")
        reality_settings = stream_settings.get("realitySettings", {})
        reality_sub_settings = reality_settings.get("settings", {})
        pbk = reality_sub_settings.get("publicKey", "")
        fp = reality_sub_settings.get("fingerprint", "chrome")
        spx = reality_sub_settings.get("spiderX", "")
        server_names = reality_settings.get("serverNames", [])
        sni = server_names[0] if server_names else ""
        short_ids = reality_settings.get("shortIds", [])
        sid = short_ids[0] if short_ids else ""

        # Parse XHTTP path if applicable
        xhttp_settings = stream_settings.get("xhttpSettings", {})
        xhttp_path = xhttp_settings.get("path", "")

        user = update.effective_user
        base_email = user.username if user.username else f"user{user.id}"
        client_email = f"{base_email}-xhttp" if int(inbound_id) == 3 else base_email
        logger.debug("User email to check: %s (base: %s)", client_email, base_email)

        # 1. Check if client already exists in the TARGET inbound
        existing = find_client_in_inbound(int(inbound_id), client_email)

        if existing:
            # Client already has a config on this inbound — return it
            logger.debug("Client '%s' already exists in inbound %s", client_email, inbound_id)
            await query.message.reply_text("You already have a config! Here it is:")
            client_id = existing.get("id")
            context.user_data["client_id"] = client_id
            context.user_data["client_email"] = client_email
        else:
            # 2. Check if client exists in the OLD inbound #1 (WS+TLS) for migration
            old_client = find_client_in_inbound(1, base_email)
            if old_client:
                logger.info("Migrating client '%s' from old inbound 1 to inbound %s", base_email, inbound_id)
                deleted = delete_client(1, old_client.get("id"))
                if not deleted:
                    logger.error("Failed to delete client '%s' from old inbound 1", base_email)
                    await query.message.reply_text("Error migrating your config. Please try again later.")
                    return

            # 3. Create new client in the target inbound
            new_client = create_client(int(inbound_id), client_email)
            if not new_client:
                logger.error("Error creating client '%s' in inbound %s", client_email, inbound_id)
                await query.message.reply_text("Error creating new client. Please try again later.")
                return
            client_id = new_client["client_id"]
            client_email = new_client["email"]
            if old_client:
                logger.info("Client '%s' migrated from inbound 1 to inbound %s", client_email, inbound_id)
                await query.message.reply_text("Your config has been migrated from the old server. Here is your new config:")
            else:
                logger.debug("New client created: %s", new_client)
                await notify_channel(context.bot, user, remark, inbound_id)
            context.user_data["client_id"] = client_id
            context.user_data["client_email"] = client_email

        fragment = f"{remark}-{client_email}"
        server_host = urllib.parse.urlparse(API_HOST).hostname
        encoded_spx = urllib.parse.quote(spx) if spx else ""
        link = (
            f"vless://{client_id}@{server_host}:{port}"
            f"?type={network}&security={security}"
            f"&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}"
            f"&spx={encoded_spx}"
        )
        if network == "xhttp" and xhttp_path:
            encoded_path = urllib.parse.quote(xhttp_path)
            link += f"&path={encoded_path}"
        link += f"#{fragment}"
        logger.debug("Generated link: %s", link)

        context.user_data["last_config"] = link

        qr_img = qrcode.make(link)
        bio = BytesIO()
        qr_img.save(bio, format="PNG")
        bio.seek(0)

        config_message = f"Your config:\n```\n{escape_markdown(link, version=2)}\n```"
        await query.message.reply_text(config_message, parse_mode="MarkdownV2")
        await query.message.reply_photo(photo=bio)

    elif data == "stats":
        user = update.effective_user
        user_id = user.id
        logger.debug("Retrieving stats for user id: %s", user_id)
        base_email = user.username if user.username else f"user{user.id}"

        # Collect stats for both protocols (TCP = base_email, XHTTP = base_email-xhttp)
        emails_to_check = [
            ("Reality (TCP)", base_email),
            ("Reality (XHTTP)", f"{base_email}-xhttp"),
        ]
        stats_lines = []
        has_any_stats = False
        for label, email in emails_to_check:
            stats_data = get_client_traffic(email)
            if stats_data and stats_data.get("success") and stats_data.get("obj"):
                stats_obj = stats_data["obj"]
                up = stats_obj.get("up", 0)
                down = stats_obj.get("down", 0)
                up_str = format_traffic(up)
                down_str = format_traffic(down)
                stats_lines.append(
                    f"*{label}:*\n"
                    f"  📤 Uploaded: `{up_str}`\n"
                    f"  📥 Downloaded: `{down_str}`"
                )
                has_any_stats = True

        if not has_any_stats:
            await query.message.reply_text("No statistics available. Generate a config first!")
            return

        stats_message = (
            "📊 *Traffic Statistics*\n\n"
            f"👤 *User ID:* `{user_id}`\n\n"
            + "\n\n".join(stats_lines) + "\n"
        )
        await query.message.reply_text(stats_message, parse_mode="Markdown")

    elif data == "faq":
        faq_message = (
            "❓ *FAQ: How to Load Your Config*\n\n"
            "*Two protocols available:*\n"
            "• *Reality (TCP)* — standard, proven protocol. Works everywhere.\n"
            "• *Reality (XHTTP)* — newer protocol with better anti-censorship properties. "
            "Try this if TCP is blocked in your region.\n"
            "You can have configs on *both* protocols at the same time.\n\n"
            "1. *Copy the Config*: Tap the config message to copy the VLESS link shown in the code block.\n"
            "2. *Open Your Client*: Launch your VLESS-compatible client (e.g., v2rayNG 1.9+, Hiddify, Streisand).\n"
            "3. *Import Config*: Look for an option like 'Import Config' or 'Scan QR Code'.\n"
            "   - You can paste the copied config string, or scan the QR code provided.\n"
            "4. *Connect*: Save the configuration and connect to start using your VPN.\n\n"
            "If you have any questions, feel free to ask!"
        )
        await query.message.reply_text(faq_message, parse_mode="Markdown")
    else:
        await query.message.reply_text("Unknown action.")

def main() -> None:
    """
    Main entry point.
    First performs API authentication, then sets up and starts the Telegram bot.
    """
    if not api_login():
        logger.error("Failed to authenticate with the API. Exiting.")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Register command and callback query handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("Bot started.")
    app.run_polling()  # Blocking call – runs the bot

if __name__ == "__main__":
    main()
