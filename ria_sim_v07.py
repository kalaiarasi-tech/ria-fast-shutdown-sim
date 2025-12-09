#!/usr/bin/env python3
"""
RIA Simulation Validator (v0.7 - Final with Tiny Fixes)
Author: Steven Lanier-Egu (SEAL Division credit)
Final polishing by Grok
"""

import os
import json
import csv
import argparse
from dataclasses import dataclass, asdict
import numpy as np
import matplotlib.pyplot as plt

# ---------- Dataclasses and Config ----------

@dataclass
class CoreParams:
    beta_eff: float = 0.0065        # effective delayed neutron fraction
    Lambda: float = 1e-5            # prompt neutron lifetime (s)
    lambda_eff: float = 0.08        # effective delayed decay constant (s^-1)
    HFP_P0: float = 1.0             # normalized initial power
    Cp_fuel: float = 1.0            # (unused, for future enthalpy)
    mk: float = 1e-3                # milli-k

@dataclass
class DetectionParams:
    d_rho_dt_trip: float = 50.0     # mk/s threshold
    flux_ror_trip: float = 30.0     # 1/s power rate-of-rise threshold
    acquisition_us: float = 100.0
    decision_us: float = 200.0
    actuation_cmd_us: float = 100.0
    non_blocking_cap_us: float = 500.0

@dataclass
class WorthTargets:
    mk_20ms_primary: float = 0.5
    mk_50ms_primary: float = 1.0
    mk_20ms_backup: float = 0.4
    mk_50ms_backup: float = 0.8

@dataclass
class ActuationParams:
    primary_insert_ms: float = 15.0   # tuned to reliably meet targets
    backup_insert_ms: float = 40.0
    primary_max_mk: float = 1.5
    backup_max_mk: float = 1.2
    poison_max_mk: float = 3.0
    poison_start_ms: float = 10.0
    poison_full_s: float = 1.0
    primary_fail_prob: float = 0.1    # demo chance primary fails → backup fires

@dataclass
class Scenario:
    pos_step_dollars: float = 1.2     # prompt supercritical insertion
    t_insert_ms: float = 2.0          # fast insertion ramp

# ---------- Helpers ----------

def smooth_ramp(t, t_start, duration, max_val):
    """Smoothstep ramp for realistic insertion."""
    if t < t_start:
        return 0.0
    frac = min((t - t_start) / duration, 1.0)
    return max_val * (3 * frac**2 - 2 * frac**3)

def _to_jsonable(obj):
    """Make dataclass/np types JSON serializable."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(i) for i in obj]
    if hasattr(obj, '__dict__'):
        return _to_jsonable(obj.__dict__)
    if isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, bool):
        return bool(obj)
    if obj is None:
        return None
    return obj

# ---------- Main Simulation ----------

def simulate(core, det, act, scn, worth, dt_us=50.0, T_end_s=1.5, outdir="./out", seed=1,
             primary_fail_prob=None, non_blocking_us=None):
    if primary_fail_prob is not None:
        act.primary_fail_prob = primary_fail_prob
    supervisory_delay = (non_blocking_us if non_blocking_us is not None else np.random.uniform(0, det.non_blocking_cap_us)) * 1e-6

    np.random.seed(seed)
    os.makedirs(outdir, exist_ok=True)

    dt = dt_us * 1e-6
    t = np.arange(0, T_end_s + dt, dt)
    N = len(t)

    rho = np.zeros(N)
    P = np.zeros(N)
    C = np.zeros(N)  # delayed precursors
    worth_primary = np.zeros(N)
    worth_backup = np.zeros(N)
    worth_poison = np.zeros(N)

    P[0] = core.HFP_P0
    C[0] = core.beta_eff * P[0] / core.lambda_eff

    # Positive reactivity insertion
    t_insert = scn.t_insert_ms * 1e-3
    pos_rho_max = scn.pos_step_dollars * core.beta_eff
    pos_rho = np.array([smooth_ramp(ti, 0, t_insert, pos_rho_max) for ti in t])

    # Events
    trip_time = None
    primary_release_time = None
    backup_release_time = None
    poison_start_time = None

    primary_fails = np.random.rand() < act.primary_fail_prob

    for i in range(1, N):
        current_net_rho = pos_rho[i] - (worth_primary[i-1] + worth_backup[i-1] + worth_poison[i-1]) * core.mk

        dPdt = ((current_net_rho - core.beta_eff) / core.Lambda) * P[i-1] + core.lambda_eff * C[i-1]
        dCdt = (core.beta_eff / core.Lambda) * P[i-1] - core.lambda_eff * C[i-1]

        P[i] = P[i-1] + dPdt * dt
        C[i] = C[i-1] + dCdt * dt

        if P[i] > 1e12:
            P[i] = 1e12
        if P[i] < 1e-10:
            P[i] = 1e-10  # floor for log plot stability

        rho[i] = current_net_rho

        if trip_time is None:
            flux_ror = dPdt / P[i-1] if P[i-1] > 1e-6 else 0
            prev_net = pos_rho[i-1] - (worth_primary[i-1] + worth_backup[i-1] + worth_poison[i-1]) * core.mk
            d_rho_dt_mk_s = (current_net_rho - prev_net) / dt / core.mk

            if d_rho_dt_mk_s > det.d_rho_dt_trip or flux_ror > det.flux_ror_trip:
                trip_time = t[i]
                base_delay = (det.acquisition_us + det.decision_us + det.actuation_cmd_us) * 1e-6
                primary_release_time = trip_time + base_delay + supervisory_delay
                poison_start_time = trip_time + act.poison_start_ms * 1e-3
                if primary_fails:
                    backup_release_time = trip_time + 0.030

        # Actuation
        if primary_release_time and not primary_fails:
            worth_primary[i] = smooth_ramp(t[i], primary_release_time, act.primary_insert_ms * 1e-3, act.primary_max_mk)
        if backup_release_time:
            worth_backup[i] = smooth_ramp(t[i], backup_release_time, act.backup_insert_ms * 1e-3, act.backup_max_mk)
        if poison_start_time:
            worth_poison[i] = smooth_ramp(t[i], poison_start_time, act.poison_full_s, act.poison_max_mk)

    # Event flags (only if actually executed)
    event_flags = {
        "trip": trip_time,
        "primary_release": primary_release_time if not primary_fails else None,
        "backup_release": backup_release_time,
        "poison_start": poison_start_time
    }

    # Checks — now relative to trip_time
    checks = {}
    delay_us = supervisory_delay * 1e6
    checks["non_blocking"] = {"value_us": delay_us, "limit": det.non_blocking_cap_us, "pass": delay_us <= det.non_blocking_cap_us}

    if trip_time is not None:
        t20 = trip_time + 0.020
        t50 = trip_time + 0.050
        idx20 = np.argmin(np.abs(t - t20))
        idx50 = np.argmin(np.abs(t - t50))
    else:
        idx20 = idx50 = 0  # fallback

    wp20 = worth_primary[idx20]
    wp50 = worth_primary[idx50]
    primary_pass = wp20 >= worth.mk_20ms_primary and wp50 >= worth.mk_50ms_primary
    checks["primary_targets"] = {"20ms_mk": wp20, "50ms_mk": wp50, "pass": primary_pass if not primary_fails else "N/A (primary failed)"}

    backup_pass = "unneeded"
    if primary_fails:
        wb20 = worth_backup[idx20]
        wb50 = worth_backup[idx50]
        backup_pass = wb20 >= worth.mk_20ms_backup and wb50 >= worth.mk_50ms_backup
    checks["backup_targets"] = {"pass": backup_pass}

    # CSV
    csv_path = os.path.join(outdir, "timeseries.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time_s", "reactivity_mk", "power_norm", "worth_primary_mk", "worth_backup_mk", "worth_poison_mk"])
        for i in range(N):
            writer.writerow([t[i], rho[i]/core.mk, P[i], worth_primary[i], worth_backup[i], worth_poison[i]])

    # Reactivity plot (single legend)
    plt.figure(figsize=(10, 6))
    plt.plot(t, rho / core.mk, label="Net Reactivity")
    plt.plot(t, pos_rho / core.mk, '--', label="Inserted Positive")
    plt.plot(t, -(worth_primary + worth_backup + worth_poison), label="Inserted Negative Worth")
    plt.xlabel("Time (s)")
    plt.ylabel("Reactivity (mk)")
    plt.title("Reactivity vs Time")
    if trip_time: plt.axvline(trip_time, color='red', linestyle='--', label="Trip")
    if event_flags["primary_release"]: plt.axvline(event_flags["primary_release"], color='green', linestyle=':', label="Primary Release")
    if event_flags["backup_release"]: plt.axvline(event_flags["backup_release"], color='orange', linestyle=':', label="Backup Release")
    if poison_start_time: plt.axvline(poison_start_time, color='purple', linestyle='-.', label="Poison Start")
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "reactivity.png"), dpi=180)
    plt.close()

    # Power plot
    plt.figure(figsize=(10, 6))
    plt.plot(t, P, label="Power")
    plt.yscale('log')
    plt.xlabel("Time (s)")
    plt.ylabel("Normalized Power")
    plt.title("Power Excursion vs Time")
    if trip_time: plt.axvline(trip_time, color='red', linestyle='--')
    if event_flags["primary_release"]: plt.axvline(event_flags["primary_release"], color='green', linestyle=':')
    if event_flags["backup_release"]: plt.axvline(event_flags["backup_release"], color='orange', linestyle=':')
    if poison_start_time: plt.axvline(poison_start_time, color='purple', linestyle='-.')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "power.png"), dpi=180)
    plt.close()

    # JSON log
    log = {
        "params": {"core": asdict(core), "detection": asdict(det), "actuation": asdict(act), "scenario": asdict(scn), "targets": asdict(worth)},
        "runtime": {"seed": seed, "primary_fail_prob": act.primary_fail_prob, "supervisory_delay_us": delay_us},
        "events": event_flags,
        "checks": checks
    }
    with open(os.path.join(outdir, "sim_log.json"), "w") as f:
        json.dump(_to_jsonable(log), f, indent=2)

    summary = {
        "seed": seed,
        "scenario": args.scenario if 'args' in globals() else "unknown",
        "trip_time_s": event_flags["trip"],
        "primary_release_s": event_flags["primary_release"],
        "backup_release_s": event_flags["backup_release"],
        "poison_start_s": event_flags["poison_start"],
        "non_blocking_pass": checks["non_blocking"]["pass"],
        "primary_targets_pass": checks["primary_targets"]["pass"],
        "backup_pass_or_unneeded": checks["backup_targets"]["pass"]
    }

    return {"paths": {"csv": csv_path, "json": os.path.join(outdir, "sim_log.json"),
                      "reactivity": os.path.join(outdir, "reactivity.png"),
                      "power": os.path.join(outdir, "power.png")},
            "summary": summary}

# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="RIA Simulation Validator v0.7 (final)")
    parser.add_argument("--outdir", type=str, default="./out")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dt_us", type=float, default=50.0)
    parser.add_argument("--T_end_s", type=float, default=1.5)
    parser.add_argument("--scenario", type=str, choices=["rod_ejection", "cold_water"], default="rod_ejection")
    parser.add_argument("--primary-fail-prob", type=float, default=None, help="Override primary failure probability")
    parser.add_argument("--non-blocking-us", type=float, default=None, help="Fix supervisory delay in µs (for sweeps)")
    args = parser.parse_args()

    core = CoreParams()
    det = DetectionParams()
    act = ActuationParams()
    worth = WorthTargets()
    scn = Scenario(pos_step_dollars=1.2 if args.scenario == "rod_ejection" else 0.9,
                    t_insert_ms=2.0 if args.scenario == "rod_ejection" else 5.0)

    results = simulate(core, det, act, scn, worth,
                       dt_us=args.dt_us, T_end_s=args.T_end_s,
                       outdir=args.outdir, seed=args.seed,
                       primary_fail_prob=args.primary_fail_prob,
                       non_blocking_us=args.non_blocking_us)

    print("=== Simulation Summary ===")
    print(f"Seed: {results['summary']['seed']}")
    print(f"Scenario: {args.scenario}")
    for k, v in results["summary"].items():
        if k not in ["seed", "scenario"]:
            print(f"{k}: {v}")
    print("\nOutputs written to:", args.outdir)
    print("Files:", results["paths"])

if __name__ == "__main__":
    main()