# Synthetic stability report

- Generator: Gemini
- **Consistency score:** 0.914 (0–1, higher = more robust; combines workload stability, component overlap, and crash rate)

## Overall (averaged across reference cases)

| Mode | N | workload_flip | comp_jaccard | compliance_drift | tf_valid | crash |
|---|---|---|---|---|---|---|
| paraphrase | 45 | 0.022 | 0.925 | 0.133 | 1.0 | 0.0 |
| adversarial | 45 | 0.0 | 0.955 | 0.111 | 1.0 | 0.0 |
| multilingual | 45 | 0.022 | 0.943 | 0.089 | 1.0 | 0.0 |
| noisy | 45 | 0.044 | 0.914 | 0.111 | 1.0 | 0.0 |