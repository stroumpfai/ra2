# Layer 5 — eval

`@pytest.mark.eval`, 30-100 hand-labelled records, run against real Ollama,
failing if accuracy drops more than N % below `evals/baseline.json`. Nightly CI
plus `just eval`.

**Out of phase 1.** The directory and the marker exist so the shape is settled
(sw-design.md §11.6).
