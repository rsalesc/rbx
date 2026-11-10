"""Every bundled preset carries the same copy of each shared file (#969).

The source is `rbx/resources/presets/_shared/`; `scripts/sync_preset_shared.py`
copies it into the presets. These tests fail when a copy was edited in place,
or when the shared file changed and nobody re-synced.
"""

import pathlib
import subprocess

from scripts import sync_preset_shared


def test_presets_carry_the_shared_icpc_sty():
    assert pathlib.Path('contest/statements/icpc.sty') in (
        sync_preset_shared.shared_files()
    )
    assert len(sync_preset_shared.bundled_presets()) >= 2


def test_shared_files_are_in_sync():
    stale = sync_preset_shared.out_of_sync()
    assert stale == [], (
        'Bundled presets diverge from rbx/resources/presets/_shared/. Edit the '
        'file under _shared/ and run `mise run sync-presets`.'
    )


def test_icpc_sty_defines_every_string_in_every_language():
    sty = (
        sync_preset_shared.SHARED_DIR / 'contest' / 'statements' / 'icpc.sty'
    ).read_text()
    head, _, rest = sty.partition('\\ifx\\lang\\portuguese')
    assert '\\def\\portuguese{pt}' in head
    assert '\\def\\spanish{es}' in head
    pt, _, rest = rest.partition('\\else\\ifx\\lang\\spanish')
    es, _, rest = rest.partition('\\else')
    en, _, _ = rest.partition('\\fi\\fi')

    def names(block: str):
        return {
            line.strip().split('{')[0]
            for line in block.splitlines()
            if line.strip().startswith('\\def\\str')
        }

    assert names(en)
    assert names(pt) == names(en)
    assert names(es) == names(en)


def test_bundled_presets_are_the_shipped_ones():
    names = [p.name for p in sync_preset_shared.bundled_presets()]
    assert 'default' in names
    assert 'olympiad' in names
    assert '_shared' not in names


def test_release_flow_syncs_and_build_checks():
    root = sync_preset_shared.REPO_ROOT
    assert 'python3 scripts/sync_preset_shared.py --stage' in (
        (root / 'pyproject.toml').read_text()
    )
    assert 'python scripts/sync_preset_shared.py --check' in (
        (root / 'mise.toml').read_text()
    )


def test_stage_adds_a_copy_new_to_its_preset(tmp_path, monkeypatch):
    presets = tmp_path / 'presets'
    shared = presets / '_shared'
    (shared / 'contest').mkdir(parents=True)
    (shared / 'contest' / 'x.sty').write_text('new')
    for name in ('a', 'b'):
        (presets / name).mkdir()
        (presets / name / 'preset.rbx.yml').write_text('name: x\n')
    (presets / 'a' / 'contest').mkdir()
    (presets / 'a' / 'contest' / 'x.sty').write_text('old')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    monkeypatch.setattr(sync_preset_shared, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(sync_preset_shared, 'PRESETS_DIR', presets)
    monkeypatch.setattr(sync_preset_shared, 'SHARED_DIR', shared)

    assert sync_preset_shared.main(['--check']) == 1
    assert sync_preset_shared.main(['--stage']) == 0
    assert sync_preset_shared.main(['--check']) == 0

    staged = subprocess.run(
        ['git', 'diff', '--cached', '--name-only'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert staged == ['presets/a/contest/x.sty', 'presets/b/contest/x.sty']
