from mkdocs_review.site import (
    Page,
    dest_path,
    list_built_pages,
    load_mkdocs_config,
    page_table,
)


def test_load_config_tolerates_custom_tags():
    config = load_mkdocs_config(
        'site_name: x\n'
        'docs_dir: !ENV [DOCS, "documentation"]\n'
        'markdown_extensions:\n'
        '  - pymdownx.superfences:\n'
        '      custom_fences:\n'
        '        - format: !!python/name:pymdownx.superfences.fence_code_format\n'
    )
    assert config['site_name'] == 'x'


def test_load_config_defaults():
    config = load_mkdocs_config('site_name: x\n')
    assert config['docs_dir'] == 'docs'
    assert config['use_directory_urls'] is True


def test_load_config_ignores_unresolvable_docs_dir():
    assert load_mkdocs_config('docs_dir: !ENV X\n')['docs_dir'] == 'docs'


def test_dest_path():
    assert dest_path('index.md', True) == 'index.html'
    assert dest_path('a/README.md', True) == 'a/index.html'
    assert dest_path('a/b.md', True) == 'a/b/index.html'
    assert dest_path('a/b.md', False) == 'a/b.html'


def test_list_built_pages_skips_assets_and_404(tmp_path):
    for rel in [
        'index.html',
        'a/index.html',
        '404.html',
        'assets/x.html',
        'search/search.html',
        'style.css',
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x')
    assert list_built_pages(tmp_path) == {'index.html', 'a/index.html'}


def test_page_table_unions_sides_and_attaches_sources():
    pages = page_table(
        base_pages={'index.html', 'old/index.html'},
        head_pages={'index.html', 'new/index.html', 'gen/index.html'},
        base_sources={'index.html': 'docs/index.md', 'old/index.html': 'docs/old.md'},
        head_sources={'index.html': 'docs/index.md', 'new/index.html': 'docs/new.md'},
    )
    assert pages == [
        Page('gen/index.html', None, None, False, True),
        Page('index.html', 'docs/index.md', 'docs/index.md', True, True),
        Page('new/index.html', None, 'docs/new.md', False, True),
        Page('old/index.html', 'docs/old.md', None, True, False),
    ]
