// moswalk // — MicroLLM CoreML Wrapper
//
// Wraps the MoswalkLLM.mlpackage exported by iphone-llm/micro_export.py.
// Exposes AsyncStream<String> for token-by-token streaming generation.
//
// CoreML model I/O contract (mirrors micro_export.py MLPackageExporter):
//   Input:  "input_ids"     — MLMultiArray shape [1, seq_len] dtype Int32
//   Output: "token_logits"  — MLMultiArray shape [1, vocab_size] dtype Float32
//
// Hardware: iPhone 17 Pro Neural Engine handles INT4 via ANE compute units.
// Target: < 30ms/token on ANE (1.1B INT4, ~560MB model).

import CoreML
import Foundation

@MainActor
final class MicroInference: ObservableObject {
    @Published var isLoaded     = false
    @Published var isGenerating = false
    @Published var loadError: String?

    private var model: MLModel?

    private static let eosTokenId = 2   // <EOS> — matches Llama tokenizer
    private static let maxSeqLen  = 512

    // ── Load ─────────────────────────────────────────────────────────────

    func load(from url: URL? = nil) async {
        let modelURL = url ?? Self.bundledModelURL()
        guard let modelURL else {
            loadError = "MoswalkLLM.mlpackage not found in bundle. Run micro_export.py first."
            return
        }
        do {
            let config = MLModelConfiguration()
            // Neural Engine + CPU fallback — ANE handles INT4 on A18 Pro
            config.computeUnits = .cpuAndNeuralEngine
            model = try await MLModel.load(contentsOf: modelURL, configuration: config)
            isLoaded = true
        } catch {
            loadError = "CoreML load failed: \(error.localizedDescription)"
        }
    }

    // ── Generate ──────────────────────────────────────────────────────────

    /// Stream generated tokens for `prompt`. Each yielded String is one decoded piece.
    func generate(prompt: String, maxTokens: Int = 256, temperature: Float = 0.7) -> AsyncStream<String> {
        AsyncStream { continuation in
            guard let model = self.model else {
                continuation.finish()
                return
            }
            isGenerating = true
            Task.detached(priority: .userInitiated) {
                var tokenIds = Self.tokenize(prompt)
                var generated = 0

                while generated < maxTokens {
                    // Truncate to maxSeqLen context window
                    let window = Array(tokenIds.suffix(Self.maxSeqLen))
                    guard let inputArray = try? MLMultiArray(shape: [1, window.count as NSNumber],
                                                             dataType: .int32) else { break }
                    for (i, t) in window.enumerated() { inputArray[i] = NSNumber(value: t) }

                    guard let features = try? MLDictionaryFeatureProvider(
                        dictionary: ["input_ids": inputArray]
                    ),
                    let output = try? model.prediction(from: features),
                    let logits = output.featureValue(for: "token_logits")?.multiArrayValue
                    else { break }

                    let nextToken = Self.sample(logits: logits, temperature: temperature)
                    if nextToken == Self.eosTokenId { break }

                    tokenIds.append(nextToken)
                    generated += 1
                    let piece = Self.decode(token: nextToken)
                    continuation.yield(piece)
                }

                continuation.finish()
                await MainActor.run { self.isGenerating = false }
            }
        }
    }

    // ── Tokenizer stubs ───────────────────────────────────────────────────
    // Full BPE tokenizer loads from tokenizer.json alongside the .mlpackage.
    // These stubs allow the scaffold to compile and run before weights arrive.

    static func tokenize(_ text: String) -> [Int] {
        // Byte-level fallback: one token per UTF-8 byte. Replace with BPE.
        text.utf8.map { Int($0) }
    }

    static func decode(token: Int) -> String {
        // Byte-level fallback: single character decode. Replace with BPE vocab.
        guard let scalar = Unicode.Scalar(token) else { return "" }
        return String(scalar)
    }

    // ── Sampling ──────────────────────────────────────────────────────────

    static func sample(logits: MLMultiArray, temperature: Float) -> Int {
        guard logits.count > 0 else { return eosTokenId }
        if temperature <= 0 { return argmax(logits) }

        // Temperature-scaled softmax
        var maxLogit = Float(-Float.infinity)
        for i in 0..<logits.count { maxLogit = max(maxLogit, logits[i].floatValue) }
        var probs = (0..<logits.count).map { exp((logits[$0].floatValue - maxLogit) / temperature) }
        let sum = probs.reduce(0, +)
        probs = probs.map { $0 / sum }

        // Multinomial sample
        var r = Float.random(in: 0..<1)
        for (i, p) in probs.enumerated() {
            r -= p
            if r <= 0 { return i }
        }
        return probs.count - 1
    }

    static func argmax(_ array: MLMultiArray) -> Int {
        var maxVal = Float(-Float.infinity)
        var maxIdx = 0
        for i in 0..<array.count {
            let v = array[i].floatValue
            if v > maxVal { maxVal = v; maxIdx = i }
        }
        return maxIdx
    }

    // ── Bundle lookup ─────────────────────────────────────────────────────

    static func bundledModelURL() -> URL? {
        Bundle.main.url(forResource: "MoswalkLLM", withExtension: "mlpackage")
    }
}
