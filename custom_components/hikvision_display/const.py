"""Integration constants."""
from homeassistant.const import Platform

DOMAIN = "hikvision_display"
PLATFORMS = [Platform.SELECT, Platform.NUMBER, Platform.BUTTON, Platform.SENSOR]
DEFAULT_INTERVAL = 300
DEFAULT_BRIGHTNESS = 60
