"""A recording fake for the Polygon API client used by e2e statement-upload
scenarios. Patched in over ``rbx.box.packaging.polygon.upload._get_polygon_api``
so ``rbx package polygon -u`` performs no network I/O while every uploaded
statement and statement resource is serialized to disk for the
``polygon_upload`` e2e matcher to assert on.
"""

import json
import threading
from pathlib import Path
from typing import List, Optional

# Module-level holder for the active capture directory. The e2e runner sets this
# to ``<pkg_tmpdir>/.rbx/polygon_capture`` before each scenario's steps and resets
# it afterwards, so concurrent scenarios in one process do not leak.
_CAPTURE_DIR: Optional[Path] = None
_LOCK = threading.Lock()


def set_capture_dir(path: Path) -> None:
    global _CAPTURE_DIR
    _CAPTURE_DIR = Path(path)


def get_capture_dir() -> Optional[Path]:
    return _CAPTURE_DIR


def reset_capture_dir() -> None:
    global _CAPTURE_DIR
    _CAPTURE_DIR = None


class RecordingProblem:
    def __init__(self, capture_dir: Path):
        self._dir = capture_dir
        (self._dir / 'statements').mkdir(parents=True, exist_ok=True)
        (self._dir / 'resources').mkdir(parents=True, exist_ok=True)
        self._resources: List[str] = []
        self._calls: List[dict] = []

    # --- recorded statement surface -------------------------------------
    def save_statement(self, lang: str, problem_statement) -> None:
        s = problem_statement
        payload = {
            'name': s.name,
            'legend': s.legend,
            'input': s.input,
            'output': s.output,
            'interaction': getattr(s, 'interaction', None),
            'notes': s.notes,
        }
        with _LOCK:
            (self._dir / 'statements' / f'{lang}.json').write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )

    def save_statement_resource(self, name: str, file: bytes) -> None:
        with _LOCK:
            (self._dir / 'resources' / name).write_bytes(file)
            self._resources.append(name)
            (self._dir / 'resources.json').write_text(
                json.dumps(sorted(set(self._resources)), ensure_ascii=False, indent=2)
            )

    # --- everything else: record-and-ignore ------------------------------
    def _record(self, method: str, **kw) -> None:
        with _LOCK:
            self._calls.append({'method': method, **{k: str(v) for k, v in kw.items()}})
            (self._dir / 'calls.json').write_text(
                json.dumps(self._calls, ensure_ascii=False, indent=2)
            )

    def update_info(self, info) -> None:
        self._record('update_info')

    def save_file(self, type=None, name=None, file=None, source_type=None) -> None:
        self._record('save_file', name=name, type=type)

    def set_checker(self, name) -> None:
        self._record('set_checker', name=name)

    def set_interactor(self, name) -> None:
        self._record('set_interactor', name=name)

    def set_validator(self, name) -> None:
        self._record('set_validator', name=name)

    def save_solution(self, name, content, source_type=None, tag=None) -> None:
        self._record('save_solution', name=name, tag=tag)

    def solutions(self) -> list:
        return []

    def save_test(self, *args, **kw) -> None:
        self._record('save_test', index=kw.get('test_index'))

    def save_script(self, testset=None, source=None) -> None:
        self._record('save_script', testset=testset)

    def commit_changes(self) -> None:
        self._record('commit_changes')


class RecordingPolygon:
    def __init__(self, capture_dir: Path):
        self._dir = capture_dir

    def problems_list(self, name: Optional[str] = None) -> list:
        return []

    def problem_create(self, name: str) -> RecordingProblem:
        return RecordingProblem(self._dir)


def make_recording_polygon(*args, **kwargs) -> RecordingPolygon:
    """Factory patched in over ``upload._get_polygon_api`` (ignores api url/keys)."""
    capture_dir = get_capture_dir()
    if capture_dir is None:
        raise RuntimeError(
            'polygon_capture.make_recording_polygon called with no capture dir set; '
            'the e2e runner must set_capture_dir before running steps'
        )
    capture_dir.mkdir(parents=True, exist_ok=True)
    return RecordingPolygon(capture_dir)
