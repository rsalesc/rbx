# flake8: noqa
import nest_asyncio
import sys

from rbx.box.exception import RbxException

nest_asyncio.apply()

from rbx.box.cli import app as app_cli


def app():
    try:
        app_cli()
    except RbxException as e:
        print(str(e))
        sys.exit(1)
