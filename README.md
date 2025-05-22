# 🏛️ scotustician

**scotustician** is a data ingestion pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts, deployed on AWS using Docker, CDK, and GitHub Actions.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. Rather than overengineering the initial pipeline, this project takes a minimalist approach to data ingestion in order to prioritize building an end-to-end system for interacting with SCOTUS OA transcripts using vector representations (text embeddings).

This pipeline supports downstream tasks such as semantic search, clustering, and interactive visualization by transforming transcripts into structured embeddings using [Hugging Face transformer models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) and storing them in an OpenSearch vector database.

The current model generates 384-dimensional embeddings optimized for clustering and retrieval. Future work may experiment with alternative models to improve domain-specific accuracy or efficiency.

---

## Repository, System Design, and Data Pipeline Summaries
```
scotustician/
├── ingest/            	# Containerized task to ingest raw data from Oyez.org API to S3
├── transformers/      	# Containerized task for generating and storing text embeddings on OpenSearch
├── infra/             	# AWS CDK code defining ECS services and other infrastructure
└── .github/workflows/ 	# CI/CD pipelines via GitHub Actions
```
- AWS CDK (TypeScript) provisions clusters, networking, and ECS tasks using Docker images.
- ECS Fargate task for `ingest` parallelizes ingestion of JSON data from Oyez.org API to S3 using Python, logging 'junk' and other pipeline info to the bucket for audit.
- ECS EC2 task with GPU support for `transformers` (separate tasks available conditional on GPU availability) that also serializes and stores transcript data as XML files on S3
- Shared infrastructure (e.g., EC2 instance, security groups) for GPU tasks is also conditionally deployed in the above stack.
- GitHub Actions CI/CD wrapping the logic and `cdk` steps for above - after a few prerequisites, outlined below.

Data Pipeline:
1. `ingest` collects and loads SCOTUS metadata and case text from Oyez.org API to S3.
2. Processed text from `ingest` on S3 is read by `transformers`, which uses [Hugging Face models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) to generate embeddings. 
* Also serialized data (XML) for the transcript is written out to S3.
3. Embeddings are stored in an [OpenSearch vector database](https://www.github.com/reedmarkham/scotustician-db), which was deployed separately.

After tasks complete, the S3 bucket should (depending on any actual "junk" data) look like:
```
scotustician/
├── raw/oa/      	# Raw oral argument JSON files
├── xml/ 			    # Serialized XML for the oral argument transcripts if raw data contains this
├── junk/      		# Raw oral argument JSON files malformed, missing key data, etc.
├── logs/       	# JSON representations of pipeline metrics, later to be queried in Athena, etc.
```
---
## Prerequisites
1. The ARN, access key, and secret key ID for a previously-created (i.e. via console or other stack) AWS IAM user, with a minimal policy like [iam-sample.json](iam-sample.json).
* To-do: implement the IAM user in CDK as a separate repository
2. Deploy [`scotustician-db`](github.com/reedmarkham/scotustician-db)
3. Ensure the following secrets are configured in your GitHub at **Settings > Secrets and variables > Actions > repository secrets**:

| Secret Name         | Description                                                       | Example Value                                  |
|---------------------|-------------------------------------------------------------------|------------------------------------------------|
| `AWS_ACCOUNT_ID`    | AWS account ID                                                    | `123456789012`                                 |
| `AWS_REGION`        | AWS region                                                        | `us-east-1`                                    |
| `AWS_IAM_ARN`       | AWS IAM user's ARN                                                | `arn:aws:iam::123456789012:user/github-actions`|
| `AWS_ACCESS_KEY`    | AWS IAM user's access key                                         | `AKIAIOSFODNN7EXAMPLE`                         |
| `AWS_SECRET_KEY_ID` | AWS IAM user's secret key                                         | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`     |
| `OPENSEARCH_HOST`   | URL of your OpenSearch domain                                     | `search-my-domain.us-east-1.es.amazonaws.com`  |
| `OPENSEARCH_PASS`   | Password for the OpenSearch admin user                            | `superSecurePass123!`                          |

4. **Bootstrap the environment outside of CI/CD**
4a. Make sure to use a <=10 chracter `--qualifier` and run the bootstrap command out of CI/CD:
```
npx cdk bootstrap \
  --toolkit-stack-name CDKToolkit-scotustician \
  --qualifier sctstcn \
  aws://<AWS_ACCOUNT_ID>/<AWS_REGION>
```
4b. Then update the `infra/cdk.json` accordingly:
```
{
  "app": "npx ts-node --prefer-ts-exts bin/scotustician.ts",
  "context": {
    "aws:cdk:bootstrap-qualifier": "sctstcn"
  }
}
```
4c. As well as the stacks:
```
const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'YOUR_QUALIFIER';
...
super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });
```
5. **Request vCPU quota increase for GPU-type instances on your AWS account**
* When deploying via GitHub Actions, the presence of AWS GPU compute capacity (e.g., vCPU quota for `p2`, `p3`, `p4`, or `g4dn` instance families) is checked. If no GPU capacity is available, the EC2 instance and GPU-based `transformers` task definition are **skipped**, and only CPU-based fallback infrastructure is provisioned.
* To enable GPU support:
- Submit a vCPU quota increase request (see below).
- The CI/CD pipeline will include GPU resources only if quotas are available.
* General steps for the AWS process:
```
Go to the EC2 vCPU Limits page:
* https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas

Look for the quota named:
* Running On-Demand G and VT instances
* OR Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances if you’re using a different instance type

Click on the relevant quota
* Request quota increase

Submit
* AWS typically approves within a few hours to a day, especially for small (1 instance) increases.
```
6. **Run the tasks in an ad-hoc script**
* You can manually trigger ECS tasks using the AWS CLI.
6a. First, **review the CDK stack outputs** for the following values:
- `ClusterName`
- `PublicSubnetId1` or `PrivateSubnetId`
- `SecurityGroupId`
- Task Definition ARNs for each service
6b. Run ingest task on Fargate (always CPU)
```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianIngestStack-IngestTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                      # Public or NAT-enabled private subnet
SG_ID="sg-xxxxxxxxxxxxxxxxx"                              # Must allow HTTPS egress
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```
Check out your S3!

6c. (if GPU successful) run transformer task on EC2
```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianTransformersStack-TransformersGpuTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                                     # Private subnet for EC2
SG_ID="sg-xxxxxxxxxxxxxxxxx"
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type EC2 \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```
 * ⚠️ The GPU instance used to run this task is provisioned as a **Spot EC2 instance** and tagged with `AutoStop=true`. Some unavailability is to be expected with Spot instances, but we accept that for the discounted cost.
- It will be **automatically stopped at 7 PM ET** each day by a scheduled Lambda rule.
- To run a GPU task after that time, **manually start the instance**:
```bash
aws ec2 start-instances --instance-ids i-xxxxxxxxxxxxxxxxx --region us-east-1
```
6c. (If GPU unavailable) Fargate Transformers Task (CPU)
```bash
#!/bin/bash

CLUSTER_NAME="ScotusticianCluster"
TASK_DEF="ScotusticianTransformersStack-TransformersCpuTaskDefXXXXXXXX"  # Replace with actual ARN
SUBNET_ID="subnet-xxxxxxxxxxxxxxxxx"                                     # Public or private subnet with NAT
SG_ID="sg-xxxxxxxxxxxxxxxxx"
REGION="us-east-1"

aws ecs run-task \
  --cluster "$CLUSTER_NAME" \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --count 1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_ID],securityGroups=[$SG_ID],assignPublicIp=DISABLED}" \
  --region "$REGION"
```

Check out your OpenSearch!

To-do: Semantic Search API + UI

---
## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk`.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.