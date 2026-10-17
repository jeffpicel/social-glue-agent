"""Version N+1 loop: run train group(s), reflect, keep the new playbook only if train score improves,
then report before/after on held-out groups next to a no-brain baseline.

python -m social_glue.evolve --rounds 2
"""
import argparse
import json
from pathlib import Path

from social_glue.brain import DEFAULT_PLAYBOOK
from social_glue.agents.reflector import reflect
from social_glue.sim.run import load_group, run_episode

TRAIN = ["train_1"]
HELDOUT = ["heldout_1", "heldout_2"]


def mean_scores(groups, **kw) -> dict:
    eps = [run_episode(load_group(g), verbose=False, **kw) for g in groups]
    keys = eps[0]["score"].keys()
    return {k: round(sum(e["score"][k] for e in eps) / len(eps), 3) for k in keys}, eps


def main(rounds: int, seed: int):
    playbook = DEFAULT_PLAYBOOK
    best, eps = mean_scores(TRAIN, playbook=playbook, seed=seed)
    print(f"v0 train: {best}")
    for r in range(1, rounds + 1):
        candidate = reflect(eps[0])
        s, cand_eps = mean_scores(TRAIN, playbook=candidate, seed=seed)
        kept = s["score"] > best["score"]
        print(f"v{r} train: {s}  -> {'KEPT' if kept else 'rejected'}")
        if kept:
            playbook, best, eps = candidate, s, cand_eps

    rows = {
        "no brain, playbook v0": mean_scores(HELDOUT, playbook=DEFAULT_PLAYBOOK, use_brain=False, seed=seed)[0],
        "brain, playbook v0": mean_scores(HELDOUT, playbook=DEFAULT_PLAYBOOK, seed=seed)[0],
        "brain, playbook vN": mean_scores(HELDOUT, playbook=playbook, seed=seed)[0],
    }
    out = Path("results")
    out.mkdir(exist_ok=True)
    (out / "playbook_vN.md").write_text(playbook)
    (out / "heldout.json").write_text(json.dumps(rows, indent=2))
    lines = ["| setup (held-out groups) | plan_quality | meetups | annoyance | tokens/call | score |", "|---|---|---|---|---|---|"]
    lines += [f"| {k} | {v['plan_quality']} | {v['meetups']} | {v['annoyance']} | {v['cost']} | {v['score']} |" for k, v in rows.items()]
    table = "\n".join(lines)
    (out / "heldout.md").write_text(table + "\n")
    print("\n" + table)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    main(a.rounds, a.seed)
