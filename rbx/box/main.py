# flake8: noqa

import os
import sys


def _check_completions():
    if os.environ.get('_TYPER_COMPLETE_ARGS'):
        sys.exit(0)


def app():
    # _check_completions()

    from rbx.box.exception import RbxException

    try:
        import nest_asyncio

        nest_asyncio.apply()
        from rbx.box.cli import app as app_cli

        app_cli()
    except RbxException as e:
        print(str(e))
        sys.exit(1)
