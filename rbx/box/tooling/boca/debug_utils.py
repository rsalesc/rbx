import urllib.parse
from typing import Any

from rbx import console


def pretty_print_request_data(req: Any) -> None:
    """
    Pretty print the POST data from a mechanize request.

    Args:
        req: A mechanize.Request object containing POST data
    """
    if hasattr(req, 'data') and req.data:
        console.console.print('\n[bold blue]POST Data:[/bold blue]')
        if isinstance(req.data, bytes):
            try:
                # Try to decode the data
                decoded_data = req.data.decode('utf-8')

                # Check if it's multipart form data
                if 'Content-Disposition: form-data' in decoded_data:
                    console.console.print('  [cyan]Format:[/cyan] multipart/form-data')
                    # Parse multipart form data
                    parts = decoded_data.split('-----------------------------')
                    for part in parts[1:-1]:  # Skip first empty part and last boundary
                        if 'Content-Disposition: form-data' in part:
                            lines = part.strip().split('\r\n')
                            for line in lines:
                                if line.startswith(
                                    'Content-Disposition: form-data; name='
                                ):
                                    # Extract field name
                                    name_start = line.find('name="') + 6
                                    name_end = line.find('"', name_start)
                                    if name_end == -1:
                                        name_end = line.find('\r', name_start)
                                    field_name = line[name_start:name_end]

                                    # Find the value (after empty line)
                                    try:
                                        empty_line_idx = lines.index('')
                                        if empty_line_idx + 1 < len(lines):
                                            field_value = lines[empty_line_idx + 1]
                                            # Handle file uploads
                                            if 'filename=' in line:
                                                filename_start = (
                                                    line.find('filename="') + 10
                                                )
                                                filename_end = line.find(
                                                    '"', filename_start
                                                )
                                                filename = line[
                                                    filename_start:filename_end
                                                ]
                                                console.console.print(
                                                    f'  [green]{field_name}[/green]: [yellow](file: {filename})[/yellow]'
                                                )
                                            else:
                                                console.console.print(
                                                    f'  [green]{field_name}[/green]: [white]{field_value}[/white]'
                                                )
                                    except (ValueError, IndexError):
                                        console.console.print(
                                            f'  [green]{field_name}[/green]: [dim](could not parse value)[/dim]'
                                        )
                                    break
                else:
                    # Try to parse as URL-encoded data
                    console.console.print(
                        '  [cyan]Format:[/cyan] application/x-www-form-urlencoded'
                    )
                    parsed_data = urllib.parse.parse_qs(decoded_data)
                    for key, values in parsed_data.items():
                        # Show first value if list has one item, otherwise show the list
                        display_value = values[0] if len(values) == 1 else values
                        console.console.print(
                            f'  [green]{key}[/green]: [white]{display_value}[/white]'
                        )

            except UnicodeDecodeError:
                console.console.print(
                    f"  [yellow]Raw bytes ({len(req.data)} bytes):[/yellow] {req.data[:100]}{'...' if len(req.data) > 100 else ''}"
                )
        else:
            console.console.print(f'  [yellow]Data:[/yellow] {req.data}')
    else:
        console.console.print('\n[yellow]No POST data found in request[/yellow]')
