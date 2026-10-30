#!/usr/bin/env python3
"""Build T1: the Bitter Lesson's chaining and fan-out subsets, rebuilt (plan §5.1).

The paper (arXiv 2608.06370 §3.4) released neither set and describes them
only loosely, so both are generated here from a fixed seed:

* chain (52): one running quantity changed step by step; each call takes the
  value just before its step, which the model must work out itself because
  the stubs only echo their arguments (the paper's design, §3.2). Lengths
  2–20, matching the only counts the paper gives: 17 tasks of length >= 6,
  10 of length >= 13. Integer arithmetic only, so exact scoring is fair.
  JSON runs these as a multi-turn loop (run.py), as the paper does.
* fanout (32): one request that needs N calls, N in the paper's sizes
  7, 9, 11, 13, 15, 20, 30, 48, four tasks per size (one per template).
  Invented entity names, so nothing can be answered from memory.

    python3 build_t1.py [--seed 0]

Writes tasks/t1.jsonl (same shape as t0.jsonl, plus "n" and "multi_turn"),
tasks/t1.meta.json, and tasks/t1-pilot.jsonl: 19 of those tasks spread over
every chain length band and fan-out size, for the M4 pilot (TIER=t1-pilot).
"""
import argparse, hashlib, json, random, sys
from collections import Counter
from pathlib import Path

CHAIN_LENGTHS = [2] * 9 + [3] * 9 + [4] * 9 + [5] * 8 + list(range(6, 13)) + list(range(13, 21)) + [15, 20]
FANOUT_SIZES = [7, 9, 11, 13, 15, 20, 30, 48]
SYL = ["ka", "lo", "mir", "ven", "tor", "sa", "bel", "quo", "dri", "nax", "pel", "zor", "ith", "mu",
       "ran", "kel", "os", "vey", "tam", "bri", "gul", "fen", "ar", "dun"]


def fn(name, desc, props, required=None):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required or list(props)}}}


def word(rng, k=2):
    return "".join(rng.choice(SYL) for _ in range(k)).capitalize()


def distinct(rng, n, make):
    out = []
    while len(out) < n:
        if (x := make(rng)) not in out:
            out.append(x)
    return out


# --- chains: domain -> state parameter, its description, intro, closing rule, ops
# an op: tool name, tool description, amount parameter, its description, step phrase, kind
CHAINS = {
    "bank": ("balance", "The account balance in dollars just before this transaction.",
             "My checking account balance is ${start}. Process these transactions in order with the tools: ",
             "Each call takes the balance just before that transaction.", [
                 ("deposit", "Deposit money into the checking account.", "amount", "Dollars to deposit.", "deposit ${a}", "+"),
                 ("withdraw", "Withdraw money from the checking account.", "amount", "Dollars to withdraw.", "withdraw ${a}", "-")]),
    "warehouse": ("stock", "Units in the bin just before this stock movement.",
                  "Warehouse bin A7 holds {start} units. Record these stock movements in order with the tools: ",
                  "Each call takes the stock level just before that movement.", [
                      ("receive_shipment", "Record units received into a warehouse bin.", "units", "Units received.", "receive {a} units", "+"),
                      ("ship_order", "Record units shipped out of a warehouse bin.", "units", "Units shipped.", "ship {a} units", "-")]),
    "game": ("score", "The player's score just before this step.",
             "A player's score is {start}. Apply these in order with the tools: ",
             "Each call takes the score just before that step.", [
                 ("add_points", "Add points to a player's score.", "points", "Points to add.", "add {a} points", "+"),
                 ("deduct_points", "Deduct points from a player's score.", "points", "Points to deduct.", "deduct {a} points", "-"),
                 ("apply_multiplier", "Multiply a player's score by a bonus multiplier.", "multiplier", "Whole-number multiplier.", "apply a {a}x multiplier", "*")]),
    "garage": ("occupied", "Cars parked just before this event.",
               "The garage has {start} cars parked. Log these events in order with the tools: ",
               "Each call takes the number of cars parked just before that event.", [
                   ("log_arrivals", "Log cars entering the garage.", "cars", "Cars that arrived.", "{a} cars arrive", "+"),
                   ("log_departures", "Log cars leaving the garage.", "cars", "Cars that left.", "{a} cars leave", "-")]),
}


def chain_task(i, length, rng):
    domain = list(CHAINS)[i % len(CHAINS)]
    state, state_desc, intro, rule, ops = CHAINS[domain]
    cap = 40 if domain == "garage" else 200  # a garage gains tens of cars, not hundreds
    x = start = rng.randrange(cap // 2, cap * 5)
    steps, truth = [], []
    for _ in range(length):
        name, _, amt, _, phrase, kind = rng.choice([o for o in ops if o[5] != "*" or x <= 1000])
        if kind == "-" and x <= 1:
            name, _, amt, _, phrase, kind = next(o for o in ops if o[5] == "+")
        a = rng.randrange(2, 4) if kind == "*" else rng.randrange(1, min(cap, x - 1 if kind == "-" else cap) + 1)
        steps.append(phrase.format(a=a))
        truth.append({name: {state: [x], amt: [a]}})
        x = x + a if kind == "+" else x - a if kind == "-" else x * a
    tools = [fn(n, d, {state: {"type": "integer", "description": state_desc},
                       am: {"type": "integer", "description": ad}}) for n, d, am, ad, _, _ in ops]
    content = intro.format(start=start) + ", then ".join(steps) + ". " + rule
    return {"id": f"chain_{i:02d}", "category": "chain", "n": length, "multi_turn": True,
            "messages": [{"role": "user", "content": content}], "tools": tools,
            "names": {t["function"]["name"]: t["function"]["name"] for t in tools}, "ground_truth": truth}


# --- fan-out: template -> tool, prompt, one item per call
def country(rng):
    return word(rng) + rng.choice(["ia", "stan", "land", "ora"])


def person(rng):
    return f"{word(rng)} {word(rng)}"


def sku(rng):
    return f"{rng.choice('ABCDEFGHJKLMNPRSTVXZ')}{rng.choice('ABCDEFGHJKLMNPRSTVXZ')}-{rng.randrange(1000, 10000)}"


FANOUT = [
    (fn("get_population", "Look up the current population of a country.",
        {"country": {"type": "string", "description": "Country name."}}),
     lambda rng, items: (f"Look up the current population of each of these countries: {', '.join(items)}.", {}),
     country, "country"),
    (fn("send_reminder", "Send a meeting reminder to one person.",
        {"recipient": {"type": "string", "description": "Full name of the person to remind."},
         "date": {"type": "string", "description": "Meeting date, YYYY-MM-DD."}}),
     lambda rng, items: (lambda d: (f"Send a reminder about the meeting on {d} to each of these people: {', '.join(items)}.",
                                    {"date": [d]}))(f"2026-11-{rng.randrange(1, 29):02d}"),
     person, "recipient"),
    (fn("check_stock", "Check how many units of a product a warehouse holds.",
        {"sku": {"type": "string", "description": "Product code."},
         "warehouse": {"type": "string", "description": "Warehouse name."}}),
     lambda rng, items: (lambda w: (f"Check the stock at the {w} warehouse for each of these product codes: {', '.join(items)}.",
                                    {"warehouse": [w]}))(word(rng)),
     sku, "sku"),
    (fn("convert_currency", "Convert an amount of money from one currency to another.",
        {"amount": {"type": "integer", "description": "Amount to convert."},
         "from_currency": {"type": "string", "description": "ISO code of the source currency."},
         "to_currency": {"type": "string", "description": "ISO code of the target currency."}}),
     lambda rng, items: (f"Convert each of these invoice amounts from EUR to USD: {', '.join(map(str, items))}.",
                         {"from_currency": ["EUR"], "to_currency": ["USD"]}),
     lambda rng: rng.randrange(20, 5000), "amount"),
]


def fanout_task(i, size, rng):
    tool, prompt, item, key = FANOUT[i % len(FANOUT)]
    items = distinct(rng, size, item)
    content, fixed = prompt(rng, items)
    name = tool["function"]["name"]
    return {"id": f"fanout_{i:02d}", "category": "fanout", "n": size, "multi_turn": False,
            "messages": [{"role": "user", "content": content}], "tools": [tool], "names": {name: name},
            "ground_truth": [{name: {key: [x], **fixed}} for x in items]}


def build(seed=0):
    # a per-task RNG, so changing one task never reshuffles another
    chains = [chain_task(i, n, random.Random(f"{seed}:chain:{i}")) for i, n in enumerate(CHAIN_LENGTHS)]
    fans = [fanout_task(i, n, random.Random(f"{seed}:fanout:{i}"))
            for i, n in enumerate(s for s in FANOUT_SIZES for _ in FANOUT)]
    return chains + fans


def pilot(tasks):
    """Every 5th chain from the second (lengths 2..20) and one fan-out per size, rotating the templates."""
    chains = [t for t in tasks if t["category"] == "chain"]
    fans = [t for t in tasks if t["category"] == "fanout"]
    k = len(FANOUT)
    return chains[1::5] + [fans[i * k + i % k] for i in range(len(fans) // k)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = Path(__file__).parent / "tasks"
    tasks = build(a.seed)
    for name, ts in (("t1", tasks), ("t1-pilot", pilot(tasks))):
        with (out / f"{name}.jsonl").open("w") as f:
            for t in ts:
                f.write(json.dumps(t) + "\n")
    meta = {"generator": "build_t1.py", "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "seed": a.seed, "total": len(tasks),
            "chain_lengths": dict(sorted(Counter(t["n"] for t in tasks if t["category"] == "chain").items())),
            "fanout_sizes": dict(sorted(Counter(t["n"] for t in tasks if t["category"] == "fanout").items()))}
    (out / "t1.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{len(tasks)} tasks -> {out / 't1.jsonl'}", file=sys.stderr)


if __name__ == "__main__":
    main()
