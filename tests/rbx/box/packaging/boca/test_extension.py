import pytest
from pydantic import ValidationError

from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguageExtension


def test_resolved_languages_uses_plural():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    assert ext.resolved_languages == ['cc', 'cpp']
    assert ext.primary_language == 'cc'


def test_resolved_languages_empty_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_languages == []
    assert ext.primary_language is None


def test_resolved_template_uses_explicit():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    assert ext.resolved_template == 'cc'


def test_resolved_template_none_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_template is None


def test_template_required_when_languages_set():
    # The implicit template fallback was removed in rbx v1: declaring `languages`
    # without an explicit `template` is now a validation error.
    with pytest.raises(ValidationError):
        BocaLanguageExtension(languages=['cc', 'cpp'])


def test_bocalanguage_field_removed():
    # The deprecated singular `bocaLanguage` was removed in rbx v1.
    with pytest.raises(ValidationError):
        BocaLanguageExtension(bocaLanguage='cc')


def test_unknown_language_field_rejected():
    with pytest.raises(ValidationError):
        BocaLanguageExtension(unknownField='x')


def test_env_level_languages_field_removed():
    # The env-level allowlist `extensions.boca.languages` was removed in rbx v1.
    with pytest.raises(ValidationError):
        BocaExtension(languages=['cc'])


def test_maximum_time_error_field_removed():
    # `maximumTimeError` (ignored since #494) was removed in rbx v1.
    with pytest.raises(ValidationError):
        BocaExtension(maximumTimeError=1.5)


def test_min_running_time_defaults_to_none():
    assert BocaExtension().minRunningTime is None


def test_min_running_time_rejects_non_positive():
    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=0)
    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=-5)


def test_min_running_time_accepts_positive_ms():
    assert BocaExtension(minRunningTime=1000).minRunningTime == 1000
