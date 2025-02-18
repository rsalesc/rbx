from rbx.box import environment, package
from rbx.box.contest import contest_package


def clear_all_caches():
    pkgs = [package, environment, contest_package]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()
