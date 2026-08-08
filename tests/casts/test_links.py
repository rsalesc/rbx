import pathlib

from scripts.casts.links import LinkReport, check_links, iter_references

LEGACY_ID = 'cqUTWgIRFA1P7VsV39uJTorKC'


def _docs(tmp_path: pathlib.Path, **pages: str) -> pathlib.Path:
    root = tmp_path / 'docs'
    root.mkdir()
    for name, body in pages.items():
        path = root / f'{name}.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def _casts(tmp_path: pathlib.Path, *names: str) -> pathlib.Path:
    root = tmp_path / 'casts'
    root.mkdir()
    for name in names:
        (root / f'{name}.cast').write_text('{}\n')
    return root


def test_iter_references_finds_macros_with_and_without_kwargs(tmp_path: pathlib.Path):
    docs = _docs(
        tmp_path,
        page='{{ asciinema("run-basic") }}\n{{ asciinema("ui-nav", speed=1.5) }}\n',
    )

    refs = sorted(ref.target for ref in iter_references(docs))

    assert refs == ['run-basic', 'ui-nav']


def test_legacy_asciinema_org_ids_are_reported_but_not_errors(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page=f'{{{{ asciinema("{LEGACY_ID}") }}}}\n')
    casts = _casts(tmp_path)

    report = check_links(docs, casts)

    assert report.legacy == [LEGACY_ID]
    assert report.missing == []
    assert report.ok


def test_a_reference_without_a_cast_file_is_missing(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='{{ asciinema("run-basic") }}\n')
    casts = _casts(tmp_path)

    report = check_links(docs, casts)

    assert [item.target for item in report.missing] == ['run-basic']
    assert not report.ok


def test_a_cast_nobody_references_is_an_orphan(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='no casts here\n')
    casts = _casts(tmp_path, 'stale')

    report = check_links(docs, casts)

    assert report.orphans == ['stale']
    assert not report.ok


def test_pending_placeholders_are_reported(tmp_path: pathlib.Path):
    docs = _docs(
        tmp_path,
        page='{{ asciinema("REPLACE_ME_CAST_ID") }}\n<!-- TODO(record): a cast -->\n',
    )
    casts = _casts(tmp_path)

    report = check_links(docs, casts)

    assert len(report.pending) == 2
    assert not report.ok


def test_a_fully_wired_cast_is_clean(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='{{ asciinema("run-basic") }}\n')
    casts = _casts(tmp_path, 'run-basic')

    report = check_links(docs, casts)

    assert report.ok
    assert isinstance(report, LinkReport)


def test_references_carry_their_page_and_line(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='intro\n\n{{ asciinema("run-basic") }}\n')

    reference = next(iter(iter_references(docs)))

    assert reference.page.name == 'page.md'
    assert reference.line == 3


def test_plan_documents_are_not_scanned(tmp_path: pathlib.Path):
    docs = _docs(tmp_path, page='clean page\n')
    plans = docs / 'plans'
    plans.mkdir()
    (plans / 'a-design.md').write_text(
        '{{ asciinema("<id>") }}\n<!-- TODO(record): explains the macro -->\n'
    )
    casts = _casts(tmp_path)

    report = check_links(docs, casts)

    assert report.missing == []
    assert report.pending == []
    assert report.ok
