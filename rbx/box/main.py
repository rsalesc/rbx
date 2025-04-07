# flake8: noqa
from gevent import monkey

monkey.patch_all()

from rbx.box.cli import app
