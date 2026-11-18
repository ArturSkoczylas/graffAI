from __future__ import annotations

import logging
import os
import sys

from .api import server
from .config import Config, ConfigError


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = Config.from_env(os.environ)
    except ConfigError as exc:
        print(f"Błąd konfiguracji: {exc}", file=sys.stderr)
        return 1
    server.run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
