#!/bin/bash
# scripts/compare.sh — STUB (instalado por mojtools/interactive/install-interactive.sh).
#
# O COMPARE genérico do protocolo interativo mora no MOJTOOLS (fonte única):
#   mojtools/interactive/compare.sh   (vazio -> 13/UE; "WRONG …" -> 6/WA; resto -> 4/AC + SCORE=)
# Este arquivo é só o PONTEIRO. Um problema que precise de compare PRÓPRIO simplesmente
# substitui este arquivo (o install-interactive.sh --keep-compare preserva o que já existe).
set -u
_mt="${MOJTOOLS_DIR:-$PWD}"    # o build-and-test.sh EXPORTA MOJTOOLS_DIR (e roda com CWD=mojtools)
[[ -x "$_mt/interactive/compare.sh" ]] || {
  echo "compare.sh: compare do interativo não encontrado em '$_mt/interactive/compare.sh'"
  exit 13
}
exec "$_mt/interactive/compare.sh" "$@"
