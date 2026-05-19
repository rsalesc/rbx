from rbx.box.packaging.boca.extension import BocaLanguageExtension


def test_resolved_boca_languages_uses_plural_when_set():
    ext = BocaLanguageExtension(bocaLanguages=['cc', 'cpp'])
    assert ext.resolved_boca_languages == ['cc', 'cpp']
    assert ext.primary_boca_language == 'cc'


def test_resolved_boca_languages_falls_back_to_singular():
    ext = BocaLanguageExtension(bocaLanguage='cc')
    assert ext.resolved_boca_languages == ['cc']
    assert ext.primary_boca_language == 'cc'


def test_resolved_boca_languages_empty_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_boca_languages == []
    assert ext.primary_boca_language is None


def test_resolved_boca_template_uses_explicit_when_set():
    ext = BocaLanguageExtension(bocaLanguages=['cc', 'cpp'], bocaTemplate='cc')
    assert ext.resolved_boca_template == 'cc'


def test_resolved_boca_template_falls_back_to_primary():
    ext = BocaLanguageExtension(bocaLanguages=['cc', 'cpp'])
    assert ext.resolved_boca_template == 'cc'


def test_resolved_boca_template_falls_back_through_singular():
    ext = BocaLanguageExtension(bocaLanguage='py3')
    assert ext.resolved_boca_template == 'py3'


def test_resolved_boca_template_none_when_unset():
    ext = BocaLanguageExtension()
    assert ext.resolved_boca_template is None
