import syncer
import typer

from rbx import annotations

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command(
    'configure, config',
    help='Configure a DOMjudge server from the languages and limits in env.rbx.yml.',
)
@annotations.docs("""
    Push the environment's languages, compilation flags and limits to the DOMjudge
    instance named by `RBX_DOMJUDGE_SERVER`, `RBX_DOMJUDGE_USERNAME` and
    `RBX_DOMJUDGE_PASSWORD`.

    DOMjudge has no contest-scoped equivalent for any of this, so every change is
    instance-wide and needs an admin account. What is changed:

    - Which languages accept submissions, and which file extensions they accept.
      Languages the server has enabled that rbx does not manage stay enabled.
    - The compile script of every rbx language whose compilation command
      translates to DOMjudge's one-command compile wrapper.
    - The limits set under `extensions.domjudge` in `env.rbx.yml`.
""")
@syncer.sync
async def configure():
    from rbx.box import environment
    from rbx.box.runners.domjudge import api as domjudge_api
    from rbx.box.tooling.domjudge import configure as configure_lib
    from rbx.box.tooling.domjudge import plan as plan_lib

    api = domjudge_api.DomjudgeApi(domjudge_api.credentials_from_env())
    env = environment.get_environment()

    plan = plan_lib.build_plan(
        env,
        await api.all_languages(),
        await api.config(),
    )
    configure_lib.print_plan(api, plan)

    if plan.is_empty():
        return

    if not await configure_lib.apply_plan(api, plan):
        raise typer.Exit(1)
