import dataclasses


@dataclasses.dataclass
class State:
    run_through_cli: bool = False


STATE = State()
