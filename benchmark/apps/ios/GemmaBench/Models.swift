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
        switch self {
        case .e2b: "42f62737af7a9fd8c1d55d79666c1a217be4e2e2"
        case .e4b: "0f35c6f6d386f7f74e628bd7c6526ce531212300"
        case .e4bOQ4: "eaa5413e7ee2ce04f6e9544c06b420b365b0bfce"
        }
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
        // A text-only copy missing a file can't be topped up from the Hub (its sizes no longer
        // match): start again from the Hub's manifest. ponytail: re-downloads the stripped shards
        // too; only happens if a file was deleted by hand.
        if isTextOnly(m) && !status(m).complete {
            try? FileManager.default.removeItem(at: m.dir.appending(path: ".manifest.json"))
            try? FileManager.default.removeItem(at: m.dir.appending(path: ".textonly"))
        }
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
        try await Task.detached { try makeTextOnly(m) }.value  // GBs of file copying: off the main thread
    }

    static func isTextOnly(_ m: GemmaModel) -> Bool {
        FileManager.default.fileExists(atPath: m.dir.appending(path: ".textonly").path)
    }

    /// Keep only the text model (language_model.*), as llama.cpp's GGUF does (vision lives in a
    /// separate mmproj there). Every kept tensor is byte-identical; the audio and vision towers
    /// (~0.9 GiB) go. Without this the loader reads them into memory too, and E4B (6.3 GiB)
    /// is killed at the ~6 GiB per-app limit of an 8 GB iPhone. Rewrites the manifest with the
    /// new sizes so "Downloaded" stays a fact about the disk.
    static func makeTextOnly(_ m: GemmaModel) throws {
        guard !isTextOnly(m) else { return }
        let manifestURL = m.dir.appending(path: ".manifest.json")
        var files = try JSONDecoder().decode([HubFile].self, from: Data(contentsOf: manifestURL))
        let size = { (u: URL) in ((try? FileManager.default.attributesOfItem(atPath: u.path))?[.size] as? Int64) ?? 0 }
        var dropped = Set<String>()
        for (i, f) in files.enumerated() where f.path.hasSuffix(".safetensors") {
            let url = m.dir.appending(path: f.path)
            dropped.formUnion(try stripSafetensors(url, free: freeBytes) { $0.hasPrefix("language_model.") })
            files[i] = HubFile(path: f.path, size: size(url))
        }
        let indexURL = m.dir.appending(path: "model.safetensors.index.json")
        if var index = try? JSONSerialization.jsonObject(with: Data(contentsOf: indexURL)) as? [String: Any],
           var map = index["weight_map"] as? [String: Any] {
            for k in dropped { map[k] = nil }
            index["weight_map"] = map
            try JSONSerialization.data(withJSONObject: index, options: [.sortedKeys]).write(to: indexURL)
            if let j = files.firstIndex(where: { $0.path == "model.safetensors.index.json" }) {
                files[j] = HubFile(path: files[j].path, size: size(indexURL))
            }
        }
        try JSONEncoder().encode(files).write(to: manifestURL)
        try Data().write(to: m.dir.appending(path: ".textonly"))
    }

    static func delete(_ m: GemmaModel) throws {
        if FileManager.default.fileExists(atPath: m.dir.path) { try FileManager.default.removeItem(at: m.dir) }
    }

    private final class Inflight: @unchecked Sendable {
        var task: URLSessionDownloadTask?
    }

    private static func fetch(_ url: URL, to dest: URL, progress: @escaping @Sendable (Int64) -> Void) async throws {
        let inflight = Inflight()
        // Poll the byte count: KVO on task.progress never fired on device (stuck at 0%).
        let poll = Task {
            while !Task.isCancelled {
                if let t = inflight.task { progress(t.countOfBytesReceived) }
                try? await Task.sleep(for: .milliseconds(500))
            }
        }
        defer { poll.cancel() }
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                let task = URLSession.shared.downloadTask(with: url) { tmp, resp, err in
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
                inflight.task = task
                task.resume()
            }
        } onCancel: {
            inflight.task?.cancel()  // completes with URLError.cancelled, which ends the continuation
        }
    }
}

/// Rewrite a .safetensors file keeping only the tensors `keep` accepts; returns the dropped names.
/// Format: 8-byte little-endian header length, JSON header (name -> dtype, shape, data_offsets
/// relative to the data section), then the data. Kept tensors are copied byte for byte, in their
/// original order, with offsets recomputed; the header is space-padded to 8 bytes as the spec
/// asks. Writes beside the original and swaps it in, so an interruption never leaves half a file.
func stripSafetensors(_ url: URL, free: Int64, keep: (String) -> Bool) throws -> Set<String> {
    func fail(_ why: String) -> NSError {
        NSError(domain: "GemmaBench", code: 3, userInfo: [NSLocalizedDescriptionKey: "\(url.lastPathComponent): \(why)"])
    }
    let src = try FileHandle(forReadingFrom: url)
    defer { try? src.close() }
    guard let lenData = try src.read(upToCount: 8), lenData.count == 8 else { throw fail("not a safetensors file") }
    let n = Int(UInt64(littleEndian: lenData.withUnsafeBytes { $0.loadUnaligned(as: UInt64.self) }))
    guard let headerData = try src.read(upToCount: n), headerData.count == n,
          let header = try JSONSerialization.jsonObject(with: headerData) as? [String: Any] else { throw fail("bad header") }
    let dropped = Set(header.keys.filter { $0 != "__metadata__" && !keep($0) })
    guard !dropped.isEmpty else { return [] }

    var kept: [(name: String, info: [String: Any], start: Int, end: Int)] = []
    for (k, v) in header where k != "__metadata__" && keep(k) {
        guard let info = v as? [String: Any], let o = info["data_offsets"] as? [Int], o.count == 2 else { throw fail("bad entry \(k)") }
        kept.append((k, info, o[0], o[1]))
    }
    kept.sort { $0.start < $1.start }
    var out: [String: Any] = [:]
    if let meta = header["__metadata__"] { out["__metadata__"] = meta }
    var offset = 0
    for t in kept {
        var info = t.info
        info["data_offsets"] = [offset, offset + t.end - t.start]
        out[t.name] = info
        offset += t.end - t.start
    }
    var newHeader = try JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
    newHeader.append(contentsOf: [UInt8](repeating: UInt8(ascii: " "), count: (8 - newHeader.count % 8) % 8))
    guard Int64(8 + newHeader.count + offset) < free else {
        throw fail("not enough free space to rewrite it (needs \(ByteCountFormatter.string(fromByteCount: Int64(offset), countStyle: .file)))")
    }

    let tmp = url.appendingPathExtension("tmp")
    FileManager.default.createFile(atPath: tmp.path, contents: nil)
    let dst = try FileHandle(forWritingTo: tmp)
    var len = UInt64(newHeader.count).littleEndian
    try dst.write(contentsOf: Data(bytes: &len, count: 8))
    try dst.write(contentsOf: newHeader)
    let dataStart = UInt64(8 + n)
    for t in kept {
        try src.seek(toOffset: dataStart + UInt64(t.start))
        var left = t.end - t.start
        while left > 0 {
            try autoreleasepool {
                guard let chunk = try src.read(upToCount: min(left, 64 << 20)), !chunk.isEmpty else { throw fail("truncated data") }
                try dst.write(contentsOf: chunk)
                left -= chunk.count
            }
        }
    }
    try dst.close()
    _ = try FileManager.default.replaceItemAt(url, withItemAt: tmp)
    return dropped
}
