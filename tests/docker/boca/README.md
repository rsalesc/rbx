# BOCA E2E Tests (docker-backed, disabled by default)

> **These tests are disabled by default and are not meant to be run by agents
> or by any regular test command.** `tests/docker/conftest.py` skips collection
> of everything under `tests/docker/` unless `RBX_DOCKER_TESTS=1` is exported,
> and `test_boca_e2e.py` carries a module-level `skipif` on the same variable
> as a second gate. They need a docker daemon, docker-compose, network access
> to clone `rsalesc/boca-docker`, and several minutes of wall-clock time.

> **Looking for the YAML-driven e2e framework?** Most CLI-level e2e tests live
> under [`tests/e2e/`](../../e2e/), where each fixture is a self-contained `rbx`
> package with an `e2e.rbx.yml` describing scenarios. See
> [`tests/e2e/README.md`](../../e2e/README.md) for the schema and authoring
> guide. **This directory houses only the docker-based BOCA upload test**
> (`test_boca_e2e.py`), which stays as Python because it needs docker-compose
> orchestration that the YAML DSL deliberately doesn't model.

## Prerequisites

- Docker and Docker Compose installed
- Python with pytest installed
- rbx CLI available

## Running the Tests

### Run them (the only supported way):
```bash
mise run test-docker
```

which is equivalent to:
```bash
RBX_DOCKER_TESTS=1 uv run pytest tests/docker -m docker -v -s
```

### Run a single test:
```bash
RBX_DOCKER_TESTS=1 uv run pytest tests/docker/boca/test_boca_e2e.py::test_boca_package_structure
```

Without `RBX_DOCKER_TESTS=1` the files are not even collected, so a plain
`pytest`, `mise run test`, `mise run test-e2e` or CI run never touches them.

## Test Structure

- `docker/` - Docker Compose configuration for BOCA environment
- `testdata/` - Test problem data
- `test_boca_e2e.py` - Main test file
- `conftest.py` - Fixtures (re-exports the ones this suite used to inherit
  from `tests/rbx/conftest.py` and `tests/rbx/box/conftest.py`)

## How It Works

1. Docker Compose spins up a complete BOCA environment (database, web, jail)
2. Tests generate BOCA packages using rbx
3. Packages are validated for correct structure
4. Packages are uploaded to BOCA, judged, and the verdicts are verified

## Troubleshooting

If tests fail with Docker issues:
- Ensure Docker daemon is running
- Check that ports 8000 and 5432 are available
- Run `docker-compose down -v` in the docker directory to clean up

## Adding New Tests

1. Create test problems in `testdata/`
2. Add test functions with appropriate markers (@pytest.mark.e2e, @pytest.mark.docker)
3. Use provided fixtures for BOCA environment and sessions
