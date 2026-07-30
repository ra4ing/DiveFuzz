# Copyright (c) 2024-2025 Institute of Information Engineering, Chinese Academy of Sciences
#
# DiveFuzz is licensed under Mulan PSL v2.
# You can use this software according to the terms and conditions of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
#          http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
#
# See the Mulan PSL v2 for more details.

"""Randomized stress / regression test for the DiveFuzz-MC generator.

The generator's only real failure mode is emitting a construct that herd7
refuses to model or that litmus7 / the cross-assembler refuse to compile
(see docs/ARCHITECTURE.md, "the only failure mode"). Randomization multiplies
the space of emitted constructs, so this script exercises it broadly: for every
test family it builds many randomized seeds (all axes on, noise levels mixed)
and pushes each through ``validate -> herd7 accepts -> litmus7 compiles``. A
sample is then run through the full ``spike + oracle`` closed loop.
A final Phase C drives the real ``generate_multicore_seeds`` pipeline to guard
the parallel-generation and herd-cache features (cache transparency, parallel
== serial determinism, parallel-build ELF safety).

It is a regression gate: exit code is 0 only if every seed validated, was
accepted by herd7, compiled, and (for the spike sample) classified SUCCESS.

Run inside the ``divefuzz-dev`` container, from the ``fuzzer/`` dir::

    python3 scripts/multicore_stress.py                 # 20 seeds/family + 1 spike/family
    python3 scripts/multicore_stress.py --seeds 50       # heavier
    python3 scripts/multicore_stress.py --no-spike       # fast: herd+compile only
    python3 scripts/multicore_stress.py --families SB,MP,AMO

Tool paths default to the container layout and can be overridden with the
``HERD7`` / ``LITMUS7`` / ``LITMUS7_SHARE`` / ``SPIKE`` environment variables.
"""

import argparse
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
# Make the parent `fuzzer/` package importable whether run as a file or module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generator.core.multicore.families import (
    available_families,
    build_program,
    family_hart_count,
)
from generator.core.multicore.litmus_exporter import export_litmus
from generator.core.multicore.outcome import parse_herd_states, parse_litmus_histogram
from generator.core.multicore.validator import validate
from generator.core.multicore.generate import (
    MultiCoreGenerationConfig,
    generate_multicore_seeds,
)
from generator.core.multicore.herd_oracle import HerdOracle
from generator.core.multicore.herd_cache import HerdCache
from executor.multicore.oracle import classify_outcomes

# Harness dir is <fuzzer>/multi-core/spike-litmus-harness, regardless of CWD.
HARNESS = Path(__file__).resolve().parent.parent / "multi-core" / "spike-litmus-harness"
HERD7 = os.environ.get("HERD7", "/home/ra4ing/.opam/default/bin/herd7")
LITMUS7 = os.environ.get("LITMUS7", "/home/ra4ing/.opam/default/bin/litmus7")
# riscv.cfg actually lives under the opam switch share, not the Makefile default.
LITMUS7_SHARE = os.environ.get(
    "LITMUS7_SHARE",
    "/home/ra4ing/.opam/ocaml-system.4.14.1/share/herdtools7/litmus",
)
SPIKE = os.environ.get("SPIKE", "/home/ra4ing/workspace/riscv/bin/spike")

NOISES = ["none", "L0", "L1"]


def herd_states(litmus_path: str) -> tuple[bool, str]:
    out = subprocess.run([HERD7, litmus_path], capture_output=True, text=True).stdout
    return ("States " in out), out


def compiles(name: str, litmus_path: str, avail: int) -> tuple[bool, str]:
    r = subprocess.run(
        ["make", "-C", str(HARNESS), "compile", f"LITMUS={litmus_path}",
         f"AVAIL={avail}", "NRUNS=20", "SIZE=20",
         f"LITMUS7={LITMUS7}", f"LITMUS7_SHARE={LITMUS7_SHARE}"],
        capture_output=True, text=True, timeout=180,
    )
    return (r.returncode == 0), (r.stdout + r.stderr)


def phase_a(families: list[str], n: int, outdir: Path, faillog: list[str]) -> dict:
    """validate -> herd accepts -> compiles, for ``n`` randomized seeds/family."""
    compiled = {}  # fam -> (seed, litmus_path, name)
    tot_ok = tot_hf = tot_cf = tot_vf = 0
    print(f"=== Phase A: {n} randomized seeds/family x {len(families)} families ===",
          flush=True)
    for fam in families:
        harts = family_hart_count(fam)
        ok = hf = cf = vf = 0
        last_good = None
        for seed in range(n):
            noise = NOISES[seed % len(NOISES)]
            rng = random.Random(seed * 131 + 7)
            try:
                prog = build_program(seed, fam, noise, rng, randomize=True)
                validate(prog)
            except Exception as e:  # generation/validator bug
                vf += 1
                faillog.append(f"[{fam}/s{seed}/{noise}] VALIDATE-FAIL: {type(e).__name__}: {e}")
                continue
            name = f"{fam}-{seed}"
            lp = outdir / f"{name}.litmus"
            lp.write_text(export_litmus(prog))
            has, out = herd_states(str(lp))
            if not has:
                hf += 1
                tail = [l for l in out.splitlines() if l.strip()][-1][:140]
                faillog.append(f"[{fam}/s{seed}/{noise}] HERD-FAIL: {tail}")
                continue
            ok_c, cout = compiles(name, str(lp), harts)
            if not ok_c:
                cf += 1
                tail = [l for l in cout.splitlines() if l.strip()][-1][:140]
                faillog.append(f"[{fam}/s{seed}/{noise}] COMPILE-FAIL: {tail}")
                continue
            ok += 1
            last_good = (seed, str(lp), name)
        compiled[fam] = last_good
        tot_ok += ok; tot_hf += hf; tot_cf += cf; tot_vf += vf
        print(f"{fam:8s} harts={harts}  ok={ok}/{n}  herd_fail={hf}  "
              f"compile_fail={cf}  validate_fail={vf}", flush=True)
    total = n * len(families)
    print(f"\nPhase A TOTAL: ok={tot_ok}/{total}  herd_fail={tot_hf}  "
          f"compile_fail={tot_cf}  validate_fail={tot_vf}", flush=True)
    return {"ok": tot_ok, "total": total, "herd": tot_hf,
            "compile": tot_cf, "validate": tot_vf, "compiled": compiled}


def phase_b(compiled: dict, spike_timeout: int) -> int:
    """Full spike + oracle closed loop on one compiled seed/family. Returns bad count."""
    print("\n=== Phase B: spike+oracle sample (1 compiled seed/family) ===", flush=True)
    bad = skip = ok = 0
    for fam, samp in compiled.items():
        if samp is None:
            print(f"{fam:8s} SKIP (no compiled seed)", flush=True)
            skip += 1
            continue
        seed, lp, name = samp
        harts = family_hart_count(fam)
        _, out = herd_states(lp)
        try:
            allowed = parse_herd_states(out)
        except Exception as e:
            print(f"{fam:8s} HERD-PARSE-FAIL {e}", flush=True)
            bad += 1
            continue
        elf = HARNESS / "build" / name / f"{name}.elf"
        r = subprocess.run(
            ["timeout", str(spike_timeout), SPIKE, f"-p{harts + 1}", str(elf)],
            capture_output=True, text=True,
        )
        try:
            observed = parse_litmus_histogram(r.stdout)
            rt, _ = classify_outcomes(allowed, observed)
            print(f"{fam:8s} {rt.name:16s} allowed={len(allowed)} "
                  f"observed={len(observed)} runs={sum(observed.values())}", flush=True)
            ok += 1 if rt.name == "SUCCESS" else 0
            bad += 0 if rt.name == "SUCCESS" else 1
        except Exception as e:
            print(f"{fam:8s} SPIKE-PARSE-FAIL {type(e).__name__}: {e}", flush=True)
            bad += 1
    print(f"\nPhase B TOTAL: SUCCESS={ok}  non-SUCCESS/parse-fail={bad}  skipped={skip}",
          flush=True)
    return bad


def phase_c(families: list[str], faillog: list[str]) -> int:
    """Guard the acceleration features via the real generation pipeline.

    Phase A/B exercise ``build_program`` plus raw herd/make; this phase drives
    ``generate_multicore_seeds`` / ``HerdOracle`` / ``HerdCache`` /
    ``LitmusExecutableBackend`` directly:
      C1 cache transparency -- fresh solve == cached miss == cached hit;
      C2 parallel == serial  -- parallel dispatch yields byte-identical artifacts;
      C3 parallel build      -- every seed gets a non-empty ELF (guards the unique
                                per-call build dir that prevents parallel clobbering).
    """
    print("\n=== Phase C: pipeline (cache transparency + parallel determinism + build) ===",
          flush=True)
    bad = 0
    base = Path(tempfile.mkdtemp(prefix="dfmc_stressC_"))
    fam3 = families[:3] or families

    # C1. cache transparency: fresh solve == cached miss == cached hit.
    pre = bad
    cache_dir = base / "herd_cache"
    fresh = HerdOracle(HERD7, cache=None)
    cached = HerdOracle(HERD7, cache=HerdCache(cache_dir))
    for fam in fam3:
        rng = random.Random(424242)
        prog = build_program(0, fam, "none", rng, randomize=True)
        validate(prog)
        lp = base / f"ct_{fam}.litmus"
        lp.write_text(export_litmus(prog))
        try:
            a0 = fresh.allowed_outcomes(str(lp)).allowed
            a1 = cached.allowed_outcomes(str(lp)).allowed   # miss -> solve -> store
            a2 = cached.allowed_outcomes(str(lp)).allowed   # hit  -> served
        except Exception as e:
            faillog.append(f"[{fam}] C1 herd error: {type(e).__name__}: {e}")
            bad += 1
            continue
        if not (a0 == a1 == a2):
            faillog.append(f"[{fam}] C1 cache NOT transparent (fresh/cached/hit differ)")
            bad += 1
    print(f"C1 cache transparency: {'OK' if bad == pre else 'FAIL'}", flush=True)

    # C2. parallel == serial determinism (herd-only, cache off).
    pre = bad
    common = dict(
        seed_offset=0, test_families=fam3, noise_level="none", herd_path=HERD7,
        litmus_harness_dir=str(HARNESS), litmus7_path=LITMUS7,
        litmus7_share=LITMUS7_SHARE, litmus_runs=20, litmus_size=20,
        build_executable=False, randomize=True, use_herd_cache=False,
    )
    n = 6
    try:
        bs = generate_multicore_seeds(
            MultiCoreGenerationConfig(seeds_output=str(base / "serial"), seeds_num=n,
                                      gen_workers=1, **common))
        bp = generate_multicore_seeds(
            MultiCoreGenerationConfig(seeds_output=str(base / "par"), seeds_num=n,
                                      gen_workers=min(4, n), **common))
    except Exception as e:
        faillog.append(f"C2 generate error: {type(e).__name__}: {e}")
        bad += 1
        bs = bp = []
    for s, p in zip(bs, bp):
        if (Path(s.litmus_path).read_text() != Path(p.litmus_path).read_text()
                or Path(s.allowed_path).read_text() != Path(p.allowed_path).read_text()):
            faillog.append(f"[seed {s.seed_id}] C2 artifact differs serial vs parallel")
            bad += 1
    print(f"C2 parallel==serial: {'OK' if bad == pre else 'FAIL'}", flush=True)

    # C3. parallel build safety: every seed must yield a non-empty ELF (guards
    # the per-call unique build dir; without it parallel builds clobber in
    # build/seed/).
    pre = bad
    try:
        generate_multicore_seeds(
            MultiCoreGenerationConfig(
                seeds_output=str(base / "pbuild"), seeds_num=4, gen_workers=3,
                build_executable=True, randomize=False, use_herd_cache=False,
                seed_offset=0, test_families=fam3, noise_level="none", herd_path=HERD7,
                litmus_harness_dir=str(HARNESS), litmus7_path=LITMUS7,
                litmus7_share=LITMUS7_SHARE, litmus_runs=20, litmus_size=20))
    except Exception as e:
        faillog.append(f"C3 parallel build error: {type(e).__name__}: {e}")
        bad += 1
    else:
        for b in sorted((base / "pbuild").glob("seed_*")):
            elf = b / "seed.elf"
            if not elf.exists() or elf.stat().st_size == 0:
                faillog.append(f"[{b.name}] C3 missing/empty ELF after parallel build")
                bad += 1
    print(f"C3 parallel build: {'OK' if bad == pre else 'FAIL'}", flush=True)

    shutil.rmtree(base, ignore_errors=True)
    return bad

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=20, help="randomized seeds per family (Phase A)")
    ap.add_argument("--families", default="", help="comma-separated subset (default: all)")
    ap.add_argument("--no-spike", action="store_true", help="skip the spike+oracle sample")
    ap.add_argument("--spike-timeout", type=int, default=20, help="per-seed spike timeout (s)")
    args = ap.parse_args()

    families = (args.families.split(",") if args.families else available_families())
    outdir = Path("/tmp/dfmc_stress")
    outdir.mkdir(parents=True, exist_ok=True)
    faillog: list[str] = []

    a = phase_a(families, args.seeds, outdir, faillog)
    if faillog:
        print(f"--- failures ({len(faillog)}, first 15) ---", flush=True)
        for line in faillog[:15]:
            print("  " + line, flush=True)

    bad = 0
    if not args.no_spike:
        bad = phase_b(a["compiled"], args.spike_timeout)

    c_bad = phase_c(families, faillog)

    # Clean the harness build dir (this script's own compile output).
    subprocess.run(["make", "-C", str(HARNESS), "clean"],
                   capture_output=True, text=True, timeout=60)

    a_fail = a["herd"] + a["compile"] + a["validate"]
    if a_fail == 0 and bad == 0 and c_bad == 0:
        print("\nALL GOOD", flush=True)
        return 0
    print(f"\nISSUES FOUND (Phase A failures={a_fail}, Phase B non-SUCCESS={bad}, Phase C={c_bad})", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
