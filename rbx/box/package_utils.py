from rbx.box import graders, header, package


def clear_package_cache():
    pkgs = [package, header, graders]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()
