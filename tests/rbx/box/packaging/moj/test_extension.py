import pytest
from pydantic import ValidationError

from rbx.box.extensions import Extensions
from rbx.box.packaging.moj.extension import MojExtension


def test_org_defaults_to_none():
    # Absent means "upload under my own login"; see `resolve_problem_id`.
    assert MojExtension().org is None


def test_org_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'org': 'unicamp'}})
    assert extensions.moj is not None
    assert extensions.moj.org == 'unicamp'


def test_unknown_field_is_rejected():
    # `extra='forbid'`, as every other extension: a typo in `env.rbx.yml` must
    # fail loudly rather than be silently ignored at upload time.
    with pytest.raises(ValidationError):
        MojExtension.model_validate({'orgs': 'unicamp'})
