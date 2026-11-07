"""Start the LAN bridge using the private local pairing configuration."""
import json
import os
from pathlib import Path
import sys

import server


def main():
    path = Path(__file__).with_name("config.local.json")
    config = json.loads(path.read_text(encoding="utf-8"))
    os.environ["DESK_ACCESS_TOKEN"] = config["access_token"]
    sys.argv = ["server.py", "--live", "--host", config["host"], "--port", "8787"]
    server.main()


if __name__ == "__main__":
    main()
