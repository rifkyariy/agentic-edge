import Foundation

/// Where the two models live on the phone, and how they get there.
///
/// Each model is a plain folder, Application Support/models/<repo name>/, holding exactly the
/// files of one pinned Hugging Face commit. "Downloaded" means every file is present at the size
/// the Hub reports, so the list on screen is a fact about the disk, not a cache guess. The folder
/// is excluded from iCloud backup (≈11 GB for both).
extension GemmaModel {
    /// Pinned commits: every iPhone run uses the same weights even if the repo is updated.
    var revision: String {
        self == .e2b ? "42f62737af7a9fd8c1d55d79666c1a217be4e2e2" : "0f35c6f6d386f7f74e628bd7c6526ce531212300"
    }

    var dir: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appending(path: "models/\(repo.split(separator: "/").last!)")
    }
}

struct HubFile: Codable, Sendable {
    let path: String
    let size: Int64
}

enum ModelStore {
    /// The files the loader needs: weights, configs, tokenizer, chat template (no README).
    static func manifest(_ m: GemmaModel) async throws -> [HubFile] {
        let cached = m.dir.appending(path: ".manifest.json")
        if let d = try? Data(contentsOf: cached), let f = try? JSONDecoder().decode([HubFile].self, from: d) { return f }
        let url = URL(string: "https://huggingface.co/api/models/\(m.repo)/tree/\(m.revision)")!
        let (data, resp) = try await URLSession.shared.data(from: url)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        struct Entry: Decodable { let type: String; let path: String; let size: Int64 }
        let files = try JSONDecoder().decode([Entry].self, from: data)
            .filter { e in e.type == "file" && [".json", ".safetensors", ".jinja"].contains { e.path.hasSuffix($0) } }
            .map { HubFile(path: $0.path, size: $0.size) }
        try FileManager.default.createDirectory(at: m.dir, withIntermediateDirectories: true)
        try JSONEncoder().encode(files).write(to: cached)
        return files
    }

    static func onDisk(_ f: HubFile, _ m: GemmaModel) -> Int64 {
        ((try? FileManager.default.attributesOfItem(atPath: m.dir.appending(path: f.path).path))?[.size] as? Int64) ?? -1
    }

    /// Bytes present, and whether every manifest file is complete. Offline-safe once the manifest is cached.
    static func status(_ m: GemmaModel) -> (bytes: Int64, total: Int64, complete: Bool) {
        guard let d = try? Data(contentsOf: m.dir.appending(path: ".manifest.json")),
              let files = try? JSONDecoder().decode([HubFile].self, from: d) else { return (0, 0, false) }
        let have = files.map { max(onDisk($0, m), 0) }
        let complete = zip(files, have).allSatisfy { $0.size == $1 }
        return (have.reduce(0, +), files.reduce(0) { $0 + $1.size }, complete)
    }

    static var freeBytes: Int64 {
        let home = URL(fileURLWithPath: NSHomeDirectory())
        return (try? home.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage ?? 0
    }

    /// Downloads what's missing, file by file (a finished file is never fetched again).
    /// ponytail: plain URLSession, so it needs the app in the foreground; a background
    /// URLSession would survive the screen locking if that turns out to matter.
    static func download(_ m: GemmaModel, progress: @escaping @Sendable (Int64, Int64) -> Void) async throws {
        let files = try await manifest(m)
        let total = files.reduce(0) { $0 + $1.size }
        let missing = files.filter { onDisk($0, m) != $0.size }
        let need = missing.reduce(0) { $0 + $1.size }
        guard need < freeBytes else {
            throw NSError(domain: "GemmaBench", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "Not enough space: \(ByteCountFormatter.string(fromByteCount: need, countStyle: .file)) needed, "
                + "\(ByteCountFormatter.string(fromByteCount: freeBytes, countStyle: .file)) free"])
        }
        var dir = m.dir
        var rv = URLResourceValues()
        rv.isExcludedFromBackup = true
        try? dir.setResourceValues(rv)

        var done = total - need
        for f in missing {
            try Task.checkCancellation()
            let url = URL(string: "https://huggingface.co/\(m.repo)/resolve/\(m.revision)/\(f.path)")!
            let base = done
            try await fetch(url, to: m.dir.appending(path: f.path)) { progress(base + $0, total) }
            guard onDisk(f, m) == f.size else {
                throw NSError(domain: "GemmaBench", code: 2, userInfo: [NSLocalizedDescriptionKey:
                    "\(f.path) arrived at the wrong size; tap Download again"])
            }
            done += f.size
            progress(done, total)
        }
    }

    static func delete(_ m: GemmaModel) throws {
        if FileManager.default.fileExists(atPath: m.dir.path) { try FileManager.default.removeItem(at: m.dir) }
    }

    private final class Inflight: @unchecked Sendable {
        var task: URLSessionDownloadTask?
        var observation: NSKeyValueObservation?
    }

    private static func fetch(_ url: URL, to dest: URL, progress: @escaping @Sendable (Int64) -> Void) async throws {
        let inflight = Inflight()
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                let task = URLSession.shared.downloadTask(with: url) { tmp, resp, err in
                    inflight.observation?.invalidate()
                    if let err { return c.resume(throwing: err) }
                    guard let tmp, (resp as? HTTPURLResponse)?.statusCode == 200 else {
                        return c.resume(throwing: URLError(.badServerResponse))
                    }
                    do {
                        try? FileManager.default.removeItem(at: dest)
                        try FileManager.default.moveItem(at: tmp, to: dest)
                        c.resume()
                    } catch { c.resume(throwing: error) }
                }
                inflight.observation = task.progress.observe(\.completedUnitCount) { p, _ in progress(p.completedUnitCount) }
                inflight.task = task
                task.resume()
            }
        } onCancel: {
            inflight.task?.cancel()  // completes with URLError.cancelled, which ends the continuation
        }
    }
}
