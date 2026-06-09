# `rbx` completion — ⚠️ experimental, AI-authored

**This module was coded entirely with AI** (Claude / Claude Code). It is
**experimental**: the design, implementation, and tests were produced in an
AI-driven session, and while it is covered by a differential test against real
Typer, an import-firewall test, and a drift guard, its behaviour has not yet been
battle-tested across shells, terminals, and real-world usage. Expect rough edges,
and treat it as provisional until it has seen wider use.

It exists to make `<tab>` shell completion fast — see [`CLAUDE.md`](CLAUDE.md) for
the architecture and how to add a completer, and
[`docs/plans/2026-06-09-fast-completion-design.md`](../../../docs/plans/2026-06-09-fast-completion-design.md)
for the design rationale. Tracking issue:
[#333](https://github.com/rsalesc/rbx/issues/333).

If you hit a completion bug, the safe fallback is built in: on any error the
engine hands control back to the shell's own default completion, so a defect here
should degrade gracefully rather than break your shell.
