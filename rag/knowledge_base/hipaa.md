# HIPAA on AWS — Key Requirements

A HIPAA-compliant architecture on AWS must:

1. **Sign a Business Associate Addendum (BAA)** with AWS before storing or processing PHI.
2. **Use only HIPAA-eligible services** (see AWS list: Lambda, API Gateway, DynamoDB, S3, RDS, KMS, CloudTrail, and more).
3. **Encrypt PHI at rest** with customer-managed KMS keys. DynamoDB, RDS, S3 all support CMK encryption natively.
4. **Encrypt PHI in transit** — enforce TLS 1.2+ on every endpoint. Disable HTTP.
5. **Audit all access** — enable CloudTrail in all regions with log file validation, deliver logs to a locked S3 bucket.
6. **Least-privilege IAM** — no wildcards in production policies.
7. **No public ingress to PHI-bearing resources** — block public S3 access, no public IPs on EC2/RDS.
8. **Backups and DR** — PITR for DynamoDB/RDS, cross-region replication for the DR strategy if RPO demands it.
