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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /start command. Sends a welcome message with inline keyboard buttons.
    """
    welcome_text = (
        "Welcome to the VPN Config Generator Bot!\n\n"
        "Choose your platform or generate your configuration below."
    )
    keyboard = [
        [
            InlineKeyboardButton("Android 📱", url="https://play.google.com/store/apps/details?id=com.v2raytun.android&hl=en&pli=1"),
            InlineKeyboardButton("iOS 🍎", url="https://apps.apple.com/pl/app/v2raytun/id6476628951")
        ],
        [
            # Example: using inbound with id = 1. Modify if you implement inbound selection.
            InlineKeyboardButton("Generate Config 🔧", callback_data="config_1")
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
    """
    Handles callback queries triggered by inline keyboard buttons.
    Generates a configuration link for the selected inbound.
    """
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("config_"):
        await query.message.reply_text("Unknown action.")
        return

    inbound_id = data.split("_", 1)[1]
    await query.edit_message_text(text="Processing configuration generation request...")

    # Retrieve inbound details via API (get_inbound_config should return a JSON string or dict)
    inbound_details = get_inbound_config(inbound_id)
    if not inbound_details:
        await query.message.reply_text("Error retrieving inbound data. Please try again later.")
        return
    if isinstance(inbound_details, str):
        try:
            inbound_details = json.loads(inbound_details)
        except Exception:
            await query.message.reply_text("Error parsing inbound data.")
            return

    # If the API returns an object under "obj", use it
    if "obj" in inbound_details:
        inbound_details = inbound_details["obj"]

    # Extract the port; if it is 0, return an error
    port = inbound_details.get("port", 0)
    if not port or port == 0:
        await query.message.reply_text("Error: inbound port is 0")
        return

    # Use the 'remark' field for the link fragment (if empty, set a default value)
    remark = inbound_details.get("remark")
    if not remark:
        remark = "vless-ws-tls"

    # Retrieve streamSettings (stored as a JSON string)
    try:
        stream_settings = json.loads(inbound_details.get("streamSettings", "{}"))
    except Exception:
        stream_settings = {}
    ws_settings = stream_settings.get("wsSettings", {})
    ws_path = ws_settings.get("path", "/ws")
    ws_host = ws_settings.get("host", "vpn.example.com")
    security = stream_settings.get("security", "tls")
    alpn_list = stream_settings.get("alpn", [])
    alpn_str = ",".join(alpn_list) if isinstance(alpn_list, list) else alpn_list
    tls_settings = stream_settings.get("tlsSettings", {})
    sni = tls_settings.get("serverName", ws_host)

    # Retrieve client data from context.user_data; if absent, create a new client via the API
    user = update.effective_user
    client_id = context.user_data.get("client_id")
    client_email = context.user_data.get("client_email")
    if not client_id or not client_email:
        client_email = user.username if user.username else f"user{user.id}"
        new_client = create_client(int(inbound_id), client_email)
        if not new_client:
            await query.message.reply_text("Error creating a new client. Please try again later.")
            return
        client_id = new_client["client_id"]
        client_email = new_client["email"]
        context.user_data["client_id"] = client_id
        context.user_data["client_email"] = client_email

    # Form the fragment and the final vless connection link
    fragment = f"{remark}-{client_email}"
    encoded_path = urllib.parse.quote(ws_path)
    link = (f"vless://{client_id}@{ws_host}:{port}"
            f"?type=ws&path={encoded_path}&host={ws_host}&security={security}"
            f"&fp=chrome&alpn={alpn_str}&sni={sni}#{fragment}")

    # Save the generated config for potential future use
    context.user_data["last_config"] = link

    # Generate a QR code for the connection link
    qr_img = qrcode.make(link)
    bio = BytesIO()
    qr_img.save(bio, format="PNG")
    bio.seek(0)

    # Send the configuration wrapped in a Markdown code block for easy copying
    config_message = f"Your configuration:\n```\n{escape_markdown(link, version=2)}\n```"
    await query.message.reply_text(config_message, parse_mode="MarkdownV2")
    await query.message.reply_photo(photo=bio)

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
