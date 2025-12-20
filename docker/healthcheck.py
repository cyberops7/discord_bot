#!/usr/bin/env python3
"""Healthcheck script for Docker HEALTHCHECK."""

import json
import sys
from urllib.error import URLError
from urllib.request import urlopen

try:
    with urlopen(  # nosec B310
        "http://localhost:8080/healthcheck", timeout=5
    ) as response:
        data = json.loads(response.read())
        sys.exit(0 if data.get("status") == "ok" else 1)
except (OSError, URLError, ValueError):
    sys.exit(1)
