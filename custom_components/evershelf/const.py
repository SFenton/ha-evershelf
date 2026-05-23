"""Constants for the EverShelf integration."""
from datetime import timedelta

DOMAIN = "evershelf"

CONF_URL = "url"
CONF_TOKEN = "token"

# Default polling interval
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

PLATFORMS = ["sensor", "binary_sensor"]
