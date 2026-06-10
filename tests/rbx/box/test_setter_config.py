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
