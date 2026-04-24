# AWS Well-Architected Framework — Pillars Summary

## 1. Operational Excellence
Run and monitor systems, continually improve processes. Infrastructure as code, frequent small reversible changes, anticipate failure, learn from events.

## 2. Security
Defense in depth at every layer. Least privilege IAM, encryption in transit and at rest, traceability via CloudTrail, automated security response.

## 3. Reliability
Recover from failures, scale dynamically. Multi-AZ for workloads with tight RTO/RPO; multi-region for regulated or globally distributed workloads. Test recovery procedures.

## 4. Performance Efficiency
Use serverless where possible, right-size instances, use caching (ElastiCache, CloudFront). Measure and iterate.

## 5. Cost Optimization
Match supply to demand — auto-scale, use Spot/Savings Plans. Measure unit economics. Remove unused resources.

## 6. Sustainability
Select regions with lower carbon intensity. Right-size and consolidate workloads. Use managed services.
