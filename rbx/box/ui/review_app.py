import pathlib

from textual.app import App

from rbx.box.ui.screens.review import ReviewScreen


class rbxReviewApp(App):
    TITLE = 'rbx review'
    CSS_PATH = 'css/app.tcss'

    def __init__(self, path: pathlib.Path):
        super().__init__()
        self.path = path
        self.confirmed: bool = False

    def on_mount(self):
        self.push_screen(ReviewScreen(self.path))


def start_review(path: pathlib.Path) -> bool:
    app = rbxReviewApp(path)
    app.run()
    return bool(getattr(app, 'confirmed', False))
