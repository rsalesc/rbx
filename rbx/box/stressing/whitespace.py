from typing import List


def normalize_text(text: str) -> str:
    stripped = text.strip()
    if stripped == '':
        return ''
    return stripped + '\n'


def normalize_line(line: str) -> str:
    return line.strip() + '\n'


def normalize_lines(lines: List[str]) -> str:
    return normalize_text(''.join(normalize_line(line) for line in lines))


def normalize_lines_from_text(text: str) -> str:
    return normalize_lines(text.splitlines())


def normalize_trailing_lines(lines: List[str]) -> str:
    i = 0
    while i < len(lines) and lines[i].strip() == '':
        i += 1
    if i == len(lines):
        return ''
    lines = lines[i:]
    while lines and lines[-1].strip() == '':
        lines.pop()
    lines = [line.rstrip('\n') for line in lines]
    return normalize_text('\n'.join(lines))


def normalize_trailing_lines_from_text(text: str) -> str:
    return normalize_trailing_lines(text.splitlines())
