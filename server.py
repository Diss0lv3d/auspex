"""Entrypoint: `python server.py` or `uvicorn server:app`."""

import uvicorn

from auspex.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000)  # noqa: S104 — container bind
