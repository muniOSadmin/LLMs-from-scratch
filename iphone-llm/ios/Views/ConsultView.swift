// moswalk // — Main Consultation View
// BBL input → filing type picker → flags → consult → ResultView

import SwiftUI

struct ConsultView: View {
    @EnvironmentObject private var fieldClient: FieldAPIClient
    @EnvironmentObject private var swarmSession: SwarmSession

    @State private var bbl          = ""
    @State private var address      = ""
    @State private var project      = ""
    @State private var filingType   = ConsultRequest.FilingType.a2
    @State private var landmarked   = false
    @State private var yearBuilt    = ""
    @State private var floodZone    = ""
    @State private var openViolations = ""
    @State private var showFlags    = false
    @State private var result: ConsultResult?
    @State private var errorMessage: String?
    @State private var isLoading    = false

    private var bblFormatted: String {
        // Accepts "1-00846-0001" or "1 00846 0001" or "100846001"
        bbl.trimmingCharacters(in: .whitespaces)
    }

    var body: some View {
        NavigationStack {
            Form {
                // ── Property ──────────────────────────────────────────────
                Section("Property") {
                    TextField("BBL  (e.g. 3-00783-0001)", text: $bbl)
                        .keyboardType(.numbersAndPunctuation)
                        .autocorrectionDisabled()
                    TextField("Address  (optional)", text: $address)
                        .autocorrectionDisabled()
                }

                // ── Project ───────────────────────────────────────────────
                Section("Project") {
                    TextField("Description  (e.g. rooftop deck addition)", text: $project)
                    Picker("Filing type", selection: $filingType) {
                        ForEach(ConsultRequest.FilingType.allCases) { ft in
                            Text(ft.label).tag(ft)
                        }
                    }
                }

                // ── Property flags (collapsible) ──────────────────────────
                Section {
                    DisclosureGroup("Property flags", isExpanded: $showFlags) {
                        Toggle("Landmarked / historic district", isOn: $landmarked)
                        TextField("Year built  (e.g. 1924)", text: $yearBuilt)
                            .keyboardType(.numberPad)
                        TextField("Flood zone  (AE / VE / leave blank)", text: $floodZone)
                            .autocorrectionDisabled()
                        TextField("Open violations  (count)", text: $openViolations)
                            .keyboardType(.numberPad)
                    }
                }

                // ── Swarm status ──────────────────────────────────────────
                Section("Mesh") {
                    HStack {
                        Circle()
                            .fill(swarmSession.inferenceNodeReachable ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        Text(swarmSession.inferenceNodeReachable
                             ? "Inference node reachable"
                             : "Inference node offline — using stub")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                // ── Action ────────────────────────────────────────────────
                Section {
                    Button(action: runConsult) {
                        HStack {
                            if isLoading {
                                ProgressView().scaleEffect(0.8)
                            }
                            Text(isLoading ? "Consulting…" : "Run Consultation")
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .disabled(bblFormatted.isEmpty || isLoading)
                    .buttonStyle(.borderedProminent)
                    .listRowBackground(Color.clear)
                }

                if let error = errorMessage {
                    Section {
                        Text(error)
                            .foregroundStyle(.red)
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("moswalk //")
            .navigationDestination(item: $result) { res in
                ResultView(result: res)
            }
        }
    }

    private func runConsult() {
        errorMessage = nil
        isLoading = true
        let req = ConsultRequest(
            bbl: bblFormatted,
            address: address.isEmpty ? bblFormatted : address,
            engagementId: "FIELD-\(Date().formatted(.dateTime.year().month().day()))-\(bblFormatted)",
            project: project,
            filingType: filingType,
            flags: ConsultRequest.PropertyFlags(
                landmarked: landmarked,
                yearBuilt: Int(yearBuilt),
                floodZone: floodZone.isEmpty ? nil : floodZone.uppercased(),
                openViolations: Int(openViolations) ?? 0
            )
        )
        Task {
            do {
                let res = try await fieldClient.consult(req)
                await MainActor.run {
                    result = res
                    isLoading = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = error.localizedDescription
                    isLoading = false
                }
            }
        }
    }
}

#Preview {
    ConsultView()
        .environmentObject(FieldAPIClient())
        .environmentObject(SwarmSession())
        .environmentObject(MicroInference())
}
