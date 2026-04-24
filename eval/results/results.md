# Eval Results

## Summary

- **cases**: 15
- **pass_count**: 15
- **fail_count**: 0
- **pass_rate**: 1.0
- **workload_match_rate**: 1.0
- **mean_component_recall**: 0.978
- **mean_component_precision**: 0.422
- **tf_validity_rate**: 1.0
- **cost_within_range_rate**: 1.0
- **compliance_match_rate**: 1.0
- **total_tfsec_high**: 0
- **total_input_tokens**: 0
- **total_output_tokens**: 0
- **total_cost_usd**: 0.0
- **mean_cost_per_run_usd**: 0.0
- **mean_wall_seconds**: 1.579
- **p50_wall_seconds**: 1.421
- **p95_wall_seconds**: 2.4405
- **p50_extract_seconds**: 0.3724
- **p95_extract_seconds**: 1.3099
- **p50_defaults_seconds**: 0.0001
- **p95_defaults_seconds**: 0.0002
- **p50_assumptions_seconds**: 0.0
- **p95_assumptions_seconds**: 0.0
- **p50_base_template_seconds**: 0.0004
- **p95_base_template_seconds**: 0.0005
- **p50_template_engine_seconds**: 0.0006
- **p95_template_engine_seconds**: 0.0012
- **p50_tf_generator_seconds**: 0.0001
- **p95_tf_generator_seconds**: 0.0001
- **p50_validator_seconds**: 0.0125
- **p95_validator_seconds**: 0.0159
- **p50_diagram_seconds**: 0.9388
- **p95_diagram_seconds**: 1.0709
- **p50_cost_seconds**: 0.0001
- **p95_cost_seconds**: 0.0002
- **p50_explainer_seconds**: 0.0804
- **p95_explainer_seconds**: 0.1732
- **workload_stability_rate**: 0.978

## Per-case breakdown

| id | pass | workload | recall | precision | tf_valid | tfsec_high | cost | $ / run | wall (s) |
|----|------|----------|--------|-----------|----------|------------|------|---------|----------|
| detailed_hipaa | PASS | True | 1.0 | 0.385 | True | 0 | $98.03 | $0.00000 | 4.411 |
| moderate_ecom | PASS | True | 1.0 | 0.667 | True | 0 | $5.70 | $0.00000 | 1.196 |
| vague_api | PASS | True | 1.0 | 0.333 | True | 0 | $5.70 | $0.00000 | 1.156 |
| ambiguous_pipeline | PASS | True | 1.0 | 0.444 | True | 0 | $19.00 | $0.00000 | 1.253 |
| contradictory_webapp | PASS | True | 1.0 | 0.333 | True | 0 | $5.70 | $0.00000 | 1.469 |
| pci_payments | PASS | True | 1.0 | 0.375 | True | 0 | $11.20 | $0.00000 | 1.321 |
| soc2_saas | PASS | True | 1.0 | 0.625 | True | 0 | $6.20 | $0.00000 | 1.441 |
| multi_region_saas | PASS | True | 1.0 | 0.25 | True | 0 | $21.70 | $0.00000 | 1.421 |
| ml_training_cv | PASS | True | 1.0 | 0.667 | True | 0 | $41.60 | $0.00000 | 1.393 |
| static_marketing | PASS | True | 0.667 | 0.429 | True | 0 | $2.35 | $0.00000 | 1.423 |
| iot_telemetry | PASS | True | 1.0 | 0.333 | True | 0 | $19.00 | $0.00000 | 1.464 |
| healthcare_ml | PASS | True | 1.0 | 0.462 | True | 0 | $45.10 | $0.00000 | 1.596 |
| internal_crud | PASS | True | 1.0 | 0.333 | True | 0 | $5.70 | $0.00000 | 1.413 |
| gaming_leaderboard | PASS | True | 1.0 | 0.375 | True | 0 | $1420.00 | $0.00000 | 1.286 |
| fintech_hipaa_pci | PASS | True | 1.0 | 0.312 | True | 0 | $29.70 | $0.00000 | 1.443 |

## Latency histogram (per stage, seconds)

| Stage | n | p50 | p95 | mean | max |
|---|---:|---:|---:|---:|---:|
| extract | 15 | 0.3724 | 1.3099 | 0.5557 | 3.0782 |
| defaults | 15 | 0.0001 | 0.0002 | 0.0001 | 0.0005 |
| assumptions | 15 | 0.0 | 0.0 | 0.0 | 0.0 |
| base_template | 15 | 0.0004 | 0.0005 | 0.0004 | 0.0005 |
| template_engine | 15 | 0.0006 | 0.0012 | 0.0006 | 0.0013 |
| tf_generator | 15 | 0.0001 | 0.0001 | 0.0001 | 0.0001 |
| validator | 15 | 0.0125 | 0.0159 | 0.0132 | 0.017 |
| diagram | 15 | 0.9388 | 1.0709 | 0.9055 | 1.2236 |
| cost | 15 | 0.0001 | 0.0002 | 0.0001 | 0.0006 |
| explainer | 15 | 0.0804 | 0.1732 | 0.0987 | 0.3315 |