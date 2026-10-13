# agentic-edge

The code and data behind **"Never Compute Twice: Exact-Output Speedups for
Gemma 4 on Edge Devices"** (R. A. Yunanto, NTUST), plus every other experiment
the project ran on the way there.

The paper asks how much speed an edge board offers **without changing a single
output byte**. On an NVIDIA Jetson Orin Nano 8 GB at 15 W, with Gemma 4 E2B and
E4B on 300 MMLU-Pro questions per model, **CoPR** adds two exact techniques to
the little-gemma runtime: prompt-lookup drafting through its existing batched
verify, and shared-prefix KV reuse made exact for sliding-window ring buffers.
It reproduces little-gemma's replies byte for byte and is faster and cheaper
than llama.cpp:

| Jetson Orin Nano, 15 W, n=300 | llama.cpp | llama.cpp + n-gram | little-gemma | **CoPR** |
|---|---|---|---|---|
| E2B accuracy | 52.7% | 53.3% | 53.0% | **53.0%** (300/300 replies = little-gemma) |
| E2B decode tok/s · J/token | 23.00 · 0.465 | 26.63 · 0.429 | 25.58 · 0.446 | **29.52 · 0.370** |
| E4B accuracy | 66.0% | 65.0% | 65.3% | **65.3%** (300/300 replies = little-gemma) |
| E4B decode tok/s · J/token | 11.62 · 0.965 | 13.83 · 0.871 | 15.05 · 0.838 | **17.67 · 0.676** |

Every number in that table, and in the paper's Tables I, III, IV, V, VI and
VIII, is rebuilt from the raw runs committed here by one command (step 1
below).

---

## Contents

- [Repository map](#repository-map)
- [Reproducing the paper](#reproducing-the-paper)
  - [1. Check the paper against the committed data (no hardware, 2 seconds)](#1-check-the-paper-against-the-committed-data)
  - [2. Re-run the experiments on a Jetson Orin Nano (~42 board-hours)](#2-re-run-the-experiments-on-a-jetson-orin-nano)
  - [3. The other devices in Table VIII](#3-the-other-devices-in-table-viii)
  - [4. Table by table](#4-table-by-table)
  - [5. Where the data and the manuscript disagree](#5-where-the-data-and-the-manuscript-disagree)
- [Other experiments in this repository](#other-experiments-in-this-repository)
- [Documentation](#documentation)

---

## Repository map

| folder | what it holds |
|---|---|
| [`benchmark/`](benchmark/) | everything that runs on the boards: run scripts, telemetry, the job queue, the engine patches (`little_gemma/`), the paper's analysis (`paper_tables.py`, `collect_runs.py`), tests, and the iPhone app (`apps/ios/`) |
| [`findings/`](findings/) | every result. `runs/jetson/` holds the paper's raw Jetson runs; `RESULTS.md` is the full write-up |
| [`docs/`](docs/) | the protocol as run, the index of every experiment, the queue's design record |
| [`dashboard/`](dashboard/) | optional Next.js monitor and queue UI for the boards; runs on a laptop |

The voice agent (the own suite's condition E: ASR, LLM, TTS, orchestrator,
tools, web UI) is on the
[`voice-agent`](https://github.com/rifkyariy/agentic-edge/tree/voice-agent)
branch. Nothing in the paper needs it.

---

## Reproducing the paper

### 1. Check the paper against the committed data

Needs Python 3.9+ and nothing else: no packages, no network, no board.

```bash
git clone https://github.com/rifkyariy/agentic-edge.git
cd agentic-edge
python3 benchmark/paper_tables.py
```

It recomputes each table from the raw files, then prints the paper's value
beside the recomputed one, line by line:

```
Table III — engines on the Jetson Orin Nano at 15 W, n=300 per cell
  E2B CoPR: accuracy %                                       paper 53.0       here 53.0       ok
  E2B CoPR: decode tok/s                                     paper 29.52      here 29.52      ok
  ...
every number matches the manuscript
2 manuscript errata (the data is right, the paper's rounding is not): ...
```

The exit status is 1 if any number differs. `--table 1|3|4|5|6|8|text|issues`
prints a single table. The same check runs in the test suite:

```bash
cd benchmark && python3 -m unittest discover -s tests
```

**What it reads.** Each run of the paper is one directory under
`findings/runs/jetson/<run>/`:

| file | what it is | used for |
|---|---|---|
| `samples.jsonl.gz` | lm-eval's per-question records: prompt, reply, extracted answer, score | accuracy, byte identity, McNemar |
| `results.json` | lm-eval's results file | per-run accuracy |
| `measured/summary.json` | `summarize_run.py`: energy, tokens, rates, thermals, utilisation | decode rate, energy per token, wall time, power |
| `measured/telemetry.csv.gz` | 1 Hz board telemetry incl. INA3221 `VDD_IN` power | request-window energy, clock state |
| `measured/requests.csv` | per-request prompt/generated tokens and timings | capped replies, request windows |
| `queue/fingerprint.json` | the live serving command line, diffed against `benchmark/baselines.json` | proof the run served the declared flags |
| `engine_build.txt` | little-gemma pin and patch hashes | which binary answered |
| `engine.log.gz` | verify-width sweeps only: the engine's per-turn and per-verify lines | Table VI |
| `server.log.gz` | llama.cpp runs only: llama-server's log | n-gram draft acceptance |

Run names follow `mmlupro100-<row><model>-<subset>`. `<row>` is empty for
llama.cpp, `lg-` for little-gemma, `ae-full-` for CoPR, `ae-ngram-` /
`ae-reuse-` for its ablations, and `ngram-n3m3-` for llama.cpp's n-gram
drafting. "ae" and "S9" in file names are the working names for CoPR.

### 2. Re-run the experiments on a Jetson Orin Nano

This regenerates every Jetson run the paper uses from scratch. The full grid
takes about **42 hours** of board time: E2B ≈ 14 h and E4B ≈ 25 h for Table III
and V, plus ~3 h for Table IV's extra settings and Table VI's sweep. Runs are
queued and survive logouts. **Run one job at a time**: a second concurrent
run invalidates the telemetry of both.

#### 2.1 What you need

| | used for the paper |
|---|---|
| board | NVIDIA Jetson Orin Nano 8 GB developer kit, active cooling, NVMe SSD for models and results |
| OS | JetPack R39.2.1 (L4T), kernel 6.8.12-tegra, CUDA 13.2 |
| power mode | `nvpmodel` mode 0 = **15 W**: GPU capped at 612 MHz, CPU at 1,497.6 MHz |
| toolchain | CMake ≥ 3.24 (the scripts expect it at `~/build/cmake/bin/cmake`), git, Python 3.12, curl |
| disk | ~7 GB of models, ~2 GB of results |
| not needed | sudo for anything except setting the power mode; pip system packages |

The scripts assume this layout on the board. Keep it, or edit the paths at
the top of each script:

```
~/research/agentic-edge/     this repository        (scripts look for ~/research, lowercase)
~/research/models/           the two GGUFs
~/research/stdbench/         lm-eval output, one directory per run
~/research/measured/         telemetry, one directory per run
~/build/llama.cpp/           llama.cpp @ a894dae, CUDA build
~/build/little-gemma/        little-gemma @ aee759d + agentic-edge.patch       (the baseline)
~/build/little-gemma-ae/     little-gemma @ aee759d + agentic-edge.patch + ae.patch  (CoPR)
~/venvs/eval/                lm-evaluation-harness 0.4.13
```

#### 2.2 Set the power mode, and leave the clocks free

```bash
sudo nvpmodel -m 0          # 15 W
nvpmodel -q                 # should print 15W / 0
cat /sys/class/devfreq/17000000.gpu/max_freq                   # 612000000
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq      # 1497600
```

**Do not run `jetson_clocks`.** It pins the clocks at their caps. Speed stays
within ±3% but energy rises 5–9% (`findings/RESULTS.md` §7.7). If a reboot
leaves `nvpmodel` unapplied, `nvpmodel -q` can still say 15 W while the GPU
runs at 1,020 MHz; the queue's `clocks` precheck refuses to start a run until
the caps match. Fix it with `sudo systemctl restart nvpmodel`.

#### 2.3 Get the repository and the models

```bash
mkdir -p ~/research/models ~/research/stdbench ~/research/measured ~/build
git clone https://github.com/rifkyariy/agentic-edge.git ~/research/agentic-edge
```

Download Unsloth's Gemma 4 QAT GGUFs (`UD-Q4_K_XL`) into `~/research/models/`
with exactly these names. Verify the checksums: every engine must load the
same bytes.

```bash
cd ~/research/models
sha256sum gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf
# e531007218dfab990486a5de7676a6932d6ea8dea233d1f698d7c21cf8a16889  gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf
# df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3  gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf
```

#### 2.4 The evaluation environment

lm-evaluation-harness 0.4.13. The Jetson image has no `python3-venv`
package, so the venv is created without pip and pip is bootstrapped into it:

```bash
python3 -m venv --without-pip ~/venvs/eval
curl -sSL https://bootstrap.pypa.io/get-pip.py | ~/venvs/eval/bin/python
~/venvs/eval/bin/pip install "lm_eval[api]==0.4.13"
```

lm-eval downloads MMLU-Pro (`TIGER-Lab/MMLU-Pro`) on first use. The three
question subsets are committed; put them where the run scripts read them:

```bash
cp ~/research/agentic-edge/findings/stdbench/mmlupro_subset100_s?_*.json ~/research/stdbench/
```

`s1`/`s2`/`s3` are 100 questions each, stratified over all 14 subjects, drawn
with seeds 20260918/19/20 by `benchmark/mmlupro_subset.py`, and disjoint.
`*_samples.json` is lm-eval's `--samples` argument and `*_ids.json` the record
of how each subset was drawn.

#### 2.5 Build the three engines

**llama.cpp** at the commit the paper used, CUDA for the Orin's sm_87:

```bash
git clone https://github.com/ggml-org/llama.cpp.git ~/build/llama.cpp
cd ~/build/llama.cpp && git checkout a894dae939d426954ce54bb604824f1ae918a0c5
export PATH=/usr/local/cuda/bin:$PATH
~/build/cmake/bin/cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87
~/build/cmake/bin/cmake --build build --config Release --target llama-server -j"$(nproc)"
```

**little-gemma** (the baseline) and **CoPR**. One script pins
`cortexist/little-gemma` at `aee759d`, applies the patches and builds the
CUDA int8 runner, about 5 minutes each:

```bash
cd ~/research/agentic-edge/benchmark
./little_gemma/setup_jetson.sh            # -> ~/build/little-gemma/build/run-cuda-i8
AE=1 ./little_gemma/setup_jetson.sh       # -> ~/build/little-gemma-ae/build/run-cuda-i8 (CoPR)
cat ~/build/little-gemma/build/BUILD_INFO ~/build/little-gemma-ae/build/BUILD_INFO
```

`BUILD_INFO` must show these patch hashes. They are the ones in every run's
`engine_build.txt` in `findings/runs/jetson/`:

```
patch:    agentic-edge.patch sha256 33acf2820d31e87b
patch:    ae.patch sha256 021e910489def3e9          (CoPR only)
```

What the patches do:

- [`agentic-edge.patch`](benchmark/little_gemma/agentic-edge.patch) lets
  little-gemma take lm-eval's prompts unchanged (`-raw`), tokenises the whole
  prompt at once, and raises the answer budget to 2,048 tokens. No kernel,
  sampling or tokenizer change.
- [`ae.patch`](benchmark/little_gemma/ae.patch) is CoPR. It adds `-ngram`
  (prompt-lookup drafts through the batched verify), `-reuse` (shared-prefix
  KV snapshots that store the sliding-window rings whole) and `-block N`
  (verify width). Every switch is off by default.

#### 2.6 Check the setup, then start the queue

```bash
cd ~/research/agentic-edge/benchmark
python3 -m unittest discover -s tests     # 218 tests; the paper check skips without findings data
./install_queue.sh                        # systemd user unit, survives logout
./queue_ctl.py --status
```

Every queued job runs four steps:

1. Prechecks: free memory, an idle board, the subset file, and the clock caps.
2. The run itself, under `run_measured.sh`: 30 s idle baselines before and after, and 1 Hz telemetry throughout.
3. A capture of the live server command line once it is serving, diffed against `baselines.json`. A mismatch fails the run.
4. The summary.

`./queue_ctl.py --preflight '<job>'` runs the prechecks without queueing.

#### 2.7 Run the grid

Each line below is one job. Paste a block onto the board as it is; jobs run
in order.

**Table III and Table I: the baselines, CoPR and llama.cpp's n-gram drafting**
(n=300 per cell = 3 subsets × 2 models):

```bash
cd ~/research/agentic-edge/benchmark
for m in e2b e4b; do for s in s1 s2 s3; do
  ./queue_ctl.py --add "{\"kind\":\"mmlupro\",\"params\":{\"model\":\"$m\",\"subset\":\"$s\",\"thinking\":\"off\"}}"       # llama.cpp
  ./queue_ctl.py --add "{\"kind\":\"mmlupro-lg\",\"params\":{\"model\":\"$m\",\"subset\":\"$s\",\"thinking\":\"off\"}}"    # little-gemma
  ./queue_ctl.py --add "{\"kind\":\"mmlupro-ae\",\"params\":{\"model\":\"$m\",\"subset\":\"$s\",\"variant\":\"full\"}}"    # CoPR
  ./queue_ctl.py --add "{\"kind\":\"mmlupro-ngram\",\"params\":{\"model\":\"$m\",\"subset\":\"$s\",\"cfg\":\"n3m3\"}}"     # llama.cpp + n-gram, width 4
done; done
```

**Table V: the ablation.** One switch at a time; "both" is CoPR above:

```bash
for m in e2b e4b; do for s in s1 s2 s3; do for v in ngram reuse; do
  ./queue_ctl.py --add "{\"kind\":\"mmlupro-ae\",\"params\":{\"model\":\"$m\",\"subset\":\"$s\",\"variant\":\"$v\"}}"
done; done; done
```

**Table IV: llama.cpp's n-gram drafting in its other settings, plus the CoPR
repeat** (E2B, s1):

```bash
./queue_ctl.py --add '{"kind":"mmlupro-ngram","params":{"model":"e2b","subset":"s1","cfg":"n3m2"}}'     # width 3
./queue_ctl.py --add '{"kind":"mmlupro-ngram","params":{"model":"e2b","subset":"s1","cfg":"default"}}'  # stock: 12-token lookup, 48-token drafts
./queue_ctl.py --add '{"kind":"mmlupro-ae","params":{"model":"e2b","subset":"s1","variant":"full-r2"}}' # the repeat run
```

**Table VI: choosing the verify width.** Each sweep replays 28 s1 questions
(2 per subject) that little-gemma already answered, so it needs the
`mmlupro-lg` s1 runs above. Every reply must come back byte-identical:

```bash
for m in e2b e4b; do
  ./queue_ctl.py --add "{\"kind\":\"ae-gate\",\"params\":{\"model\":\"$m\",\"flags\":\"\",\"name\":\"b0\"}}"
  for b in 2 3 4; do
    ./queue_ctl.py --add "{\"kind\":\"ae-gate\",\"params\":{\"model\":\"$m\",\"flags\":\"-reuse -ngram -block $b\",\"name\":\"b$b\"}}"
  done
done
```

Watch progress with `./queue_ctl.py --status`, or open the dashboard (below).
Each finished run lands in `~/research/stdbench/<run>/` and
`~/research/measured/<label>-<stamp>/`.

**Without the queue**, any single run can be launched by hand. These are the
exact commands the queue runs:

```bash
SRVLOG=~/research/stdbench/mmlupro100-e2b-s1/server.log \
  ./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 THINKING=off ./std_mmlupro_jetson.sh e2b
SRVLOG=~/research/stdbench/mmlupro100-ae-full-e2b-s1/server.log \
  ./run_measured.sh mmlupro-ae-full-e2b-s1 -- env SUBSET=s1 THINKING=off VARIANT=full ./std_mmlupro_lg_jetson.sh e2b
SRVLOG=~/research/stdbench/mmlupro100-ngram-n3m3-e2b-s1/server.log \
  ./run_measured.sh mmlupro-ngram-n3m3-e2b-s1 -- env SUBSET=s1 THINKING=off SPEC=n3m3 ./std_mmlupro_jetson.sh e2b
```

The serving flags each script uses, all identical across engines except the
engine itself:

| run | server |
|---|---|
| llama.cpp | `llama-server -m <gguf> -c 8192 -ngl 99 -rea off --reasoning-budget -1 --cache-ram 0` |
| llama.cpp + n-gram | the same, plus `--spec-type ngram-simple --spec-ngram-simple-size-n 3 --spec-ngram-simple-size-m 3 --spec-draft-n-max 3` |
| little-gemma | `run-cuda-i8 -m <gguf> -raw -think -1` behind `lg_openai_shim.py --thinking off` |
| CoPR | the same with the CoPR binary and `-reuse -ngram -block 3` |

`-rea` is `--reasoning`, the thinking switch itself. It is a different flag
from `--reasoning-format`. Left out, it defaults to `auto` and Gemma thinks
into a field lm-eval never reads (`AGENTS.md` §5).

#### 2.8 Check byte identity

CoPR's quality standard is that every reply equals little-gemma's reply to
the same question:

```bash
cd ~/research/agentic-edge/benchmark
for m in e2b e4b; do for s in s1 s2 s3; do for v in full ngram reuse; do
  ./ae_gate.py --diff ~/research/stdbench/mmlupro100-ae-$v-$m-$s ~/research/stdbench/mmlupro100-lg-$m-$s | tail -1
done; done; done
# == 100/100 byte-identical: ...      (all 18 lines; 1,800 replies)
```

#### 2.9 Collect the runs and rebuild the tables

Back on your own machine, copy the runs into `findings/runs/jetson/` and run
the step 1 check against your data:

```bash
python3 benchmark/collect_runs.py --board jetson --from <ssh-host>:research --paper
python3 benchmark/paper_tables.py
```

Accuracy and byte identity should match exactly: decoding is greedy, and the
engines and weights are pinned. Speed should land within about 1% of the
paper. A repeat CoPR run three days later reproduced all 100 replies, with
decode within 0.8%. Energy per token can move by up to ±9% between days, with
the board's idle floor and temperature (Sec. V), so compare energy only
between runs made on the same day.

### 3. The other devices in Table VIII

Table VIII sets the Jetson result beside other deployments of the same
checkpoint on the same 300 questions. Its rows compare deployments, not
engines.

**Raspberry Pi 5 (llama.cpp, CPU).** Committed in
`findings/export/experiment-full.json.gz`, and checked by
`paper_tables.py --table 8`. To re-run: llama.cpp `661643e`, CPU build with
`GGML_NATIVE=ON`, the same GGUFs, eval venv at `~/Research/eval-venv`. Then
per model and subset:

```bash
cd ~/Research/agentic-edge/benchmark          # capital R on the Pi
./run_measured.sh mmlupro-e2b-s1 -- env SUBSET=s1 ./std_mmlupro.sh e2b
```

`std_mmlupro.sh` serves through the Pi's `va-llm` systemd unit and sets
`-c 8192 --cache-ram 0 -rea off --reasoning-budget -1` in its `runtime.env`,
restoring the deployed values afterwards. On a Pi without that unit, launch
`llama-server` with those flags as `std_mmlupro_jetson.sh` does, minus `-ngl`.
Then `python3 benchmark/export_experiment.py --out findings/export/experiment-full.json`
regenerates the export.

**iPhone 15 Pro (MLX).** The GemmaBench app in `benchmark/apps/ios/` runs the
same prompts on-device and uploads each run. Build and run it by following
[`benchmark/apps/ios/AGENTS.md`](benchmark/apps/ios/AGENTS.md). The ten
uploads, including the superseded and stopped ones, are in
[`findings/phone/`](findings/phone/README.md). Its energy is a whole-phone
battery estimate, not board DC power, so it cannot be compared with the
boards' energy.

### 4. Table by table

| paper | runs (in `findings/runs/jetson/` unless noted) | how to regenerate | rebuilt by |
|---|---|---|---|
| **Table I**: baseline anatomy | `mmlupro100-e2b-s*`, `mmlupro100-lg-e2b-s*` | 2.7, first block | `paper_tables.py --table 1` |
| **Table II**: protocol | — | [`docs/protocol.md`](docs/protocol.md) §2–§3 | — |
| **Table III**: the engine comparison | S1, S3, CoPR, n-gram `n3m3`, both models × s1–s3 | 2.7, first block | `--table 3` |
| **Table IV**: llama.cpp n-gram vs CoPR | `mmlupro100-e2b-s1`, `-ngram-n3m2-`, `-ngram-n3m3-`, `-ngram-default-`, `-ae-full-`, `-ae-full-r2-e2b-s1` | 2.7, third block | `--table 4` |
| **Table V**: ablation | `-lg-`, `-ae-ngram-`, `-ae-reuse-`, `-ae-full-`, both models × s1–s3 | 2.7, second block | `--table 5` |
| **Table VI**: verify width | `ae-sweep-<model>-b{0,2,3,4}` | 2.7, fourth block | `--table 6` |
| **Table VII**: replayed acceptance | recorded replies from several engines and tasks | **not yet reproducible from the repo**: `replay_lookup.py` and the Pi's thinking-on replies are on the Pi | — |
| **Table VIII**: other devices | Jetson rows = Table III; Pi in `findings/export/`; iPhone in `findings/phone/` | §3 | `--table 8` |
| §III: 97% decode, 3.8× prefill, 17 capped replies | as Table I | — | `--table 1`, `--table text` |
| §III: replay 1.29/1.41/1.48/1.52 tokens per pass | little-gemma E2B replies | needs `replay_lookup.py` (on the Pi) | — |
| §V: request-window energy, the repeat run, 612 MHz | CoPR and llama.cpp runs | — | `--table text` |
| §VI-A–C: McNemar tests, 271/280 replies changed, speedup ratios | as Table III | — | `--table text` |
| §VI-D: six `-reuse` runs failed at startup | `findings/runs/jetson/failed/` (server logs show the parse error) | — | — |
| §VII: Pi batched-verify cost (132 / 140 ms) | llama.cpp `llama-batched-bench`, E2B, 3 threads, on the Pi | **output is on the Pi** | — |

The three Pi-only items will be added with `collect_runs.py` and
`paper_tables.py` the next time the Pi is available. It is currently on loan.

### 5. Where the data and the manuscript disagree

`paper_tables.py` found these. The repository records the data as measured.
Fix the paper, not the data.

1. **Two rounding errata, both in Table IV.** The llama.cpp n-gram width-4
   row's "above idle" is 0.22447 J, printed 0.225; it should be 0.224. CoPR
   width 3's J/tok is 0.36947 J, printed 0.370; it should be 0.369. Both were
   rounded twice. Table III's pooled 0.370 is correct.
2. **Table IV's "llama.cpp n-gram, width 3" run never drafted.** Its
   llama-server log has no draft-acceptance line on any of its 100 requests.
   Width 4 has one on 100/100, stock settings on 94/100. So that row is a plain
   llama.cpp rerun. Its "100/100 exact" and "+3%" say nothing about whether
   width-3 drafting in llama.cpp is exact (`RESULTS.md` §7.8;
   `paper_tables.py --table issues`).
3. **The Oct 7–8 runs had the Jetson's clocks pinned.** These are all of
   llama.cpp + n-gram, the reuse-only ablation, and the CoPR repeat. The CPU
   sat at its 1,497.6 MHz cap instead of scaling, with the `jetson_clocks`
   signature (`RESULTS.md` §7.7). The caps were the 15 W caps, as the paper
   says, but the lock adds 5–9% energy. The paper's ±9% cross-day band puts
   this down to the idle floor and temperature without naming the lock.

---

## Other experiments in this repository

Everything that actually ran is reported, whether the paper uses it or not.
That covers the own 10-case suite (five architectures, MTP × thinking,
quantisation), tinyGSM8k, thinking-on MMLU-Pro, letter-only answers, a
permutation ensemble and a model cascade, a TurboQuant KV cache, and the
iPhone arm. [`docs/experiments.md`](docs/experiments.md) lists every one,
with its data and write-up. The full numbers are in
[`findings/RESULTS.md`](findings/RESULTS.md).

## Documentation

| if you want to… | read |
|---|---|
| change anything in the repo: rules, devices, invariants | [`AGENTS.md`](AGENTS.md) — **start here** |
| know exactly how every measurement was taken | [`docs/protocol.md`](docs/protocol.md) |
| see every experiment that ran, and where its data is | [`docs/experiments.md`](docs/experiments.md) |
| see every number and the current status | [`findings/RESULTS.md`](findings/RESULTS.md) (§10 is the status) |
| read one experiment's analysis | [`findings/analyses/`](findings/analyses/): letter-only, permutation ensemble, model cascade, iso-accuracy |
| use the harness beyond the paper | [`benchmark/README.md`](benchmark/README.md) |
| watch the boards and manage the queue in a browser | [`dashboard/README.md`](dashboard/README.md) |
| work on the iPhone arm | [`benchmark/apps/ios/AGENTS.md`](benchmark/apps/ios/AGENTS.md) |
| understand the queue's design | [`docs/design/experiment-queue.md`](docs/design/experiment-queue.md) |
| see the first engine comparison (Sep 14, Pi only) | [`findings/early-engine-benchmarks/README.md`](findings/early-engine-benchmarks/README.md) |
