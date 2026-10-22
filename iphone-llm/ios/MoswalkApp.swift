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

    var body: some Scene {
        WindowGroup {
            ConsultView()
                .environmentObject(swarmSession)
                .environmentObject(fieldClient)
                .environmentObject(microInference)
        }
    }
}
