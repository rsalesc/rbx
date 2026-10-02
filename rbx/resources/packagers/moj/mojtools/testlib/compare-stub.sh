#!/bin/bash
# scripts/compare.sh — STUB (instalado por mojtools/testlib/install-checker.sh).
#
# O BRIDGE do checker testlib mora no MOJTOOLS (fonte única):
#   mojtools/testlib/checker-bridge.sh   — compila o scripts/checker.cpp DESTE pacote (na 1ª
#   comparação, cache fora de scripts/) e traduz o resultado p/ o contrato do juiz.
# Este arquivo é só o PONTEIRO: não edite, não copie o bridge para cá. (O pacote carregar a
# sua própria cópia do bridge foi o que espalhou um bug de bwrap por 198 pacotes.)
#
# Contrato do MOJ:  compare.sh <saída do time> <esperada> <entrada>
#                   -> exit 4=AC  5=AC,PE  6=WA  (qualquer outro = UE)
# O pacote traz só o scripts/checker.cpp — o testlib.h vem do mojtools.
# Guia de autoria: mojtools/docs/checker-testlib.md
set -u
_pkg="$(cd "$(dirname "$(readlink -f "$0")")/.." 2>/dev/null && pwd)"
_mt="${MOJTOOLS_DIR:-$PWD}"    # o build-and-test.sh EXPORTA MOJTOOLS_DIR (e roda com CWD=mojtools)
_br="$_mt/testlib/checker-bridge.sh"
[[ -x "$_br" ]] || {
  echo "compare.sh: bridge do checker não encontrado em '$_br' (MOJTOOLS_DIR='${MOJTOOLS_DIR:-}')"
  exit 7
}
exec "$_br" --pkg "$_pkg" "$@"
