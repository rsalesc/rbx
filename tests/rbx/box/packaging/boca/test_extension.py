from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguageExtension


def test_resolved_languages_uses_plural_when_set():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'])
    assert ext.resolved_languages == ['cc', 'cpp']
    assert ext.primary_language == 'cc'


def test_resolved_languages_falls_back_to_singular():
    ext = BocaLanguageExtension(bocaLanguage='cc')
    assert ext.resolved_languages == ['cc']
    assert ext.primary_language == 'cc'


def test_resolved_languages_empty_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_languages == []
    assert ext.primary_language is None


def test_resolved_template_uses_explicit_when_set():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'], template='cc')
    assert ext.resolved_template == 'cc'


def test_resolved_template_falls_back_to_primary():
    ext = BocaLanguageExtension(languages=['cc', 'cpp'])
    assert ext.resolved_template == 'cc'


def test_resolved_template_falls_back_through_singular():
    ext = BocaLanguageExtension(bocaLanguage='py3')
    assert ext.resolved_template == 'py3'


def test_resolved_template_none_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_template is None


def test_boca_extension_languages_defaults_to_empty():
    assert BocaExtension().languages == []


def test_min_running_time_defaults_to_none():
    assert BocaExtension().minRunningTime is None


def test_min_running_time_rejects_non_positive():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=0)
    with pytest.raises(ValidationError):
        BocaExtension(minRunningTime=-5)


def test_min_running_time_accepts_positive_ms():
    assert BocaExtension(minRunningTime=1000).minRunningTime == 1000
