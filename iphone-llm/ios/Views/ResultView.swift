// moswalk // — Consultation Result View
// Displays agency pathway, optimization tracks, HEP escalation card.

import SwiftUI

struct ResultView: View {
    let result: ConsultResult
    @EnvironmentObject private var microInference: MicroInference
    @State private var generatedSummary = ""
    @State private var isGenerating = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                headerCard
                pathwaySection
                if !result.escalationFlags.isEmpty || result.hepPayload != nil {
                    hepSection
                }
                if !result.MASTFlags.isEmpty {
                    flagsSection
                }
                if microInference.isLoaded {
                    llmSection
                }
                disclaimer
            }
            .padding()
        }
        .navigationTitle(result.bbl)
        .navigationBarTitleDisplayMode(.inline)
    }

    // ── Header ─────────────────────────────────────────────────────────────

    private var headerCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(result.address)
                .font(.headline)
            Text("\(result.projectType)  ·  \(result.engagementId)")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 16) {
                statTile(label: "Critical path", value: "~\(result.criticalPathDays)d", accent: .primary)
                statTile(label: "Optimized", value: "~\(result.optimizedDays)d", accent: .green)
                if result.daysSaved > 0 {
                    statTile(label: "Saves", value: "~\(result.daysSaved)d", accent: .blue)
                }
                confidenceTile
            }
        }
        .padding()
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private func statTile(label: String, value: String, accent: Color) -> some View {
        VStack(spacing: 2) {
            Text(value).font(.title3.bold()).foregroundStyle(accent)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var confidenceTile: some View {
        VStack(spacing: 2) {
            Text("\(Int(result.overallConfidence * 100))%")
                .font(.title3.bold())
                .foregroundStyle(modeColor)
            Text(result.filingMode.label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var modeColor: Color {
        switch result.filingMode {
        case .a: return .green
        case .b: return .yellow
        case .c: return .red
        }
    }

    // ── Agency pathway ─────────────────────────────────────────────────────

    private var pathwaySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Agency Pathway")
                .font(.subheadline.bold())
            ForEach(result.agencyPathway) { step in
                AgencyStepRow(step: step)
            }
        }
    }

    // ── HEP escalation ─────────────────────────────────────────────────────

    private var hepSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("HEP Escalation", systemImage: "exclamationmark.triangle.fill")
                .font(.subheadline.bold())
                .foregroundStyle(.red)

            if let hep = result.hepPayload {
                HEPCard(payload: hep)
            }

            ForEach(result.escalationFlags, id: \.self) { flag in
                flagRow(flag, color: .orange)
            }
        }
        .padding()
        .background(Color.red.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
    }

    // ── MAST flags ───────────────────────────────────────────────────

    private var flagsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Flags")
                .font(.subheadline.bold())
            ForEach(result.MASTFlags, id: \.self) { flag in
                flagRow(flag, color: .secondary)
            }
        }
    }

    private func flagRow(_ text: String, color: Color) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text("⚑").foregroundStyle(color)
            Text(text).font(.caption)
        }
    }

    // ── MicroLLM generation ────────────────────────────────────────────────

    private var llmSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("On-device Summary").font(.subheadline.bold())
                Spacer()
                if isGenerating {
                    ProgressView().scaleEffect(0.7)
                } else {
                    Button("Generate") { runGeneration() }
                        .font(.caption)
                }
            }
            if !generatedSummary.isEmpty {
                Text(generatedSummary)
                    .font(.caption)
                    .padding(8)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
            }
        }
    }

    private func runGeneration() {
        isGenerating = true
        generatedSummary = ""
        let prompt = result.agencyPathway
            .map { "\($0.code) ~\($0.estimatedDays)d" }
            .joined(separator: " → ")
        Task {
            for await token in microInference.generate(
                prompt: "NYC filing pathway for \(result.bbl): \(prompt). Key risks:",
                maxTokens: 120
            ) {
                await MainActor.run { generatedSummary += token }
            }
            await MainActor.run { isGenerating = false }
        }
    }

    // ── Disclaimer ─────────────────────────────────────────────────────────

    private var disclaimer: some View {
        Text("⚖  Information only — not legal or professional advice. Licensed professional sign-off required before any action. NY S7263.")
            .font(.caption2)
            .foregroundStyle(.secondary)
            .multilineTextAlignment(.center)
    }
}

// ── Supporting views ────────────────────────────────────────────────────────

struct AgencyStepRow: View {
    let step: AgencyStep

    var body: some View {
        HStack(spacing: 10) {
            // Status indicator
            Circle()
                .fill(stepColor)
                .frame(width: 8, height: 8)
            // Agency code
            Text(step.code)
                .font(.caption.bold().monospaced())
                .frame(width: 60, alignment: .leading)
            // Days
            Text("~\(step.estimatedDays)d")
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .frame(width: 40, alignment: .trailing)
            // Tags
            HStack(spacing: 4) {
                if step.blocking {
                    tag("blocking", color: .orange)
                }
                if step.isConditional {
                    tag("triggered", color: .blue)
                }
                if step.isStale {
                    tag("stale", color: .yellow)
                }
            }
            Spacer()
            // Confidence
            Text("\(Int(step.confidence * 100))%")
                .font(.caption2)
                .foregroundStyle(step.isStale ? .yellow : .secondary)
        }
        .padding(.vertical, 2)
    }

    private var stepColor: Color {
        if step.isBlocked { return .red }
        if step.isStale   { return .yellow }
        return .green
    }

    private func tag(_ label: String, color: Color) -> some View {
        Text(label)
            .font(.system(size: 9, weight: .medium))
            .padding(.horizontal, 4).padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }
}

struct HEPCard: View {
    let payload: HEPPayload

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(payload.tierLabel)
                    .font(.caption.bold())
                    .foregroundStyle(.red)
                Spacer()
                Text("SLA: \(payload.slaLabel)")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Text("Mode \(payload.filingMode)  ·  \(payload.triggerType)")
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
            Text(payload.triggerDetail)
                .font(.caption)
        }
        .padding(10)
        .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}

#Preview {
    NavigationStack {
        ResultView(result: ConsultResult(
            engagementId: "PREVIEW-001",
            bbl: "3-00783-0001",
            address: "123 Flatbush Ave Brooklyn",
            projectType: "A2 alteration",
            agencyPathway: [
                AgencyStep(code: "DEP", role: "asbestos_clearance", status: "READY",
                           blocking: true, estimatedDays: 14, confidence: 1.0,
                           notes: "ACP5 or ACP21 required", isConditional: true,
                           sequentialAfter: []),
                AgencyStep(code: "DOB", role: "primary", status: "READY",
                           blocking: true, estimatedDays: 45, confidence: 0.85,
                           notes: nil, isConditional: false, sequentialAfter: ["DEP"]),
            ],
            criticalPathDays: 59,
            optimizedDays: 45,
            daysSaved: 14,
            escalationFlags: [],
            MASTFlags: [],
            overallConfidence: 0.85,
            staleAgencies: [],
            hepPayload: nil,
            queryMs: 42
        ))
        .environmentObject(MicroInference())
    }
}
