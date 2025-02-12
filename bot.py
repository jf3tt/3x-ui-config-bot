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

if not all([API_HOST, API_USERNAME, API_PASSWORD, TELEGRAM_TOKEN]):
    logger.error("Missing one or more required environment variables: API_HOST, API_USERNAME, API_PASSWORD, TELEGRAM_TOKEN")
    exit(1)

# ---------------------------
# Create a session to store cookies (or token) for authentication
# ---------------------------
session = requests.Session()

def api_login() -> bool:
    """
    Performs a POST request to /login to authenticate with the API.
    On successful authentication, the session will store the necessary data.
    """
    login_url = f"{API_HOST}/login"
    payload = {"username": API_USERNAME, "password": API_PASSWORD}
    try:
        response = session.post(login_url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("Successfully authenticated with the API")
            return True
        else:
            logger.error(f"Authentication error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.exception("Error during API authentication request:")
        return False

def get_inbounds_list() -> list:
    """
    Retrieves a list of inbounds via the API.
    """
    url = f"{API_HOST}/panel/api/inbounds/list"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("success") and "obj" in data:
                inbounds = data["obj"]
                logger.info(f"Retrieved {len(inbounds)} inbounds")
                return inbounds
            else:
                logger.error(f"API error: {data.get('msg', 'No message provided')}")
                return []
        else:
            logger.error(f"Error retrieving inbound list: {response.status_code} - {response.text}")
            return []
    except Exception as e:
        logger.exception("Error while retrieving inbound list:")
        return []

def get_inbound_config(inbound_id: str) -> str:
    """
    Retrieves the configuration for the specified inbound by its ID via a GET request to /panel/api/inbounds/get/:id.
    """
    url = f"{API_HOST}/panel/api/inbounds/get/{inbound_id}"
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200:
            return response.text
        else:
            logger.error(
                f"Error retrieving config for inbound {inbound_id}: {response.status_code} - {response.text}"
            )
            return None
    except Exception as e:
        logger.exception("Error while accessing the API for config retrieval:")
        return None

def format_traffic(traffic_bytes: int) -> str:
    """Format traffic in MB if less than 1 GB, otherwise in GB."""
    if traffic_bytes < 1073741824:
        return f"{traffic_bytes / 1048576:.2f} MB"
    else:
        return f"{traffic_bytes / 1073741824:.2f} GB"

def get_client_traffic(email: str) -> dict:
    url = f"{API_HOST}/panel/api/inbounds/getClientTraffics/{email}"
    try:
        response = session.get(url, timeout=10)
        logger.debug("Client traffic response: %s", response.text)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            logger.error("Error retrieving client traffic: %s", response.text)
            return None
    except Exception as e:
        logger.exception("Exception retrieving client traffic:")
        return None

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
            InlineKeyboardButton("Generate Config 🔧", callback_data="config_1"),
            InlineKeyboardButton("Statistics 📊", callback_data="stats")
        ],
        [
            InlineKeyboardButton("FAQ ❓", callback_data="faq")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

def create_client(inbound_id: int, email: str) -> dict:
    """
    Creates a new client for the specified inbound via a POST request to /panel/api/inbounds/addClient.
    Returns the data needed to generate the connection link.
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
    try:
        response = session.post(f"{API_HOST}/panel/api/inbounds/addClient", json=payload, timeout=10, headers=headers)
        logger.info(f"Client creation request payload: {payload}")
        logger.info(f"API response: {response.text}")
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                # Return the data needed to form the connection link
                return {"client_id": client_id, "sub_id": sub_id, "email": email}
            else:
                logger.error(f"Client creation error: {data.get('msg', 'No message provided')}")
                return None
        else:
            logger.error(f"Error creating client: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.exception("Error during client creation:")
        return None

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.debug("button_handler invoked")
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.debug("Callback data: %s", data)

    if data.startswith("config_"):
        inbound_id = data.split("_", 1)[1]
        logger.debug("Parsed inbound_id: %s", inbound_id)
        await query.edit_message_text(text=f"Processing request for inbound {inbound_id}...")

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

        ws_settings = stream_settings.get("wsSettings", {})
        ws_path = ws_settings.get("path", "/ws")
        ws_host = ws_settings.get("host", "vpn.jfett.cloud")
        security = stream_settings.get("security", "tls")
        alpn_list = stream_settings.get("alpn", [])
        alpn_str = ",".join(alpn_list) if isinstance(alpn_list, list) else alpn_list
        tls_settings = stream_settings.get("tlsSettings", {})
        sni = tls_settings.get("serverName", ws_host)

        user = update.effective_user
        client_email = user.username if user.username else f"user{user.id}"
        logger.debug("User email to check: %s", client_email)

        try:
            settings = json.loads(inbound_details.get("settings", "{}"))
            logger.debug("Inbound settings: %s", settings)
        except Exception as e:
            logger.error("Error parsing inbound settings: %s", e)
            settings = {}
        clients = settings.get("clients", [])
        existing_client = None
        for c in clients:
            if c.get("email") == client_email:
                existing_client = c
                break

        if existing_client:
            await query.message.reply_text("You already have a config in the 3x‑ui system!")
            client_id = existing_client.get("id")
            logger.debug("Existing client found: %s", existing_client)
            context.user_data["client_id"] = client_id
            context.user_data["client_email"] = client_email
        else:
            new_client = create_client(int(inbound_id), client_email)
            if not new_client:
                logger.error("Error creating new client")
                await query.message.reply_text("Error creating new client. Please try again later.")
                return
            client_id = new_client["client_id"]
            client_email = new_client["email"]
            logger.debug("New client created: %s", new_client)
            context.user_data["client_id"] = client_id
            context.user_data["client_email"] = client_email

        fragment = f"{remark}-{client_email}"
        encoded_path = urllib.parse.quote(ws_path)
        link = (f"vless://{client_id}@{ws_host}:{port}"
                f"?type=ws&path={encoded_path}&host={ws_host}&security={security}"
                f"&fp=chrome&alpn={alpn_str}&sni={sni}#{fragment}")
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
        client_email = user.username if user.username else f"user{user.id}"
        stats_data = get_client_traffic(client_email)
        if not stats_data or not stats_data.get("success"):
            await query.message.reply_text("Error retrieving statistics. Please try again later.")
            return
        stats_obj = stats_data.get("obj")
        if not stats_obj:
            await query.message.reply_text("No statistics available.")
            return
        up = stats_obj.get("up", 0)
        down = stats_obj.get("down", 0)
        up_str = format_traffic(up)
        down_str = format_traffic(down)
        stats_message = (
            "📊 *Traffic Statistics*\n\n"
            f"👤 *User ID:* `{user_id}`\n"
            f"📤 *Uploaded:* `{up_str}`\n"
            f"📥 *Downloaded:* `{down_str}`\n"
        )
        await query.message.reply_text(stats_message, parse_mode="Markdown")
        
    elif data == "faq":
        faq_message = (
            "❓ *FAQ: How to Load Your Config*\n\n"
            "1. *Copy the Config*: Tap the config message to copy the VLESS link shown in the code block.\n"
            "2. *Open Your Client*: Launch your VLESS-compatible client (e.g., v2rayNG).\n"
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
