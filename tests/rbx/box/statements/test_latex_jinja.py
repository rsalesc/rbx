from rbx.box.statements.latex_jinja import JinjaGroupsGetter, StrictChainableUndefined


def _make(items):
    """Helper: build a JinjaGroupsGetter with insertion-ordered keys."""
    return JinjaGroupsGetter('groups', dict(items))


class TestJinjaGroupsGetter:
    def test_iter_yields_values_in_insertion_order(self):
        groups = _make([('samples', 'S'), ('subtask1', '1'), ('subtask2', '2')])

        assert list(groups) == ['S', '1', '2']

    def test_getitem_returns_value_by_name(self):
        groups = _make([('subtask1', 'A'), ('subtask2', 'B')])

        assert groups['subtask1'] == 'A'
        assert groups['subtask2'] == 'B'

    def test_missing_key_returns_undefined_with_hint(self):
        groups = _make([('subtask1', 'A')])

        result = groups['bogus']

        assert isinstance(result, StrictChainableUndefined)

    def test_contains_checks_keys(self):
        groups = _make([('subtask1', 'A')])

        assert 'subtask1' in groups
        assert 'bogus' not in groups

    def test_len_counts_entries(self):
        groups = _make([('a', 1), ('b', 2), ('c', 3)])

        assert len(groups) == 3

    def test_keys_values_items_preserve_order(self):
        groups = _make([('a', 1), ('b', 2), ('c', 3)])

        assert list(groups.keys()) == ['a', 'b', 'c']
        assert list(groups.values()) == [1, 2, 3]
        assert list(groups.items()) == [('a', 1), ('b', 2), ('c', 3)]
