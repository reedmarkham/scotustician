# 🏛️ scotustician

**scotustician** is a data ingestion pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts, deployed on AWS using Docker, CDK, and GitHub Actions.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. Rather than overengineering the initial pipeline, this project takes a minimalist approach to data ingestion in order to prioritize building an end-to-end system for interacting with SCOTUS OA transcripts using vector representations (text embeddings).

This pipeline supports downstream tasks such as semantic search, clustering, and interactive visualization by transforming transcripts into structured embeddings using [Hugging Face transformer models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) and storing them in a PostgreSQL database with pgvector extension.

The current model generates 384-dimensional embeddings optimized for clustering and retrieval. Future work may experiment with alternative models to improve domain-specific accuracy or efficiency.

---

## System Design
![scotustician](/scotustician-architecture.svg)
```
scotustician/
├── ingest/            	# Containerized task to ingest raw data from Oyez.org API to S3
├── transformers/      	# Containerized task for generating and storing text embeddings in PostgreSQL
├── infra/             	# AWS CDK code defining ECS services and other infrastructure
└── .github/workflows/ 	# CI/CD pipelines via GitHub Actions
```
- AWS CDK (TypeScript) provisions clusters, networking, and ECS tasks using Docker images.
- ECS Fargate task for `ingest` parallelizes ingestion of JSON data from Oyez.org API to S3 using Python, logging 'junk' and other pipeline info to the bucket for audit.
- ECS EC2 task with GPU support for `transformers` (separate tasks available conditional on GPU availability) that also serializes and stores transcript data as XML files on S3.
- Shared infrastructure (e.g., EC2 instance, security groups) for GPU tasks is also conditionally deployed in the above stack.
- GitHub Actions CI/CD wrapping the logic and `cdk` steps for above - after a few prerequisites, outlined below.

Data Pipeline:
1. `ingest` collects and loads SCOTUS metadata and case text from Oyez.org API to S3.
2. Processed text from `ingest` on S3 is read by `transformers`, which uses [Hugging Face models](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) to generate embeddings. 
* Also serialized data (XML) for the transcript is written out to S3.
3. Embeddings are stored in a [PostgreSQL database with pgvector extension](https://www.github.com/reedmarkham/scotustician-db), which was deployed separately.

After tasks complete, the S3 bucket should (depending on any actual "junk" data) look like:
```
scotustician/
├── raw/oa/      	  # Raw oral argument JSON files
├── xml/              # Serialized XML for the oral argument transcripts
├── junk/      		  # Raw oral argument JSON files missing key data or malformed
├── logs/       	  # JSON representations of pipeline metrics, later to be queried in Athena, etc.
```
---
## Prerequisites

### 1. AWS IAM Credentials

You will need the ARN, access key, and secret access key for an existing AWS IAM user with permissions defined in [`iam-sample.json`](iam-sample.json). This user is used to authenticate CDK deployments via GitHub Actions.

> To-do: define and manage this IAM user in a separate CDK repository.

### 2. Deploy `scotustician-db`

Make sure [`scotustician-db`](https://github.com/reedmarkham/scotustician-db) is deployed first. This provides the S3 and PostgreSQL infrastructure for storage and indexing.

### 3. Set GitHub Repository Secrets

Configure the following repository secrets in **GitHub > Settings > Secrets and variables > Actions > Repository secrets**:

| Secret Name         | Description                                       | Example Value                                      |
|---------------------|---------------------------------------------------|----------------------------------------------------|
| `AWS_ACCOUNT_ID`    | AWS account ID                                    | `123456789012`                                     |
| `AWS_REGION`        | AWS region                                        | `us-east-1`                                        |
| `AWS_IAM_ARN`       | IAM user's ARN                                    | `arn:aws:iam::123456789012:user/github-actions`    |
| `AWS_ACCESS_KEY_ID` | IAM user's access key                             | `AKIAIOSFODNN7EXAMPLE`                             |
| `AWS_SECRET_ACCESS_KEY` | IAM user's secret access key                      | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`         |
| `S3_BUCKET`         | S3 bucket name (optional, defaults to scotustician) | `scotustician`                                   |

> **Note**: PostgreSQL credentials are now managed through AWS Secrets Manager. The database host and secret name are configured via CDK context parameters. See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for details.

---

## Bootstrap the CDK Environment

You must manually bootstrap the CDK environment before running CI/CD deployments.

### a. Run the Bootstrap Command

```bash
npx cdk bootstrap \
  --toolkit-stack-name CDKToolkit-scotustician \
  --qualifier sctstcn \
  aws://<AWS_ACCOUNT_ID>/<AWS_REGION>
```

### b. Update `infra/cdk.json`

```json
{
  "app": "npx ts-node --prefer-ts-exts bin/scotustician.ts",
  "context": {
    "aws:cdk:bootstrap-qualifier": "sctstcn"
  }
}
```

### c. Update CDK Stacks with Qualifier

```ts
const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

super(scope, id, {
  ...props,
  synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
});
```

---

## (Optional) Enable GPU Support on AWS EC2

To run GPU-enabled `transformers` tasks, your AWS account must have GPU vCPU quotas.

### Requesting a Quota Increase

1. Go to the [EC2 vCPU Limits page](https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas)
2. Search for:
   - **Running Spot/On-Demand G and VT instances**, or
   - **Running Spot/On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances**
3. Click the relevant quota and **Request quota increase**
4. AWS typically approves small increases (1 instance) within a few hours

> If GPU capacity is unavailable, the pipeline will fall back to CPU-based infrastructure.

> The [ECS cluster](infra/lib/scotustician-shared-stack.ts#62) and [transformers task definition](infra/lib/scotustician-transformers-stack.ts#41) should be adjusted depending on intended workload, budget, etc.

---

## Running ECS Tasks

After deployment via CDK, you can run the data ingestion and transformation tasks using the provided shell scripts. These scripts automatically retrieve AWS resource identifiers from CloudFormation outputs, eliminating the need for manual configuration.

### Prerequisites

1. Ensure AWS CLI is configured with appropriate credentials
2. Verify that all CDK stacks have been successfully deployed
3. Make scripts executable: `chmod +x scripts/*.sh`

### Available Scripts

The `scripts/` directory contains the following utilities:

| Script | Purpose |
|--------|---------|
| `ingest-data.sh` | Runs the data ingestion task to fetch SCOTUS oral arguments from Oyez.org API |
| `transform-data.sh` | Runs the transformer task to generate embeddings and store them in PostgreSQL |
| `test-deployment.sh` | Validates the deployment and runs diagnostic checks |

### Running Data Ingestion

To ingest oral argument data from the Oyez.org API:

```bash
./scripts/ingest-data.sh
```

This script will:
- Dynamically retrieve the ECS cluster name and task definition from CloudFormation
- Launch a Fargate task to ingest data
- Store raw JSON files in S3 under `s3://scotustician/raw/oa/`
- Print sample data for validation after completion

You can override default environment variables:
```bash
aws ecs run-task ... --overrides '{
  "containerOverrides": [{
    "name": "IngestContainer",
    "environment": [
      {"name": "START_TERM", "value": "2023"},
      {"name": "END_TERM", "value": "2024"},
      {"name": "DRY_RUN", "value": "true"}
    ]
  }]
}'
```

### Running Embedding Generation

To generate embeddings from ingested data:

```bash
./scripts/transform-data.sh
```

This script will:
- Detect whether GPU or CPU task definitions are available
- Use appropriate security groups for RDS access
- Read data from S3 and generate embeddings using Hugging Face models
- Store embeddings in PostgreSQL with pgvector
- Print database validation summary after completion

### Testing the Deployment

To validate your deployment:

```bash
./scripts/test-deployment.sh
```

This comprehensive test script will:
- Verify all CloudFormation stacks exist
- Check ECS cluster status and running tasks
- Validate VPC endpoints and networking configuration
- Test S3 bucket accessibility
- Verify database secret configuration
- Run a dry-run test of the ingest task
- Provide a summary of deployment health

### Monitoring Task Execution

After launching tasks, monitor their progress:

```bash
# View real-time logs for ingest tasks
aws logs tail /ecs/ingest --follow

# View real-time logs for transformer tasks
aws logs tail /ecs/transformers --follow

# Check task status
aws ecs describe-tasks \
  --cluster <cluster-name> \
  --tasks <task-arn>
```

### Advanced Usage

For detailed AWS CLI commands and troubleshooting, refer to:
- [AWS_RESOURCE_GUIDE.md](AWS_RESOURCE_GUIDE.md) - Comprehensive guide for AWS resource management
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Fargate to RDS connectivity setup

### Important Notes

- The ingest task requires public subnet access to reach the Oyez.org API
- The transformer task should use private subnets when accessing RDS
- GPU tasks will fall back to CPU if GPU resources are unavailable
- All scripts respect the `AWS_REGION` environment variable (defaults to `us-east-1`)

---

## To-Do

- Add Semantic Search API CDK stack
- Build and deploy UI (another CDK stack) with search and visualization


---
## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk`.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.