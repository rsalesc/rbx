# BOCA E2E Tests

> **Looking for the YAML-driven e2e framework?** Most CLI-level e2e tests now
> live under [`tests/e2e/`](../../../../e2e/), where each fixture is a
> self-contained `rbx` package with an `e2e.rbx.yml` describing scenarios. See
> [`tests/e2e/README.md`](../../../../e2e/README.md) for the schema and
> authoring guide. **This directory now houses only the docker-based BOCA
> upload test** (`test_boca_e2e.py`), which stays as Python because it needs
> docker-compose orchestration that the YAML DSL deliberately doesn't model.

This directory contains end-to-end tests for BOCA package generation and upload functionality.

## Prerequisites

- Docker and Docker Compose installed
- Python with pytest installed
- rbx CLI available

## Running the Tests

### Run all E2E tests:
```bash
pytest tests/rbx/box/packaging/e2e/ -m e2e
```

### Run only BOCA E2E tests:
```bash
pytest tests/rbx/box/packaging/e2e/test_boca_e2e.py
```

### Skip E2E/slow tests during regular test runs:
```bash
pytest -m "not e2e and not slow"
```

### Run tests without Docker requirement:
```bash
pytest tests/rbx/box/packaging/e2e/test_boca_e2e.py::test_boca_package_structure
```

## Test Structure

- `docker/` - Docker Compose configuration for BOCA environment
- `testdata/` - Test problem data
- `test_boca_e2e.py` - Main test file
- `conftest.py` - Pytest configuration and fixtures

## How It Works

1. Docker Compose spins up a complete BOCA environment (database, web, jail)
2. Tests generate BOCA packages using rbx
3. Packages are validated for correct structure
4. (Future) Packages are uploaded to BOCA and verified

## Troubleshooting

If tests fail with Docker issues:
- Ensure Docker daemon is running
- Check that ports 8000 and 5432 are available
- Run `docker-compose down -v` in the docker directory to clean up

## Adding New Tests

1. Create test problems in `testdata/`
2. Add test functions with appropriate markers (@pytest.mark.e2e, @pytest.mark.docker)
3. Use provided fixtures for BOCA environment and sessions