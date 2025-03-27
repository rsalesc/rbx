def get_formatted_memory(memory_in_bytes: int, mib_decimal_places: int = 0) -> str:
    if memory_in_bytes < 1024 * 1024:
        if memory_in_bytes < 1024:
            return f'{memory_in_bytes} B'
        return f'{memory_in_bytes / 1024:.0f} KiB'
    return f'{memory_in_bytes / (1024 * 1024):.{mib_decimal_places}f} MiB'


def get_formatted_time(time_in_ms: int) -> str:
    return f'{time_in_ms} ms'
