from rbx_boca import assets


def test_cache_key_depends_on_source_and_flags():
    a = assets.NativeAsset(
        name='checker', source=b'int main(){}', compile_argv=['g++', '-O2']
    )
    b = assets.NativeAsset(
        name='checker', source=b'int main(){}', compile_argv=['g++', '-O3']
    )
    c = assets.NativeAsset(
        name='checker', source=b'int main(){ }', compile_argv=['g++', '-O2']
    )
    assert a.cache_key() != b.cache_key()  # flags differ
    assert a.cache_key() != c.cache_key()  # source differs
    assert (
        a.cache_key()
        == assets.NativeAsset('checker', b'int main(){}', ['g++', '-O2']).cache_key()
    )
