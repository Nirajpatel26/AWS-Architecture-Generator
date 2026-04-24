# AWS Lambda

AWS Lambda is a serverless compute service that lets you run code without provisioning servers. You pay only for compute time consumed. Lambda scales automatically with request volume and integrates natively with API Gateway, S3, DynamoDB, SQS, and EventBridge.

## When to use
- Event-driven workloads, APIs with bursty traffic, glue code between services.
- Workloads that can tolerate cold starts or where provisioned concurrency is acceptable.

## Limits and caveats
- 15-minute max execution.
- 10 GB memory max; CPU scales with memory.
- Cold starts can be 100ms–2s depending on runtime and VPC attachment.

## Production best practices
- Use provisioned concurrency for latency-sensitive paths.
- Place inside a VPC only when you need private resource access; it adds cold start latency.
- Stream logs to CloudWatch Logs and set a retention policy (default is forever).
- For HIPAA workloads, encrypt environment variables with a customer-managed KMS key.
