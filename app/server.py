"""Local API entry point: python -m app.server."""
import uvicorn
from app.api.application import create_app


def main():
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info"))
    app.state.controller = server
    server.run()


if __name__ == "__main__":
    main()
