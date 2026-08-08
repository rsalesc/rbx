from scripts.casts.autocast_input import build_autocast_input
from scripts.casts.spec import RecordingSpec, Tagged, dump_autocast_yaml


def _spec(**kwargs) -> RecordingSpec:
    base = dict(name='run-basic', fixture='ab-problem', instructions=['rbx run'])
    base.update(kwargs)
    return RecordingSpec(**base)


def test_settings_carry_spec_values():
    data = build_autocast_input(_spec(title='Running solutions'), workdir='/tmp/wd')

    settings = data['settings']
    assert settings['width'] == 100
    assert settings['height'] == 30
    assert settings['title'] == 'Running solutions'
    assert settings['type_speed'] == '60ms'
    assert settings['timeout'] == '120s'
    assert settings['prompt'] == '$ '


def test_shell_uses_a_sentinel_prompt_so_autocast_can_detect_completion():
    data = build_autocast_input(_spec(), workdir='/tmp/wd')

    shell = data['settings']['shell']
    assert shell['program'] == 'bash'
    assert shell['prompt'] == 'AUTOCAST_PROMPT'
    assert shell['quit_command'] == 'exit'

    env = {pair['name']: pair['value'] for pair in data['settings']['environment']}
    assert 'PS1=AUTOCAST_PROMPT' in env['PROMPT_COMMAND']


def test_environment_is_normalized_for_reproducibility():
    data = build_autocast_input(_spec(), workdir='/tmp/wd', home='/tmp/home')

    env = {pair['name']: pair['value'] for pair in data['settings']['environment']}
    assert env['TERM'] == 'xterm-256color'
    assert env['COLUMNS'] == '100'
    assert env['LINES'] == '30'
    assert env['LC_ALL'] == 'C.UTF-8'
    assert env['TZ'] == 'UTC'
    assert env['HOME'] == '/tmp/home'


def test_workdir_and_setup_are_hidden_leading_commands():
    data = build_autocast_input(_spec(setup=['rbx build']), workdir='/tmp/wd')

    instructions = data['instructions']
    assert instructions[0].tag == 'Command'
    assert instructions[0].value['command'] == 'cd /tmp/wd'
    assert instructions[0].value['hidden'] is True
    assert instructions[1].value['command'] == 'rbx build'
    assert instructions[1].value['hidden'] is True


def test_plain_string_instructions_become_visible_commands():
    data = build_autocast_input(_spec(instructions=['rbx run']), workdir='/tmp/wd')

    last = data['instructions'][-1]
    assert last.tag == 'Command'
    assert last.value == {'command': 'rbx run', 'hidden': False}


def test_tagged_instructions_pass_through_untouched():
    wait = Tagged('Wait', '3s')
    data = build_autocast_input(_spec(instructions=[wait]), workdir='/tmp/wd')

    assert data['instructions'][-1] is wait


def test_output_is_serializable_with_tags_intact():
    data = build_autocast_input(
        _spec(instructions=['rbx run', Tagged('Wait', '3s')]), workdir='/tmp/wd'
    )

    text = dump_autocast_yaml(data)

    assert '!Command' in text
    assert '!Wait' in text
