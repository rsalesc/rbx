"""Write the verdict enums the VS Code extension mirrors to a JSON fixture.

The extension keeps hand-written tables for `ExpectedOutcome` (display and
aliases, `vscode/src/rbx/expectation.ts` and `manifest.ts`) and for `Outcome`
(`vscode/src/rbx/outcome.ts`). Hand-written on purpose -- each row is a display
decision -- but nothing compared them with rbx, so `MLE_OR_RTE` shipped in
rbx and rendered as an unknown expectation in the editor (#901).

This dumps both enums to `vscode/src/rbx/rbxEnums.json`. The extension's tests
read that file and fail when a member or alias has no row, and
`tests/rbx/box/vscode/enums_test.py` fails when the file itself is stale -- so
a new member cannot reach a release without its extension row. Regenerate with:

    uv run python scripts/gen_vscode_enums.py
"""

import json
import pathlib
from typing import Any, Dict

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ENUMS_JSON = REPO_ROOT / 'vscode' / 'src' / 'rbx' / 'rbxEnums.json'


def dump() -> Dict[str, Any]:
    from rbx.box.schema import ExpectedOutcome
    from rbx.grading.steps import Outcome

    return {
        'ExpectedOutcome': {
            member.name: list(member.aliases) for member in ExpectedOutcome
        },
        # The values, not the names: `.eval` files carry `wrong-answer`.
        'Outcome': [outcome.value for outcome in Outcome],
    }


def render() -> str:
    return json.dumps(dump(), indent=2, ensure_ascii=False) + '\n'


def main() -> None:
    ENUMS_JSON.write_text(render(), encoding='utf-8')
    print(f'Wrote {ENUMS_JSON.relative_to(REPO_ROOT)}.')


if __name__ == '__main__':
    main()
