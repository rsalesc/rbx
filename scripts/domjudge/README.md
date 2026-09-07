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
| `up [--no-judgehost] [--bare]` | Start the full stack, wait until healthy, print credentials |
| `down [--volumes]` | Stop the containers; `--volumes` also drops the database |
| `nuke` | `down --volumes` -- start over from scratch next time |
| `restart` | `down` then `up` |
| `status` | Container and health status |
| `creds` | Re-print URL, admin password, judgehost password |
| `logs [service] [-f]` | Tail logs (default service: `domserver`) |
| `shell [service]` | Open a shell inside a container |
| `import <zip> [--contest <id>] [--problem <id>]` | Import a DOMjudge problem zip into a contest |

Environment knobs: `DJ_PORT` (default `12345`), `DJ_VERSION` (image tag,
default `latest`) and `DJ_CONTEST` (import target, default `demo`).

## Importing a problem package

`import` uploads a DOMjudge-compatible problem zip -- the kind `rbx package
domjudge` builds -- into a contest on the running server, through the same REST
endpoint DOMjudge's own `import-contest` uses:

```bash
scripts/domjudge/domjudge.sh import path/to/problem.zip
```

It prints the problem id DOMjudge assigned plus whatever the importer had to
say, and the problem is immediately submittable and judged.

Two things about the problem id are worth knowing:

- With no `--problem`, DOMjudge **derives the new problem's id from the zip's
  filename** (`aplusb.zip` becomes problem `aplusb`), not from anything inside
  the package. Name the file accordingly.
- `--problem <id>` overwrites an existing problem in place, which is what you
  want when re-importing after a rebuild. The id has to already exist -- against
  a fresh id the API answers `Specified 'problem' does not exist`.

`--contest <id>` targets a contest other than `demo`. Both a missing contest and
a package DOMjudge dislikes surface as the API's own error message.

## About the judgehost

`up` starts a judgedaemon along with the server, so submissions are actually
judged. Pass `--no-judgehost` to skip it; submissions then sit at `PENDING`,
which is fine if you only care about the web interface or the REST API.

The judgedaemon needs three things, all set in the compose file: a privileged
container, the host's cgroup namespace (`cgroup: host` -- without it the
daemon exits at startup complaining about a missing cgroup hierarchy prefix),
and `/sys/fs/cgroup` mounted. The generated judgehost password is read out of
the domserver's `restapi.secret` by the script and injected into the judgehost
container, so there is no manual credential wiring.

This works on Docker Desktop for Mac (verified on Apple silicon, DOMjudge
9.0.0): a correct C submission to the demo `hello` problem gets `AC` and a
wrong one gets `WA`. Judging is slower than native because the images are
emulated, but it is correct.

## Troubleshooting

- **Port already in use.** `DJ_PORT=13000 scripts/domjudge/domjudge.sh up`.
- **`up` times out waiting for the domserver.** The first install can be slow
  on a cold cache; check `domjudge.sh logs domserver` and re-run `up` -- it is
  idempotent.
- **Weird state after upgrading `DJ_VERSION`.** The database schema is tied to
  the image version; `domjudge.sh nuke` and start over.
- **`MySQL server has gone away` during the first install.** The compose file
  already raises mariadb's `max_allowed_packet` to 512M, which is what the
  demo problem import needs; if you changed that, put it back.

## A note on Apple silicon

DOMjudge only publishes amd64 images, so on an M-series Mac everything runs
emulated. It works -- the first `up` just takes a few minutes rather than
seconds -- and the compose file pins `platform: linux/amd64` so the behaviour
is the same everywhere.
