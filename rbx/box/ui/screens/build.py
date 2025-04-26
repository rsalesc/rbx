from rbx.box.ui.screens.command import CommandScreen


class BuildScreen(CommandScreen):
    def __init__(self):
        super().__init__(['rbx', 'build'])
