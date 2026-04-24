# Amazon API Gateway

API Gateway is a managed service for creating REST, HTTP, and WebSocket APIs. HTTP APIs (v2) are cheaper and faster than REST APIs and are the recommended default for new serverless workloads.

## Auth
- Native Cognito User Pool authorizers for JWT-based auth.
- Lambda authorizers for custom logic.
- IAM authorizers for service-to-service.

## TLS
- All endpoints enforce TLS 1.2+.
- Custom domains require an ACM certificate in us-east-1 for edge-optimized endpoints, or in the API region for regional endpoints.

## Rate limiting
- Default account-level throttle 10,000 rps; per-stage and per-method throttles configurable.
