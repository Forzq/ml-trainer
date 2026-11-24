"""Local API entry point: python -m app.server."""
import os

import uvicorn
from app.api.application import create_app


def main():
    app = create_app()
    port = int(os.getenv("MOCKROOM_PORT", "8765"))
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="info", forwarded_allow_ips="127.0.0.1",
    ))
    app.state.controller = server
    server.run()


if __name__ == "__main__":
    main()
