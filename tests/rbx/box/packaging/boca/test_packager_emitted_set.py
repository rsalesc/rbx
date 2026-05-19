import inspect


def test_packager_iterates_emitted_set():
    """The BOCA packager must use get_emitted_boca_languages() rather than reading
    BocaExtension.languages directly, so that bocaLanguages aliases are honored."""
    from rbx.box.packaging.boca import packager as pkgr

    src = inspect.getsource(pkgr)
    assert 'get_emitted_boca_languages' in src, (
        'packager.py must import and call get_emitted_boca_languages'
    )


def test_packager_sources_compile_template_via_resolved_boca_template():
    """The compile/run template source dir must come from resolved_boca_template,
    not from the emitted BOCA language name directly."""
    from rbx.box.packaging.boca import packager as pkgr

    src = inspect.getsource(pkgr)
    assert 'resolved_boca_template' in src, (
        'packager.py must use resolved_boca_template for compile/run template sourcing'
    )
