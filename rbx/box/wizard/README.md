# Robox.io WebServer

* THIS WAS VIBE CODED AND IS JUST A BETA EXPERIMENT.

A simple FastAPI server for robox.io.

## Features

- Root endpoint (`/`) - Serves a dummy HTML page
- API endpoint (`/api/`) - Returns a Hello World JSON response
- Auto-generated API documentation at `/docs`

## Usage

### Running the server

```python
from webserver.server import run_server

# Run on default port 8000
run_server()

# Run on custom port
run_server(port=3000)

# Run with auto-reload enabled (for development)
run_server(reload=True)

# Run on a different host
run_server(host="0.0.0.0", port=8080)
```

### Direct execution

You can also run the example script:

```bash
python webserver/example.py
```

## Endpoints

- `GET /` - Returns an HTML welcome page
- `GET /api/` - Returns a JSON response: `{"message": "Hello World", "status": "success"}`
- `GET /docs` - Interactive API documentation (Swagger UI)
- `GET /redoc` - Alternative API documentation (ReDoc)
