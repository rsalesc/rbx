"""Example script showing how to use the webserver."""

from rbx.box.wizard.server import run_server

if __name__ == '__main__':
    # Run the server on the default port (8000)
    # You can also specify a custom port: run_server(port=3000)
    run_server()
