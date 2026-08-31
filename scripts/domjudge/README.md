# Local DOMjudge test server

A throwaway [DOMjudge](https://www.domjudge.org/) instance for poking at by
hand: importing packages, exercising the API, checking what an export looks
like from the other side. It is **not** wired into any test suite, and nothing
here is production-grade -- the passwords are fixed and the whole thing is
meant to be thrown away with one command.

## Quick start

```bash
scripts/domjudge/domjudge.sh up
```

The first run pulls `domjudge/domserver` and `mariadb` (a few hundred MB) and
takes a couple of minutes while the database is installed; later runs come up
in seconds. When it is healthy the script prints the URL and the credentials:

```
DOMjudge is up:
  url:             http://localhost:12345/
  admin user:      admin
  admin password:  <generated>
  judgehost pass:  <generated>
  demo accounts:   demo / demo (team), judge / judge (jury)
```

Print them again at any time with `scripts/domjudge/domjudge.sh creds`.

By default the install is seeded with DOMjudge's demo contest, teams and
problems, which is what you usually want for a test server. Pass `--bare` on
the very first `up` (it only affects a fresh database) for an empty install.

## Commands

| Command | What it does |
| --- | --- |
| `up [--with-judgehost] [--bare]` | Start mariadb + domserver, wait until healthy, print credentials |
| `down [--volumes]` | Stop the containers; `--volumes` also drops the database |
| `nuke` | `down --volumes` -- start over from scratch next time |
| `restart` | `down` then `up` |
| `status` | Container and health status |
| `creds` | Re-print URL, admin password, judgehost password |
| `logs [service] [-f]` | Tail logs (default service: `domserver`) |
| `shell [service]` | Open a shell inside a container |

Environment knobs: `DJ_PORT` (default `12345`) and `DJ_VERSION` (image tag,
default `latest`).

## About the judgehost

`up` starts only the web server and its database. That is enough to browse the
interface, import problems, and drive the REST API, but submissions sit at
`PENDING` because nothing judges them.

`up --with-judgehost` also starts a judgedaemon. The script reads the generated
judgehost password out of the domserver's `restapi.secret` and passes it to the
judgehost container, so no manual credential wiring is needed. The catch is
that a judgedaemon needs a **privileged container with the host's cgroups**
(`/sys/fs/cgroup`) and specific kernel boot parameters; in practice it only
works on Linux. On macOS and Windows Docker Desktop the container starts and
then fails to claim cgroups -- the script warns and starts it anyway, and
`domjudge.sh logs judgehost` will show why it gave up.

For judging on a non-Linux host, run the whole thing inside a Linux VM (with
`systemd.unified_cgroup_hierarchy=0` and the cgroup memory/swap accounting
parameters DOMjudge's docs list) rather than on Docker Desktop.

## Troubleshooting

- **Port already in use.** `DJ_PORT=13000 scripts/domjudge/domjudge.sh up`.
- **`up` times out waiting for the domserver.** The first install can be slow
  on a cold cache; check `domjudge.sh logs domserver` and re-run `up` -- it is
  idempotent.
- **Weird state after upgrading `DJ_VERSION`.** The database schema is tied to
  the image version; `domjudge.sh nuke` and start over.
