import SwiftUI

@main
struct GemmaBenchApp: App {
    init() {
        #if DEBUG
            scoringSelfCheck()
        #endif
    }

    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

struct ContentView: View {
    @State private var bench = Bench()
    @State private var model = GemmaModel.e2b
    @State private var subset = "s1"
    @State private var detail: RunRecord?
    @State private var settings = false
    @State private var deleting: GemmaModel?
    @Environment(\.verticalSizeClass) private var vSize  // .compact = iPhone in landscape

    private var ref: [String: Ref] { bench.prompts.reference["\(model.base)-\(subset)"] ?? [:] }
    private var pct: Double { bench.done > 0 ? 100 * Double(bench.correct) / Double(bench.done) : 0 }

    var body: some View {
        NavigationStack {
            ScrollView {
                if vSize == .compact {
                    // Landscape: what you set and run on the left, what came out on the right.
                    HStack(alignment: .top, spacing: 16) {
                        VStack(spacing: 16) {
                            setup
                            models
                            actions
                            if bench.total > 0 { progress }
                        }
                        VStack(spacing: 16) {
                            compare
                            if !bench.runs.isEmpty { history }
                            if !bench.log.isEmpty { logCard }
                        }
                    }
                    .padding()
                } else {
                    VStack(spacing: 16) {
                        setup
                        models
                        compare
                        actions
                        if bench.total > 0 { progress }
                        if !bench.runs.isEmpty { history }
                        if !bench.log.isEmpty { logCard }
                    }
                    .padding()
                }
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("GemmaBench")
            .toolbar {
                Button { settings = true } label: { Image(systemName: "gearshape") }
                    .accessibilityLabel("Settings")
            }
            .sheet(isPresented: $settings) { SettingsView(bench: bench) }
            .task { if CommandLine.arguments.contains("-downloadModels") { bench.downloadAll() } }  // devicectl hook
            .confirmationDialog("Delete \(deleting?.title ?? "") from this iPhone?",
                                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                                titleVisibility: .visible) {
                Button("Delete", role: .destructive) { if let m = deleting { bench.deleteModel(m) } }
            } message: {
                Text("Frees the space. Runs and results are kept; the model downloads again on the next run.")
            }
            .sheet(item: $detail, onDismiss: { bench.runs = RunRecord.loadAll(); bench.writeComparison() }) {
                RunDetailView(rec: $0, ref: bench.prompts.reference["\(GemmaModel.base($0.model))-\($0.subset)"] ?? [:],
                              upload: { await bench.upload($0) })
            }
        }
    }

    // MARK: sections

    private var setup: some View {
        let _ = bench.modelTick  // chips show downloaded state; re-read after a download/delete
        return Card {
            HStack {
                Label(Telemetry.deviceName, systemImage: "iphone").font(.headline)
                Spacer()
                Pill("\(ProcessInfo.processInfo.physicalMemory >> 30) GB", .gray)
                Pill("iOS \(UIDevice.current.systemVersion)", .gray)
                Pill("MLX", .blue)
            }
            Label("MMLU-Pro · 5-shot CoT · greedy · 2048 tok", systemImage: "graduationcap")
                .font(.caption).foregroundStyle(.secondary)
            Group {
                Text("Model").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    ForEach(GemmaModel.allCases) { m in
                        ModelChip(model: m, selected: model == m, downloaded: ModelStore.status(m).complete) { model = m }
                    }
                }
                Text("Subset").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                HStack(spacing: 8) {
                    ForEach(["s1", "s2", "s3"], id: \.self) { s in
                        Chip(s, nil, .teal, selected: subset == s) { subset = s }.frame(maxWidth: .infinity)
                    }
                }
            }
            .disabled(bench.running)
            Text(model.repo).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            if !model.fitsThisPhone {
                Label("Too big for this iPhone's per-app memory (iOS kills it after loading). Use E4B oQ4.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.caption).foregroundStyle(.orange)
            }
        }
    }

    private var compare: some View {
        Card {
            Label("iPhone vs Pi 5 vs Jetson · same 100 questions", systemImage: "chart.bar.xaxis")
                .font(.subheadline.weight(.semibold))
            HStack(spacing: 8) {
                Stat("iPhone", "iphone", .blue, bench.done > 0 ? String(format: "%.1f%%", pct) : "—")
                Stat("Pi 5", "memorychip", .orange, ref["pi"].map { String(format: "%.1f%%", $0.score) } ?? "—")
                Stat("Jetson", "bolt", .green, ref["jetson"].map { String(format: "%.1f%%", $0.score) } ?? "—")
            }
        }
    }

    private var actions: some View {
        VStack(spacing: 10) {
            if bench.running {
                Button(role: .destructive) { bench.stop() } label: {
                    Label("Stop", systemImage: "stop.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent).tint(.red)
            } else {
                Button { bench.start([(model, subset)]) } label: {
                    Label("Run \(model.title) \(subset)", systemImage: "play.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent).tint(.indigo)
                .disabled(!model.fitsThisPhone)
                Button {
                    // Skips what this phone can't hold (qat-4bit E4B on 8 GB): those runs only crash.
                    bench.start(GemmaModel.allCases.filter(\.fitsThisPhone).flatMap { m in ["s1", "s2", "s3"].map { (m, $0) } })
                } label: {
                    Label("Run full grid · \(GemmaModel.allCases.filter(\.fitsThisPhone).count * 3) runs", systemImage: "square.grid.3x2").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered).tint(.indigo)
            }
            Label("Keep the app open, screen on. Unplug for battery data.", systemImage: "info.circle")
                .font(.caption).foregroundStyle(.secondary)
        }
        .controlSize(.large)
    }

    private var progress: some View {
        let thermal = ProcessInfo.processInfo.thermalState
        return Card {
            HStack {
                Label(bench.running ? "Running" : "Last run", systemImage: bench.running ? "waveform" : "flag.checkered")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text("\(bench.done)/\(bench.total)").font(.subheadline.monospacedDigit()).foregroundStyle(.secondary)
            }
            ProgressView(value: Double(bench.done), total: Double(max(bench.total, 1))).tint(.indigo)
            Text(bench.status).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            HStack(spacing: 8) {
                Stat("Correct", "checkmark.circle", .green, "\(bench.correct)")
                Stat("Decode", "speedometer", .blue, String(format: "%.1f t/s", bench.lastTokS))
                Stat("Thermal", "thermometer.medium", thermalColor(thermal), thermalName(thermal))
            }
            if !bench.lastAnswer.isEmpty {
                Label(bench.lastAnswer, systemImage: bench.lastOK ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.caption)
                    .foregroundStyle(bench.lastOK ? .green : .red)
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background((bench.lastOK ? Color.green : .red).opacity(0.12), in: Capsule())
            }
            if let cur = bench.current, !cur.qa.isEmpty {
                Button { detail = cur } label: {
                    Label("Open run detail", systemImage: "chart.xyaxis.line").frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered).tint(.indigo)
            }
        }
    }

    private var history: some View {
        Card {
            Label("Runs", systemImage: "clock.arrow.circlepath").font(.subheadline.weight(.semibold))
            ForEach(bench.runs) { r in
                Button { detail = r } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r.label).font(.subheadline.weight(.medium))
                            Text(r.dir.suffix(15)).font(.caption2.monospaced()).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Pill(r.status == "done" ? "done" : r.status == "stopped" ? "stopped"
                             : r.status == "running" && !bench.running ? "interrupted" : r.status == "running" ? "running" : "failed",
                             r.status == "done" ? .green : .orange)
                        Pill(String(format: "%.1f%%", r.score), .indigo)
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var models: some View {
        let _ = bench.modelTick  // re-read the disk after a download or delete
        let gb = { (b: Int64) in ByteCountFormatter.string(fromByteCount: b, countStyle: .file) }
        return Card {
            HStack {
                Label("Models on this iPhone", systemImage: "externaldrive").font(.subheadline.weight(.semibold))
                Spacer()
                Text("\(gb(ModelStore.freeBytes)) free").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(GemmaModel.allCases) { m in
                let st = ModelStore.status(m)
                let p = bench.modelProgress[m]
                HStack(spacing: 10) {
                    Image(systemName: st.complete ? "checkmark.circle.fill" : p != nil ? "arrow.down.circle" : "icloud.and.arrow.down")
                        .font(.title3).foregroundStyle(st.complete ? .green : p != nil ? .blue : .secondary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(m.title) · \(m.quant)").font(.subheadline.weight(.semibold))
                        if !m.fitsThisPhone {
                            Text("Too big for this iPhone's per-app memory: loads, then iOS kills it").font(.caption2).foregroundStyle(.orange)
                        }
                        Text(p.map { "Downloading \(Int($0 * 100))%" + (st.total > 0 ? " of \(gb(st.total))" : "") }
                             ?? (st.complete ? "Downloaded · \(gb(st.bytes)) · rev \(m.revision.prefix(7))"
                                 + (ModelStore.isTextOnly(m) ? " · text-only" : "")
                                 : st.bytes > 0 ? "\(gb(st.bytes)) of \(gb(st.total)) · tap Download to resume"
                                 : "Not downloaded"))
                            .font(.caption2).foregroundStyle(.secondary)
                        if let p { ProgressView(value: p).tint(.blue) }
                        if let e = bench.modelError[m] { Text(e).font(.caption2).foregroundStyle(.red) }
                    }
                    Spacer()
                    if p != nil {
                        Button { bench.cancelDownload(m) } label: { Image(systemName: "xmark.circle.fill") }
                            .foregroundStyle(.secondary).accessibilityLabel("Cancel download")
                    } else if st.complete {
                        Button { deleting = m } label: { Image(systemName: "trash") }
                            .foregroundStyle(.red).disabled(bench.running).accessibilityLabel("Delete \(m.title)")
                    } else {
                        Button("Download") { bench.download(m) }.buttonStyle(.bordered).controlSize(.small)
                    }
                }
                .buttonStyle(.borderless)
            }
            Text("Pinned Hugging Face commits, stored on the phone (not backed up). A run downloads its model first if needed, before anything is measured.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    private var logCard: some View {
        Card {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(bench.log.suffix(20).reversed(), id: \.self) {
                        Text($0).font(.caption2.monospaced()).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Label("Log", systemImage: "list.bullet.rectangle").font(.subheadline.weight(.semibold))
            }
            .tint(.primary)
        }
    }

    private func thermalName(_ t: ProcessInfo.ThermalState) -> String {
        ["Nominal", "Fair", "Serious", "Critical"][min(t.rawValue, 3)]
    }

    private func thermalColor(_ t: ProcessInfo.ThermalState) -> Color {
        [Color.green, .yellow, .orange, .red][min(t.rawValue, 3)]
    }
}

// MARK: - small pieces

struct Card<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct Chip: View {
    let title: String, symbol: String?, color: Color, selected: Bool, action: () -> Void
    init(_ title: String, _ symbol: String?, _ color: Color, selected: Bool, action: @escaping () -> Void) {
        (self.title, self.symbol, self.color, self.selected, self.action) = (title, symbol, color, selected, action)
    }
    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if let symbol { Image(systemName: symbol) }
                Text(title)
            }
            .font(.subheadline.weight(.medium))
            .padding(.horizontal, 12).padding(.vertical, 6)
            .foregroundStyle(selected ? .white : color)
            .background(selected ? color : color.opacity(0.12), in: Capsule())
        }
        .buttonStyle(.plain)
    }
}

struct Stat: View {
    let title: String, symbol: String, color: Color, value: String
    init(_ title: String, _ symbol: String, _ color: Color, _ value: String) {
        (self.title, self.symbol, self.color, self.value) = (title, symbol, color, value)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(title, systemImage: symbol).font(.caption).foregroundStyle(color)
            Text(value).font(.headline.monospacedDigit()).lineLimit(1).minimumScaleFactor(0.7)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(color.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: - Settings: everything the app keeps between launches

struct SettingsView: View {
    @Bindable var bench: Bench
    @State private var showToken = false
    @State private var test: String?
    @State private var testing = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://…", text: $bench.apiURL)
                        .textContentType(.URL).keyboardType(.URL)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    HStack {
                        Group {
                            if showToken { TextField("API_TOKEN", text: $bench.apiToken) }
                            else { SecureField("API_TOKEN", text: $bench.apiToken) }
                        }
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .font(.body.monospaced())
                        Button { showToken.toggle() } label: { Image(systemName: showToken ? "eye.slash" : "eye") }
                            .buttonStyle(.borderless).accessibilityLabel(showToken ? "Hide token" : "Show token")
                    }
                    Toggle("Upload each run when it ends", isOn: $bench.autoUpload)
                    Button {
                        testing = true
                        Task { test = await bench.testConnection(); testing = false }
                    } label: {
                        HStack {
                            Label(testing ? "Testing…" : "Test connection", systemImage: "network")
                            Spacer()
                            if let test {
                                Image(systemName: test.hasPrefix("OK") ? "checkmark.circle.fill" : "xmark.circle.fill")
                                    .foregroundStyle(test.hasPrefix("OK") ? .green : .red)
                            }
                        }
                    }
                    .disabled(testing)
                    if let test { Text(test).font(.caption).foregroundStyle(test.hasPrefix("OK") ? .green : .red) }
                } header: {
                    Label("Dashboard API", systemImage: "icloud.and.arrow.up")
                } footer: {
                    Text("Runs are POSTed to /api/phone and show up as the iPhone next to the Pi 5 and Jetson. The token is kept in the Keychain. Empty URL = never upload.")
                }

                Section {
                    HStack {
                        Text("Battery capacity")
                        Spacer()
                        TextField("Wh", value: $bench.batteryWh, format: .number.precision(.fractionLength(2)))
                            .keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(width: 80)
                        Text("Wh").foregroundStyle(.secondary)
                    }
                    if Telemetry.nominalBatteryWh > 0 {
                        Button("Reset to nominal (\(fmt(Telemetry.nominalBatteryWh, 2)) Wh)") {
                            bench.batteryWh = Telemetry.nominalBatteryWh
                        }
                    }
                } header: {
                    Label("Energy estimate", systemImage: "battery.100")
                } footer: {
                    Text("Nominal Wh × Settings › Battery › Battery Health %. Used only when no PowerLog data is attached. Saved with each run, so changing it doesn't rewrite past runs.")
                }

                Section {
                    LabeledContent("Device", value: "\(Telemetry.deviceName) (\(Telemetry.machine))")
                    LabeledContent("Memory", value: "\(ProcessInfo.processInfo.physicalMemory >> 30) GB")
                    LabeledContent("iOS", value: UIDevice.current.systemVersion)
                    LabeledContent("Engine", value: "mlx-swift-lm 3.31.4")
                    LabeledContent("Runs on this phone", value: "\(bench.runs.count)")
                } header: {
                    Label("About", systemImage: "info.circle")
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { Button("Done") { dismiss() } }
            .disabled(bench.running)  // settings are captured per run; don't change them mid-run
        }
    }
}

/// One model in the picker: name, quantization, downloaded or not, and a warning when this phone
/// can't hold it. Equal widths so three fit a portrait row.
struct ModelChip: View {
    let model: GemmaModel, selected: Bool, downloaded: Bool, action: () -> Void
    var body: some View {
        let tint: Color = model.fitsThisPhone ? .indigo : .orange
        Button(action: action) {
            VStack(spacing: 2) {
                HStack(spacing: 4) {
                    Image(systemName: !model.fitsThisPhone ? "exclamationmark.triangle.fill"
                          : downloaded ? "checkmark.circle.fill" : "icloud.and.arrow.down")
                        .font(.caption2)
                    Text(model.title).font(.subheadline.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.8)
                }
                Text(model == .e4bOQ4 ? "oQ4 · 4/5/6-bit" : "QAT 4-bit")
                    .font(.caption2).lineLimit(1).minimumScaleFactor(0.8)
                    .opacity(0.85)
            }
            .padding(.vertical, 8).padding(.horizontal, 6)
            .frame(maxWidth: .infinity)
            .foregroundStyle(selected ? .white : tint)
            .background(selected ? tint : tint.opacity(0.12), in: RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(model.title), \(model.quant), \(downloaded ? "downloaded" : "not downloaded")"
                            + (model.fitsThisPhone ? "" : ", too big for this iPhone"))
    }
}
