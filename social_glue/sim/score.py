"""score(episode): a confusion matrix over (activity, week) decisions, plus annoyance.

For each activity and each 7-day window:
- TP: we proposed it and the group took it (confirmed)
- FP: we proposed it and it wasn't taken. Each FP carries a reason from the replies:
      activity (wrong kind of hangout), timing (wrong day / too soon), specifics (wrong event/place/price)
- FN: the group wanted it (hidden appetite >= 0.5), it wasn't done recently enough, and we didn't offer it.
      Each FN carries a reason from the bot's own timer log for that window:
      unexplored (belief low, never probed), misread (belief low despite probing),
      nudge_budget / waiting_for_quiet / no_availability (wanted to propose but was blocked),
      not_due (belief high but cadence said not yet)
- TN: we didn't offer it and they didn't want it
Probes are exploration (how FNs get found) and are counted separately; they cost only through annoyance.
score = F1 - 0.1 * annoyance
"""
from collections import Counter
from datetime import datetime

from social_glue.agents.interests import DEFAULT_CADENCE


def fn_reason(activity: str, window_days: range, decisions: list[dict], probes: list[dict], day_of) -> str:
    ticks = [d for d in decisions if day_of(d["ts"]) in window_days]
    blocked = [d["blocked"] for d in ticks if d["choice"] == ("propose", activity) and d["blocked"]]
    if blocked:
        return max(set(blocked), key=blocked.count)
    believed_low = all(d["levels"][activity] < 0.35 for d in ticks) if ticks else True
    if believed_low:
        probed = any(p["activity"] == activity and day_of(p["ts"]) <= window_days[-1] for p in probes)
        return "misread" if probed else "unexplored"
    return "not_due"

W_ANNOY = 0.1
WINDOW = 7


def appetite_at(group: dict, activity: str, day: int) -> float:
    level = group["appetite"][activity]
    d = group.get("drift", {}).get(activity)
    return d[1] if d and day >= d[0] else level


def score(episode: dict) -> dict:
    g, days = episode["group"], episode["days"]
    start = datetime.fromisoformat(episode["start"])
    day_of = lambda ts: (datetime.fromisoformat(ts) - start).days  # noqa: E731
    proposals = [b for b in episode["bot_messages"] if b["kind"] == "propose" and b.get("activity")]
    probes = [b for b in episode["bot_messages"] if b["kind"] == "probe"]

    tp = sum(1 for b in proposals if b.get("confirmed"))
    fp_reasons = Counter(Counter(b.get("reasons") or ["ignored"]).most_common(1)[0][0] for b in proposals if not b.get("confirmed"))
    fp = sum(fp_reasons.values())
    fn = tn = 0
    fn_reasons = Counter()
    done_days = {a: [day_of(m["ts"]) for m in episode["meetups"] if m["activity"] == a] for a in g["appetite"]}
    for a in g["appetite"]:
        for w0 in range(0, days, WINDOW):
            w = range(w0, min(w0 + WINDOW, days))
            offered = any(b["activity"] == a and day_of(b["ts"]) in w for b in proposals)
            wanted = sum(appetite_at(g, a, d) for d in w) / len(w) >= 0.5
            recent = any(w0 - DEFAULT_CADENCE[a] < d < w0 + WINDOW for d in done_days[a])
            if not offered and wanted and not recent:
                fn += 1
                fn_reasons[fn_reason(a, w, episode.get("decisions", []), probes, day_of)] += 1
            elif not offered and not wanted:
                tn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    annoyance = sum(1 for r in episode["reactions"] if r == "annoyed") + 2 * sum(1 for r in episode["reactions"] if r == "muted")
    usage = episode["usage"]
    return {
        "score": round(f1 - W_ANNOY * annoyance, 3), "f1": round(f1, 3),
        "precision": round(precision, 3), "recall": round(recall, 3),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "fp_reasons": dict(fp_reasons), "fn_reasons": dict(fn_reasons),
        "probes": len(probes), "annoyance": annoyance,
        "cost": round(usage["prompt_tokens"] / max(usage["calls"], 1), 1),
    }
