import dataclasses


@dataclasses.dataclass
class State:
    run_through_cli: bool = False
    sanitized: bool = False
    capture_pipes: bool = False


STATE = State()
