# Amazon DynamoDB

DynamoDB is a serverless NoSQL key-value and document database. It offers single-digit-millisecond latency at any scale and on-demand (pay-per-request) pricing for unpredictable workloads.

## Capacity modes
- **On-demand (PAY_PER_REQUEST)**: no capacity planning, per-request pricing. Best for spiky or new workloads.
- **Provisioned**: reserved RCU/WCU, optionally autoscaled. Cheaper at steady high throughput.

## HA and durability
- Data replicated across 3 AZs automatically.
- Global Tables for active-active multi-region replication.
- Point-in-time recovery (PITR) enables restore to any second in the last 35 days.

## Compliance
- HIPAA-eligible with a signed BAA.
- Server-side encryption is on by default; use a customer-managed KMS key for PHI.
