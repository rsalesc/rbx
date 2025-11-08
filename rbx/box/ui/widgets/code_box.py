import json
import pathlib
from typing import Optional

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog


def detect_language(path: pathlib.Path) -> str:
    ext = path.suffix.lower().lstrip('.')
    if ext in {'py', 'pyw'}:
        return 'python'
    if ext in {'cpp', 'cc', 'cxx', 'hpp', 'hxx', 'h'}:
        return 'cpp'
    if ext in {'java'}:
        return 'java'
    if ext in {'kt', 'kts'}:
        return 'kotlin'
    if ext in {
        'json',
        'yml',
        'yaml',
        'toml',
        'ini',
        'md',
        'sh',
        'bash',
        'zsh',
        'js',
        'ts',
    }:
        return ext
    return 'text'


class CodeBox(Widget, can_focus=False):
    path: reactive[Optional[pathlib.Path]] = reactive(None)
    language_override: reactive[Optional[str]] = reactive(None)

    def __init__(self):
        super().__init__()

    def compose(self) -> ComposeResult:
        log = RichLog()
        log.border_title = 'Review'
        yield log

    def _normalize_language(self, token: str) -> Optional[str]:
        t = token.strip().lower()
        if not t:
            return None
        # Common normalizations
        if 'c++' in t or 'g++' in t or 'cpp' in t or 'gnu g++' in t:
            return 'cpp'
        if 'python' in t or t == 'py':
            return 'python'
        if 'java' in t:
            return 'java'
        if 'kotlin' in t or t == 'kt' or t == 'kts':
            return 'kotlin'
        if t in {'json', 'yaml', 'yml', 'toml', 'ini', 'md', 'markdown'}:
            return (
                'json'
                if t == 'json'
                else (
                    'yaml'
                    if t in {'yaml', 'yml'}
                    else ('markdown' if t in {'md', 'markdown'} else t)
                )
            )
        if t in {'sh', 'bash', 'zsh'}:
            return t
        if t in {'js', 'ts', 'typescript', 'javascript'}:
            return 'ts' if t in {'ts', 'typescript'} else 'js'
        if t in {'text', 'plain'}:
            return 'text'
        return t

    def _read_metadata_language(self, path: pathlib.Path) -> Optional[str]:
        meta_path = (
            path.with_suffix(path.suffix + '.json')
            if path.suffix
            else pathlib.Path(str(path) + '.json')
        )
        try:
            if not meta_path.exists():
                # Also try sibling with exact stem + '.json' (for files without extension)
                alt = pathlib.Path(str(path) + '.json')
                meta_path = alt if alt.exists() else meta_path
            if not meta_path.exists():
                return None
            data = json.loads(meta_path.read_text())
        except Exception:
            return None
        # Prefer explicit 'language', fallback to 'language_repr', else derive from 'filename' ext
        lang = None
        try:
            lang = data.get('language')
            if not lang:
                lang = data.get('language_repr')
            if not lang:
                filename = data.get('filename')
                if filename:
                    lang = detect_language(pathlib.Path(str(filename)))
        except Exception:
            lang = None
        if not lang:
            return None
        return self._normalize_language(str(lang))

    async def watch_path(self, path: Optional[pathlib.Path]):
        log = self.query_one(RichLog)
        log.clear()
        if path is None:
            return
        code = path.read_text()
        # Priority: explicit override > metadata > filename-based detection
        lang = (
            self.language_override
            or self._read_metadata_language(path)
            or detect_language(path)
        )
        md = Markdown(f'```{lang}\n{code}\n```', code_theme='monokai')
        log.write(md)
