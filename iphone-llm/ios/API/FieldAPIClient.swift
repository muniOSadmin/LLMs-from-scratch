// moswalk // — FieldAPI HTTP Client
//
// Calls the Python FieldAPI server (pantocraft/field/server.py) running on the
// Mac Inference node over Tailscale. Falls back to a deterministic stub when
// the node is unreachable (field offline mode).
//
// Endpoint contract (mirrors server.py):
//   POST /consult          → ConsultResult JSON
//   GET  /health           → { "status": "ok", "kernel": true|false }
//   GET  /archive/signal   → TOON string for a BBL+filing_type

import Foundation

@MainActor
final class FieldAPIClient: ObservableObject {
    @Published var lastError: String?
    @Published var isOnline = false

    var baseURL: URL = URL(string: "http://100.64.0.2:7430")!  // Inference node Tailscale IP

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest  = 15
        config.timeoutIntervalForResource = 30
        return URLSession(configuration: config)
    }()

    private let encoder = JSONEncoder()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    // ── Health check ──────────────────────────────────────────────────────

    func checkHealth() async {
        let url = baseURL.appendingPathComponent("health")
        isOnline = (try? await session.data(from: url)) != nil
    }

    // ── Consult ───────────────────────────────────────────────────────────

    func consult(_ request: ConsultRequest) async throws -> ConsultResult {
        // Try Inference node first
        if let result = try? await remoteConsult(request) { return result }
        // Offline fallback: deterministic stub (no LLM, pathway from flags)
        return stubConsult(request)
    }

    private func remoteConsult(_ request: ConsultRequest) async throws -> ConsultResult {
        var req = URLRequest(url: baseURL.appendingPathComponent("consult"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(request)
        let (data, resp) = try await session.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            throw FieldAPIError.serverError((resp as? HTTPURLResponse)?.statusCode ?? 0)
        }
        return try decoder.decode(ConsultResult.self, from: data)
    }

    // ── Archive signal (TOON string) ──────────────────────────────────────

    func archiveSignal(bbl: String, filingType: String) async -> String? {
        var components = URLComponents(url: baseURL.appendingPathComponent("archive/signal"),
                                       resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "bbl", value: bbl),
            URLQueryItem(name: "filing_type", value: filingType),
        ]
        guard let url = components?.url,
              let (data, _) = try? await session.data(from: url),
              let text = String(data: data, encoding: .utf8)
        else { return nil }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // ── Offline stub ──────────────────────────────────────────────────────
    // Deterministic pathway from filing type + flags. No kernel, no LLM.
    // Gives the operator enough signal to work while offline.

    private func stubConsult(_ req: ConsultRequest) -> ConsultResult {
        var steps: [AgencyStep] = []
        var flags: [String] = []
        var confidence = 0.80

        // Pre-1987 → DEP first (legal invariant, rule_confidence 1.0)
        if req.flags.hasPre1987Risk {
            steps.append(AgencyStep(
                code: "DEP", role: "asbestos_clearance", status: "READY",
                blocking: true, estimatedDays: 14, confidence: 1.0,
                notes: "LEGAL INVARIANT: ACP5 or ACP21 before DOB work permit.",
                isConditional: true, sequentialAfter: []))
            flags.append("Pre-1987: DEP ACP5/ACP21 required before DOB Ready-for-Submission.")
        }

        // Landmark → LPC before DOB (legal invariant, rule_confidence 1.0)
        if req.flags.landmarked {
            steps.append(AgencyStep(
                code: "LPC", role: "landmark_approval", status: "READY",
                blocking: true, estimatedDays: 30, confidence: 1.0,
                notes: "LEGAL INVARIANT: LPC approval before any DOB exterior permit.",
                isConditional: true, sequentialAfter: steps.map(\.code)))
            flags.append("Landmark: LPC Certificate required. HEP Tier 3.")
            confidence = min(confidence, 0.65)
        }

        // DOB — always present
        let depOrLpc = steps.map(\.code)
        steps.append(AgencyStep(
            code: "DOB", role: "primary", status: "READY",
            blocking: true, estimatedDays: 45, confidence: 0.80,
            notes: "\(req.filingType.rawValue) filing.",
            isConditional: false, sequentialAfter: depOrLpc))

        flags.append("OFFLINE MODE: Inference node unreachable. Pathway is deterministic stub — connect to mesh for full kernel resolution.")

        let critDays = steps.filter(\.blocking).reduce(0) { $0 + $1.estimatedDays }

        return ConsultResult(
            engagementId: req.engagementId,
            bbl: req.bbl,
            address: req.address,
            projectType: req.project,
            agencyPathway: steps,
            criticalPathDays: critDays,
            optimizedDays: critDays,
            daysSaved: 0,
            escalationFlags: flags.filter { $0.contains("HEP") || $0.contains("Landmark") },
            pantocraftFlags: flags,
            overallConfidence: confidence,
            staleAgencies: [],
            hepPayload: nil,
            queryMs: 0
        )
    }

    // ── Update Tailscale IP at runtime (operator can change in Settings) ──

    func setInferenceNode(ip: String, port: Int = 7430) {
        baseURL = URL(string: "http://\(ip):\(port)")!
    }
}

enum FieldAPIError: LocalizedError {
    case serverError(Int)
    case decodingFailed
    case offline

    var errorDescription: String? {
        switch self {
        case .serverError(let code): return "Server returned \(code)"
        case .decodingFailed: return "Response decode failed"
        case .offline: return "Inference node unreachable"
        }
    }
}
