# 🤖 Telegram Chat Bot

A feature-rich Telegram bot built with Python, designed to enhance group engagement through interactive games, media tools, and robust admin controls.

## 📋 Overview

This bot provides a complete community management and entertainment toolkit for Telegram groups — combining moderation utilities, interactive mini-games, and media processing into a single, extensible application.

## ✨ Features

- **Admin Tools** — Owner-restricted broadcast messaging, warning system, and group moderation commands
- **Interactive Games** — Trivia and word-grid games with difficulty levels to drive group engagement
- **Media Processing** — Image and media handling powered by third-party APIs
- **Access Control** — Optional force-subscribe gating, requiring users to join designated groups/channels before interacting with the bot
- **Engagement System** — Randomized XP-drop events with time-limited claims to encourage active participation
- **Persistent Logging** — Structured logging for monitoring bot health and diagnosing issues in production

## 🛠️ Tech Stack

- **Language:** Python 3.x
- **Bot Framework:** python-telegram-bot
- **Data Storage:** JSON-based persistence
- **External Integrations:** Third-party APIs for media and AI-assisted features

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
git clone https://github.com/yourusername/your-repo-name.git
cd your-repo-name
pip install -r requirements.txt
```

### Configuration

Copy `config.example.py` to `config.py` and fill in your credentials:

```bash
cp config.example.py config.py
```

### Running the Bot

```bash
python bot.py
```

## 📁 Project Structure
├── bot.py # Application entry point
├── config.py # Configuration (not tracked in git)
├── database.py # Data persistence layer
├── handlers_admin.py # Admin command handlers
├── handlers_forcesub.py # Force-subscribe access control
├── handlers_greetings.py # Group greeting logic
├── handlers_media.py # Media processing handlers
├── upgraded_features.py # Games and engagement features
├── utils/ # Shared helper functions
└── assets/ # Static assets

## 🔒 Security

Sensitive credentials are managed via a local `config.py` file, which is excluded from version control. A `config.example.py` template is provided to show the required configuration structure without exposing real values.

## 📄 License

This project is available for educational and personal use.

## 👤 Author

Built by [Haggai Eziwanee] — [haggaieziwanee2803@gmail.com]