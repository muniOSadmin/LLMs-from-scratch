// moswalk // — iOS App Entry Point
// iPhone 17 Pro mobile command center
//
// Architecture: local-first. All determinstic pathway resolution happens
// on-device via FieldAPIClient (Tailscale → Mac Inference node). The
// MicroLLM (1.1B INT4 CoreML) handles natural-language generation locally.
// No cloud. No persistent PII. NY S7263 information-not-advice framing.

import SwiftUI

@main
struct MoswalkApp: App {
    @StateObject private var swarmSession  = SwarmSession()
    @StateObject private var fieldClient   = FieldAPIClient()
    @StateObject private var microInference = MicroInference()

    init() {
        // Restore saved Tailscale IP and auth token from previous session
        if let ip   = UserDefaults.standard.string(forKey: "inference_ip"), !ip.isEmpty {
            let port = Int(UserDefaults.standard.string(forKey: "inference_port") ?? "7430") ?? 7430
            fieldClient.setInferenceNode(ip: ip, port: port)
        }
        // Token is read from keychain inside SettingsView.onAppear — no access here
    }

    var body: some Scene {
        WindowGroup {
            TabView {
                ConsultView()
                    .tabItem { Label("Consult", systemImage: "building.2") }

                SettingsView()
                    .tabItem { Label("Settings", systemImage: "gear") }
            }
            .environmentObject(swarmSession)
            .environmentObject(fieldClient)
            .environmentObject(microInference)
        }
    }
}
