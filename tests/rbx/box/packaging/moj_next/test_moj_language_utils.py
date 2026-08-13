import pytest
from pydantic import ValidationError

from rbx.box.packaging.moj_next.extension import MojLanguageExtension
from rbx.box.packaging.moj_next.moj_language_utils import (
    get_emitted_moj_languages,
    get_moj_template_name,
    get_rbx_language_from_moj_language,
)


def test_default_env_emits_the_five_preset_languages(testing_pkg):
    testing_pkg.save()
    assert set(get_emitted_moj_languages()) >= {'c', 'cpp', 'py', 'java', 'kt'}


def test_template_defaults_to_the_language_name(testing_pkg):
    testing_pkg.save()
    assert get_moj_template_name('cpp') == 'cpp'
    assert get_moj_template_name('py') == 'py'


def test_unclaimed_moj_language_falls_back_to_its_own_name(testing_pkg):
    testing_pkg.save()
    assert get_rbx_language_from_moj_language('hs') is None
    assert get_moj_template_name('hs') == 'hs'


def test_python_maps_to_the_unified_moj_id(testing_pkg):
    testing_pkg.save()
    # MOJ unified python under `py`; `py3` is only a legacy spelling there.
    assert get_rbx_language_from_moj_language('py') == 'py'


def test_template_is_required_when_languages_is_set():
    with pytest.raises(ValidationError):
        MojLanguageExtension(languages=['cpp'])


def test_flags_default_to_none():
    assert MojLanguageExtension().flags is None
    assert MojLanguageExtension().resolved_languages == []
