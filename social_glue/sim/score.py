"""score(episode): value-weighted accuracy of a confusion matrix over (activity, week) decisions.

For each activity and each 7-day window:
- TP: we proposed it, the group took it, and it was rated at or above the success cutoff (default 7/10)
- FP: we proposed it and it wasn't a success. Each FP carries a reason:
      activity (wrong kind of hangout), timing (wrong day / too soon), specifics (wrong event/place/price),
      ignored (nobody answered), low_rating (it happened but was rated below the cutoff)
- FN: the group wanted it (hidden appetite >= 0.5), it wasn't done recently enough, and we didn't offer it.
      Each FN carries a reason from the bot's own timer log for that window:
      unexplored (belief low, never probed), misread (belief low despite probing),
      nudge_budget / waiting_for_quiet / no_availability (wanted to propose but was blocked),
      not_due (belief high but no candidate cleared the bar), recent_meetup (recency penalty kept it quiet)
- TN: we didn't offer it and they didn't want it
Probes are exploration (how FNs get found); they count only as messages.
score = (w * (TP - FN) + (1 - w) * (TN - FP)) / decisions
using this group's TRUE w (hidden in the group JSON, defaults in agents/values.py). The bot only ever sees its
own estimate of it in brain/values.md.
"""
from collections import Counter
from datetime import datetime

from social_glue.agents.interests import DEFAULT_CADENCE
from social_glue.agents.tracker import PLANS
from social_glue.agents.values import normalize


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

WINDOW = 7


def appetite_at(group: dict, activity: str, day: int) -> float:
    level = group["appetite"][activity]
    d = group.get("drift", {}).get(activity)
    return d[1] if d and day >= d[0] else level


def score(episode: dict) -> dict:
    g, days = episode["group"], episode["days"]
    start = datetime.fromisoformat(episode["start"])
    day_of = lambda ts: (datetime.fromisoformat(ts) - start).days  # noqa: E731
    proposals = [b for b in episode["bot_messages"] if b["kind"] in PLANS and b.get("activity")]
    probes = [b for b in episode["bot_messages"] if b["kind"] == "probe"]

    cut = g.get("success_cutoff", 7)
    rating = lambda b: sum(b["ratings"].values()) / len(b["ratings"]) if b.get("ratings") else None  # noqa: E731
    success = lambda b: bool(b.get("confirmed")) and (rating(b) or 0) >= cut  # noqa: E731
    tp = sum(1 for b in proposals if success(b))
    fp_reasons = Counter(
        "low_rating" if b.get("confirmed") else Counter(b.get("reasons") or ["ignored"]).most_common(1)[0][0]
        for b in proposals if not success(b))
    # Calibration: how good were the bot's own estimates? (Brier score on success; lower is better)
    est = [(b["estimate"]["p_success"], 1.0 if success(b) else 0.0) for b in proposals if b.get("estimate")]
    brier = round(sum((p - y) ** 2 for p, y in est) / len(est), 3) if est else None
    rated = [rating(b) for b in proposals if rating(b) is not None]
    fp = sum(fp_reasons.values())
    fn = tn = 0
    fn_reasons = Counter()
    done_days = {a: [day_of(b["ts"]) for b in proposals if b["activity"] == a and success(b)] for a in g["appetite"]}
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
    total = tp + fp + fn + tn
    accuracy = (tp + tn) / total if total else 1.0
    messages = len(episode["bot_messages"])
    w = normalize(g.get("values", {}))["w"]
    usage = episode["usage"]
    return {
        "score": round((w * (tp - fn) + (1 - w) * (tn - fp)) / max(total, 1), 3),
        "accuracy": round(accuracy, 3), "f1": round(f1, 3),
        "precision": round(precision, 3), "recall": round(recall, 3),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn, "fp_reasons": dict(fp_reasons), "fn_reasons": dict(fn_reasons),
        "probes": len(probes), "messages": messages,
        "avg_rating": round(sum(rated) / len(rated), 1) if rated else None, "brier": brier,
        "cost": round(usage["prompt_tokens"] / max(usage["calls"], 1), 1),
    }
