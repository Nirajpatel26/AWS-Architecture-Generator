# S3 + CloudFront Static Sites

Hosting a static site cost-effectively on AWS typically uses:

- **S3** for object storage with static website content. Block all public access and use an Origin Access Control (OAC) policy.
- **CloudFront** as the CDN in front of the bucket. Cache static assets aggressively; invalidate on deploy.
- **Route53** for DNS, with alias records to the CloudFront distribution.
- **ACM** for TLS certificates — must be in us-east-1 for CloudFront.

Typical monthly cost for a low-traffic static site: < $2 including CloudFront transfer and Route53 hosted zone.
