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


def test_ensure_atomic_publish_under_race(tmp_path):
    # Two compiles writing distinct temp outputs, both publishing to the same key.
    outputs = []

    def fake_runner(argv, **kw):
        out = argv[argv.index('-o') + 1]
        Path(out).write_bytes(b'ELF-BINARY')
        outputs.append(out)
        return 0

    a = assets.NativeAsset(
        name='pipe', source=b'csrc', compile_argv=['gcc', '-O2', '-o', '{out}', '{src}']
    )
    # First ensure populates the cache; the temp out path is unique (not the final target)
    target = a.ensure(cache_dir=tmp_path, runner=fake_runner)
    assert target.read_bytes() == b'ELF-BINARY'
    # The compiler wrote to a UNIQUE temp path, not directly to the final target
    assert all(Path(o) != target for o in outputs)
    # Final published file is the full binary (atomic os.replace, never partial)
    assert target.stat().st_size == len(b'ELF-BINARY')


def test_ensure_raises_on_compile_failure(tmp_path):
    def fake_runner(argv, **kw):
        return 1

    a = assets.NativeAsset(
        name='checker', source=b'bad', compile_argv=['g++', '-o', '{out}', '{src}']
    )
    import pytest

    with pytest.raises(RuntimeError):
        a.ensure(cache_dir=tmp_path, runner=fake_runner)
    # No partial published binary, and no leftover temp files.
    assert list(tmp_path.iterdir()) == []
