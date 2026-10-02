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

    private var ref: [String: Ref] { bench.prompts.reference["\(model.rawValue)-\(subset)"] ?? [:] }
    private var pct: Double { bench.done > 0 ? 100 * Double(bench.correct) / Double(bench.done) : 0 }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    setup
                    compare
                    actions
                    if bench.total > 0 { progress }
                    if !bench.runs.isEmpty { history }
                    if !bench.log.isEmpty { logCard }
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("GemmaBench")
            .toolbar {
                Button { settings = true } label: { Image(systemName: "gearshape") }
                    .accessibilityLabel("Settings")
            }
            .sheet(isPresented: $settings) { SettingsView(bench: bench) }
            .sheet(item: $detail, onDismiss: { bench.runs = RunRecord.loadAll(); bench.writeComparison() }) {
                RunDetailView(rec: $0, ref: bench.prompts.reference["\($0.model)-\($0.subset)"] ?? [:],
                              upload: { await bench.upload($0) })
            }
        }
    }

    // MARK: sections

    private var setup: some View {
        Card {
            HStack {
                Label(Telemetry.deviceName, systemImage: "iphone").font(.headline)
                Spacer()
                Pill("\(ProcessInfo.processInfo.physicalMemory >> 30) GB", .gray)
                Pill("iOS \(UIDevice.current.systemVersion)", .gray)
                Pill("MLX", .blue)
            }
            Label("MMLU-Pro · 5-shot CoT · greedy · 2048 tok", systemImage: "graduationcap")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                ForEach(GemmaModel.allCases) { m in
                    Chip(m.rawValue.uppercased(), "cpu", .indigo, selected: model == m) { model = m }
                }
                Spacer()
                ForEach(["s1", "s2", "s3"], id: \.self) { s in
                    Chip(s, nil, .teal, selected: subset == s) { subset = s }
                }
            }
            .disabled(bench.running)
            Text(model.repo).font(.caption.monospaced()).foregroundStyle(.secondary)
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
                    Label("Run \(model.rawValue.uppercased()) \(subset)", systemImage: "play.fill").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent).tint(.indigo)
                Button {
                    bench.start(GemmaModel.allCases.flatMap { m in ["s1", "s2", "s3"].map { (m, $0) } })
                } label: {
                    Label("Run full grid · 6 runs", systemImage: "square.grid.3x2").frame(maxWidth: .infinity)
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
