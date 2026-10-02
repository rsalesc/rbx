#!/bin/bash
# scripts/c/run.sh (instalado por mojtools/interactive/install-interactive.sh; as demais
# linguagens symlinkam o diretório: scripts/<lang> -> c) — DRIVER COMUM de PROBLEMA
# INTERATIVO do MOJ. Roda ÁRBITRO + JOGADOR dentro da jaula, cruzando stdin/stdout por
# FIFOs, e materializa o RESULTADO em /tmp/out p/ o compare decidir o veredicto.
#
# Protocolo (tutorial: mojtools/docs/problema-interativo.md):
#   - árbitro = /tmp/dir/arbitro (materializado pelo prep.sh), recebe o teste em argv[1];
#   - árbitro stdout -> stdin do jogador; jogador stdout -> stdin do árbitro (stdbuf -oL);
#   - a ÚLTIMA linha do stderr do árbitro é o RESULTADO: score/info no sucesso,
#     "WRONG <motivo>" no erro. (Compat: árbitro que grava /tmp/out direto é respeitado.)
#   - O RESULTADO do árbitro MANDA: com resultado, o exit do jogador é ignorado;
#     sem resultado, jogador que morreu = RTE (exit 3) e silêncio = UE (compare 13).
#   - Morte ANORMAL do árbitro: SIGPIPE (13) = o JOGADOR fechou o pipe -> RTE (jogador
#     morto) ou WRONG (saiu sem ler); qualquer outro sinal = erro do JUIZ -> UE; exit != 0
#     sem resultado = UE. De árbitro morto/anormal só se honra /tmp/out explícito ou última
#     linha "WRONG …" — linha de log benigna viraria AC FALSO (compare: não-WRONG = SCORE).
#   - TL: o juiz manda TERM; materializamos o que houver e saímos 0 (o TLE sai pelo
#     tempo medido, como em qualquer problema).

exec 2>/tmp/stderrlog

# materializa /tmp/out: respeita se o árbitro já gravou algo; senão usa a última linha
# não-vazia do log (stderr) dele. NUNCA recriar /tmp/out (é um bind de arquivo): só '>'.
materializa() {
  [[ -s /tmp/out ]] && return 0
  [[ -s /tmp/arbitro.log ]] || return 0
  grep -v '^[[:space:]]*$' /tmp/arbitro.log | tail -n1 > /tmp/out
}

sai_tl() {
  echo "======== DRIVER: TERM recebido (time limit do jogador)" >&2
  cat /tmp/arbitro.log >&2 2>/dev/null
  materializa
  exit 0
}
trap sai_tl TERM

cd /tmp/dir
source binfile.sh

# dispatch de linguagem pela extensão do binário/fonte (testado: compilados ELF, py, sh,
# java, kt; melhor esforço: js — ver limitações no tutorial). Os ramos da JVM espelham
# lang/java/run.sh e lang/kt/run.sh (mesmas flags de heap/stack, locale e charset): java roda a CLASSE
# (compile.sh elege a que tem main), kotlin roda o JAR (kotlinc -include-runtime já põe o
# Main-Class no manifest). ⚠ na JVM o `stdbuf -oL` abaixo é NO-OP (I/O próprio, não libc):
# a solução TEM de dar flush a cada resposta — está no enunciado/tutorial.
CMD=(/tmp/dir/"$BIN")
_JVM=(-Duser.language=en -Duser.country=US -Dstdout.encoding=UTF-8 -Dstderr.encoding=UTF-8
      -Xms10m -Xmx${MOJ_MEMLIMITMB:-500}m -Xss${MOJ_STACKKB:-131072}k)
case "$BIN" in
  *.py|*.py2|*.py3) CMD=(python3 /tmp/dir/"$BIN") ;;
  *.sh)             CMD=(bash /tmp/dir/"$BIN") ;;
  *.js)             CMD=(node /tmp/dir/"$BIN") ;;
  *.class)          export CLASSPATH=/tmp/dir
                    CMD=(java "${_JVM[@]}" "$(basename "$BIN" .class)") ;;
  *.jar)            CMD=(java "${_JVM[@]}" -jar /tmp/dir/"$BIN") ;;
esac

mkfifo /tmp/fifo.in /tmp/fifo.out
cd /tmp/

stdbuf -oL /bin/time --output /tmp/aluno.time -f "%M %U" "${CMD[@]}" < /tmp/fifo.out > /tmp/fifo.in 2>/tmp/aluno.log &
stdbuf -oL /bin/time --output /tmp/arbitro.time -f "%M %U" /tmp/dir/arbitro /tmp/in > /tmp/fifo.out < /tmp/fifo.in 2> /tmp/arbitro.log &

wait

# log do árbitro + stderr do JOGADOR + medidas vão p/ o stderr (aparecem no report). O
# stderr do jogador é o único diagnóstico de exceção em JVM/Python — não jogar fora.
cat /tmp/arbitro.log >&2 2>/dev/null
if [[ -s /tmp/aluno.log ]]; then
  echo "======== stderr do jogador (últimas 40 linhas)" >&2
  tail -n 40 /tmp/aluno.log >&2 2>/dev/null
fi
read -r MEMORIA TEMPO <<< "$(tail -n1 /tmp/aluno.time 2>/dev/null)"
echo "Tempo do jogador (segundos de CPU): ${TEMPO:-?}" >&2
echo "Memória do jogador (KB): ${MEMORIA:-?}" >&2

# --- pós-morte: decidir o veredicto a partir de COMO cada lado terminou -----------------
# aluno_died: o texto do GNU time é a única fonte (o `wait` sem PID não colhe status)
aluno_died=0
grep -Eqi "(non-zero|signal)" /tmp/aluno.time 2>/dev/null && aluno_died=1
# número do sinal que matou o árbitro ("Command terminated by signal N"), vazio = sem sinal
arbsig="$(grep -i 'terminated by signal' /tmp/arbitro.time 2>/dev/null | grep -oE '[0-9]+' | head -1)"

# wrong_do_log: honra a última linha do stderr do árbitro SÓ se for um "WRONG …" — a última
# linha de um árbitro que MORREU é log benigno, e o compare trata qualquer não-WRONG como
# ACCEPTED (SCORE=<linha>); materializá-la seria AC falso. (Árbitro com a proteção de SIGPIPE
# imprime o WRONG antes de sair — inclusive sob driver antigo.)
wrong_do_log() {
  local last
  last="$(grep -v '^[[:space:]]*$' /tmp/arbitro.log 2>/dev/null | tail -n1)"
  [[ "$last" == WRONG* ]] || return 1
  printf '%s\n' "$last" > /tmp/out
}

if [[ "$arbsig" == 13 ]]; then
  # SIGPIPE = o JOGADOR fechou o pipe e o árbitro morreu escrevendo a resposta: erro do
  # ALUNO, não do juiz (era a vala comum do "sinal ⇒ UE" — cada aluno virava chamado).
  if [[ -s /tmp/out ]] || wrong_do_log; then
    echo "DRIVER: árbitro levou SIGPIPE (jogador fechou o pipe); resultado do árbitro mantido" >&2
  elif (( aluno_died )); then
    echo "DRIVER: jogador morreu sem ler a resposta pendente (árbitro levou SIGPIPE) -> Runtime Error" >&2
    exit 3
  else
    echo "DRIVER: jogador ENCERROU sem ler a resposta pendente (árbitro levou SIGPIPE) -> Wrong Answer" >&2
    printf 'WRONG o programa encerrou sem ler a resposta do árbitro\n' > /tmp/out
  fi
  exit 0
fi

if [[ -n "$arbsig" ]]; then
  # qualquer OUTRO sinal (SEGV/ABRT/…) = erro do JUIZ: invalida o resultado -> UE (compare 13)
  echo "DRIVER: árbitro terminou por SINAL $arbsig — resultado invalidado (vira UE)" >&2
  : > /tmp/out
  exit 0
fi

if grep -qi "non-zero" /tmp/arbitro.time 2>/dev/null; then
  # árbitro saiu ≠0 (o contrato manda SEMPRE 0). Cobrir o caso Python: pipe quebrado vira
  # BrokenPipeError + exit 1 (SEM sinal) e a última linha do TRACEBACK virava "resultado"
  # (= AC FALSO, pois compare trata não-WRONG como Accepted). Resultado explícito/WRONG
  # valem; senão jogador morto -> RTE; senão árbitro bugado -> UE.
  if [[ -s /tmp/out ]] || wrong_do_log; then
    echo "DRIVER: árbitro saiu com exit != 0, mas deixou resultado — mantido" >&2
  elif (( aluno_died )); then
    echo "DRIVER: jogador morreu e o árbitro saiu com exit != 0 sem resultado -> Runtime Error" >&2
    exit 3
  else
    echo "DRIVER: árbitro saiu com exit != 0 sem resultado (vira UE)" >&2
    : > /tmp/out
  fi
  exit 0
fi

materializa

# sem resultado do árbitro: jogador que morreu explica o silêncio -> RTE; senão UE
if [[ ! -s /tmp/out ]] && (( aluno_died )); then
  echo "DRIVER: jogador terminou com erro e o árbitro não produziu resultado -> Runtime Error" >&2
  exit 3
fi

exit 0
