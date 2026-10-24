"""Helpers for packaging rbx problems for CMS (cms-dev).

Not a packager: these are the pieces any route into CMS needs -- how CMS scores
a problem, how it judges an interactive one, what it cannot judge -- shared by
the Polygon packager's `--cms` flag (through `polygon_loader`, what CMS's
Polygon importer reads) and by a future native CMS packager (#944).
"""
