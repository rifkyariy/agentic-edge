#!/usr/bin/env python3
"""Build T0: the Bitter Lesson's BFCL v4 main subset, rebuilt (plan §5.1).

The paper (arXiv 2608.06370, Table 6) gives per-category counts but never
released its entry IDs, so this samples the same counts from BFCL v4 with a
fixed seed. live_parallel holds only 16 entries, fewer than the paper's 24,
so it is taken whole: 301 tasks, not 309.

    python3 build_t0.py <bfcl_eval/data dir> [--seed 0]

Writes tasks/t0.jsonl (one task per line, tools already in OpenAI form) and
tasks/t0.meta.json (source version, file hashes, seed, counts).
"""
import argparse, copy, hashlib, json, random, re, sys
from pathlib import Path

COUNTS = {  # paper Table 6
    "simple_python": 40, "multiple": 20, "parallel": 40, "parallel_multiple": 40,
    "live_simple": 25, "live_multiple": 96, "live_parallel": 24, "live_parallel_multiple": 24,
}
# bfcl_eval/constants/type_mappings.py GORILLA_TO_OPENAPI, the types BFCL v4 uses
TYPES = {"dict": "object", "float": "number", "tuple": "array", "any": "string",
         "integer": "integer", "string": "string", "boolean": "boolean", "array": "array"}


def to_openai(schema):
    """BFCL's convert_to_tool, recursively: map types, note floats as BFCL does."""
    if isinstance(schema, list):
        return [to_openai(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: to_openai(v) for k, v in schema.items()}
    t = schema.get("type")
    if isinstance(t, str):
        out["type"] = TYPES.get(t, "string")
        if t == "float":
            out["description"] = out.get("description", "") + " This is a float type value."
    return out


def tool(fn):
    fn = copy.deepcopy(fn)
    params = to_openai(fn["parameters"])
    params["type"] = "object"
    # OpenAI-style names allow no "."; BFCL replaces it with "_" too
    return {"type": "function", "function": {
        "name": re.sub(r"\.", "_", fn["name"]), "description": fn.get("description", ""),
        "parameters": params}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out = Path(__file__).parent / "tasks"
    out.mkdir(exist_ok=True)
    meta = {"source": "bfcl-eval (PyPI) data/", "seed": a.seed, "files": {}, "counts": {}}
    version = next(a.data.parent.parent.glob("bfcl_eval-*.dist-info"), None)
    meta["source_version"] = version.name if version else "unknown"
    tasks = []
    for cat, n in COUNTS.items():
        q_path = a.data / f"BFCL_v4_{cat}.json"
        a_path = a.data / "possible_answer" / f"BFCL_v4_{cat}.json"
        for p in (q_path, a_path):
            meta["files"][str(p.relative_to(a.data))] = hashlib.sha256(p.read_bytes()).hexdigest()
        answers = {e["id"]: e["ground_truth"] for e in map(json.loads, a_path.open())}
        entries = [json.loads(l) for l in q_path.open()]
        # a per-category RNG, so changing one category's count never reshuffles another
        picked = random.Random(f"{a.seed}:{cat}").sample(entries, min(n, len(entries)))
        meta["counts"][cat] = {"paper": n, "taken": len(picked), "available": len(entries)}
        for e in sorted(picked, key=lambda e: entries.index(e)):
            tools = [tool(f) for f in e["function"]]
            tasks.append({
                "id": e["id"], "category": cat, "messages": e["question"][0], "tools": tools,
                "names": {t["function"]["name"]: f["name"] for t, f in zip(tools, e["function"])},
                "ground_truth": answers[e["id"]]})
    meta["total"] = len(tasks)
    with (out / "t0.jsonl").open("w") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    (out / "t0.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{len(tasks)} tasks -> {out / 't0.jsonl'}", file=sys.stderr)


if __name__ == "__main__":
    main()
