"""Settings read from the environment, and from .env in development."""

import os

from dotenv import load_dotenv

load_dotenv()

# Where the API is reachable from outside. The MCP server only accepts this host and localhost.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
