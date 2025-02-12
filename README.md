# 3x-ui VPN Config Generator Bot

This repository contains a Telegram bot designed for use with [3x-ui](https://github.com/MHSanaei/3x-ui). The bot interacts with a VPN API to generate VPN configuration links. It creates new clients via the API and provides users with a configuration link (and a QR code) that they can use to connect to the VPN.

## Features

- **3x-ui Integration:**  
  This bot is specifically designed to work with 3x-ui. For more details about 3x-ui, see its [GitHub repository](https://github.com/MHSanaei/3x-ui).

- **API Integration:**  
  Authenticates with the VPN API and retrieves inbound configuration details.

- **Client Creation:**  
  Generates new clients on demand.

- **Configuration Link:**  
  Constructs a VLESS connection link based on inbound settings and client data.

- **QR Code Generation:**  
  Creates a QR code for easy scanning.

- **Cross-Platform:**  
  Provides quick links for Android and iOS apps.

## Prerequisites

- Python 3.10 or later
- A Telegram Bot Token from [BotFather](https://t.me/BotFather)
- VPN API credentials (host, username, and password)
- [3x-ui](https://github.com/MHSanaei/3x-ui) setup (for integration purposes)

## Environment Variables
The following environment variables are required:

API_HOST: The base URL for the 3x-ui API.
API_USERNAME: The username for the 3x-ui API.
API_PASSWORD: The password for the 3x-ui API.
TELEGRAM_TOKEN: The token for your Telegram bot.