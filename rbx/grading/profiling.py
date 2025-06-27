import contextvars
import functools
import math
import threading
import time

ALL_CONTEXTS_BY_NAME = {}
_ALL_CONTEXTS_BY_NAME_LOCK = threading.Lock()


@functools.cache
def _get_threadsafe_context(name: str) -> 'Context':
    with _ALL_CONTEXTS_BY_NAME_LOCK:
        if name not in ALL_CONTEXTS_BY_NAME:
            ALL_CONTEXTS_BY_NAME[name] = Context(name)
        return ALL_CONTEXTS_BY_NAME[name]


class Distribution:
    def __init__(self):
        self.values = []

    def add(self, value: float):
        self.values.append(value)

    def mean(self) -> float:
        return sum(self.values) / len(self.values)

    def median(self) -> float:
        return sorted(self.values)[len(self.values) // 2]

    def stddev(self) -> float:
        mean = self.mean()
        return math.sqrt(sum((x - mean) ** 2 for x in self.values) / len(self.values))


class Context:
    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self.distributions = {}
        self.counters = {}

    def add_to_distribution(self, name: str, value: float):
        with self._lock:
            if name not in self.distributions:
                self.distributions[name] = Distribution()
            self.distributions[name].add(value)

    def add_to_counter(self, name: str):
        with self._lock:
            if name not in self.counters:
                self.counters[name] = 0
            self.counters[name] += 1

    def print_summary(self):
        with self._lock:
            print(f'{self.name}:')
            for name, distribution in sorted(self.distributions.items()):
                print(f'  ~ {name}: {distribution.mean():.2f}')
            for name, count in sorted(self.counters.items()):
                print(f'  + {name}: {count}')


profiling_stack_var = contextvars.ContextVar(
    'profiling_stack', default=[_get_threadsafe_context('root')]
)


def _push_profiling_stack(name: str):
    return profiling_stack_var.set(
        profiling_stack_var.get() + [_get_threadsafe_context(name)]
    )


class PushContext:
    def __init__(self, name: str):
        self.name = name
        self.token = None

    def __enter__(self):
        self.token = _push_profiling_stack(self.name)
        return profiling_stack_var.get()[-1]

    def __exit__(self, exc_type, exc_value, traceback):
        if self.token is not None:
            profiling_stack_var.reset(self.token)


def print_summary():
    print('\n' + ('-') * 3 + '\n')
    with _ALL_CONTEXTS_BY_NAME_LOCK:
        for context in ALL_CONTEXTS_BY_NAME.values():
            context.print_summary()


### Public API


class Profiler:
    def __init__(self, name: str, start: bool = False):
        self.name = name
        self.start_time = 0
        if start:
            self.start()

    def start(self):
        self.start_time = time.monotonic()
        return self

    def stop(self):
        self.end_time = time.monotonic()
        self.duration = self.end_time - self.start_time
        for context in profiling_stack_var.get():
            context.add_to_distribution(self.name, self.duration)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()


def add_to_counter(name: str):
    for context in profiling_stack_var.get():
        context.add_to_counter(name)
