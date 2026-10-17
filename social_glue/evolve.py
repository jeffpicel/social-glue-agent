"""Version N+1 loop, per group: the group's playbook improves from its own history.

For one friend group:
  1. run the current playbook on training seeds (simulated weeks it learns from)
  2. reflector proposes an edit; keep it only if the training score improves
  3. report v0 vs vN on fresh seeds it never saw (new chats, same group, including its drift)

python -m social_glue.evolve --group train_1 --rounds 3
python -m social_glue.evolve --all
"""
import argparse
import json
from pathlib import Path

from social_glue.agents.reflector import reflect
from social_glue.brain import DEFAULT_PLAYBOOK
from social_glue.sim.run import GROUPS, load_group, run_episode

TRAIN_SEEDS = [0, 1]
EVAL_SEEDS = [100, 101, 102]
SHOW = ["score", "accuracy", "tp", "fp", "fn", "tn", "precision", "recall", "messages", "probes", "cost"]


def evaluate(group: dict, playbook: str, seeds: list[int], **kw) -> tuple[dict, list[dict]]:
    eps = [run_episode(group, playbook=playbook, seed=s, verbose=False, **kw) for s in seeds]
    avg = {k: round(sum(e["score"][k] for e in eps) / len(eps), 3) for k in SHOW}
    for k in ("fp_reasons", "fn_reasons"):
        merged = {}
        for e in eps:
            for r, n in e["score"][k].items():
                merged[r] = merged.get(r, 0) + n
        avg[k] = merged
    return avg, eps


def evolve(gid: str, rounds: int) -> dict:
    group = load_group(gid)
    playbook = DEFAULT_PLAYBOOK
    best, eps = evaluate(group, playbook, TRAIN_SEEDS)
    print(f"[{gid}] v0 train: {best}")
    for r in range(1, rounds + 1):
        worst = min(eps, key=lambda e: e["score"]["score"])
        candidate = reflect(worst)
        s, cand_eps = evaluate(group, candidate, TRAIN_SEEDS)
        kept = s["score"] > best["score"]
        print(f"[{gid}] v{r} train: {s}  -> {'KEPT' if kept else 'rejected'}")
        if kept:
            playbook, best, eps = candidate, s, cand_eps
    rows = {"v0": evaluate(group, DEFAULT_PLAYBOOK, EVAL_SEEDS)[0], "vN": evaluate(group, playbook, EVAL_SEEDS)[0]}
    out = Path("results") / gid
    out.mkdir(parents=True, exist_ok=True)
    (out / "playbook_vN.md").write_text(playbook)
    (out / "unseen.json").write_text(json.dumps(rows, indent=2))
    return rows


def table(results: dict) -> str:
    fmt = lambda d: ", ".join(f"{k} {n}" for k, n in sorted(d.items(), key=lambda x: -x[1])) or "-"  # noqa: E731
    lines = ["| group | playbook | " + " | ".join(SHOW) + " | FP why | FN why |", "|" + "---|" * (len(SHOW) + 4)]
    for gid, rows in results.items():
        for name, v in rows.items():
            lines.append(f"| {gid} | {name} | " + " | ".join(str(v[k]) for k in SHOW) + f" | {fmt(v['fp_reasons'])} | {fmt(v['fn_reasons'])} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="train_1")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    gids = sorted(p.stem for p in GROUPS.glob("*.json")) if a.all else [a.group]
    results = {g: evolve(g, a.rounds) for g in gids}
    t = table(results)
    Path("results").mkdir(exist_ok=True)
    (Path("results") / "unseen.md").write_text("Scores on unseen simulated runs (fresh seeds) of each group.\n\n" + t + "\n")
    print("\n" + t)
