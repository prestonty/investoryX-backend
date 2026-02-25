from __future__ import annotations

import os


# Prevent import-time failure in src.api.database.database during test discovery.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
