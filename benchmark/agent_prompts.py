#!/usr/bin/env python3
"""Build the agent-shaped prompt sets for the CoPR replay and exactness checks.

    bfcl   BFCL v4 simple_python + multiple, first N of each, rendered with
           BFCL's own prompt-mode system prompt (bfcl_eval, the Pi's
           ~/Research/bfcl-venv); each row also carries a reference reply
           built from the first acceptable value of its ground truth, in the
           [func(arg=value, ...)] format that prompt asks for.
    ifeval google/IFEval, first N prompts, a single user turn as lm-eval's
           ifeval task sends it (needs `datasets`: the eval venv).

    ~/Research/bfcl-venv/bin/python agent_prompts.py bfcl 100 > prompts_bfcl.jsonl
    ~/Research/eval-venv/bin/python agent_prompts.py ifeval 100 > prompts_ifeval.jsonl

One JSON object per line: id, category, messages, max_tokens, stop[, reference].
"""
import json
import sys


def bfcl(n):
    import os
    import bfcl_eval
    from bfcl_eval.model_handler.utils import system_prompt_pre_processing_chat_model
    data = os.path.join(os.path.dirname(bfcl_eval.__file__), "data")

    def call(name, args):   # first acceptable value of each argument; "" means "omit"
        kv = ["%s=%r" % (k, v[0]) for k, v in args.items() if v and v[0] != ""]
        return "%s(%s)" % (name, ", ".join(kv))

    for cat in ("simple_python", "multiple"):
        with open(os.path.join(data, "BFCL_v4_%s.json" % cat)) as f:
            rows = [json.loads(line) for line in f][:n]
        with open(os.path.join(data, "possible_answer", "BFCL_v4_%s.json" % cat)) as f:
            truth = {r["id"]: r["ground_truth"] for r in map(json.loads, f)}
        for r in rows:
            msgs = system_prompt_pre_processing_chat_model([dict(m) for m in r["question"][0]],
                                                           r["function"], r["id"])
            ref = "[" + ", ".join(call(name, args) for g in truth[r["id"]] for name, args in g.items()) + "]"
            print(json.dumps({"id": r["id"], "category": "bfcl_" + cat, "messages": msgs,
                              "max_tokens": 512, "stop": [], "reference": ref}))


def ifeval(n):
    from datasets import load_dataset
    ds = load_dataset("google/IFEval", split="train")
    for i, r in enumerate(ds):
        if i >= n:
            break
        # lm-eval's ifeval task: the prompt as one user turn, max_gen_toks 1280, no stop
        print(json.dumps({"id": "ifeval_%d" % r["key"], "category": "ifeval",
                          "messages": [{"role": "user", "content": r["prompt"]}],
                          "max_tokens": 1280, "stop": []}))


if __name__ == "__main__":
    {"bfcl": bfcl, "ifeval": ifeval}[sys.argv[1]](int(sys.argv[2]))
