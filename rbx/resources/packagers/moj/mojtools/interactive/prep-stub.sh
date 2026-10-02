#!/bin/bash
# scripts/c/prep.sh — STUB (instalado por mojtools/interactive/install-interactive.sh; as
# demais linguagens symlinkam o diretório: scripts/<lang> -> c).
#
# O PREP do interativo (materializa/compila o ÁRBITRO) mora no MOJTOOLS (fonte única):
#   mojtools/interactive/prep.sh
# Este arquivo é só o PONTEIRO — não edite, não copie o prep para cá.
#
# É SOURCED pelo build-and-test NO HOST, com $1 = workdir e $PROBLEMTEMPLATEDIR no ambiente:
#   - nada de `exit` (mataria o julgamento) — só mensagem no stderr;
#   - o bit +x IMPORTA: o build-and-test testa `[[ -x "$PREPLANGUAGE" ]]` antes de dar source.
#
# ⚠ O prep do PACOTE SUBSTITUI o da LINGUAGEM no build-and-test (são mutuamente exclusivos):
# sem a linha abaixo, `lang/kt/prep.sh` (bind /opt/kotlin), `lang/apl` e `lang/hs` nunca rodam
# num pacote interativo e o compilador some — em modo HOST isso é Compilation Error.
_mt_lang_prep="${MOJTOOLS_DIR:-$PWD}/lang/${LANGUAGE:-}/prep.sh"
[[ -n "${LANGUAGE:-}" && -f "$_mt_lang_prep" ]] && source "$_mt_lang_prep" "$@"
unset _mt_lang_prep

if [[ -f "${MOJTOOLS_DIR:-$PWD}/interactive/prep.sh" ]]; then
  source "${MOJTOOLS_DIR:-$PWD}/interactive/prep.sh" "$@"
else
  echo "prep.sh: prep do interativo não encontrado em '${MOJTOOLS_DIR:-$PWD}/interactive/prep.sh' (MOJTOOLS_DIR='${MOJTOOLS_DIR:-}') — sem árbitro" >&2
fi
