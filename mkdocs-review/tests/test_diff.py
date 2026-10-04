from mkdocs_review.diff import Row, align, hunks, word_marks


def test_align_identical():
    assert align(['a', 'b'], ['a', 'b']) == [
        Row(0, 0, 'same'),
        Row(1, 1, 'same'),
    ]


def test_align_insert_and_delete():
    assert align(['p:a', 'p:b'], ['p:a', 'p:new', 'p:b']) == [
        Row(0, 0, 'same'),
        Row(None, 1, 'added'),
        Row(1, 2, 'same'),
    ]
    assert align(['p:a', 'p:b'], ['p:b']) == [
        Row(0, None, 'removed'),
        Row(1, 0, 'same'),
    ]


def test_align_pairs_similar_replacements():
    base = ['p:keep', 'p:the quick brown fox', 'p:totally unrelated']
    head = ['p:keep', 'p:the quick red fox', 'p:something else entirely new']
    assert align(base, head) == [
        Row(0, 0, 'same'),
        Row(1, 1, 'changed'),
        Row(2, None, 'removed'),
        Row(None, 2, 'added'),
    ]


def test_hunks_group_changes_and_anchor_on_neighbours():
    rows = [
        Row(0, 0, 'same'),
        Row(None, 1, 'added'),
        Row(None, 2, 'added'),
        Row(1, 3, 'same'),
        Row(2, None, 'removed'),
    ]
    assert hunks(rows) == [
        {'id': 0, 'base': 0, 'head': 1},
        {'id': 1, 'base': 2, 'head': 3},
    ]


def test_hunk_at_start_anchors_forward():
    rows = [Row(None, 0, 'added'), Row(0, 1, 'same')]
    assert hunks(rows) == [{'id': 0, 'base': 0, 'head': 0}]


def test_word_marks():
    removed, added = word_marks(
        ['the', 'quick', 'brown', 'fox'], ['the', 'red', 'fox', '!']
    )
    assert removed == {1, 2}
    assert added == {1, 3}
