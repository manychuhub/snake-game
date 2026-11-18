from pathlib import Path
import os
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.getenv('BRIDGE_DATA_DIR', ROOT / 'data'))
HOST = '127.0.0.1'
PORT = int(os.getenv('BRIDGE_PORT','8011'))
TOKEN = (os.getenv('HYBRID_API_AUTH_TOKEN') or '').strip()
KEY = (os.getenv('GEMINI_API_KEY') or '').strip()
MODEL = os.getenv('GEMINI_MODEL','').removeprefix('models/')
EMBED_MODEL = os.getenv('GEMINI_EMBED_MODEL','').removeprefix('models/')
MAX_CONCURRENT = max(1,min(8,int(os.getenv('MAX_CLI_CONCURRENCY','3'))))
MAX_QUEUE = max(1,min(100,int(os.getenv('REQUEST_QUEUE_MAXSIZE','50'))))
TIMEOUT = max(10,min(300,int(os.getenv('BRIDGE_TIMEOUT','90'))))
BASE_URL = f'http://{HOST}:{PORT}'
