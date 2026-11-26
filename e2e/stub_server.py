"""Test-only server: the real app with a fake signed-in user and no Databricks. Never deployed."""
import os
import sys

os.environ.update(PORTAL_ENV="dev", PORTAL_WARM="0")  # must be set before importing app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import app as portal_app
from portal.auth import User

portal_app.current_user = lambda request: User(key="u1", email="test@example.com", groups=frozenset(), client=None)

import uvicorn

uvicorn.run(portal_app.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
