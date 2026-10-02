import Charts
import SwiftUI
import UniformTypeIdentifiers

// MARK: - Saved run (Documents/measured/<run>/run.json)

struct QA: Codable, Identifiable, Sendable {
    var id: Int { i }
    let i: Int
    let task: String
    let docID: Int
    let question: String
    let options: [String]
    let gold: String
    let got: String
    let r: ReqResult
    var questionID: Int?  // MMLU-Pro's own id: what pairs this answer with the boards' (McNemar)
    var ok: Bool { got == gold }
    var subject: String { task.dropFirst(9).replacingOccurrences(of: "_", with: " ") }
}

struct RunRecord: Codable, Identifiable {
    var id: String { dir }
    let dir: String
    let label: String
    let model: String
    let subset: String
    var status: String
    var loadS: Double
    var qa: [QA]
    var telemetry: [Telemetry.Sample]
    var batteryWh: Double?
    var power: PowerData?  // attached Power Profiler export (prep/power_trace.py)
    var uploaded: String?  // last /api/phone result, shown in the run header

    static var root: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appending(path: "measured")
    }

    func save(in dir: URL) {
        try? JSONEncoder().encode(self).write(to: dir.appending(path: "run.json"))
    }

    /// Every run on disk, newest first — failed and stopped included (report every run).
    static func loadAll() -> [RunRecord] {
        let dirs = (try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? []
        return dirs.compactMap { try? JSONDecoder().decode(RunRecord.self, from: Data(contentsOf: $0.appending(path: "run.json"))) }
            .sorted { $0.dir.suffix(15) > $1.dir.suffix(15) }
    }

    // derived, the same aggregates summary.json carries
    var n: Int { qa.count }
    var correct: Int { qa.filter(\.ok).count }
    var score: Double { n > 0 ? 100 * Double(correct) / Double(n) : 0 }
    var stderr: Double { let p = score / 100; return n > 1 ? 100 * (p * (1 - p) / Double(n - 1)).squareRoot() : 0 }
    var minutes: Double { guard let a = qa.first, let b = qa.last else { return 0 }; return b.r.end.timeIntervalSince(a.r.start) / 60 }
    var medianDecode: Double { median(qa.map(\.r.decodeTokS)) }
    var run: [Telemetry.Sample] { telemetry.filter { $0.t >= 0 } }
    var cpuMean: Double { mean(run.map(\.cpu)) }
    var thermalMax: Int { run.map(\.thermal).max() ?? 0 }
    var thermalSeriousS: Int { run.filter { $0.thermal >= 2 }.count }
    var memPeakMB: Double { run.map(\.footprint).max() ?? 0 }
    var prefillTokS: Double {
        let s = qa.reduce(0.0) { $0 + $1.r.promptMs } / 1000
        return s > 0 ? Double(qa.reduce(0) { $0 + $1.r.promptTokens }) / s : 0
    }
    /// Battery % used across the requests (load and idle baseline excluded). nil if the phone was
    /// ever on the charger (batteryState 1 = unplugged) — then the delta means nothing.
    var batteryUsed: Double? {
        guard let s = qa.first?.r.start.timeIntervalSince1970, let e = qa.last?.r.end.timeIntervalSince1970 else { return nil }
        let w = telemetry.filter { $0.ts >= s - 1 && $0.ts <= e + 1 }
        guard let a = w.first, let b = w.last, a.battery >= 0, w.allSatisfy({ $0.batteryState == 1 }) else { return nil }
        return Double(a.battery - b.battery) * 100
    }
    /// Estimates from battery drain x capacity. Whole phone incl. screen, 1% steps: coarse on short runs.
    var energyWh: Double? { batteryUsed.flatMap { u in batteryWh.map { u / 100 * $0 } } }
    var meanW: Double? { bestWh.flatMap { minutes > 0 ? $0 / (minutes / 60) : nil } }
    var jPerToken: Double? {
        let g = qa.reduce(0) { $0 + $1.r.genTokens }
        return bestWh.flatMap { g > 0 ? $0 * 3600 / Double(g) : nil }
    }

    /// What the phone was doing during one request: the telemetry samples inside its window.
    func dev(_ q: QA) -> (cpu: Double, thermal: Int, mem: Double, samples: Int)? {
        let s = telemetry.filter { $0.ts >= q.r.start.timeIntervalSince1970 && $0.ts <= q.r.end.timeIntervalSince1970 }
        guard !s.isEmpty else { return nil }
        return (mean(s.map(\.cpu)), s.map(\.thermal).max()!, s.map(\.footprint).max()!, s.count)
    }
}

// MARK: - Power Profiler (relative "power impact", not watts)

struct PowerData: Codable {
    struct Series: Codable { let name: String; let t: [Double]; let v: [Double] }
    let source: String
    let kind: String?  // "impact" = Power Profiler score, "watts" = PowerLog battery V x I
    let trace_start: Double
    let series: [Series]
    var isWatts: Bool { kind == "watts" }
}

/// Unit from the series name suffix power_trace.py writes.
func unit(_ name: String) -> String {
    name.hasSuffix("_w") ? "W" : name.hasSuffix("_v") ? "V" : name.hasSuffix("_a") ? "A" : name.hasSuffix("_c") ? "°C" : ""
}

extension RunRecord {
    var window: ClosedRange<Double>? {
        guard let a = qa.first?.r.start.timeIntervalSince1970, let b = qa.last?.r.end.timeIntervalSince1970, a <= b else { return nil }
        return a...b
    }
    /// Series that overlap the requests, most interesting (cpu, gpu, display, network) first.
    var powerSeries: [PowerData.Series] {
        guard let power, let w = window else { return [] }
        let rank = { (n: String) in ["power_w", "cpu", "gpu", "display", "network", "temp"].firstIndex { n.lowercased().contains($0) } ?? 9 }
        return power.series.filter { $0.t.contains(where: w.contains) }.sorted { rank($0.name) < rank($1.name) }
    }
    /// Measured battery power over the requests (PowerLog). Needs >= 3 samples in the window:
    /// PowerLog samples every few tens of seconds, so short runs get no measured figure.
    var powerW: PowerData.Series? { power?.isWatts == true ? power?.series.first { $0.name.hasSuffix("power_w") } : nil }
    var measuredW: [Double] {
        guard let s = powerW, let w = window else { return [] }
        return zip(s.t, s.v).filter { w.contains($0.0) }.map(\.1)
    }
    var measuredWh: Double? {
        guard measuredW.count >= 3, let w = window else { return nil }
        return mean(measuredW) * (w.upperBound - w.lowerBound) / 3600
    }
    /// Measured beats estimated; everything downstream reads this.
    var bestWh: Double? { measuredWh ?? energyWh }
    var energySource: String {
        measuredWh != nil ? "measured · PowerLog battery V×I" : energyWh != nil ? "estimate · battery % × capacity" : "none"
    }
    func powerMean(_ s: PowerData.Series, _ w: ClosedRange<Double>) -> Double? {
        let v = zip(s.t, s.v).filter { w.contains($0.0) }.map(\.1)
        return v.isEmpty ? nil : mean(v)
    }
    func powerMean(_ s: PowerData.Series, _ q: QA) -> Double? {
        powerMean(s, q.r.start.timeIntervalSince1970...q.r.end.timeIntervalSince1970)
    }
    /// power_summary.json next to summary.json, so the numbers leave the phone too.
    func writePowerSummary() {
        guard let power, let w = window else { return }
        var out: [String: Any] = ["source": power.source, "kind": power.kind ?? "impact",
                                  "unit": power.isWatts ? "battery-side W/V/A/°C from PowerLog" : "Power Profiler power impact (relative score, not watts)",
                                  "energy_wh": measuredWh.map { $0 as Any } ?? NSNull(),
                                  "mean_w": measuredW.isEmpty ? NSNull() : mean(measuredW) as Any,
                                  "peak_w": measuredW.max().map { $0 as Any } ?? NSNull(),
                                  "j_per_token": measuredWh != nil ? jPerToken as Any : NSNull(),
                                  "power_samples": measuredW.count]
        var ser: [String: Any] = [:]
        for s in powerSeries {
            let perReq: [Any] = qa.map { q in powerMean(s, q).map { $0 as Any } ?? NSNull() }
            ser[s.name] = ["run_mean": powerMean(s, w).map { $0 as Any } ?? NSNull(), "per_request": perReq]
        }
        out["series"] = ser
        writeJSON(out, RunRecord.root.appending(path: "\(dir)/power_summary.json"))
    }
}

func shortName(_ s: String) -> String { String(s.split(separator: "/").last ?? Substring(s)) }

func mean(_ v: [Double]) -> Double { v.isEmpty ? 0 : v.reduce(0, +) / Double(v.count) }
func median(_ v: [Double]) -> Double { v.isEmpty ? 0 : v.sorted()[v.count / 2] }
func fmt(_ x: Double, _ d: Int = 0) -> String { x.formatted(.number.precision(.fractionLength(d))) }
let thermalNames = ["nominal", "fair", "serious", "critical"]
let thermalColors: [Color] = [.green, .yellow, .orange, .red]

// MARK: - Detail sheet: Device tab + Questions tab, as agentic-edge RunDetail.js

struct RunDetailView: View {
    @State var rec: RunRecord
    let ref: [String: Ref]
    let upload: (RunRecord) async -> String
    @State private var uploading = false
    @State private var importing = false
    @State private var importError: String?
    @State private var tab = "device"
    @State private var filter = "all"
    @State private var open: Int?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        header
                        Picker("", selection: $tab) {
                            Text("Device").tag("device")
                            Text("Questions (\(rec.n))").tag("questions")
                        }.pickerStyle(.segmented)
                        if tab == "device" { device } else { questions }
                    }
                    .padding()
                }
                .onChange(of: open) { _, i in
                    if let i { withAnimation { proxy.scrollTo(i, anchor: .top) } }
                }
                .safeAreaInset(edge: .bottom) { if tab == "questions" && !shown.isEmpty { navigator } }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle(rec.label)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { Button("Done") { dismiss() } }
        }
    }

    /// Requests and answers are in the order the model produced them, so request #i is question #i.
    private func pick(_ i: Int) {
        filter = "all"
        tab = "questions"
        open = i
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("\(Telemetry.deviceName) · \(ProcessInfo.processInfo.physicalMemory >> 30) GB · iOS \(UIDevice.current.systemVersion)",
                  systemImage: "iphone")
                .font(.subheadline.weight(.semibold))
            HStack(spacing: 6) {
            Pill(rec.status == "done" ? "complete" : rec.status == "running" ? "in progress" : rec.status,
                 rec.status == "done" ? .green : rec.status == "running" ? .blue : .orange)
            Pill(String(format: "%.1f%% ±%.1f", rec.score, rec.stderr), .indigo)
            Pill("\(fmt(rec.minutes)) min", .gray)
            Pill("MLX", .blue)
            }
            HStack(spacing: 8) {
                if let u = rec.uploaded {
                    Pill(u, u.hasPrefix("uploaded") ? .green : .red)
                }
                Spacer()
                Button {
                    uploading = true
                    Task { rec.uploaded = await upload(rec); uploading = false }
                } label: {
                    Label(uploading ? "Uploading…" : rec.uploaded == nil ? "Upload to dashboard" : "Re-upload",
                          systemImage: "icloud.and.arrow.up")
                        .font(.caption.weight(.medium))
                }
                .disabled(uploading || rec.status == "running")
            }
        }
    }

    // MARK: device tab

    @ViewBuilder private var device: some View {
        Comparison(rec: rec, ref: ref)
        powerCard
        Card {
            HStack {
                Text("This iPhone").font(.headline)
                Spacer()
                rec.thermalSeriousS > 0
                    ? Pill("⚠ thermal serious · \(rec.thermalSeriousS)s", .orange)
                    : Pill("✓ never throttled", .green)
            }
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading) {
                    Text("Energy").font(.caption).foregroundStyle(.secondary)
                    Text(rec.bestWh.map { "\(fmt($0, 2)) Wh" } ?? "n/a").font(.largeTitle.weight(.semibold))
                    Text(rec.measuredWh != nil ? rec.energySource
                         : rec.batteryUsed == nil ? "phone was charging — no battery estimate"
                         : "estimate · \(fmt(rec.batteryUsed!))% battery × \(fmt(rec.batteryWh ?? 0, 2)) Wh · attach PowerLog for measured W")
                        .font(.caption2).foregroundStyle(rec.measuredWh != nil ? .green : .secondary)
                }
                Spacer()
            }
            Tiles {
                Tile("Decode", fmt(rec.medianDecode, 1), "tok/s", sub: "median")
                Tile("Prefill", fmt(rec.prefillTokS, 0), "tok/s", sub: "all requests")
                Tile("CPU", fmt(rec.cpuMean), "%", .blue, sub: "mean, % of one core")
                Tile("Peak thermal", thermalNames[rec.thermalMax], nil, thermalColors[rec.thermalMax], sub: "0 nominal … 3 critical")
                Tile("App memory", fmt(rec.memPeakMB / 1024, 2), "GB", .purple, sub: "phys_footprint peak")
                Tile("Model load", fmt(rec.loadS, 1), "s", sub: "outside request timing")
                Tile("Mean power", rec.meanW.map { fmt($0, 2) } ?? "—", "W", .orange, sub: "estimate")
                Tile("Energy / token", rec.jPerToken.map { fmt($0, 2) } ?? "—", "J/tok", .orange, sub: "estimate")
                Tile("Total time", fmt(rec.minutes, 1), "min", sub: "100 requests")
            }
        }

        Card {
            Section2("Request timeline", "tap a bar to open its question")
            Chart(rec.qa) { q in
                BarMark(x: .value("#", q.i + 1), y: .value("s", q.r.promptMs / 1000))
                    .foregroundStyle(by: .value("phase", "prefill"))
                BarMark(x: .value("#", q.i + 1), y: .value("s", q.r.genMs / 1000))
                    .foregroundStyle(by: .value("phase", "decode"))
            }
            .chartForegroundStyleScale(["prefill": Color.blue, "decode": Color.indigo])
            .chartYAxisLabel("seconds")
            .chartXSelection(value: Binding(get: { nil as Int? }, set: { if let i = $0 { pick(i - 1) } }))
            .frame(height: 160)

            if !rec.telemetry.isEmpty {
                Track(rec.telemetry, "CPU", "%", .blue) { $0.cpu }
                Track(rec.telemetry, "App memory", "MB", .purple) { $0.footprint }
                Track(rec.telemetry, "Thermal state", "", .orange) { Double($0.thermal) }
                Track(rec.telemetry, "Battery", "%", .green) { Double($0.battery) * 100 }
                Text("x = minutes into the run; left of 0 is the 30 s idle baseline").font(.caption2).foregroundStyle(.secondary)
            }
        }

        Card {
            Section2("Per request", "▲▼ = the run's extreme in that column")
            RequestTable(rec: rec, onPick: pick)
        }
    }

    // MARK: power profiler

    @ViewBuilder private var powerCard: some View {
        Card {
            HStack {
                Label(rec.power?.isWatts == true ? "Battery power" : "Power data",
                      systemImage: "bolt.horizontal.circle").font(.headline)
                Spacer()
                if let p = rec.power { p.isWatts ? Pill("measured W · PowerLog", .green) : Pill("power impact · not watts", .orange) }
                Button { importing = true } label: {
                    Image(systemName: rec.power == nil ? "square.and.arrow.down" : "arrow.triangle.2.circlepath")
                }
            }
            let series = rec.powerSeries
            if rec.power == nil {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Measured watts, any Xcode (PowerLog)").font(.caption.weight(.semibold))
                    Label("Right after the run, unplugged: press both volume buttons + side button ~1 s (sysdiagnose)", systemImage: "1.circle")
                    Label("~10 min later: Settings › Privacy › Analytics Data › sysdiagnose_… › share to the Mac", systemImage: "2.circle")
                    Label("python3 prep/power_trace.py --powerlog <sysdiagnose.tar.gz>", systemImage: "3.circle")
                    Label("Send the .power.json back, tap ↓ above and pick it", systemImage: "4.circle")
                    Text("Xcode 26 alternative: Power Profiler trace → python3 prep/power_trace.py <trace>")
                        .font(.caption2).padding(.top, 2)
                }
                .font(.caption).foregroundStyle(.secondary)
            } else if series.isEmpty {
                Label("This trace doesn't cover this run's time window.", systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
            } else if let w = rec.window {
                Tiles {
                    if rec.power?.isWatts == true {
                        Tile("Energy", rec.measuredWh.map { fmt($0, 2) } ?? "—", "Wh", .green,
                             sub: rec.measuredWh == nil ? "needs ≥ 3 samples in the run" : "mean W × run time")
                        Tile("Mean power", rec.measuredW.isEmpty ? "—" : fmt(mean(rec.measuredW), 2), "W", .orange)
                        Tile("Peak power", rec.measuredW.max().map { fmt($0, 2) } ?? "—", "W", .red)
                        Tile("Samples", "\(rec.measuredW.count)", nil, sub: "in the run window")
                        if let t = series.first(where: { $0.name.hasSuffix("temp_c") }) {
                            Tile("Battery temp", zip(t.t, t.v).filter { w.contains($0.0) }.map(\.1).max().map { fmt($0, 1) } ?? "—",
                                 "°C", .red, sub: "max in the run")
                        }
                    } else {
                        ForEach(series.prefix(6), id: \.name) { s in
                            Tile(shortName(s.name), rec.powerMean(s, w).map { fmt($0, 1) } ?? "—", nil, .orange, sub: "mean over the run")
                        }
                    }
                }
                ForEach(series.prefix(4), id: \.name) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(unit(s.name).isEmpty ? shortName(s.name) : "\(shortName(s.name)) (\(unit(s.name)))")
                            .font(.caption2).foregroundStyle(.orange)
                        Chart(Array(zip(s.t, s.v).filter { w.contains($0.0) }.enumerated()), id: \.offset) { _, p in
                            LineMark(x: .value("min", (p.0 - w.lowerBound) / 60), y: .value("value", p.1)).foregroundStyle(.orange)
                            if rec.power?.isWatts == true {
                                PointMark(x: .value("min", (p.0 - w.lowerBound) / 60), y: .value("value", p.1))
                                    .foregroundStyle(.orange).symbolSize(12)
                            }
                        }
                        .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) }
                        .frame(height: 70)
                    }
                }
                Text(rec.power?.isWatts == true
                     ? "x = minutes from the first request. Battery-side power from PowerLog (whole phone incl. screen), sparse samples."
                     : "x = minutes from the first request. Relative score from Apple's Power Profiler; compare runs on this iPhone, not with board watts.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let importError { Text(importError).font(.caption).foregroundStyle(.red) }
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.json]) { result in
            importError = nil
            do {
                let url = try result.get()
                let ok = url.startAccessingSecurityScopedResource()
                defer { if ok { url.stopAccessingSecurityScopedResource() } }
                rec.power = try JSONDecoder().decode(PowerData.self, from: Data(contentsOf: url))
                if rec.powerSeries.isEmpty { importError = "Imported, but no series overlaps this run — wrong trace?" }
                rec.save(in: RunRecord.root.appending(path: rec.dir))
                rec.writePowerSummary()
            } catch {
                importError = "Couldn't read that file: \(error.localizedDescription)"
            }
        }
    }

    // MARK: questions tab

    // MARK: bottom navigator — prev/next within the current filter, a jump to the next miss,
    // and a one-cell-per-question strip coloured by verdict for jumping anywhere.

    private func verdict(_ q: QA) -> Color { q.got == "[invalid]" ? .orange : q.ok ? .green : .red }

    private func step(_ d: Int) {
        let ids = shown.map(\.i)
        guard let first = ids.first else { return }
        guard let o = open, let p = ids.firstIndex(of: o) else { open = d > 0 ? first : ids.last; return }
        open = ids[min(max(p + d, 0), ids.count - 1)]
    }

    private func nextMiss() {
        let misses = shown.filter { !$0.ok }.map(\.i)
        open = misses.first { $0 > (open ?? -1) } ?? misses.first  // wraps around
    }

    private var navigator: some View {
        let ids = shown.map(\.i)
        let pos = open.flatMap { ids.firstIndex(of: $0) }
        return VStack(spacing: 8) {
            HStack(spacing: 12) {
                Button { step(-1) } label: { Image(systemName: "chevron.left.circle.fill").font(.title) }
                    .disabled(pos == 0)
                VStack(spacing: 1) {
                    Text(pos.map { "\($0 + 1) of \(ids.count)" } ?? "\(ids.count) questions")
                        .font(.subheadline.weight(.semibold).monospacedDigit())
                    if let o = open {
                        HStack(spacing: 4) {
                            Image(systemName: rec.qa[o].ok ? "checkmark.circle.fill" : "xmark.circle.fill").foregroundStyle(verdict(rec.qa[o]))
                            Text("#\(o + 1) · \(rec.qa[o].subject)").foregroundStyle(.secondary)
                        }
                        .font(.caption2)
                    } else {
                        Text("tap a cell or press next").font(.caption2).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity)
                if shown.contains(where: { !$0.ok }) {
                    Button { nextMiss() } label: {
                        Label("Next miss", systemImage: "arrow.down.to.line").font(.caption.weight(.medium))
                            .padding(.horizontal, 8).padding(.vertical, 5)
                            .background(Color.red.opacity(0.12), in: Capsule()).foregroundStyle(.red)
                    }
                }
                Button { step(1) } label: { Image(systemName: "chevron.right.circle.fill").font(.title) }
                    .disabled(pos == ids.count - 1)
            }
            .tint(.indigo)
            ScrollViewReader { strip in
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(spacing: 3) {
                        ForEach(shown) { q in
                            RoundedRectangle(cornerRadius: 3)
                                .fill(verdict(q).opacity(open == q.i ? 1 : 0.55))
                                .frame(width: open == q.i ? 16 : 10, height: open == q.i ? 26 : 20)
                                .overlay(RoundedRectangle(cornerRadius: 3).stroke(.primary, lineWidth: open == q.i ? 1.5 : 0))
                                .id(q.i)
                                .onTapGesture { open = q.i }
                                .accessibilityLabel("Question \(q.i + 1), \(q.ok ? "correct" : "wrong")")
                        }
                    }
                    .padding(.horizontal)
                    .animation(.snappy, value: open)
                }
                .frame(height: 28)
                .onChange(of: open) { _, i in if let i { withAnimation { strip.scrollTo(i, anchor: .center) } } }
            }
            .padding(.horizontal, -16)
        }
        .padding(.horizontal)
        .padding(.top, 10)
        .padding(.bottom, 4)
        .background(.bar)
    }

    private var shown: [QA] {
        rec.qa.filter {
            filter == "all" || (filter == "ok" && $0.ok) || (filter == "bad" && !$0.ok) || (filter == "none" && $0.got == "[invalid]")
        }
    }

    @ViewBuilder private var questions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                ForEach([("all", "All", Color.indigo), ("ok", "Correct", .green), ("bad", "Wrong", .red),
                         ("none", "No answer letter", .orange)], id: \.0) { v, l, c in
                    Chip(l, nil, c, selected: filter == v) { filter = v }
                }
            }
        }
        Text("\(shown.count) shown").font(.caption).foregroundStyle(.secondary)
        LazyVStack(spacing: 10) {
            ForEach(shown) { q in
                QuestionRow(q: q, rec: rec, open: open == q.i) { open = open == q.i ? nil : q.i }.id(q.i)
            }
        }
    }
}

// MARK: - one question

struct QuestionRow: View {
    let q: QA, rec: RunRecord, open: Bool, toggle: () -> Void

    private var verdictColor: Color { q.got == "[invalid]" ? .orange : q.ok ? .green : .red }
    private var verdictIcon: String {
        q.got == "[invalid]" ? "questionmark.circle.fill" : q.ok ? "checkmark.circle.fill" : "xmark.circle.fill"
    }

    var body: some View {
        Card {
            // Collapsed: verdict, subject, question — nothing else.
            Button(action: toggle) {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: verdictIcon).font(.title3).foregroundStyle(verdictColor)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 6) {
                            Pill(q.subject, .teal)
                            Text("#\(q.i + 1)").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        Text(q.question).font(.subheadline).lineLimit(open ? nil : 2).multilineTextAlignment(.leading)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.down").font(.caption).foregroundStyle(.tertiary)
                        .rotationEffect(.degrees(open ? 180 : 0))
                }
            }
            .buttonStyle(.plain)

            if open {
                Block("Options", "list.bullet", .blue) { options }
                Block("Model answer", "text.bubble", verdictColor) { answer }
                Perf(q: q, rec: rec)
            }
        }
    }

    private var options: some View {
        VStack(spacing: 4) {
            ForEach(Array(q.options.enumerated()), id: \.offset) { j, o in
                let L = String(UnicodeScalar(65 + j)!)
                let gold = L == q.gold, wrongPick = L == q.got && !q.ok
                HStack(alignment: .top, spacing: 8) {
                    Text(L).font(.caption.weight(.bold)).frame(width: 20, height: 20)
                        .foregroundStyle(gold || wrongPick ? .white : .secondary)
                        .background(gold ? Color.green : wrongPick ? .red : Color(.tertiarySystemFill), in: Circle())
                    Text(o).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(6)
                .background(gold ? Color.green.opacity(0.1) : wrongPick ? Color.red.opacity(0.1) : .clear,
                            in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    @ViewBuilder private var answer: some View {
        // Verdict first, in one line: the thing being read.
        HStack(spacing: 8) {
            Text(q.got == "[invalid]" ? "?" : q.got).font(.title2.weight(.bold)).foregroundStyle(verdictColor)
            Image(systemName: "arrow.right").font(.caption).foregroundStyle(.tertiary)
            Text(q.got == "[invalid]" ? "No answer letter found" : q.ok ? "Correct" : "Wrong — gold is \(q.gold)")
                .font(.subheadline.weight(.medium)).foregroundStyle(verdictColor)
        }
        ScrollViewReader { proxy in
            ScrollView {
                Text(highlighted(q.r.text))
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                Color.clear.frame(height: 1).id("end")
            }
            .frame(height: 240)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 10))
            .onAppear { proxy.scrollTo("end", anchor: .bottom) }  // the verdict is at the end of the reasoning
        }
        Label("\(q.r.text.count) chars · scroll up for the reasoning", systemImage: "arrow.up.and.down")
            .font(.caption2).foregroundStyle(.secondary)
    }

    /// Mark "the answer is (X)" the way the dashboard does.
    private func highlighted(_ s: String) -> AttributedString {
        var a = AttributedString(s)
        for m in s.matches(of: /[Tt]he answer is \(?[A-J]\)?\.?/) {
            if let r = Range(m.range, in: a) {
                a[r].backgroundColor = .yellow.opacity(0.45)
                a[r].font = .caption.monospaced().bold()
            }
        }
        return a
    }
}

/// A titled, tinted section inside a card — keeps question, answer and cost visually apart.
struct Block<Content: View>: View {
    let title: String, icon: String, color: Color
    @ViewBuilder let content: Content
    init(_ title: String, _ icon: String, _ color: Color, @ViewBuilder content: () -> Content) {
        (self.title, self.icon, self.color, self.content) = (title, icon, color, content())
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: icon).font(.caption.weight(.semibold)).foregroundStyle(color)
            content
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(color.opacity(0.25), lineWidth: 0.5))
    }
}

/// What one question cost: three numbers and the prefill/decode split; device detail on demand.
struct Perf: View {
    let q: QA, rec: RunRecord

    var body: some View {
        let d = rec.dev(q)
        let pre = q.r.promptMs / 1000, dec = q.r.genMs / 1000, tot = max(pre + dec, 0.001)
        Block("Performance", "speedometer", .indigo) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                IconStat("gauge.with.dots.needle.67percent", .indigo, fmt(q.r.decodeTokS, 1), "tok/s") {
                    Delta(value: q.r.decodeTokS, base: rec.medianDecode, decimals: 1, higherIsGood: true, vs: "med")
                }
                IconStat("text.insert", .blue, "\(q.r.promptTokens)", "tokens in") { EmptyView() }
                IconStat("text.append", .teal, "\(q.r.genTokens)", q.r.stop == "length" ? "⚠ hit cap" : "tokens out") { EmptyView() }
                IconStat("hourglass", .blue, "\(fmt(pre, 1))s", "prefill") { EmptyView() }
                IconStat("waveform", .indigo, "\(fmt(dec, 1))s", "decode") { EmptyView() }
                IconStat("clock", .gray, "\(fmt(tot, 1))s", "total") { EmptyView() }
                IconStat("cpu", .blue, d.map { "\(fmt($0.cpu))%" } ?? "—", "CPU") {
                    if let d { Delta(value: d.cpu, base: rec.cpuMean, decimals: 0, unit: "%", vs: "avg") }
                }
                IconStat("thermometer.medium", d.map { thermalColors[$0.thermal] } ?? .gray,
                         d.map { thermalNames[$0.thermal] } ?? "—", "thermal") { EmptyView() }
                IconStat("memorychip", .purple, d.map { "\(fmt($0.mem / 1024, 2)) GB" } ?? "—", "memory") { EmptyView() }
                if let w = rec.window {
                    ForEach(rec.powerSeries.prefix(3), id: \.name) { s in
                        let v = rec.powerMean(s, q), base = rec.powerMean(s, w)
                        IconStat("bolt.fill", .orange, v.map { fmt($0, 1) + unit(s.name) } ?? "—", shortName(s.name)) {
                            if let v, let base { Delta(value: v, base: base, decimals: 1, vs: "avg") }
                        }
                    }
                }
            }
            GeometryReader { g in
                HStack(spacing: 0) {
                    Rectangle().fill(.blue).frame(width: g.size.width * pre / tot)
                    Rectangle().fill(.indigo)
                }
                .clipShape(Capsule())
            }
            .frame(height: 6)
            HStack(spacing: 10) {
                Label("prefill", systemImage: "circle.fill").foregroundStyle(.blue)
                Label("decode", systemImage: "circle.fill").foregroundStyle(.indigo)
            }
            .font(.caption2).labelStyle(DotLabel())
        }
    }
}

struct IconStat<Extra: View>: View {
    let icon: String, color: Color, value: String, label: String
    @ViewBuilder let extra: Extra
    init(_ icon: String, _ color: Color, _ value: String, _ label: String, @ViewBuilder extra: () -> Extra) {
        (self.icon, self.color, self.value, self.label, self.extra) = (icon, color, value, label, extra())
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Image(systemName: icon).font(.caption).foregroundStyle(color)
                .frame(width: 22, height: 22).background(color.opacity(0.14), in: RoundedRectangle(cornerRadius: 6))
            Text(value).font(.subheadline.weight(.semibold).monospacedDigit()).lineLimit(1).minimumScaleFactor(0.6)
            Text(label).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
            extra
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct DotLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 3) { configuration.icon.font(.system(size: 6)); configuration.title.foregroundStyle(.secondary) }
    }
}

// MARK: - per-request table

struct RequestTable: View {
    let rec: RunRecord, onPick: (Int) -> Void
    @State private var all = false

    var body: some View {
        let devs = rec.qa.map { rec.dev($0) }
        let slowest = rec.qa.map(\.r.decodeTokS).min()
        let hottest = devs.compactMap { $0?.thermal }.max()
        let biggest = devs.compactMap { $0?.mem }.max()
        let busiest = devs.compactMap { $0?.cpu }.max()
        let rows = all ? rec.qa : Array(rec.qa.prefix(8))
        VStack(spacing: 0) {
            row(["#", "in", "out", "pre s", "dec s", "tok/s", "cpu", "therm", "mem"], head: true)
            ForEach(rows) { q in
                let d = devs[q.i]
                Button { onPick(q.i) } label: {
                    row(["\(q.i + 1)", "\(q.r.promptTokens)", "\(q.r.genTokens)", fmt(q.r.promptMs / 1000, 1), fmt(q.r.genMs / 1000, 1),
                         (q.r.decodeTokS == slowest ? "▼" : "") + fmt(q.r.decodeTokS, 1),
                         d.map { ($0.cpu == busiest ? "▲" : "") + fmt($0.cpu) } ?? "—",
                         d.map { ($0.thermal == hottest && $0.thermal > 0 ? "▲" : "") + "\($0.thermal)" } ?? "—",
                         d.map { ($0.mem == biggest ? "▲" : "") + fmt($0.mem) } ?? "—"],
                        tint: q.ok ? nil : .red.opacity(0.06))
                }
                .buttonStyle(.plain)
            }
            row(["all \(rec.n)", "\(rec.qa.reduce(0) { $0 + $1.r.promptTokens })", "\(rec.qa.reduce(0) { $0 + $1.r.genTokens })",
                 fmt(rec.qa.reduce(0) { $0 + $1.r.promptMs } / 1000), fmt(rec.qa.reduce(0) { $0 + $1.r.genMs } / 1000),
                 fmt(rec.medianDecode, 1), fmt(rec.cpuMean), "\(rec.thermalMax)", fmt(rec.memPeakMB)], head: true)
            row(["", "total", "total", "total", "total", "median", "mean", "max", "max"], head: true)
            if rec.n > 8 {
                Button(all ? "show fewer" : "show all \(rec.n) requests") { all.toggle() }.font(.caption).padding(.top, 8)
            }
        }
    }

    private func row(_ cells: [String], head: Bool = false, tint: Color? = nil) -> some View {
        HStack(spacing: 2) {
            ForEach(Array(cells.enumerated()), id: \.offset) { i, c in
                Text(c).frame(maxWidth: .infinity, alignment: i == 0 ? .leading : .trailing)
                    .foregroundStyle(c.hasPrefix("▲") || c.hasPrefix("▼") ? .orange : head ? .secondary : .primary)
            }
        }
        .font(.system(size: 10, design: .monospaced).weight(head ? .semibold : .regular))
        .lineLimit(1).minimumScaleFactor(0.7)
        .padding(.vertical, 5)
        .background(tint ?? .clear)
        .overlay(alignment: .bottom) { Divider() }
    }
}

// MARK: - small pieces

struct Track: View {
    let pts: [Telemetry.Sample], title: String, unit: String, color: Color, y: (Telemetry.Sample) -> Double
    init(_ pts: [Telemetry.Sample], _ title: String, _ unit: String, _ color: Color, y: @escaping (Telemetry.Sample) -> Double) {
        (self.pts, self.title, self.unit, self.color, self.y) = (pts, title, unit, color, y)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(unit.isEmpty ? title : "\(title) (\(unit))").font(.caption2).foregroundStyle(color)
            Chart(pts, id: \.ts) { s in
                LineMark(x: .value("min", s.t / 60), y: .value(title, y(s))).foregroundStyle(color).interpolationMethod(.stepEnd)
                RuleMark(x: .value("start", 0)).foregroundStyle(.secondary.opacity(0.4))
            }
            .chartYAxis { AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) }
            .frame(height: 70)
        }
    }
}

struct Tiles<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 8)], spacing: 8) { content }
    }
}

struct Tile: View {
    let label: String, value: String, unit: String?, color: Color, sub: String?, delta: Delta?
    init(_ label: String, _ value: String, _ unit: String?, _ color: Color = .primary, sub: String? = nil, delta: Delta? = nil) {
        (self.label, self.value, self.unit, self.color, self.sub, self.delta) = (label, value, unit, color, sub, delta)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(value).font(.headline.monospacedDigit()).foregroundStyle(color == .primary ? Color.primary : color)
                if let unit { Text(unit).font(.caption2).foregroundStyle(.secondary) }
            }
            .lineLimit(1).minimumScaleFactor(0.6)
            if let delta { delta }
            if let sub { Text(sub).font(.caption2).foregroundStyle(.secondary).lineLimit(2) }
        }
        .padding(10)
        .frame(maxWidth: .infinity, minHeight: 64, alignment: .topLeading)
        .background(Color(.tertiarySystemFill).opacity(0.6), in: RoundedRectangle(cornerRadius: 10))
    }
}

/// ▲/▼ against a baseline, green when it's the good direction — arrow and colour, never colour alone.
struct Delta: View {
    let value: Double, base: Double, decimals: Int
    var higherIsGood = false
    var unit = ""
    var vs = "run avg"
    var body: some View {
        let diff = value - base
        if base == 0 {
            EmptyView()
        } else if abs(diff / base) < 0.02 {
            Text("level with \(vs)").font(.caption2).foregroundStyle(.secondary)
        } else {
            let good = higherIsGood ? diff > 0 : diff < 0
            Text("\(diff > 0 ? "▲" : "▼") \(fmt(abs(diff), decimals))\(unit) vs \(vs)")
                .font(.caption2).foregroundStyle(good ? .green : .orange)
        }
    }
}

struct Pill: View {
    let text: String, color: Color
    init(_ text: String, _ color: Color) { (self.text, self.color) = (text, color) }
    var body: some View {
        Text(text).font(.caption2.weight(.medium)).lineLimit(1)
            .padding(.horizontal, 8).padding(.vertical, 4)
            .foregroundStyle(color).background(color.opacity(0.14), in: Capsule())
    }
}

struct Section2: View {
    let title: String, sub: String
    init(_ title: String, _ sub: String) { (self.title, self.sub) = (title, sub) }
    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(.headline)
            Text(sub).font(.caption).foregroundStyle(.secondary)
        }
    }
}

// MARK: - iPhone vs Pi 5 vs Jetson (same model, same 100 questions)

struct Comparison: View {
    let rec: RunRecord, ref: [String: Ref]

    struct Row {
        let name: String, icon: String, color: Color
        let score: Double?, tokS: Double?, minutes: Double?, wh: Double?, jPerTok: Double?
    }

    private var rows: [Row] {
        let me = rec.n > 0
        return [
            Row(name: "iPhone", icon: "iphone", color: .blue, score: me ? rec.score : nil, tokS: me ? rec.medianDecode : nil,
                minutes: me ? rec.minutes : nil, wh: rec.bestWh, jPerTok: rec.jPerToken),
            Row(name: "Pi 5", icon: "memorychip", color: .orange, score: ref["pi"]?.score, tokS: ref["pi"]?.decode_tok_s,
                minutes: ref["pi"]?.minutes, wh: ref["pi"]?.energy_wh, jPerTok: ref["pi"]?.j_per_token),
            Row(name: "Jetson", icon: "bolt", color: .green, score: ref["jetson"]?.score, tokS: ref["jetson"]?.decode_tok_s,
                minutes: ref["jetson"]?.minutes, wh: ref["jetson"]?.energy_wh, jPerTok: ref["jetson"]?.j_per_token),
        ]
    }

    var body: some View {
        Card {
            HStack {
                Label("iPhone vs Pi 5 vs Jetson", systemImage: "chart.bar.xaxis").font(.headline)
                Spacer()
                Pill("\(rec.model.uppercased()) · \(rec.subset)", .indigo)
            }
            metric("Accuracy", "target", "%", \.score, max: 100, decimals: 1, lowerIsBetter: false)
            metric("Decode speed", "gauge.with.dots.needle.67percent", "tok/s", \.tokS, decimals: 1, lowerIsBetter: false)
            metric("Total time", "clock", "min", \.minutes, decimals: 0, lowerIsBetter: true)
            metric("Energy", "bolt.batteryblock", "Wh", \.wh, decimals: 2, lowerIsBetter: true)
            metric("Energy per token", "leaf", "J/tok", \.jPerTok, decimals: 2, lowerIsBetter: true)
            VStack(alignment: .leading, spacing: 3) {
                if rec.n < 100 {
                    Label("iPhone partial: \(rec.n)/100 answered — compare when the run is done", systemImage: "hourglass")
                }
                Label("Boards: measured board DC draw. iPhone: \(rec.energySource), whole phone incl. screen.",
                      systemImage: "info.circle")
                Label("Same QAT 4-bit checkpoint, same prompts, greedy. Pi/Jetson from agentic-edge.", systemImage: "checkmark.seal")
            }
            .font(.caption2).foregroundStyle(.secondary)
        }
    }

    /// One metric, three bars on a shared scale; the best device gets a crown.
    private func metric(_ title: String, _ icon: String, _ unit: String, _ key: KeyPath<Row, Double?>,
                        max: Double? = nil, decimals: Int, lowerIsBetter: Bool) -> some View {
        let vals = rows.compactMap { $0[keyPath: key] }
        let top = max ?? (vals.max() ?? 1)
        let best = lowerIsBetter ? vals.min() : vals.max()
        return VStack(alignment: .leading, spacing: 5) {
            HStack {
                Label(title, systemImage: icon).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Spacer()
                Text(lowerIsBetter ? "lower is better" : "higher is better").font(.caption2).foregroundStyle(.tertiary)
            }
            ForEach(rows, id: \.name) { r in
                let v = r[keyPath: key]
                HStack(spacing: 8) {
                    Label(r.name, systemImage: r.icon).font(.caption).foregroundStyle(r.color).frame(width: 74, alignment: .leading)
                    GeometryReader { g in
                        Capsule().fill(r.color.opacity(0.15))
                            .overlay(alignment: .leading) {
                                Capsule().fill(r.color).frame(width: g.size.width * min((v ?? 0) / Swift.max(top, 0.001), 1))
                            }
                    }
                    .frame(height: 10)
                    HStack(spacing: 2) {
                        if let v, v == best, vals.count > 1 { Image(systemName: "crown.fill").font(.system(size: 8)).foregroundStyle(.yellow) }
                        Text(v.map { fmt($0, decimals) + (unit == "%" ? "%" : "") } ?? "—")
                            .font(.caption.monospacedDigit().weight(r.name == "iPhone" ? .bold : .regular))
                    }
                    .frame(width: 58, alignment: .trailing)
                }
            }
            if unit != "%" { Text(unit).font(.caption2).foregroundStyle(.tertiary) }
        }
    }
}

// MARK: - /api/phone payload: run_detail.py --run's shape, so the dashboard renders it as-is

extension RunRecord {
    func apiPayload() -> [String: Any] {
        let t0 = qa.first?.r.start.timeIntervalSince1970 ?? 0
        let nul = NSNull()
        func opt(_ x: Double?) -> Any { x.map { $0 as Any } ?? nul }
        let questions: [[String: Any]] = qa.map { q in
            ["subject": q.subject, "q": q.question, "options": q.options, "gold": q.gold,
             "got": q.got == "[invalid]" ? nul : q.got, "ok": q.ok, "resp": q.r.text, "chars": q.r.text.count,
             "question_id": opt(q.questionID.map(Double.init)), "stop": q.r.stop]
        }
        let timeline: [[String: Any]] = qa.map { q in
            let d = dev(q)
            return ["i": q.i, "t": q.r.start.timeIntervalSince1970 - t0,
                    "start_epoch": q.r.start.timeIntervalSince1970, "end_epoch": q.r.end.timeIntervalSince1970,
                    "pt": q.r.promptTokens, "pms": q.r.promptMs, "gt": q.r.genTokens, "gms": q.r.genMs,
                    "pts": q.r.promptMs > 0 ? Double(q.r.promptTokens) / q.r.promptMs * 1000 : 0, "gts": q.r.decodeTokS,
                    "dev": d.map { ["cpu": $0.cpu, "thermal": $0.thermal, "rss_mb": $0.mem, "samples": $0.samples,
                                    "throttled": $0.thermal >= 2] as [String: Any] } ?? [:]]
        }
        // ponytail: every 1 Hz sample (~3k rows a run); downsample here if uploads get slow on cellular.
        let telemetry: [[String: Any]] = self.telemetry.map {
            ["t": $0.ts - t0, "cpu": $0.cpu, "rss": $0.footprint, "thermal": $0.thermal,
             "battery": Double($0.battery) * 100, "w": nul, "temp": nul, "gpu": nul]
        }
        let batteryTemp = power?.series.first { $0.name.hasSuffix("temp_c") }.flatMap { s in
            window.flatMap { w in zip(s.t, s.v).filter { w.contains($0.0) }.map(\.1).max() }
        }
        let device: [String: Any] = [
            "energy_wh": opt(bestWh), "energy_source": energySource,
            "mean_w": opt(measuredW.isEmpty ? meanW : mean(measuredW)), "peak_w": opt(measuredW.max()),
            "idle_w": nul, "j_per_token": opt(jPerToken),
            "tok_s_per_w": opt(meanW.flatMap { $0 > 0 ? medianDecode / $0 : nil }),
            "decode_tok_s": medianDecode, "prefill_tok_s": prefillTokS,
            "gen_tokens": qa.reduce(0) { $0 + $1.r.genTokens },
            "temp_max": opt(batteryTemp), "throttled": thermalSeriousS, "thermal_max": thermalMax,
            "cpu_mean": cpuMean, "gpu_mean": nul, "gpu_max": nul, "gpu_mhz_mean": nul,
            "mem_peak_mb": memPeakMB, "battery_used_pct": opt(batteryUsed), "battery_wh_capacity": opt(batteryWh),
            "dir": dir,
            "na_reasons": ["gpu_mean": "iOS exposes no GPU utilisation to apps",
                           "idle_w": "no power reading during the idle baseline on iOS",
                           "temp_max": "battery temperature from PowerLog when attached; iOS gives apps no SoC temperature"],
        ]
        return [
            "run": dir, "engine": "mlx", "model": model, "subset": subset, "thinking": "off",
            "status": status == "done" ? "done" : status == "running" ? "running" : "incomplete",
            "note": status == "done" ? nul : status,
            "summary": ["score": (score * 10).rounded() / 10, "stderr": (stderr * 10).rounded() / 10, "minutes": minutes.rounded()],
            "n": n, "questions": questions, "timeline": timeline, "telemetry": telemetry,
            "telemetry_raw": true, "telemetry_hz": 1, "device": device,
            "host": Telemetry.machine, "host_name": Telemetry.deviceName,
            "os": "iOS " + UIDevice.current.systemVersion, "ram_gb": ProcessInfo.processInfo.physicalMemory >> 30,
            "load_s": loadS, "generated_at": ISO8601DateFormatter().string(from: .now),
        ]
    }
}
