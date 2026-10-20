# MEDSAFE-DSL (Phase 3.1)

A domain-specific language, compiler and bytecode virtual machine for verifying clinical infusion protocols.
Pure Python 3.10+ standard library. No installation needed.
Author: Immanuel G., 24BKT0067, BCSE307P, VIT.

## Pipeline
source (.smed) -> lexer -> LL(1) parser -> AST -> semantic analysis (rate, same-drug concurrency, cumulative dose, interaction)
-> IR -> optimizer -> bytecode (.medc) -> VM load-time re-verification -> discrete-event simulation + runtime monitor

## Run
    python main.py phase3_demo.smed                  # compile + VM run (safe protocol)
    python main.py phase3_demo.smed --trace          # event table
    python main.py phase3_alarm_demo.smed --strict   # passes static checks, runtime alarm, exit code 2
    python main.py phase31_demo.smed                 # Phase 3.1: same-drug sources summed and proven
    python main.py concurrent_error.smed             # Phase 3.1: rejected at compile time
    python run_cases.py                              # 17 end-to-end cases, expected vs actual
    python main.py phase3_demo.smed --emit-bytecode demo.medc
    python main.py --exec demo.medc                  # run bytecode with no source
    python main.py phase3_demo.smed --perf           # timing / memory / optimizer stats
    python benchmark.py                              # scaling benchmark
    python -m unittest discover -s tests -v          # 131 tests

## Options
--tokens --ast --symtab --ir --optimize --bytecode --emit-bytecode FILE --exec FILE --trace --perf --horizon HOURS --strict
Exit codes: 0 ok, 1 compile/VM error, 2 runtime alarms with --strict.

## Language additions in Phase 3
    DRUG d { MAX_RATE: 20 mg/hr; MAX_TOTAL: 400 mg; }
    INTERACTION a WITH b LIMIT 30 mg/hr;        # LIMIT 0 = contraindicated
    REPEAT r FOR p USING d AT 3 mg/hr EVERY 6 hr UNTIL 24 hr OVER 2 hr;

## Files
tokens, lexer, parser, ast_nodes, symbol_table, semantic (front-end); ir, optimizer, bytecode (back-end);
vm (Phase 3: verifier, simulator, monitor); main (CLI); benchmark; tests/.
Sample programs: valid, phase2_demo, phase3_demo, phase3_alarm_demo and the *_error.smed files.

## Phase 3.1: same-drug concurrency (static)
Several INFUSION / conditional / REPEAT sources of the same drug for one patient add up. The analyzer
computes the exact peak of the summed rate (continuous sources from t=0, REPEAT doses at k*EVERY for OVER hours)
and rejects the program if it exceeds MAX_RATE. phase2_demo.smed (38 mg/hr vs 20) is now a compile-time error.

## Known limitations
- MAX_TOTAL is proven statically for REPEAT schedules only; continuous infusions are checked by the VM runtime monitor.
- INTERACTION limits are proven statically for continuous infusions; REPEAT doses are covered by the runtime monitor.
