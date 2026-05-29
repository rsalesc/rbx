from pathlib import Path

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


def test_ensure_compiles_on_miss_then_caches(tmp_path):
    compiled = []

    def fake_runner(argv, **kw):
        out = argv[argv.index('-o') + 1]
        Path(out).write_bytes(b'ELF')  # emulate compiler producing the output binary
        compiled.append(argv)
        return 0

    a = assets.NativeAsset(
        name='checker',
        source=b'src',
        compile_argv=['g++', '-O2', '-o', '{out}', '{src}'],
    )
    out1 = a.ensure(cache_dir=tmp_path, runner=fake_runner)
    out2 = a.ensure(cache_dir=tmp_path, runner=fake_runner)
    assert out1 == out2
    assert out1.exists()
    assert len(compiled) == 1  # second call is a cache hit, no recompile
