from bs4 import BeautifulSoup

from mkdocs_review.annotate import diff_page


def _page(body):
    return f'<html><head><title>t</title></head><body><nav><p>menu</p></nav><article>{body}</article></body></html>'


def _soup(html):
    return BeautifulSoup(html, 'html.parser')


def test_unchanged_page_has_no_hunks_but_is_still_instrumented():
    page = _page('<p>Hello</p>')
    diff = diff_page(page, page)
    assert diff.hunks == []
    assert diff.counts == {'added': 0, 'removed': 0, 'changed': 0}
    head = _soup(diff.head_html)
    assert head.select_one('script[src="/_mr/inject.js"]')['data-side'] == 'head'
    assert head.select_one('link[href="/_mr/inject.css"]') is not None
    assert head.select_one('article p')['data-mr-pair'] == '0'


def test_navigation_outside_main_content_is_not_diffed():
    diff = diff_page(_page('<p>a</p>').replace('menu', 'old'), _page('<p>a</p>'))
    assert diff.hunks == []


def test_added_removed_and_changed_blocks_are_marked():
    base = _page(
        '<h1>Title</h1><p>The quick brown fox.</p><p>Gone forever and ever.</p>'
    )
    head = _page(
        '<h1>Title</h1><p>The quick red fox.</p><p>Brand new paragraph here.</p>'
    )
    diff = diff_page(base, head)

    assert diff.counts == {'added': 1, 'removed': 1, 'changed': 1}
    assert [b.status for b in diff.head_blocks] == ['same', 'changed', 'added']
    assert [b.status for b in diff.base_blocks] == ['same', 'changed', 'removed']
    assert diff.head_blocks[1].words == ['red']
    assert diff.base_blocks[1].words == ['brown']
    assert diff.head_blocks[2].words == ['Brand', 'new', 'paragraph', 'here', '.']

    head_soup = _soup(diff.head_html)
    changed = head_soup.select('article p')[0]
    assert 'mr-changed' in changed['class']
    assert [s.get_text() for s in changed.select('span.mr-w-add')] == ['red']
    assert 'mr-added' in head_soup.select('article p')[1]['class']

    base_soup = _soup(diff.base_html)
    assert [s.get_text() for s in base_soup.select('span.mr-w-del')] == ['brown']
    assert 'mr-removed' in base_soup.select('article p')[1]['class']


def test_adjacent_changed_words_are_wrapped_together():
    diff = diff_page(_page('<p>keep a b keep</p>'), _page('<p>keep x y keep</p>'))
    spans = _soup(diff.head_html).select('span.mr-w-add')
    assert [s.get_text() for s in spans] == ['x y']


def test_word_marks_survive_inline_markup():
    diff = diff_page(
        _page('<p>Run <code>rbx build</code> now</p>'),
        _page('<p>Run <code>rbx run</code> now</p>'),
    )
    code = _soup(diff.head_html).select_one('article code')
    assert code.select_one('span.mr-w-add').get_text() == 'run'


def test_missing_side_makes_everything_added():
    diff = diff_page(None, _page('<p>a</p><p>b</p>'))
    assert diff.base_html is None
    assert [b.status for b in diff.head_blocks] == ['added', 'added']
    assert diff.counts['added'] == 2
    assert diff.hunks == [{'id': 0, 'base': None, 'head': 0}]


def test_blocks_carry_hunk_ids():
    diff = diff_page(
        _page('<p>a</p><p>b</p>'), _page('<p>new one here</p><p>a</p><p>b</p>')
    )
    first = _soup(diff.head_html).select_one('article p')
    assert first['data-mr-hunk'] == '0'
    assert first['data-mr-block'] == '0'
