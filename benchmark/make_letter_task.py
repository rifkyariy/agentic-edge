#!/usr/bin/env python3
"""Generate the `mmlu_pro_letter` lm-eval task: MMLU-Pro with no chain of thought.

    python3 make_letter_task.py --out ~/Research/lm_eval_tasks

Why a task variant rather than a flag: `--system_instruction` *prepends* to the
task's own description, and MMLU-Pro's description says "Think step by step and
then finish your answer with ...". The two then contradict each other and the
task's wins — measured 2026-09-27, the model opened with "Step 1: Analyze the
question." and was truncated by the token cap, scoring 0/14.

So this copies the installed task and changes exactly three things:
  * the description, to ask for the letter and nothing else
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


def build(src, out, gen_toks):
    dst = os.path.join(out, "mmlu_pro_letter")
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
        s = s.replace(f'task: "mmlu_pro_{subj}"', f'task: "mmlu_pro_letter_{subj}"')
        s = s.replace(f'task_alias: "', 'task_alias: "letter ')
        open(f, "w").write(s)
        os.rename(f, f"{dst}/mmlu_pro_letter_{subj}.yaml")

    g = f"{dst}/_mmlu_pro.yaml"
    s = open(g).read()
    s = s.replace("group: mmlu_pro", "group: mmlu_pro_letter")
    s = re.sub(r"- mmlu_pro_(\w+)", r"- mmlu_pro_letter_\1", s)
    open(g, "w").write(s)
    os.rename(g, f"{dst}/_mmlu_pro_letter.yaml")

    t = f"{dst}/_default_template_yaml"
    s = open(t).read()
    s = re.sub(r"^num_fewshot:.*$", "num_fewshot: 0", s, flags=re.M)
    s = re.sub(r"^(\s*)max_gen_toks:.*$", rf"\g<1>max_gen_toks: {gen_toks}", s, flags=re.M)
    open(t, "w").write(s)
    return dst


def build_letter_samples(stdbench, subset):
    """A baseline samples file, rekeyed onto the letter task names.

    Every task in the group must appear or lm-eval silently runs the omitted
    ones in full — 8 of 14 listed once turned 14 questions into 5,980.
    """
    src = f"{stdbench}/mmlupro_subset100_{subset}_samples.json"
    d = json.load(open(src))
    out = {k.replace("mmlu_pro_", "mmlu_pro_letter_"): v for k, v in d.items()}
    dst = f"{stdbench}/mmlupro_subset100_{subset}_letter_samples.json"
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
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    dst = build(find_installed(), args.out, args.gen_toks)
    print(f"task dir: {dst}  ({len(glob.glob(dst + '/mmlu_pro_letter_*.yaml'))} subjects, "
          f"num_fewshot 0, max_gen_toks {args.gen_toks})")
    for sub in args.subsets.split(","):
        if os.path.exists(f"{args.stdbench}/mmlupro_subset100_{sub}_samples.json"):
            p, t, q = build_letter_samples(args.stdbench, sub)
            print(f"  samples {sub}: {t} tasks, {q} questions -> {os.path.basename(p)}")


if __name__ == "__main__":
    main()
