#!/usr/bin/env python3
"""Generate the `mmlu_pro_letter` lm-eval task: MMLU-Pro with no chain of thought.

    python3 make_letter_task.py --out ~/Research/lm_eval_tasks

Why a task variant rather than a flag: `--system_instruction` *prepends* to the
task's own description, and MMLU-Pro's description says "Think step by step and
then finish your answer with ...". The two then contradict each other and the
task's wins — measured 2026-09-27, the model opened with "Step 1: Analyze the
question." and was truncated by the token cap, scoring 0/14.

So this copies the installed task and changes exactly four things:
  * the description, to ask for the letter and nothing else
  * utils.py's format_cot_example, which appends "Answer: Let's think step by
    step." to EVERY prompt. Leaving it in made the condition contradict itself
    — system saying "do not explain", the user turn ending "think step by
    step" — and the first run measured that contradiction rather than the
    condition. Replaced with a plain "Answer:".
  * num_fewshot 5 -> 0, because the exemplars are chain-of-thought ones and
    would instruct the model twice, in opposite directions
  * max_gen_toks 2048 -> a handful, which is the point of the experiment

Everything else — dataset, split, doc_to_text, the `answer is (X)` extraction
filter, greedy decoding, the metric — is the installed task's, untouched, so a
score here is comparable with the baseline on the same subset ids.

Task names gain a `_letter` infix (`mmlu_pro_letter_biology`) so they cannot
collide with the installed ones, which also means `--samples` keys must use the
new names. build_letter_samples() rewrites a baseline samples file accordingly.
"""
import argparse, glob, json, os, re, shutil, sys

DESC = ('The following are multiple choice questions (with answers) about {subject}. '
        'Reply with only "the answer is (X)" where X is the correct letter choice. '
        'Do not explain and do not show any working.\n')


def find_installed():
    for p in glob.glob(os.path.expanduser(
            "~/*/eval-venv/lib/python3*/site-packages/lm_eval/tasks/mmlu_pro")) + glob.glob(
            os.path.expanduser("~/venvs/eval/lib/python3*/site-packages/lm_eval/tasks/mmlu_pro")):
        if os.path.isdir(p):
            return p
    sys.exit("could not find the installed mmlu_pro task directory")


ROT_CODE = """

# agentic-edge: rotate the option order so one question can be asked K ways.
# The gold rotates with it, so each run stays a valid self-contained eval.
# Downstream analysis pairs on the chosen option TEXT rather than its letter,
# which makes un-rotating unnecessary.
_ROTATE = {rot}


def _rotate_doc(x):
    o = list(x["options"])
    n = len(o)
    r = _ROTATE % n if n else 0
    x["options"] = o[r:] + o[:r]
    x["answer_index"] = (x["answer_index"] - r) % n
    x["answer"] = "ABCDEFGHIJ"[x["answer_index"]]
    return x

"""


def build(src, out, gen_toks, rot=0):
    name = "mmlu_pro_letter" if not rot else "mmlu_pro_letter_r%d" % rot
    dst = os.path.join(out, name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))

    for f in glob.glob(f"{dst}/mmlu_pro_*.yaml"):
        s = open(f).read()
        subject = re.search(r'task:\s*"mmlu_pro_(\w+)"', s)
        if not subject:
            continue
        subj = subject[1]
        s = re.sub(r'^description:.*$',
                   'description: ' + json.dumps(DESC.format(subject=subj.replace("_", " "))),
                   s, flags=re.M)
        s = s.replace(f'task: "mmlu_pro_{subj}"', f'task: "{name}_{subj}"')
        s = s.replace(f'task_alias: "', 'task_alias: "letter ')
        open(f, "w").write(s)
        os.rename(f, f"{dst}/{name}_{subj}.yaml")

    g = f"{dst}/_mmlu_pro.yaml"
    s = open(g).read()
    s = s.replace("group: mmlu_pro", "group: " + name)
    s = re.sub(r"- mmlu_pro_(\w+)", "- " + name + r"_\1", s)
    open(g, "w").write(s)
    os.rename(g, f"{dst}/_{name}.yaml")

    # utils.py appends the CoT trigger to every prompt; without this the
    # condition argues with itself and the measurement is of the argument.
    u = f"{dst}/utils.py"
    src_u = open(u).read()
    patched = src_u.replace('prompt += "Answer: Let\'s think step by step."',
                            'prompt += "Answer:"')
    if patched == src_u:
        sys.exit("utils.py: could not find the CoT trigger to remove — check upstream")
    if rot:
        old = ('def process_docs(dataset, subject):\n'
               '    return dataset.filter(lambda x: x["category"] == subject)')
        new = (ROT_CODE.format(rot=rot) +
               'def process_docs(dataset, subject):\n'
               '    return dataset.filter(lambda x: x["category"] == subject).map(_rotate_doc)')
        if old not in patched:
            sys.exit("utils.py: process_docs is not the shape the rotation patch expects")
        patched = patched.replace(old, new)
    open(u, "w").write(patched)

    t = f"{dst}/_default_template_yaml"
    s = open(t).read()
    s = re.sub(r"^num_fewshot:.*$", "num_fewshot: 0", s, flags=re.M)
    s = re.sub(r"^(\s*)max_gen_toks:.*$", rf"\g<1>max_gen_toks: {gen_toks}", s, flags=re.M)
    open(t, "w").write(s)
    return dst


def build_letter_samples(stdbench, subset, name="mmlu_pro_letter"):
    """A baseline samples file, rekeyed onto the letter task names.

    Every task in the group must appear or lm-eval silently runs the omitted
    ones in full — 8 of 14 listed once turned 14 questions into 5,980.
    """
    src = f"{stdbench}/mmlupro_subset100_{subset}_samples.json"
    d = json.load(open(src))
    out = {k.replace("mmlu_pro_", name + "_"): v for k, v in d.items()}
    tag = "letter" if name == "mmlu_pro_letter" else name[len("mmlu_pro_"):]
    dst = f"{stdbench}/mmlupro_subset100_{subset}_{tag}_samples.json"
    json.dump(out, open(dst, "w"))
    return dst, len(out), sum(len(v) for v in out.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    home = os.path.expanduser("~")
    root = next((p for p in (f"{home}/Research", f"{home}/research") if os.path.isdir(p)), home)
    ap.add_argument("--out", default=f"{root}/lm_eval_tasks")
    ap.add_argument("--stdbench", default=f"{root}/stdbench")
    ap.add_argument("--gen-toks", type=int, default=16)
    ap.add_argument("--subsets", default="s1,s2,s3,letsmoke")
    ap.add_argument("--rotate", type=int, default=0,
                    help="rotate the option order by N places; 0 is the plain task")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    name = "mmlu_pro_letter" if not args.rotate else "mmlu_pro_letter_r%d" % args.rotate
    dst = build(find_installed(), args.out, args.gen_toks, args.rotate)
    print(f"task dir: {dst}  ({len(glob.glob(dst + '/' + name + '_*.yaml'))} subjects, "
          f"num_fewshot 0, max_gen_toks {args.gen_toks}, rotate {args.rotate})")
    for sub in args.subsets.split(","):
        if os.path.exists(f"{args.stdbench}/mmlupro_subset100_{sub}_samples.json"):
            p, t, q = build_letter_samples(args.stdbench, sub, name)
            print(f"  samples {sub}: {t} tasks, {q} questions -> {os.path.basename(p)}")


if __name__ == "__main__":
    main()
