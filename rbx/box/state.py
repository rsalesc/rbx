import dataclasses


@dataclasses.dataclass
class State:
    run_through_cli: bool = False
    sanitized: bool = False
    debug_logs: bool = False


STATE = State()
