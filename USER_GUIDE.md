# MEDSAFE-DSL User Guide

## Requirements
Python 3.10+ (check: `python --version`). No packages to install.

## VS Code setup
1. Unzip the project, then File > Open Folder > `medsafe-dsl-src`.
2. Terminal > New Terminal (it must be inside `medsafe-dsl-src`).

## Commands
    python main.py phase3_demo.smed                 # safe protocol: compile + VM run
    python main.py phase3_demo.smed --trace         # simulation event table
    python main.py phase3_alarm_demo.smed           # passes static checks, runtime alarms
    python main.py phase3_alarm_demo.smed --strict  # exit code 2 on alarms
    python main.py cumulative_error.smed            # static cumulative-dose error
    python main.py interaction_error.smed           # static interaction error
    python main.py over_error.smed                  # OVER > EVERY error
    python main.py phase3_demo.smed --emit-bytecode demo.medc
    python main.py --exec demo.medc                 # run bytecode, no source
    python main.py phase3_demo.smed --perf          # timing / memory / optimizer
    python benchmark.py                             # scaling benchmark
    python -m unittest discover -s tests -v         # all 114 tests

## Your own protocol
    PATIENT p1 { WEIGHT: 70 kg; }
    DRUG dopamine { MAX_RATE: 20 mg/hr; MAX_TOTAL: 400 mg; }
    INFUSION a FOR p1 USING dopamine AT 8 mg/hr;
    REPEAT b FOR p1 USING dopamine AT 4 mg/hr EVERY 6 hr UNTIL 24 hr OVER 1 hr;
Units: mg, mcg, g; hr, min; kg for weight. Comments start with `#`.

## Exit codes
0 ok; 1 compile or VM error; 2 runtime alarms with --strict.
