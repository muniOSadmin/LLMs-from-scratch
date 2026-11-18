// moswalk // — Swarm Session (MultipeerConnectivity + Tailscale mesh)
//
// Two transport layers:
//   1. MultipeerConnectivity (MPC) — local WiFi/BT peer discovery for Mac mesh
//      nodes on the same network as the iPhone.
//   2. Tailscale HTTP — WireGuard-encrypted calls to fixed Tailscale IPs when
//      MPC peers are not reachable (e.g. field use off local network).
//
// Node roles (from CLAUDE.md topology):
//   Sifting    — MBA 2020 M1   — Phi-4 Mini 3.8B — crawl + filtering
//   Inference  — Mac Desktop   — Qwen2.5-14B Q4  — planning + pathway resolution
//   Archival   — MBA 2014 i7   — none             — BIS mirror, backup
//
// The iPhone is always coordinator. It delegates heavy inference to the Inference
// node and streams results back via HTTP SSE over Tailscale.

import MultipeerConnectivity
import Foundation

// ── Node registry ─────────────────────────────────────────────────────────

struct MeshNode: Identifiable {
    let id = UUID()
    let name: String           // "sifting" | "inference" | "archival"
    let tailscaleIP: String    // set in SwarmConfig.json (not committed)
    let port: Int
    var isReachable: Bool = false
    var latencyMs: Double = 0

    var baseURL: URL {
        URL(string: "http://\(tailscaleIP):\(port)")!
    }
}

// ── Session ────────────────────────────────────────────────────────────────

@MainActor
final class SwarmSession: NSObject, ObservableObject {
    @Published var peers: [MCPeerID: MCSessionState] = [:]
    @Published var meshNodes: [MeshNode] = []
    @Published var inferenceNodeReachable = false

    private let myPeerID = MCPeerID(displayName: UIDevice.current.name)
    private let serviceType = "moswalk-swarm"
    private var mcSession: MCSession?
    private var advertiser: MCNearbyServiceAdvertiser?
    private var browser: MCNearbyServiceBrowser?

    override init() {
        super.init()
        loadMeshConfig()
        startMPC()
        Task { await pingMeshNodes() }
    }

    // ── Mesh config ────────────────────────────────────────────────────────

    private func loadMeshConfig() {
        // SwarmConfig.json lives in the app bundle (not in source control).
        // Format: { "nodes": [{ "name": "inference", "ip": "100.x.x.x", "port": 7430 }] }
        guard let url = Bundle.main.url(forResource: "SwarmConfig", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let config = try? JSONDecoder().decode(SwarmConfigFile.self, from: data)
        else {
            // Fallback: default Tailscale subnet addresses (operator sets these)
            meshNodes = [
                MeshNode(name: "inference", tailscaleIP: "100.64.0.2", port: 7430),
                MeshNode(name: "sifting",   tailscaleIP: "100.64.0.3", port: 7431),
                MeshNode(name: "archival",  tailscaleIP: "100.64.0.4", port: 7432),
            ]
            return
        }
        meshNodes = config.nodes.map {
            MeshNode(name: $0.name, tailscaleIP: $0.ip, port: $0.port)
        }
    }

    private struct SwarmConfigFile: Codable {
        struct NodeEntry: Codable { let name, ip: String; let port: Int }
        let nodes: [NodeEntry]
    }

    // ── MultipeerConnectivity ──────────────────────────────────────────────

    private func startMPC() {
        let session = MCSession(peer: myPeerID, securityIdentity: nil, encryptionPreference: .required)
        session.delegate = self
        mcSession = session

        advertiser = MCNearbyServiceAdvertiser(peer: myPeerID, discoveryInfo: ["role": "mobile"], serviceType: serviceType)
        advertiser?.delegate = self
        advertiser?.startAdvertisingPeer()

        browser = MCNearbyServiceBrowser(peer: myPeerID, serviceType: serviceType)
        browser?.delegate = self
        browser?.startBrowsingForPeers()
    }

    // ── Health checks ──────────────────────────────────────────────────────

    func pingMeshNodes() async {
        await withTaskGroup(of: (Int, Bool, Double).self) { group in
            for (i, node) in meshNodes.enumerated() {
                group.addTask {
                    let start = Date()
                    let url = node.baseURL.appendingPathComponent("health")
                    var req = URLRequest(url: url)
                    req.timeoutInterval = 3.0
                    let reachable = (try? await URLSession.shared.data(for: req)) != nil
                    let ms = Date().timeIntervalSince(start) * 1000
                    return (i, reachable, ms)
                }
            }
            for await (i, reachable, ms) in group {
                meshNodes[i].isReachable = reachable
                meshNodes[i].latencyMs = ms
            }
        }
        inferenceNodeReachable = meshNodes.first(where: { $0.name == "inference" })?.isReachable ?? false
    }

    /// Returns the base URL of the Inference node if reachable, nil otherwise.
    var inferenceBaseURL: URL? {
        meshNodes.first(where: { $0.name == "inference" && $0.isReachable })?.baseURL
    }

    /// Send a raw message to a connected MPC peer (for swarm coordination).
    func send(data: Data, to peerID: MCPeerID) throws {
        guard let session = mcSession else { return }
        try session.send(data, toPeers: [peerID], with: .reliable)
    }
}

// ── MCSession delegate ─────────────────────────────────────────────────────

extension SwarmSession: MCSessionDelegate {
    nonisolated func session(_ session: MCSession, peer peerID: MCPeerID, didChange state: MCSessionState) {
        Task { @MainActor in self.peers[peerID] = state }
    }
    nonisolated func session(_ session: MCSession, didReceive data: Data, fromPeer _: MCPeerID) {
        // Route inbound swarm messages — extend for speculative decode results
        _ = data
    }
    nonisolated func session(_: MCSession, didReceive _: InputStream, withName _: String, fromPeer _: MCPeerID) {}
    nonisolated func session(_: MCSession, didStartReceivingResourceWithName _: String, fromPeer _: MCPeerID, with _: Progress) {}
    nonisolated func session(_: MCSession, didFinishReceivingResourceWithName _: String, fromPeer _: MCPeerID, at _: URL?, withError _: Error?) {}
}

// ── MCAdvertiser delegate ──────────────────────────────────────────────────

extension SwarmSession: MCNearbyServiceAdvertiserDelegate {
    nonisolated func advertiser(_: MCNearbyServiceAdvertiser, didReceiveInvitationFromPeer peerID: MCPeerID,
                                withContext _: Data?, invitationHandler: @escaping (Bool, MCSession?) -> Void) {
        Task { @MainActor in invitationHandler(true, self.mcSession) }
    }
    nonisolated func advertiser(_: MCNearbyServiceAdvertiser, didNotStartAdvertisingPeer error: Error) {
        print("MPC advertise error: \(error)")
    }
}

// ── MCBrowser delegate ─────────────────────────────────────────────────────

extension SwarmSession: MCNearbyServiceBrowserDelegate {
    nonisolated func browser(_ browser: MCNearbyServiceBrowser, foundPeer peerID: MCPeerID, withDiscoveryInfo _: [String: String]?) {
        Task { @MainActor in browser.invitePeer(peerID, to: self.mcSession!, withContext: nil, timeout: 10) }
    }
    nonisolated func browser(_: MCNearbyServiceBrowser, lostPeer peerID: MCPeerID) {
        Task { @MainActor in self.peers.removeValue(forKey: peerID) }
    }
    nonisolated func browser(_: MCNearbyServiceBrowser, didNotStartBrowsingForPeers error: Error) {
        print("MPC browse error: \(error)")
    }
}
