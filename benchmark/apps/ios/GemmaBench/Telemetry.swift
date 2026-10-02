import Foundation
import MLX
import UIKit
import os

/// 1 Hz sampler — the iPhone counterpart of agentic-edge's telemetry.py. iOS gives no power
/// rails or temperatures, so this records what the platform does expose.
@MainActor
final class Telemetry {
    struct Sample: Codable, Sendable {
        let ts: Double  // epoch
        let t: Double  // seconds relative to the end of the idle baseline; negative = idle
        let cpu: Double
        let thermal: Int
        let battery: Float
        let batteryState: Int
        let footprint: Double
    }

    private(set) var samples: [Sample] = []
    private var task: Task<Void, Never>?

    func start(_ url: URL) {
        UIDevice.current.isBatteryMonitoringEnabled = true
        append(url, "ts_epoch,ts_iso,proc_cpu_pct,thermal_state,battery_level,battery_state,low_power,mem_footprint_mb,mem_avail_mb,mlx_active_mb,mlx_cache_mb,mlx_peak_mb\n")
        let t0 = Date().addingTimeInterval(Bench.idleBaselineS)
        task = Task { @MainActor in
            let iso = ISO8601DateFormatter()
            while !Task.isCancelled {
                let now = Date(), p = ProcessInfo.processInfo, dev = UIDevice.current
                let s = Sample(ts: now.timeIntervalSince1970, t: now.timeIntervalSince(t0), cpu: Self.processCPU(), thermal: p.thermalState.rawValue,
                               battery: dev.batteryLevel, batteryState: dev.batteryState.rawValue, footprint: Self.footprintMB())
                samples.append(s)
                let mb = { (b: Int) in String(b >> 20) }
                append(url, [String(format: "%.3f", now.timeIntervalSince1970), iso.string(from: now),
                             String(format: "%.1f", s.cpu), String(s.thermal), String(format: "%.2f", s.battery),
                             String(s.batteryState), p.isLowPowerModeEnabled ? "1" : "0", String(format: "%.0f", s.footprint),
                             String(os_proc_available_memory() >> 20), mb(Memory.activeMemory), mb(Memory.cacheMemory),
                             mb(Memory.peakMemory)].joined(separator: ",") + "\n")
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func stop() { task?.cancel() }

    /// Sum over this process's threads, percent of one core (like `ps`; can exceed 100).
    nonisolated static func processCPU() -> Double {
        var threads: thread_act_array_t?
        var count: mach_msg_type_number_t = 0
        guard task_threads(mach_task_self_, &threads, &count) == KERN_SUCCESS, let threads else { return -1 }
        defer {
            vm_deallocate(mach_task_self_, vm_address_t(bitPattern: threads),
                          vm_size_t(Int(count) * MemoryLayout<thread_t>.stride))
        }
        var total = 0.0
        for i in 0..<Int(count) {
            var info = thread_basic_info()
            var n = mach_msg_type_number_t(THREAD_INFO_MAX)
            let kr = withUnsafeMutablePointer(to: &info) {
                $0.withMemoryRebound(to: integer_t.self, capacity: Int(n)) {
                    thread_info(threads[i], thread_flavor_t(THREAD_BASIC_INFO), $0, &n)
                }
            }
            if kr == KERN_SUCCESS && info.flags & TH_FLAGS_IDLE == 0 {
                total += Double(info.cpu_usage) / Double(TH_USAGE_SCALE) * 100
            }
        }
        return total
    }

    /// phys_footprint — the number jetsam kills on.
    nonisolated static func footprintMB() -> Double {
        var info = task_vm_info_data_t()
        var n = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(n)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &n)
            }
        }
        return kr == KERN_SUCCESS ? Double(info.phys_footprint) / 1_048_576 : -1
    }

    /// Nominal battery energy (Wh) from regulatory filings for the phones we expect; 0 = unknown,
    /// the app asks for it. ponytail: short table, add a device when someone runs on it.
    nonisolated static var nominalBatteryWh: Double {
        ["iPhone16,1": 12.70, "iPhone16,2": 17.11, "iPhone17,1": 13.94, "iPhone17,2": 18.17][machine] ?? 0
    }

    /// Marketing name for the ids this is likely to meet; anything else shows the raw id.
    nonisolated static var deviceName: String {
        ["iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max", "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus",
         "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max", "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max",
         "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus", "iPhone17,5": "iPhone 16e",
         "iPhone18,1": "iPhone 17 Pro", "iPhone18,2": "iPhone 17 Pro Max", "iPhone18,3": "iPhone 17", "iPhone18,4": "iPhone Air"][machine] ?? machine
    }

    /// e.g. "iPhone16,1" (iPhone 15 Pro).
    nonisolated static let machine: String = {
        var u = utsname()
        uname(&u)
        return withUnsafeBytes(of: &u.machine) { String(decoding: $0.prefix { $0 != 0 }, as: UTF8.self) }
    }()
}
