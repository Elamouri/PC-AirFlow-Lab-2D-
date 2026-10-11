"""Who made the app: shown in the window, the About box, the exported pictures / videos and the reports."""
from . import __version__

APP_NAME = 'PC Airflow Lab'
VERSION = __version__
AUTHOR = 'ElAmouri'
POWERED_BY = 'Powered by ElAmouri'
GITHUB_URL = 'https://github.com/Elamouri'
GITHUB_TEXT = 'github.com/Elamouri'
WHATSAPP_NUMBER = '+962796742759'
WHATSAPP_TEXT = '+962 79 674 2759'
WHATSAPP_URL = 'https://wa.me/962796742759'
CREDIT_LINE = '%s  ·  %s  ·  WhatsApp %s' % (POWERED_BY, GITHUB_TEXT, WHATSAPP_TEXT)
CREDIT_ASCII = '%s - %s - WhatsApp %s' % (POWERED_BY, GITHUB_URL, WHATSAPP_NUMBER)
WINDOW_TITLE = '%s %s  —  %s' % (APP_NAME, VERSION, POWERED_BY)
