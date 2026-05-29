from rbx_boca import languages


def test_render_argv_string_substitution():
    out = languages.render_argv(
        ['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-O2 -static',
        exe='run.exe',
        src='sol.cpp',
    )
    assert out == ['g++', '-O2', '-static', '-o', 'run.exe', 'sol.cpp']


def test_render_argv_list_splice():
    out = languages.render_argv(
        ['java', '{jvm_flags}', '-jar', '{jar}'],
        jvm_flags=['-Xmx256000K', '-Xss25600K'],
        jar='run.jar',
    )
    assert out == ['java', '-Xmx256000K', '-Xss25600K', '-jar', 'run.jar']


def test_render_argv_empty_token_dropped():
    out = languages.render_argv(['cc', '{flags}', '{src}'], flags='', src='a.c')
    assert out == ['cc', 'a.c']
