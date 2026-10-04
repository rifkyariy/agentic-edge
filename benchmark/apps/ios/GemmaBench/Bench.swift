import Foundation
import HuggingFace
import MLX
import MLXHuggingFace
import MLXLLM
import MLXLMCommon
import Observation
import Tokenizers
import UIKit

// MARK: - Bundled prompts (prep/build_prompts.py)

struct Doc: Codable, Sendable {
    let task: String
    let doc_id: Int
    let question_id: Int
    let target: String
    let question: String
    let options: [String]
    let src: String
    let messages: [[String: String]]
}

struct Ref: Codable, Sendable {
    let run: String
    let score: Double
    let decode_tok_s: Double?
    let prompt_tokens_total: Int  // after llama.cpp's prefix cache: not comparable to full prompts
    let first_prompt_tokens: Int?  // the one uncached request: the template/tokenizer parity check
    let minutes: Double?
    let energy_wh: Double?  // board DC draw (PMIC / INA3221)
    let mean_w: Double?
    let j_per_token: Double?
}

struct PromptFile: Codable {
    let subsets: [String: [Doc]]
    let reference: [String: [String: Ref]]
}

enum GemmaModel: String, CaseIterable, Identifiable, Sendable {
    case e2b, e4b
    /// E4B from the same QAT checkpoint, quantized smaller (4-bit, sensitive layers 5/6-bit):
    /// qat-4bit keeps 126 layers at 8-bit and needs 5.45 GiB, which an 8 GB iPhone's ~6 GiB app
    /// limit can't hold (jetsam, 2026-10-04); this is 4.09 GiB. A different quantization of the
    /// same weights, so it reports as model e4b with engine mlx-oq4 — never mixed with qat-4bit.
    case e4bOQ4 = "e4b-oq4"
    var id: String { rawValue }
    /// Same QAT checkpoint as the agentic-edge GGUFs (gemma-4-E?B-it-qat-UD-Q4_K_XL).
    var repo: String {
        switch self {
        case .e2b: "mlx-community/gemma-4-E2B-it-qat-4bit"
        case .e4b: "mlx-community/gemma-4-E4B-it-qat-4bit"
        case .e4bOQ4: "mlx-community/unsloth-gemma-4-E4B-it-qat-oQ4"
        }
    }
    /// The model the boards ran: what reference scores and pairing use.
    var base: String { self == .e4bOQ4 ? "e4b" : rawValue }
    var engine: String { self == .e4bOQ4 ? "mlx-oq4" : "mlx" }
    var title: String { self == .e4bOQ4 ? "E4B oQ4" : rawValue.uppercased() }
    var quant: String { self == .e4bOQ4 ? "QAT oQ4 (4/5/6-bit)" : "QAT 4-bit" }
    /// qat-4bit E4B needs more than an 8 GB iPhone gives one app.
    var fitsThisPhone: Bool { self != .e4b || ProcessInfo.processInfo.physicalMemory > 10 << 30 }
    static func base(_ key: String) -> String { GemmaModel(rawValue: key)?.base ?? key }
}

// MARK: - Scoring (lm-eval mmlu_pro "custom-extract")

/// First match of `answer is \(?([ABCDEFGHIJ])\)?`, else "[invalid]" — lm-eval's regex + take_first.
func extractAnswer(_ s: String) -> String {
    guard let m = s.firstMatch(of: /answer is \(?([ABCDEFGHIJ])\)?/) else { return "[invalid]" }
    return String(m.1)
}

/// lm-eval `until: ["Question:"]` — the response is everything before the first stop string.
func cutAtStop(_ s: String) -> String {
    s.range(of: "Question:").map { String(s[..<$0.lowerBound]) } ?? s
}

func scoringSelfCheck() {
    assert(extractAnswer("so the answer is (I)") == "I")
    assert(extractAnswer("The answer is B. Wait, the answer is (C)") == "B")
    assert(extractAnswer("the answer is (K)") == "[invalid]")
    assert(extractAnswer("no idea") == "[invalid]")
    assert(cutAtStop("the answer is (A).\n\nQuestion: next") == "the answer is (A).\n\n")
    assert(cutAtStop("plain") == "plain")
}

// MARK: - Runner

struct ReqResult: Codable, Sendable {
    let promptTokens: Int
    let genTokens: Int
    let start: Date
    let firstToken: Date
    let end: Date
    let text: String
    let stop: String
}

@MainActor @Observable
final class Bench {
    static let idleBaselineS = 30.0  // run_measured.sh records an idle baseline before work starts
    static let maxGenToks = 2048

    let prompts: PromptFile = {
        let url = Bundle.main.url(forResource: "mmlupro", withExtension: "json")!
        return try! JSONDecoder().decode(PromptFile.self, from: Data(contentsOf: url))
    }()

    var status = "idle"
    var done = 0
    var total = 0
    var correct = 0
    var lastTokS = 0.0
    var lastAnswer = ""
    var lastOK = false

    // Model downloads (Models.swift). Disk status is read from the files; modelTick re-reads it.
    var modelProgress: [GemmaModel: Double] = [:]
    var modelError: [GemmaModel: String] = [:]
    var modelTick = 0
    private var downloadJobs: [GemmaModel: Task<Void, Never>] = [:]

    @discardableResult
    func download(_ m: GemmaModel) -> Task<Void, Never> {
        if let job = downloadJobs[m] { return job }
        modelError[m] = nil
        modelProgress[m] = 0
        UIApplication.shared.isIdleTimerDisabled = true
        let job = Task {
            do {
                try await ModelStore.download(m) { done, total in
                    Task { @MainActor in self.modelProgress[m] = Double(done) / Double(max(total, 1)) }
                }
            } catch {
                let cancelled = error is CancellationError || (error as? URLError)?.code == .cancelled
                if !cancelled { modelError[m] = error.localizedDescription }
            }
            modelProgress[m] = nil
            downloadJobs[m] = nil
            modelTick += 1
            if downloadJobs.isEmpty && !running { UIApplication.shared.isIdleTimerDisabled = false }
        }
        downloadJobs[m] = job
        return job
    }

    /// One after the other, so each gets the full bandwidth and E2B is usable first.
    func downloadAll() {
        Task {
            for m in GemmaModel.allCases {
                if !ModelStore.status(m).complete {
                    await download(m).value  // ends with the text-only step
                } else if !ModelStore.isTextOnly(m) {
                    do { try await Task.detached { try ModelStore.makeTextOnly(m) }.value } catch { modelError[m] = error.localizedDescription }
                    modelTick += 1
                }
            }
        }
    }

    func cancelDownload(_ m: GemmaModel) { downloadJobs[m]?.cancel() }

    func deleteModel(_ m: GemmaModel) {
        try? ModelStore.delete(m)
        modelTick += 1
    }
    var running = false
    var log: [String] = []
    var current: RunRecord?  // the live run, for the detail sheet
    /// Battery energy capacity, the one calibration knob for the iPhone energy estimate:
    /// nominal Wh x Battery Health %. Stored per run so later edits don't rewrite history.
    var batteryWh: Double = UserDefaults.standard.object(forKey: "batteryWh") as? Double ?? Telemetry.nominalBatteryWh {
        didSet { UserDefaults.standard.set(batteryWh, forKey: "batteryWh") }
    }
    var runs: [RunRecord] = RunRecord.loadAll()
    private var job: Task<Void, Never>?

    /// agentic-edge dashboard API (benchmark/apps/ios's home repo). Empty URL = never upload.
    var apiURL = UserDefaults.standard.string(forKey: "apiURL") ?? "https://edge-monitor.chaoticraccon.cloud" {
        didSet { UserDefaults.standard.set(apiURL, forKey: "apiURL") }
    }
    /// The dashboard's API_TOKEN; Keychain, never UserDefaults. First launch seeds it from the build's
    /// git-ignored Secrets.xcconfig (via Info.plist), so the token never lands in the repo.
    var apiToken = Keychain.get("apiToken") ?? (Bundle.main.object(forInfoDictionaryKey: "APIToken") as? String ?? "") {
        didSet { Keychain.set("apiToken", apiToken) }
    }

    var autoUpload = UserDefaults.standard.object(forKey: "autoUpload") as? Bool ?? true {
        didSet { UserDefaults.standard.set(autoUpload, forKey: "autoUpload") }
    }

    /// Checks URL + token without touching the boards: a missing iPhone run is a 404 when the
    /// token is accepted and a 401 when it isn't.
    func testConnection() async -> String {
        guard let base = URL(string: apiURL.trimmingCharacters(in: .whitespaces)), base.host != nil else {
            return "Set the dashboard URL first."
        }
        var req = URLRequest(url: base.appending(path: "api/run").appending(queryItems: [
            .init(name: "box", value: "iphone"), .init(name: "run", value: "connection-test")]), timeoutInterval: 20)
        if !apiToken.isEmpty { req.setValue("Bearer \(apiToken)", forHTTPHeaderField: "Authorization") }
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            switch (resp as? HTTPURLResponse)?.statusCode ?? 0 {
            case 404, 200: return "OK — dashboard reachable, token accepted."
            case 401: return "Token rejected (401). Check API_TOKEN in dashboard/.env.local."
            case 400: return "Reachable, but this dashboard has no iPhone support yet — deploy the ios-app branch."
            case let c: return "Dashboard answered HTTP \(c) — is it running behind the tunnel?"
            }
        } catch {
            return "Can't reach it: \(error.localizedDescription)"
        }
    }

    /// POST the run to /api/phone; the dashboard then serves it as box "iphone". The result is
    /// kept on the run either way, so a failed upload shows and can be retried.
    func upload(_ rec: RunRecord, record: Bool = true) async -> String {
        guard let base = URL(string: apiURL.trimmingCharacters(in: .whitespaces)), base.host != nil else {
            return "upload failed: set the dashboard URL"
        }
        var req = URLRequest(url: base.appending(path: "api/phone"), timeoutInterval: 120)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiToken.isEmpty { req.setValue("Bearer \(apiToken)", forHTTPHeaderField: "Authorization") }
        var msg: String
        do {
            req.httpBody = try JSONSerialization.data(withJSONObject: rec.apiPayload())
            let (data, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            msg = code == 200 ? "uploaded \(Date().formatted(date: .abbreviated, time: .shortened))"
                : "upload failed: HTTP \(code) \(String(decoding: data.prefix(160), as: UTF8.self))"
        } catch {
            msg = "upload failed: \(error.localizedDescription)"
        }
        // A live upload never writes run.json: it holds a snapshot, and a slow upload finishing
        // after the next question would overwrite newer answers with older ones.
        guard record else { return msg }
        var r = rec
        r.uploaded = msg
        r.save(in: RunRecord.root.appending(path: rec.dir))
        runs = RunRecord.loadAll()
        return msg
    }

    static let liveEvery = 10
    private var liveUploading = false

    /// Mid-run snapshot (status "running") so the dashboard's Monitor shows the phone live.
    /// Fire and forget: inference doesn't wait on the network.
    private func liveUpload(_ rec: RunRecord) {
        guard !liveUploading else { return }  // ponytail: skip a tick rather than queue uploads behind a slow network
        liveUploading = true
        Task {
            let msg = await upload(rec, record: false)
            if !msg.hasPrefix("uploaded") { log.append("live upload: \(msg)") }
            liveUploading = false
        }
    }

    func start(_ plan: [(GemmaModel, String)]) {
        guard !running else { return }
        running = true
        UIApplication.shared.isIdleTimerDisabled = true  // screen lock would suspend Metal mid-run
        job = Task {
            for (m, s) in plan where !Task.isCancelled {
                await runOne(m, s)
            }
            UIApplication.shared.isIdleTimerDisabled = false
            running = false
        }
    }

    func stop() { job?.cancel() }

    private func say(_ s: String) {
        status = s
        log.append("\(Date().formatted(date: .omitted, time: .standard)) \(s)")
    }

    private func runOne(_ model: GemmaModel, _ subset: String) async {
        let docs = prompts.subsets[subset] ?? []
        // Download before anything is measured: the idle baseline and timings must not include it.
        if !ModelStore.status(model).complete {
            say("mmlupro-\(model.rawValue)-\(subset): downloading \(model.repo) first")
            await download(model).value
            guard ModelStore.status(model).complete else {
                say("mmlupro-\(model.rawValue)-\(subset): not run — download failed: \(modelError[model] ?? "cancelled")")
                return
            }
        }
        // Existing downloads predate the text-only step: convert once, before anything is measured.
        if ModelStore.status(model).complete && !ModelStore.isTextOnly(model) {
            say("mmlupro-\(model.rawValue)-\(subset): making \(model.rawValue.uppercased()) text-only (one-time)")
            do {
                try await Task.detached { try ModelStore.makeTextOnly(model) }.value
                modelTick += 1
            } catch {
                say("mmlupro-\(model.rawValue)-\(subset): not run — \(error.localizedDescription)")
                return
            }
        }
        let stamp = Self.stampFmt.string(from: Date())
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let label = "mmlupro-\(model.rawValue)-\(subset)"
        let mdir = root.appending(path: "measured/\(label)-\(stamp)")
        let sdir = root.appending(path: "stdbench/mmlupro100-\(model.rawValue)-\(subset)")
        try? FileManager.default.createDirectory(at: mdir, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(at: sdir, withIntermediateDirectories: true)
        (done, total, correct) = (0, docs.count, 0)
        var rec = RunRecord(dir: mdir.lastPathComponent, label: label, model: model.rawValue, subset: subset,
                            status: "running", loadS: 0, qa: [], telemetry: [], batteryWh: batteryWh > 0 ? batteryWh : nil)
        current = rec

        let params = GenerateParameters(maxTokens: Self.maxGenToks, temperature: 0)  // greedy -> ArgMaxSampler
        var meta: [String: Any] = [
            "label": label, "model": model.rawValue, "subset": subset, "model_repo": model.repo,
            "base_model": model.base, "engine_id": model.engine, "quantization": model.quant,
            "engine": "mlx-swift-lm 3.31.4 / mlx-swift 0.31.4 (LLMModelFactory, text-only)",
            "server_args": "maxTokens=\(Self.maxGenToks) temperature=0 (argmax) enable_thinking=false extraEOS=<turn|> until=Question: kv=full prefillStep=\(params.prefillStepSize) (all but the last prompt token, cache only; last token alone) mlxCache=32MB",
            "host": Telemetry.machine, "os": UIDevice.current.systemName + " " + UIDevice.current.systemVersion,
            "cpus": ProcessInfo.processInfo.processorCount,
            "ram_mb": ProcessInfo.processInfo.physicalMemory >> 20,
            "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled,
            "thermal_at_start": ProcessInfo.processInfo.thermalState.rawValue,
            "start_epoch": Date().timeIntervalSince1970,
            "idle_baseline_s": Self.idleBaselineS,
            "model_revision": model.revision,
            "weights": "text-only: language_model.* tensors byte-identical; audio/vision towers dropped (llama.cpp's GGUF is text-only too)",
            // inside the measured window: ~1 s of radio every N questions (dashboard live view)
            "live_upload_every": autoUpload && !apiURL.isEmpty ? Self.liveEvery : 0,
        ]
        writeJSON(meta, mdir.appending(path: "meta.json"))

        let tel = Telemetry()
        tel.start(mdir.appending(path: "telemetry.csv"))
        let reqCSV = mdir.appending(path: "requests.csv")
        append(reqCSV, "task,slot,end_epoch,end_iso,start_epoch,prompt_tokens,prompt_ms,prompt_tok_s,gen_tokens,gen_ms,gen_tok_s,total_ms,question_id,stop\n")

        var results: [(Doc, ReqResult, String)] = []
        var runStatus = "done"
        var loadS = 0.0
        do {
            say("\(label): idle baseline \(Int(Self.idleBaselineS))s")
            try await Task.sleep(for: .seconds(Self.idleBaselineS))

            say("\(label): loading \(model.repo) from the phone")
            Memory.cacheLimit = 32 << 20  // freed buffers MLX keeps count against the ~6 GiB app limit too
            let t0 = Date()
            // A .directory configuration never touches the downloader; the files are already local.
            let container = try await LLMModelFactory.shared.loadContainer(
                from: #hubDownloader(), using: #huggingFaceTokenizerLoader(),
                configuration: ModelConfiguration(directory: model.dir, extraEOSTokens: ["<turn|>"]))
            loadS = Date().timeIntervalSince(t0)
            rec.loadS = loadS
            say("\(label): loaded in \(Int(loadS))s, running \(docs.count) questions")

            for (i, d) in docs.enumerated() {
                try Task.checkCancellation()
                let r = try await container.perform { ctx in try await Self.ask(d, ctx, params) }
                let got = extractAnswer(r.text)
                results.append((d, r, got))
                done = i + 1
                if got == d.target { correct += 1 }
                lastAnswer = "\(d.task.dropFirst(10)) #\(d.doc_id): got \(got), gold \(d.target)"
                lastOK = got == d.target
                lastTokS = r.decodeTokS
                append(reqCSV, r.csvRow(task: i, qid: d.question_id))
                appendSample(sdir, stamp, d, r, got)
                rec.qa.append(QA(i: i, task: d.task, docID: d.doc_id, question: d.question,
                                 options: d.options, gold: d.target, got: got, r: r, questionID: d.question_id))
                rec.telemetry = tel.samples
                rec.save(in: mdir)
                current = rec
                if autoUpload && !apiURL.isEmpty && (i + 1) % Self.liveEvery == 0 && i + 1 < docs.count { liveUpload(rec) }
            }
        } catch is CancellationError {
            runStatus = "stopped"
        } catch {
            runStatus = "failed: \(error)"
        }
        tel.stop()
        Memory.clearCache()

        meta["end_epoch"] = Date().timeIntervalSince1970
        meta["load_s"] = loadS
        meta["status"] = runStatus
        writeJSON(meta, mdir.appending(path: "meta.json"))
        writeResults(sdir, stamp, results)
        var sum = summary(model, subset, results, tel, runStatus, loadS)
        // Not board DC draw: whole-phone battery drain (screen included), 1% steps x capacity.
        sum["energy_wh_battery_est"] = rec.energyWh ?? NSNull()
        sum["mean_w_battery_est"] = rec.meanW ?? NSNull()
        sum["j_per_token_battery_est"] = rec.jPerToken ?? NSNull()
        sum["battery_wh_capacity"] = rec.batteryWh ?? NSNull()
        sum["battery_used_pct"] = rec.batteryUsed ?? NSNull()
        writeJSON(sum, mdir.appending(path: "summary.json"))
        rec.status = runStatus
        rec.telemetry = tel.samples
        rec.save(in: mdir)
        current = rec
        runs = RunRecord.loadAll()
        writeComparison()
        if autoUpload && !apiURL.isEmpty { say("\(label): \(await upload(rec))") }
        say("\(label): \(runStatus) — \(correct)/\(done) correct")
    }

    /// One MMLU-Pro request: chat template (thinking off, as llama.cpp -rea off), greedy decode,
    /// stop at "Question:" or EOS or 2048 tokens.
    nonisolated private static func ask(_ d: Doc, _ ctx: ModelContext, _ params: GenerateParameters) async throws -> ReqResult {
        let messages: [[String: any Sendable]] = d.messages.map { $0 }
        let prompt = try ctx.tokenizer.applyChatTemplate(
            messages: messages, tools: nil, additionalContext: ["enable_thinking": false])
        let start = Date()
        var first: Date?
        var out: [Int] = []
        var stop = "eos"
        // Prefill everything but the last token ourselves, in the same prefillStepSize chunks,
        // evaluating only the KV cache. mlx-swift-lm's own prepare hands the generator the last
        // chunk (up to 512 tokens), and Gemma 4 then projects every one of those positions onto
        // its 262,144-word vocabulary (plus a softcap copy) to use only the last: ~400 MB that put
        // E4B over the 8 GB iPhone's ~6 GiB app limit on its first question (2026-10-04).
        let cache = ctx.model.newCache(parameters: params)
        let tokens = MLXArray(prompt)
        var pos = 0
        while pos < prompt.count - 1 {
            let end = min(pos + params.prefillStepSize, prompt.count - 1)
            _ = ctx.model(tokens[pos ..< end][.newAxis], cache: cache)  // logits stay lazy: never computed
            eval(cache)
            pos = end
        }
        let (stream, task) = try generateTokensTask(
            input: LMInput(tokens: tokens[(prompt.count - 1)...]), cache: cache, parameters: params, context: ctx)
        for await g in stream {
            guard case .token(let t) = g else { continue }
            if first == nil { first = Date() }
            out.append(t)
            // Stop string check on the tail only; "Question:" spans at most a few tokens.
            if ctx.tokenizer.decode(tokenIds: Array(out.suffix(8))).contains("Question:") {
                stop = "until"
                break
            }
        }
        task.cancel()
        await task.value  // don't let a stopped generation overlap the next request
        if stop == "eos" && out.count >= params.maxTokens ?? .max { stop = "length" }
        let end = Date()
        return ReqResult(
            promptTokens: prompt.count, genTokens: out.count, start: start, firstToken: first ?? end,
            end: end, text: cutAtStop(ctx.tokenizer.decode(tokenIds: out)), stop: stop)
    }

    // MARK: files — same names/columns as agentic-edge measured/ and lm-eval stdbench/

    private func appendSample(_ dir: URL, _ stamp: String, _ d: Doc, _ r: ReqResult, _ got: String) {
        let row: [String: Any] = [
            "doc_id": d.doc_id,
            "doc": ["question_id": d.question_id, "question": d.question, "options": d.options,
                    "answer": d.target, "answer_index": Int(d.target.unicodeScalars.first!.value) - 65,
                    "category": d.task.replacingOccurrences(of: "mmlu_pro_", with: "").replacingOccurrences(of: "_", with: " "),
                    "src": d.src],
            "target": d.target,
            "arguments": ["gen_args_0": [
                "arg_0": [String(data: try! JSONSerialization.data(withJSONObject: d.messages), encoding: .utf8)!],
                "arg_1": ["until": ["Question:"], "max_gen_toks": Self.maxGenToks, "do_sample": false, "temperature": 0.0],
            ]],
            "resps": [[r.text]], "filtered_resps": [got], "filter": "custom-extract",
            "metrics": ["exact_match"], "exact_match": got == d.target ? 1.0 : 0.0,
            "prompt_tokens": r.promptTokens, "gen_tokens": r.genTokens, "stop": r.stop,
        ]
        let line = String(data: try! JSONSerialization.data(withJSONObject: row), encoding: .utf8)! + "\n"
        append(dir.appending(path: "samples_\(d.task)_\(stamp).jsonl"), line)
    }

    private func writeResults(_ dir: URL, _ stamp: String, _ rs: [(Doc, ReqResult, String)]) {
        func em(_ xs: [(Doc, ReqResult, String)]) -> [String: Any] {
            let n = Double(xs.count), p = xs.isEmpty ? 0 : Double(xs.filter { $0.2 == $0.0.target }.count) / n
            return ["sample_len": xs.count, "exact_match,custom-extract": p,
                    "exact_match_stderr,custom-extract": n > 1 ? (p * (1 - p) / (n - 1)).squareRoot() : 0]
        }
        var res: [String: Any] = ["mmlu_pro": em(rs).merging(["name": "mmlu_pro", "alias": "mmlu_pro"]) { a, _ in a }]
        for (task, xs) in Dictionary(grouping: rs, by: { $0.0.task }) {
            res[task] = em(xs).merging(["name": task, "alias": String(task.dropFirst(9))]) { a, _ in a }
        }
        writeJSON(["results": res, "config": ["model": "mlx-swift-lm", "num_fewshot": 5, "max_gen_toks": Self.maxGenToks]],
                  dir.appending(path: "results_\(stamp).json"))
    }

    private func summary(_ m: GemmaModel, _ s: String, _ rs: [(Doc, ReqResult, String)], _ tel: Telemetry,
                         _ status: String, _ loadS: Double) -> [String: Any] {
        let n = Double(rs.count)
        let ok = Double(rs.filter { $0.2 == $0.0.target }.count)
        let p = n > 0 ? ok / n : 0
        let genTok = rs.reduce(0) { $0 + $1.1.genTokens }, promptTok = rs.reduce(0) { $0 + $1.1.promptTokens }
        let genS = rs.reduce(0.0) { $0 + $1.1.end.timeIntervalSince($1.1.firstToken) }
        let preS = rs.reduce(0.0) { $0 + $1.1.firstToken.timeIntervalSince($1.1.start) }
        let warm = rs.dropFirst().map { $0.1.end.timeIntervalSince($0.1.start) * 1000 }.sorted()
        let run = tel.samples.filter { $0.t >= 0 }, idle = tel.samples.filter { $0.t < 0 }
        let ref = prompts.reference["\(m.base)-\(s)"] ?? [:]
        let why = "iOS exposes no power rails; only battery_level at 1% steps. See battery_* fields."
        var out: [String: Any] = [
            "status": status, "n": rs.count, "score": (p * 1000).rounded() / 10,
            "stderr": n > 1 ? ((p * (1 - p) / (n - 1)).squareRoot() * 1000).rounded() / 10 : 0,
            "invalid": rs.filter { $0.2 == "[invalid]" }.count,
            "minutes": ((rs.last?.1.end.timeIntervalSince(rs.first?.1.start ?? .now) ?? 0) / 60).rounded(),
            "load_s": loadS,
            "gen_tokens": genTok, "prompt_tokens": promptTok,
            "decode_tok_s": genS > 0 ? Double(genTok - rs.count) / genS : 0,
            "prefill_tok_s": preS > 0 ? Double(promptTok) / preS : 0,
            "cold_total_ms": rs.first.map { $0.1.end.timeIntervalSince($0.1.start) * 1000 } ?? 0,
            "warm_median_total_ms": warm.isEmpty ? 0 : warm[warm.count / 2],
            "stops": Dictionary(grouping: rs, by: { $0.1.stop }).mapValues(\.count),
            "cpu_mean": run.isEmpty ? 0 : run.map(\.cpu).reduce(0, +) / Double(run.count),
            "cpu_idle_mean": idle.isEmpty ? 0 : idle.map(\.cpu).reduce(0, +) / Double(idle.count),
            "thermal_max": run.map(\.thermal).max() ?? 0,
            "thermal_serious_s": run.filter { $0.thermal >= 2 }.count,
            "mem_footprint_peak_mb": run.map(\.footprint).max() ?? 0,
            "mlx_peak_mb": Double(Memory.peakMemory >> 20),
            "battery_start": tel.samples.first?.battery ?? -1, "battery_end": tel.samples.last?.battery ?? -1,
            "battery_state_end": tel.samples.last?.batteryState ?? 0,
            "energy_wh": NSNull(), "idle_w": NSNull(), "mean_w": NSNull(), "peak_w": NSNull(), "j_per_token": NSNull(),
            "na_reasons": ["energy_wh": why, "idle_w": why, "mean_w": why, "peak_w": why, "j_per_token": why,
                           "temp_max": "iOS exposes thermalState (0 nominal..3 critical), not temperature; see thermal_max"],
        ]
        out["reference"] = ref.mapValues { ["run": $0.run, "score": $0.score, "decode_tok_s": $0.decode_tok_s ?? 0,
                                             "prompt_tokens_total": $0.prompt_tokens_total] }
        // Parity check on request 0, the only one llama.cpp's prefix cache can't shorten:
        // 1.0 = same chat template and tokenizer as the boards.
        if let pi = ref["pi"]?.first_prompt_tokens, pi > 0, let first = rs.first {
            out["first_prompt_tokens_vs_pi"] = Double(first.1.promptTokens) / Double(pi)
        }
        return out
    }

    /// Documents/comparison.md — the iPhone vs Pi 5 vs Jetson table for the GitHub write-up. Latest
    /// complete run per model × subset, plus the pooled n=300 row per model as agentic-edge reports it.
    func writeComparison() {
        let done = Dictionary(grouping: runs.filter { $0.status == "done" && $0.n == 100 }, by: { "\($0.model)-\($0.subset)" })
            .compactMapValues(\.first)  // runs are newest first
        func cell(_ x: Double?, _ d: Int = 1) -> String { x.map { fmt($0, d) } ?? "—" }
        var md = """
        # Gemma 4 MMLU-Pro: \(Telemetry.deviceName) vs Raspberry Pi 5 vs Jetson Orin Nano

        lm-eval `mmlu_pro` 5-shot CoT, greedy, 2048 max tokens, thinking off; 100 stratified questions per subset \
        (agentic-edge s1/s2/s3). Same Gemma 4 QAT 4-bit checkpoints: MLX on the iPhone, GGUF Q4_K_XL under llama.cpp on the boards. \
        Decode tok/s: iPhone = per-request median (MLX), boards = run summary (llama.cpp). No power on iPhone (iOS exposes no rails).

        Time = minutes for the 100 requests. Energy: boards = measured board DC draw. iPhone = battery-side, whole phone incl. \
        screen: measured from PowerLog (battery V x I, mean W x run time) where attached; `*` = estimate from battery % used x \
        capacity (\(fmt(batteryWh, 2)) Wh set in the app), 1% resolution.

        | model | subset | iPhone % | Pi 5 % | Jetson % | iPhone tok/s | Pi 5 tok/s | Jetson tok/s | iPhone min | Pi 5 min | Jetson min | iPhone Wh (est) | Pi 5 Wh | Jetson Wh | iPhone thermal max | iPhone run |
        |---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

        """
        for m in GemmaModel.allCases {
            var pooled = (ok: 0, n: 0)
            for sub in ["s1", "s2", "s3"] {
                let r = done["\(m.rawValue)-\(sub)"], ref = prompts.reference["\(m.base)-\(sub)"] ?? [:]
                if let r { pooled = (pooled.ok + r.correct, pooled.n + r.n) }
                md += "| \(m.title) | \(sub) | \(cell(r?.score)) | \(cell(ref["pi"]?.score)) | \(cell(ref["jetson"]?.score)) | "
                    + "\(cell(r?.medianDecode, 2)) | \(cell(ref["pi"]?.decode_tok_s, 2)) | \(cell(ref["jetson"]?.decode_tok_s, 2)) | "
                    + "\(cell(r?.minutes, 0)) | \(cell(ref["pi"]?.minutes, 0)) | \(cell(ref["jetson"]?.minutes, 0)) | "
                    + "\(cell(r?.bestWh, 2))\(r?.measuredWh == nil && r?.energyWh != nil ? "*" : "") | \(cell(ref["pi"]?.energy_wh, 2)) | \(cell(ref["jetson"]?.energy_wh, 2)) | "
                    + "\(r.map { thermalNames[$0.thermalMax] } ?? "—") | \(r?.dir ?? "not run") |\n"
            }
            let refPool = { (b: String) -> Double? in
                let xs = ["s1", "s2", "s3"].compactMap { self.prompts.reference["\(m.base)-\($0)"]?[b]?.score }
                return xs.count == 3 ? xs.reduce(0, +) / 3 : nil
            }
            md += "| **\(m.title)** | **pooled n=\(pooled.n)** | **\(pooled.n == 300 ? fmt(100 * Double(pooled.ok) / 300, 1) : "—")** | "
                + "**\(cell(refPool("pi")))** | **\(cell(refPool("jetson")))** | | | | | | | | | | | |\n"
        }
        md += "\nGenerated by GemmaBench on \(Telemetry.deviceName) (\(Telemetry.machine)), iOS \(UIDevice.current.systemVersion), \(Date().formatted()).\n"
        let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appending(path: "comparison.md")
        try? md.write(to: url, atomically: true, encoding: .utf8)
    }

    static let stampFmt: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f
    }()
}

extension ReqResult {
    var promptMs: Double { firstToken.timeIntervalSince(start) * 1000 }
    var genMs: Double { end.timeIntervalSince(firstToken) * 1000 }
    /// Tokens after the first over the time after the first (the first token belongs to prefill).
    var decodeTokS: Double { genMs > 0 ? Double(max(genTokens - 1, 0)) / genMs * 1000 : 0 }

    func csvRow(task: Int, qid: Int) -> String {
        let f = { (x: Double) in String(format: "%.2f", x) }
        let e = end.timeIntervalSince1970
        return [String(task), "0", String(Int(e)), ISO8601DateFormatter().string(from: end),
                String(format: "%.3f", start.timeIntervalSince1970), String(promptTokens), f(promptMs),
                f(promptMs > 0 ? Double(promptTokens) / promptMs * 1000 : 0), String(genTokens), f(genMs),
                f(decodeTokS), f(promptMs + genMs), String(qid), stop].joined(separator: ",") + "\n"
    }
}

enum Keychain {
    static func get(_ key: String) -> String? {
        var out: CFTypeRef?
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key,
                                kSecReturnData as String: true]
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }

    static func set(_ key: String, _ value: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key]
        SecItemDelete(q as CFDictionary)
        guard !value.isEmpty else { return }
        var add = q
        add[kSecValueData as String] = Data(value.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)
    }
}

func writeJSON(_ obj: Any, _ url: URL) {
    try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]).write(to: url)
}

/// Append-as-you-go, so a crash or a stop still leaves every finished request on disk.
func append(_ url: URL, _ s: String) {
    guard let h = try? FileHandle(forWritingTo: url) else {
        try? s.data(using: .utf8)!.write(to: url)
        return
    }
    h.seekToEndOfFile()
    h.write(s.data(using: .utf8)!)
    try? h.close()
}
