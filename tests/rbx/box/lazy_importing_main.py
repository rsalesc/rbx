import sys

from rbx.box import main  # noqa

if __name__ == '__main__':
    for m in sys.modules:
        print(m)
