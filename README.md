# RIA Simulation Validator (v0.7)

**Author:** Steven Lanier-Egu • **Credit:** SEAL Division

This repository provides a minimal, physics-respecting simulation that validates the safety-case targets
from the paper in `docs/RIA_Protection_Upgrade_Stack_v0.7.md`:

- **Sense → Release → Terminate → Recover** control story
- **Worth-vs-time targets:** ≥ 0.5 mk at 20 ms; ≥ 1.0 mk at 50 ms (primary). Backup checked when used.
- **Non-blocking invariant:** ≤ 500 µs supervisory delay
- **Artifacts:** CSV, JSON log, reactivity & power plots

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements.txt

# Run default rod-ejection scenario
python ria_sim_v07.py --outdir ./out

# Alternative: cold-water insertion
python ria_sim_v07.py --scenario cold_water --outdir ./out_cwi
```

### Outputs
- `out/timeseries.csv` — time, ρ, power, primary/backup/poison worths, event times
- `out/sim_log.json` — config, targets, events, pass/fail checks
- `out/reactivity.png`, `out/power.png` — one plot per figure

## CI
GitHub Actions runs a smoke test on push/PR:
- Installs deps
- Runs the simulator
- Verifies JSON log exists and that checks pass

## Notes
- Reactivity units: **mk** denotes milli-k (Δk/k × 1e-3). 1 $ equals β_eff of the core (plant-specific).
- The model uses a single effective delayed group for speed; swap in your plant kinetics to tighten fidelity.


## Packaging & Make
- Install/editable: `pip install -e .` (uses `pyproject.toml`)
- Run quick demo: `make demo` (creates venv, installs, runs `ria-sim` entrypoint)
