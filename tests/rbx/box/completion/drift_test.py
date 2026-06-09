from rbx.box.completion import _spec, serialize


def test_committed_spec_matches_generated():
    payload = serialize.build_payload()
    assert payload['SPEC'] == _spec.SPEC, (
        'run `mise run gen-completion-spec` and commit the result'
    )
    assert payload['COMPLETERS'] == _spec.COMPLETERS, (
        'run `mise run gen-completion-spec` and commit'
    )
