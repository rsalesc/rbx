# Contributor Workflow Standardization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize contributor development by consolidating commands in mise.toml, adding README guidelines, expanding pre-commit hooks, and adding CI lint check.

**Architecture:** Config-only changes across 4 files. No application code changes.

**Tech Stack:** mise, uv, ruff, pre-commit, GitHub Actions

---

### Task 1: Consolidate mise.toml

**Files:**
- Modify: `mise.toml`

Add sync, lock, lint, format, check, bump, build, publish tasks to existing test tasks.

**Verify:** `mise tasks` shows all tasks.

---

### Task 2: Add uv.lock pre-commit hook

**Files:**
- Modify: `.pre-commit-config.yaml`

Add local hook running `uv lock --check` on pyproject.toml/uv.lock changes.

**Verify:** `pre-commit run uv-lock-check --all-files` passes.

---

### Task 3: Create CI lint workflow

**Files:**
- Create: `.github/workflows/lint.yml`

Runs `ruff check .` and `ruff format --check .` on PRs and pushes to main/master.

---

### Task 4: Add Contributing section to README

**Files:**
- Modify: `README.md`

Add Contributing section before License with prerequisites, setup, task table, code style, PR workflow.

---
