import logging
import pathlib
import threading
import time
from typing import List, Optional

import fastapi
import jinja2
import rich
import rich.prompt
import rich.status
import uvicorn

from rbx import hydration, metadata, providers, utils
from rbx.config import Language, get_config
from rbx.console import console
from rbx.schema import DumpedProblem, Problem


def clear_loggers():
    for logger_name in [
        'uvicorn',
        'uvicorn.access',
        'uvicorn.asgi',
    ]:
        logging.getLogger(logger_name).handlers.clear()
        logging.getLogger(logger_name).propagate = False


def create_problem_structure(
    root: pathlib.Path,
    problem: Problem,
    lang: Language,
    status: Optional[rich.status.Status],
    should_simplify: bool = False,
    verbose: bool = False,
) -> Optional[DumpedProblem]:
    # Create directory structure.
    root.parent.mkdir(parents=True, exist_ok=True)

    problem_to_dump = DumpedProblem.from_problem(
        problem,
        code=providers.get_code(problem, simplify=should_simplify),
        aliases=providers.get_aliases(problem),
    )

    if verbose:
        console.print(
            f'Creating problem structure for [item]{problem_to_dump.pretty_name()}[/item]...'
        )

    code_path = root / lang.get_file(problem_to_dump.code)
    json_path = root / f'{problem_to_dump.code}.rbx.json'

    existing_problem = metadata.find_problem_by_code(problem_to_dump.code, root)
    if existing_problem:
        console.print(
            f'[error]Problem with identifier [item]{problem_to_dump.code}[/item] already exists in this folder.[/error]'
        )
        if not utils.confirm_on_status(
            status, 'Do you want to overwrite it?', default=False
        ):
            console.print(
                f'Skipping problem [item]{problem_to_dump.pretty_name()}[/item].'
            )
            return None

    json_path.write_text(utils.model_json(problem_to_dump))
    code = jinja2.Template(lang.get_template()).render(**problem_to_dump.get_vars())
    code_path.write_text(code)

    if verbose:
        console.print(
            f'Problem structure for [item]{problem_to_dump.pretty_name()}[/item] created successfully.'
        )
    return problem_to_dump


def process_problems(
    problems: List[Problem], lang: Language, status: rich.status.Status
):
    console.print(
        f'Creating problem structure for [item]{len(problems)}[/item] problems...'
    )

    should_simplify = False
    if providers.should_simplify_contest_problems(problems):
        console.print('Detected the parsed problems are from a contest.')
        if utils.confirm_on_status(
            status,
            'Do you want to identify these problems by their letters?',
            default=True,
        ):
            should_simplify = True

    root = pathlib.Path()
    dumped_problems = []
    for problem in problems:
        dumped_problem = create_problem_structure(
            root, problem, lang, status, should_simplify=should_simplify
        )
        if dumped_problem:
            dumped_problems.append(dumped_problem)
    console.print(f'Hydrating [item]{len(dumped_problems)}[/item] problems...')
    for problem in dumped_problems:
        hydration.hydrate_problem(root, problem)


def main(lang: Optional[str] = None):
    if get_config().get_language(lang) is None:
        console.print(
            f'[error]Language {lang or get_config().defaultLanguage} not found in config. Please check your configuration.[/error]'
        )
        return

    app = fastapi.FastAPI()

    async def shutdown():
        server.should_exit = True

    batch_to_left_lock = threading.Lock()
    batch_to_left = {}
    ignored = set()
    saved_status = None
    problems_to_process = []

    def process_batch_item(problem: Problem):
        batch_to_left_lock.acquire()
        if problem.batch.id in ignored:
            batch_to_left_lock.release()
            return True
        if problem.batch.id not in batch_to_left:
            if len(batch_to_left) > 0:
                console.print(
                    f'[error]Ignoring extra batch [item]{problem.batch.id}[/item] since other batch is being parsed.[/error]'
                )
                ignored.add(problem.batch.id)
                batch_to_left_lock.release()
                return True
            if problem.batch.size > 1 and saved_status:
                saved_status.update(
                    f'[rbx]rbx[/rbx] is parsing problems from group [item]{problem.group}[/item]'
                )
            elif saved_status:
                saved_status.update('[rbx]rbx[/rbx] is parsing problems...')
            console.print(
                f'Started parsing batch [item]{problem.batch.id}[/item] with size [item]{problem.batch.size}[/item].'
            )
            batch_to_left[problem.batch.id] = problem.batch.size
        console.print(f'Parsing problem [item]{problem.name}[/item]...')
        problems_to_process.append(problem)
        finished = False
        if batch_to_left[problem.batch.id] == 1:
            finished = True
            if problem.batch.size > 1:
                console.print(
                    f'[status][rbx]rbx[/rbx] parsed all problems from group [item]{problem.group}[/item].[/status]'
                )
            else:
                console.print(
                    f'[status][rbx]rbx[/rbx] parsed problem from [item]{problem.url}[/item][/status]'
                )
        else:
            batch_to_left[problem.batch.id] -= 1
        batch_to_left_lock.release()
        return not finished

    clock = None

    @app.post('/')
    async def parse(problem: Problem, background_tasks: fastapi.BackgroundTasks):
        nonlocal clock
        if clock is None:
            clock = time.monotonic()
        if not process_batch_item(problem):
            duration = time.monotonic() - clock
            console.print(
                f'Parsed all problems in [item]{duration:.2f}[/item] seconds.'
            )
            background_tasks.add_task(shutdown)
        return {}

    config = uvicorn.Config(app, port=1327)
    server = uvicorn.Server(config=config)
    clear_loggers()
    with console.status('Waiting for Competitive Companion request...') as status:
        saved_status = status
        server.run()

    with console.status('Processing parsed problems...') as status:
        language = get_config().get_language(lang)
        if not language:
            console.print(
                f'[error]Language {lang or get_config().defaultLanguage} not found in config. Please check your configuration.[/error]'
            )
            return
        process_problems(problems_to_process, language, status)
