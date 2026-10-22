// moswalk // — Settings View
//
// Allows the operator to set the Tailscale IP of the Inference node at runtime.
// Changes take effect immediately — no app restart required.
// The server token field is stored in the keychain (not UserDefaults) so it
// never ends up in an iCloud backup or a crash log.

import SwiftUI
import Security

struct SettingsView: View {
    @EnvironmentObject var fieldClient: FieldAPIClient
    @EnvironmentObject var swarmSession: SwarmSession

    @State private var inferenceIP:   String = ""
    @State private var inferencePort: String = "7430"
    @State private var serverToken:   String = ""
    @State private var saved = false

    private let keychainService = "dev.munios.moswalk"
    private let keychainAccount = "server_token"

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    LabeledContent("Node") { Text("Inference (Qwen2.5-14B Q4)").foregroundStyle(.secondary) }
                    TextField("Tailscale IP  (100.x.x.x)", text: $inferenceIP)
                        .keyboardType(.numbersAndPunctuation)
                        .autocorrectionDisabled()
                    TextField("Port", text: $inferencePort)
                        .keyboardType(.numberPad)
                } header: {
                    Text("Inference Node")
                } footer: {
                    Text("Start the server on your Mac: python pantocraft/field/server.py --host <ip> --port 7430")
                        .font(.caption)
                }

                Section {
                    SecureField("X-Moswalk-Token value", text: $serverToken)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } header: {
                    Text("Auth Token")
                } footer: {
                    Text("Set MOSWALK_SERVER_TOKEN on the Mac to the same value. Leave blank on a trusted Tailscale network.")
                        .font(.caption)
                }

                Section {
                    Button("Save & Reconnect") { applySettings() }
                        .disabled(inferenceIP.isEmpty)
                    if saved {
                        Label("Saved", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    }
                }

                Section {
                    Button("Ping Mesh Nodes Now") {
                        Task { await swarmSession.pingMeshNodes() }
                    }
                    ForEach(swarmSession.meshNodes) { node in
                        HStack {
                            Circle()
                                .fill(node.isReachable ? Color.green : Color.red)
                                .frame(width: 8, height: 8)
                            Text(node.name)
                            Spacer()
                            if node.isReachable {
                                Text("\(Int(node.latencyMs)) ms")
                                    .foregroundStyle(.secondary)
                                    .font(.caption)
                            } else {
                                Text("unreachable").foregroundStyle(.secondary).font(.caption)
                            }
                        }
                    }
                } header: {
                    Text("Mesh Health")
                }
            }
            .navigationTitle("Settings")
            .onAppear { loadSettings() }
        }
    }

    // ── Persistence ───────────────────────────────────────────────────────

    private func loadSettings() {
        if let ip = UserDefaults.standard.string(forKey: "inference_ip"),    !ip.isEmpty   { inferenceIP   = ip }
        if let p  = UserDefaults.standard.string(forKey: "inference_port"), !p.isEmpty    { inferencePort = p  }
        if let tok = keychainRead() { serverToken = tok }
    }

    private func applySettings() {
        let port = Int(inferencePort) ?? 7430
        UserDefaults.standard.set(inferenceIP,   forKey: "inference_ip")
        UserDefaults.standard.set(inferencePort, forKey: "inference_port")
        fieldClient.setInferenceNode(ip: inferenceIP, port: port)

        if serverToken.isEmpty {
            keychainDelete()
            fieldClient.serverToken = nil
        } else {
            keychainWrite(serverToken)
            fieldClient.serverToken = serverToken
        }

        Task {
            await swarmSession.pingMeshNodes()
            await fieldClient.checkHealth()
        }

        saved = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { saved = false }
    }

    // ── Keychain helpers ──────────────────────────────────────────────────

    private func keychainRead() -> String? {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: keychainAccount,
            kSecReturnData:  true,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let str  = String(data: data, encoding: .utf8)
        else { return nil }
        return str
    }

    private func keychainWrite(_ value: String) {
        keychainDelete()
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: keychainAccount,
            kSecValueData:   value.data(using: .utf8)!,
            kSecAttrAccessible: kSecAttrAccessibleWhenUnlocked,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    private func keychainDelete() {
        let query: [CFString: Any] = [
            kSecClass:       kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: keychainAccount,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
