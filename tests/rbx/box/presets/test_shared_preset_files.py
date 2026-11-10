"""Every bundled preset carries the same copy of each shared file (#969).

The source is `rbx/resources/presets/_shared/`; `scripts/sync_preset_shared.py`
copies it into the presets. These tests fail when a copy was edited in place,
or when the shared file changed and nobody re-synced.
"""

import pathlib

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
