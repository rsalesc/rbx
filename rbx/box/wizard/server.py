"""Server utilities for running the FastAPI application."""

from typing import Optional

import uvicorn

from rbx.box.wizard.app import app


def run_server(
    port: Optional[int] = None, host: str = '127.0.0.1', reload: bool = False
):
    """
    Start the FastAPI webserver.

    Args:
        port: The port to run the server on. If None, defaults to 8000.
        host: The host address to bind to. Defaults to "127.0.0.1".
        reload: Whether to enable auto-reload on code changes. Defaults to False.

    Example:
        >>> from webserver.server import run_server
        >>> run_server(port=8080)  # Run on port 8080
        >>> run_server()  # Run on default port 8000
    """
    if port is None:
        port = 8000

    print(f'Starting Robox.io webserver on http://{host}:{port}')
    print(f'API documentation available at http://{host}:{port}/docs')

    uvicorn.run(
        'rbx.box.wizard.app:app' if reload else app, host=host, port=port, reload=reload
    )
