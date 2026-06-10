from rbx.box import setter_config
from rbx.box.setter_config import ProblemLabelMode, SetterConfig


def test_ui_problem_label_defaults_to_name():
    cfg = SetterConfig()
    assert cfg.ui.problem_label is ProblemLabelMode.NAME


def test_ui_config_absent_key_defaults_to_name():
    # Configs predating this change have no `ui:` key.
    cfg = SetterConfig.model_validate({})
    assert cfg.ui.problem_label is ProblemLabelMode.NAME


def test_default_resource_setter_config_parses_with_ui():
    cfg = setter_config.get_default_setter_config()
    assert cfg.ui.problem_label is ProblemLabelMode.NAME


def test_set_problem_label_persists_without_existing_ui_key(mock_app_path):
    # Reproduce a user config that predates the `ui` field (no `ui:` key). The
    # change must survive model_to_yaml's exclude_unset.
    path = setter_config.get_setter_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('warnings:\n  enabled: true\n')
    setter_config.get_setter_config.cache_clear()
    try:
        assert (
            setter_config.get_setter_config().ui.problem_label is ProblemLabelMode.NAME
        )

        setter_config.set_problem_label(ProblemLabelMode.TITLE)

        assert (
            setter_config.get_setter_config().ui.problem_label is ProblemLabelMode.TITLE
        )
        assert 'problem_label: title' in path.read_text()
    finally:
        # `mock_app_path` is session-scoped; don't leak this config to other tests.
        path.unlink(missing_ok=True)
        setter_config.get_setter_config.cache_clear()
