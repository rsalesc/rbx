from bs4 import BeautifulSoup

from mkdocs_review.blocks import block_key, extract_blocks, find_main, own_text


def _soup(html):
    return BeautifulSoup(html, 'html.parser')


def test_extract_blocks_in_document_order():
    soup = _soup(
        '<div><h1>Title</h1><p>Intro <b>bold</b></p>'
        '<ul><li>One</li><li>Two</li></ul></div>'
    )
    assert [b.name for b in extract_blocks(soup)] == ['h1', 'p', 'li', 'li']


def test_nested_list_item_keeps_its_own_text_only():
    soup = _soup('<ul><li>Outer<ul><li>Inner</li></ul></li></ul>')
    blocks = extract_blocks(soup)
    assert [own_text(b) for b in blocks] == ['Outer', 'Inner']


def test_blocks_without_own_text_are_skipped():
    soup = _soup('<blockquote><p>Quoted</p></blockquote><ul><li><p>Loose</p></li></ul>')
    assert [b.name for b in extract_blocks(soup)] == ['p', 'p']


def test_does_not_descend_into_pre_or_table():
    soup = _soup(
        '<pre><code><p>not a block</p></code></pre>'
        '<table><tr><td><p>cell</p></td></tr></table>'
    )
    assert [b.name for b in extract_blocks(soup)] == ['pre', 'table']


def test_image_only_paragraph_is_a_block():
    soup = _soup('<p><img src="a.png"></p>')
    blocks = extract_blocks(soup)
    assert len(blocks) == 1
    assert block_key(blocks[0]) == 'p:[img a.png]'


def test_own_text_ignores_scripts_and_normalizes_whitespace():
    soup = _soup('<p>a\n   b<script>x()</script> <style>.c{}</style>c</p>')
    assert own_text(extract_blocks(soup)[0]) == 'a b c'


def test_own_text_ignores_heading_permalinks():
    soup = _soup('<h2 id="x">Setup<a class="headerlink" href="#x">#</a></h2>')
    assert own_text(extract_blocks(soup)[0]) == 'Setup'


def test_block_key_includes_tag():
    soup = _soup('<h2>Same</h2><p>Same</p>')
    assert [block_key(b) for b in extract_blocks(soup)] == ['h2:Same', 'p:Same']


def test_find_main_uses_first_matching_selector():
    soup = _soup('<body><nav><p>nav</p></nav><article><p>x</p></article></body>')
    assert find_main(soup, ['article', 'body']).name == 'article'
    assert find_main(soup, ['main', 'body']).name == 'body'
