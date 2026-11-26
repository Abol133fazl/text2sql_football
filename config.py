import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-zMWszraO8OsZicnZM6rRTxP9OceO8Dn0FhN7ERs5v6maDK4i")
OPENAI_BASE_URL= os.getenv("OPENAI_BASE_URL", "https://api.gapgpt.app/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "football.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
SEMANTIC_MODEL_PATH = os.path.join(BASE_DIR, "semantic_model.md")
EVAL_PATH = os.path.join(BASE_DIR, "eval_questions.json")

MAX_ROWS = 100
QUERY_TIMEOUT_SEC = 3.0
MAX_SQL_RETRIES = 2