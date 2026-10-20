# MEDSAFE-DSL User Guide

## Requirements
Python 3.10+ (check: `python --version`). No packages to install.

## VS Code setup
1. Unzip the project, then File > Open Folder > `medsafe-dsl-src`.
2. Terminal > New Terminal (it must be inside `medsafe-dsl-src`).

## Commands
    python main.py phase3_demo.smed                 # safe protocol: compile + VM run
    python main.py phase3_demo.smed --trace         # simulation event table
    python main.py phase3_alarm_demo.smed           # passes static checks, runtime alarm
    python main.py phase3_alarm_demo.smed --strict  # exit code 2 on alarms
    python main.py cumulative_error.smed            # static cumulative-dose error
    python main.py interaction_error.smed           # static interaction error
    python main.py over_error.smed                  # OVER > EVERY error
    python main.py phase31_demo.smed                # Phase 3.1: same-drug sum proven safe
    python main.py concurrent_error.smed            # Phase 3.1: same-drug sum rejected
    python main.py phase32_demo.smed                # Phase 3.2: bounded infusion + interaction with a REPEAT dose
    python main.py bounded_total_error.smed         # Phase 3.2: static total for a bounded infusion
    python main.py interaction_repeat_error.smed    # Phase 3.2: interaction with a REPEAT dose
    python main.py phase2_demo.smed                 # now a compile-time error (Phase 3.1)
    python run_cases.py                             # 20 end-to-end cases
    python main.py phase3_demo.smed --emit-bytecode demo.medc
    python main.py --exec demo.medc                 # run bytecode, no source
    python main.py phase3_demo.smed --perf          # timing / memory / optimizer
    python benchmark.py                             # scaling benchmark
    python -m unittest discover -s tests -v         # all 161 tests

## Your own protocol
    PATIENT p1 { WEIGHT: 70 kg; }
    DRUG dopamine { MAX_RATE: 20 mg/hr; MAX_TOTAL: 400 mg; }
    INFUSION a FOR p1 USING dopamine AT 8 mg/hr;
    REPEAT b FOR p1 USING dopamine AT 4 mg/hr EVERY 6 hr UNTIL 24 hr OVER 1 hr;
(Phase 3.2: add OVER to an INFUSION to make it end, e.g. `INFUSION a FOR p1 USING dopamine AT 8 mg/hr OVER 10 hr;`)
Units: mg, mcg, g; hr, min; kg for weight. Comments start with `#`.

## Exit codes
0 ok; 1 compile or VM error; 2 runtime alarms with --strict.
