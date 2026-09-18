# Your configuration settings
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_WARNINGS = int(os.environ.get("MAX_WARNINGS", 3))
COHERE_KEY = os.environ.get("COHERE_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")


