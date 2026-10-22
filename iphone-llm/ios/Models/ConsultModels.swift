// moswalk // — Consultation Data Models
// Mirror of pantocraft/field/mobile_api.py ConsultResult + agentic/hep.py HEPPayload
// All structs are Codable so they round-trip cleanly over the Tailscale HTTP bridge.

import Foundation

// ── Request ────────────────────────────────────────────────────────────────

struct ConsultRequest: Codable {
    var bbl: String
    var address: String
    var engagementId: String
    var project: String
    var filingType: FilingType
    var flags: PropertyFlags

    enum FilingType: String, CaseIterable, Codable, Identifiable {
        case nb   = "NB"
        case a1   = "A1"
        case a2   = "A2"
        case a3   = "A3"
        case tr6  = "TR6"

        var id: String { rawValue }

        var label: String {
            switch self {
            case .nb:  return "New Building (NB)"
            case .a1:  return "Alt 1 — Major alteration"
            case .a2:  return "Alt 2 — Standard alteration"
            case .a3:  return "Alt 3 — Minor work"
            case .tr6: return "TR6 — Facade (FISP)"
            }
        }

        var estimatedComplexity: String {
            switch self {
            case .nb:  return "High"
            case .a1:  return "High"
            case .a2:  return "Medium"
            case .a3:  return "Low"
            case .tr6: return "Medium"
            }
        }
    }

    struct PropertyFlags: Codable {
        var landmarked: Bool        = false
        var landmarkType: String?   = nil
        var yearBuilt: Int?         = nil
        var floodZone: String?      = nil      // "AE" | "VE" | nil
        var openViolations: Int     = 0

        enum CodingKeys: String, CodingKey {
            case landmarked
            case landmarkType   = "landmark_type"
            case yearBuilt      = "year_built"
            case floodZone      = "flood_zone"
            case openViolations = "open_violations"
        }

        var hasPre1987Risk: Bool {
            guard let y = yearBuilt else { return false }
            return y < 1987
        }
    }
}

// ── Result ─────────────────────────────────────────────────────────────────

struct ConsultResult: Codable, Identifiable {
    let id = UUID()
    let engagementId: String
    let bbl: String
    let address: String
    let projectType: String
    let agencyPathway: [AgencyStep]
    let criticalPathDays: Int
    let optimizedDays: Int
    let daysSaved: Int
    let escalationFlags: [String]
    let pantocraftFlags: [String]
    let overallConfidence: Double
    let staleAgencies: [String]
    let hepPayload: HEPPayload?
    let queryMs: Double

    enum CodingKeys: String, CodingKey {
        case engagementId       = "engagement_id"
        case bbl, address
        case projectType        = "project_type"
        case agencyPathway      = "agency_pathway"
        case criticalPathDays   = "critical_path_days"
        case optimizedDays      = "optimized_days"
        case daysSaved          = "days_saved"
        case escalationFlags    = "escalation_flags"
        case pantocraftFlags    = "pantocraft_flags"
        case overallConfidence  = "overall_confidence"
        case staleAgencies      = "stale_agencies"
        case hepPayload         = "hep_payload"
        case queryMs            = "query_ms"
    }

    var filingMode: FilingMode {
        switch overallConfidence {
        case 0.80...: return .a
        case 0.40..<0.80: return .b
        default: return .c
        }
    }

    enum FilingMode {
        case a, b, c
        var label: String {
            switch self {
            case .a: return "Mode A — charted"
            case .b: return "Mode B — variable"
            case .c: return "Mode C — all hands"
            }
        }
        var color: String {
            switch self { case .a: return "green"; case .b: return "yellow"; case .c: return "red" }
        }
    }
}

struct AgencyStep: Codable, Identifiable {
    let id = UUID()
    let code: String
    let role: String
    let status: String
    let blocking: Bool
    let estimatedDays: Int
    let confidence: Double
    let notes: String?
    let isConditional: Bool
    let sequentialAfter: [String]

    enum CodingKeys: String, CodingKey {
        case code, role, status, blocking, notes
        case estimatedDays   = "estimated_days"
        case confidence
        case isConditional   = "is_conditional"
        case sequentialAfter = "sequential_after"
    }

    var isStale: Bool { confidence < 0.70 }
    var isBlocked: Bool { status == "BLOCKED" || status == "STUCK" }
}

// ── HEP Payload ────────────────────────────────────────────────────────────

struct HEPPayload: Codable {
    let traceId: String
    let tier: Int                  // 1 | 2 | 3
    let triggerType: String        // landmark | confidence | policy | …
    let triggerDetail: String
    let filingMode: String         // A | B | C
    let slaLabel: String           // "15 minutes (page counsel)" etc.
    let proposedAction: String
    let affectsLandmark: Bool
    let informationNotAdvice: Bool
    let options: [String]

    enum CodingKeys: String, CodingKey {
        case traceId             = "trace_id"
        case tier
        case triggerType         = "trigger_type"
        case triggerDetail       = "trigger_detail"
        case filingMode          = "filing_mode"
        case slaLabel            = "sla_label"
        case proposedAction      = "proposed_action"
        case affectsLandmark     = "affects_landmark"
        case informationNotAdvice = "information_not_advice"
        case options
    }

    var tierLabel: String {
        switch tier {
        case 3: return "TIER 3 — page counsel"
        case 2: return "TIER 2 — lead review"
        default: return "TIER 1 — team review"
        }
    }
}
