import asyncio
from typing import Callable, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Rule,
    Static,
    Switch,
)

from rbx import utils
from rbx.box import environment, limits_info, package
from rbx.box.schema import LimitModifiers, LimitsProfile


class ConfirmDiscardScreen(ModalScreen[bool]):
    """Modal asking whether to discard unsaved changes."""

    BINDINGS = [
        Binding('c', 'confirm', 'Confirm'),
        Binding('n', 'cancel', 'Cancel'),
        Binding('escape', 'cancel', 'Cancel', show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container(id='confirm-discard-dialog'):
            yield Static('You have unsaved changes. Discard? (c/n)')

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class LimitsEditorScreen(Screen):
    BINDINGS = [
        Binding('q', 'quit_screen', 'Quit'),
        Binding('ctrl+s', 'save', 'Save'),
        Binding('d', 'delete_profile', 'Delete profile'),
    ]

    def __init__(self):
        super().__init__()
        self._profile_names: List[str] = []
        self._selected_profile: Optional[str] = None
        self._modifier_languages: List[str] = []
        self._delete_pending: Optional[str] = None
        self._is_rendering: bool = False
        self._last_saved_profile: Optional[LimitsProfile] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        with Horizontal(id='limits-editor'):
            with Vertical(id='limits-sidebar'):
                yield ListView(id='limits-profile-list')
            with VerticalScroll(id='limits-detail'):
                yield Static('Select a profile', id='limits-placeholder')

    async def on_mount(self):
        self.query_one('#limits-profile-list').border_title = 'Profiles'
        await self._load_profiles()
        self.watch(
            self.query_one('#limits-profile-list', ListView),
            'index',
            self._on_profile_selected,
        )

    async def _load_profiles(self):
        self._profile_names = limits_info.get_available_profile_names()
        lv = self.query_one('#limits-profile-list', ListView)
        await lv.clear()
        items = [ListItem(Label(name)) for name in self._profile_names]
        items.append(ListItem(Label('[dim]+ New Profile[/dim]', markup=True)))
        await lv.extend(items)

    def _is_dirty(self) -> bool:
        """Check if the form has unsaved changes."""
        if self._last_saved_profile is None:
            return False
        try:
            current = self._build_profile_from_form()
        except Exception:
            return False
        if current is None:
            return False
        return current != self._last_saved_profile

    def _check_dirty_then(self, callback: Callable[[], None]) -> None:
        """If dirty, show confirmation modal. On confirm (or not dirty), run callback."""
        if not self._is_dirty():
            callback()
            return

        def _on_dismiss(discard: Optional[bool]) -> None:
            if discard:
                callback()

        self.app.push_screen(ConfirmDiscardScreen(), callback=_on_dismiss)

    async def action_quit_screen(self) -> None:
        """Quit with dirty check."""
        self._check_dirty_then(lambda: self.app.pop_screen())

    def _on_profile_selected(self, index: Optional[int]):
        if index is None:
            return
        self._delete_pending = None

        def _do_switch():
            if index == len(self._profile_names):
                self._selected_profile = None
                self._last_saved_profile = None
                asyncio.ensure_future(self._show_new_profile_form())
            else:
                self._selected_profile = self._profile_names[index]
                asyncio.ensure_future(self._load_profile_detail())

        self._check_dirty_then(_do_switch)

    async def _show_new_profile_form(self):
        """Replace detail pane with a form to enter a new profile name."""
        detail = self.query_one('#limits-detail', VerticalScroll)
        await detail.remove_children()
        await detail.mount(Static('Enter new profile name:'))
        name_input = Input(placeholder='e.g. local, judge', id='new-profile-name')
        await detail.mount(name_input)
        name_input.focus()

    @staticmethod
    def _normalize_profile(profile: LimitsProfile) -> LimitsProfile:
        """Build a normalized profile with only the fields the form manages.

        This ensures dirty-checking compares like-for-like, ignoring fields
        the form never displays (e.g. formula, outputLimit).
        """
        if profile.inheritFromPackage:
            return LimitsProfile(inheritFromPackage=True)
        modifiers: Dict[str, LimitModifiers] = {}
        for lang, mod in profile.modifiers.items():
            if (
                mod.time is not None
                or mod.timeMultiplier is not None
                or mod.memory is not None
            ):
                modifiers[lang] = LimitModifiers(
                    time=mod.time,
                    timeMultiplier=mod.timeMultiplier,
                    memory=mod.memory,
                )
        return LimitsProfile(
            timeLimit=profile.timeLimit,
            memoryLimit=profile.memoryLimit,
            modifiers=modifiers,
        )

    async def _load_profile_detail(self):
        """Load and display the detail form for the currently selected profile."""
        if self._selected_profile is None:
            return
        saved_profile = limits_info.get_saved_limits_profile(self._selected_profile)
        profile = saved_profile if saved_profile is not None else LimitsProfile()
        self._last_saved_profile = self._normalize_profile(profile)
        await self._load_profile_detail_from(profile)

    async def _load_profile_detail_from(self, profile: LimitsProfile):
        """Render the detail form from an in-memory LimitsProfile."""
        self._is_rendering = True
        try:
            detail = self.query_one('#limits-detail', VerticalScroll)
            await detail.remove_children()

            # Get package defaults for placeholders.
            pkg = package.find_problem_package_or_die()
            inherit = profile.inheritFromPackage

            # --- Title ---
            await detail.mount(
                Static(
                    f'[bold]{self._selected_profile}[/bold]',
                    id='limits-title',
                    markup=True,
                )
            )

            # --- Inherit toggle ---
            await detail.mount(Static('Inherit from package', classes='field-label'))
            inherit_switch = Switch(value=inherit, id='inherit-switch')
            await detail.mount(inherit_switch)

            # --- Separator ---
            await detail.mount(Rule())

            # --- Global limits ---
            await detail.mount(Static('[bold]Global Limits[/bold]', markup=True))

            if inherit:
                # Show read-only package values.
                await detail.mount(
                    Static(
                        f'Time Limit (ms): [bold]{pkg.timeLimit}[/bold]',
                        markup=True,
                    )
                )
                await detail.mount(
                    Static(
                        f'Memory Limit (MB): [bold]{pkg.memoryLimit}[/bold]',
                        markup=True,
                    )
                )
            else:
                tl_input = Input(
                    value=(
                        str(profile.timeLimit) if profile.timeLimit is not None else ''
                    ),
                    placeholder=str(pkg.timeLimit),
                    type='integer',
                    id='tl-input',
                )
                tl_input.border_title = 'Time Limit (ms)'
                await detail.mount(tl_input)

                ml_input = Input(
                    value=(
                        str(profile.memoryLimit)
                        if profile.memoryLimit is not None
                        else ''
                    ),
                    placeholder=str(pkg.memoryLimit),
                    type='integer',
                    id='ml-input',
                )
                ml_input.border_title = 'Memory Limit (MB)'
                await detail.mount(ml_input)

            # --- Per-language modifiers ---
            await detail.mount(Rule())
            await detail.mount(
                Static('[bold]Per-Language Overrides[/bold]', markup=True)
            )

            # Collect languages: environment languages + any already in profile
            # modifiers.
            env_languages: Dict[str, str] = {}
            try:
                env = environment.get_environment()
                for lang in env.languages:
                    display = lang.readableName if lang.readableName else lang.name
                    env_languages[lang.name] = display
            except SystemExit:
                pass

            # When inheriting, also show languages from package modifiers.
            if inherit:
                for lang_name in pkg.modifiers:
                    if lang_name not in env_languages:
                        env_languages[lang_name] = lang_name

            # Add any modifier languages not already in the environment list.
            for lang_name in profile.modifiers:
                if lang_name not in env_languages:
                    env_languages[lang_name] = lang_name

            self._modifier_languages = sorted(env_languages.keys())

            for lang_name in self._modifier_languages:
                display_name = env_languages[lang_name]

                await detail.mount(
                    Static(f'[bold italic]{display_name}[/bold italic]', markup=True)
                )

                if inherit:
                    # Show read-only package modifier values.
                    pkg_mod = pkg.modifiers.get(lang_name, LimitModifiers())
                    time_str = str(pkg_mod.time) if pkg_mod.time is not None else '-'
                    tmult_str = (
                        str(pkg_mod.timeMultiplier)
                        if pkg_mod.timeMultiplier is not None
                        else '-'
                    )
                    mem_str = str(pkg_mod.memory) if pkg_mod.memory is not None else '-'
                    await detail.mount(Static(f'  Time (ms): {time_str}', markup=True))
                    await detail.mount(
                        Static(f'  Time Multiplier: {tmult_str}', markup=True)
                    )
                    await detail.mount(Static(f'  Memory (MB): {mem_str}', markup=True))
                else:
                    mod = profile.modifiers.get(lang_name, LimitModifiers())

                    time_input = Input(
                        value=(str(mod.time) if mod.time is not None else ''),
                        placeholder='',
                        type='integer',
                        id=f'mod-time-{lang_name}',
                    )
                    time_input.border_title = 'Time (ms)'
                    await detail.mount(time_input)

                    time_mult_input = Input(
                        value=(
                            str(mod.timeMultiplier)
                            if mod.timeMultiplier is not None
                            else ''
                        ),
                        placeholder='',
                        type='number',
                        id=f'mod-tmult-{lang_name}',
                    )
                    time_mult_input.border_title = 'Time Multiplier'
                    await detail.mount(time_mult_input)

                    mem_input = Input(
                        value=(str(mod.memory) if mod.memory is not None else ''),
                        placeholder='',
                        type='integer',
                        id=f'mod-mem-{lang_name}',
                    )
                    mem_input.border_title = 'Memory (MB)'
                    await detail.mount(mem_input)

            # --- Add language button ---
            await detail.mount(
                Button('+ Add Language', id='add-lang-btn', variant='default')
            )

            # --- Save button ---
            await detail.mount(Button('Save', id='save-btn', variant='primary'))
        finally:
            self._is_rendering = False

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Re-render form when inherit switch changes."""
        if event.switch.id != 'inherit-switch':
            return
        if self._is_rendering:
            return
        self._delete_pending = None
        inherit = event.value
        # Build a fresh profile with the new inherit value and re-render.
        profile = LimitsProfile(inheritFromPackage=inherit)
        asyncio.ensure_future(self._load_profile_detail_from(profile))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        self._delete_pending = None
        if event.button.id == 'save-btn':
            await self.action_save()
        elif event.button.id == 'add-lang-btn':
            await self._show_add_language_input()

    async def _show_add_language_input(self):
        """Show an input field for adding a custom language."""
        # Remove any existing add-lang-input.
        try:
            existing = self.query_one('#add-lang-input', Input)
            await existing.remove()
        except Exception:
            pass

        add_btn = self.query_one('#add-lang-btn', Button)
        lang_input = Input(
            placeholder='Language key (e.g. cpp, java)', id='add-lang-input'
        )
        detail = self.query_one('#limits-detail', VerticalScroll)
        await detail.mount(lang_input, before=add_btn)
        lang_input.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dispatch input submissions based on input id."""
        self._delete_pending = None
        if event.input.id == 'new-profile-name':
            await self._handle_new_profile_submit(event)
        elif event.input.id == 'add-lang-input':
            await self._handle_add_language_submit(event)

    async def _handle_new_profile_submit(self, event: Input.Submitted) -> None:
        """Handle submission of the new profile name input."""
        name = event.value.strip()
        if not name:
            self.app.notify('Profile name cannot be empty', severity='error')
            return
        if name in self._profile_names:
            self.app.notify(f'Profile "{name}" already exists', severity='error')
            return

        # Create empty profile file.
        limits_path = package.get_limits_file(name)
        limits_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_str = utils.model_to_yaml(LimitsProfile())
        limits_path.write_text(yaml_str)

        # Refresh profile list.
        await self._load_profiles()

        # Select the new profile in the list and load its detail form.
        self._selected_profile = name
        lv = self.query_one('#limits-profile-list', ListView)
        new_index = self._profile_names.index(name)
        lv.index = new_index
        await self._load_profile_detail()

    async def _handle_add_language_submit(self, event: Input.Submitted) -> None:
        """Handle submission of the add language input."""
        lang_key = event.value.strip()
        if not lang_key:
            self.app.notify('Language key cannot be empty', severity='error')
            return
        if lang_key in self._modifier_languages:
            self.app.notify(f'Language "{lang_key}" already exists', severity='error')
            return

        # Save current form state before re-rendering.
        profile = self._build_profile_from_form()
        if profile is None:
            return

        # Add the new language as empty modifiers.
        profile.modifiers[lang_key] = LimitModifiers()

        # Re-render the form with the updated profile.
        await self._load_profile_detail_from(profile)

    def _build_profile_from_form(self) -> Optional[LimitsProfile]:
        """Extract a LimitsProfile from the current form state."""
        try:
            inherit_switch = self.query_one('#inherit-switch', Switch)
        except Exception:
            self.app.notify('No profile loaded', severity='error')
            return None

        if inherit_switch.value:
            return LimitsProfile(inheritFromPackage=True)

        # Collect global limits.
        tl_val = self.query_one('#tl-input', Input).value.strip()
        ml_val = self.query_one('#ml-input', Input).value.strip()

        time_limit = int(tl_val) if tl_val else None
        memory_limit = int(ml_val) if ml_val else None

        # Collect per-language modifiers.
        modifiers: Dict[str, LimitModifiers] = {}
        for lang_name in self._modifier_languages:
            time_val = self.query_one(f'#mod-time-{lang_name}', Input).value.strip()
            tmult_val = self.query_one(f'#mod-tmult-{lang_name}', Input).value.strip()
            mem_val = self.query_one(f'#mod-mem-{lang_name}', Input).value.strip()

            # Only include modifier if at least one field is non-empty.
            if time_val or tmult_val or mem_val:
                mod = LimitModifiers(
                    time=int(time_val) if time_val else None,
                    timeMultiplier=float(tmult_val) if tmult_val else None,
                    memory=int(mem_val) if mem_val else None,
                )
                modifiers[lang_name] = mod

        return LimitsProfile(
            timeLimit=time_limit,
            memoryLimit=memory_limit,
            modifiers=modifiers,
        )

    async def action_delete_profile(self) -> None:
        """Delete the currently selected profile with double-press confirmation."""
        if self._selected_profile is None:
            self.app.notify('No profile selected', severity='error')
            return

        if self._delete_pending == self._selected_profile:
            # Second press -- actually delete.
            self._delete_pending = None
            profile_name = self._selected_profile
            limits_path = package.get_limits_file(profile_name)
            try:
                limits_path.unlink()
            except FileNotFoundError:
                pass

            # Clear selection and refresh.
            self._selected_profile = None
            await self._load_profiles()

            # Show placeholder in detail pane.
            detail = self.query_one('#limits-detail', VerticalScroll)
            await detail.remove_children()
            await detail.mount(Static('Select a profile', id='limits-placeholder'))

            self.app.notify(f'Profile "{profile_name}" deleted')
        else:
            # First press -- set pending and notify.
            self._delete_pending = self._selected_profile
            self.app.notify(
                f"Press 'd' again to delete profile '{self._selected_profile}'"
            )

    async def action_save(self) -> None:
        """Build a LimitsProfile from form state and write to disk."""
        self._delete_pending = None
        if self._selected_profile is None:
            self.app.notify('No profile selected', severity='error')
            return

        profile = self._build_profile_from_form()
        if profile is None:
            return

        # Write to disk.
        limits_path = package.get_limits_file(self._selected_profile)
        limits_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_str = utils.model_to_yaml(profile)
        limits_path.write_text(yaml_str)

        self._last_saved_profile = self._normalize_profile(profile)
        self.app.notify(f'Profile "{self._selected_profile}" saved')
