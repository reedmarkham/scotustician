# scotustician

**scotustician** is a data ingestion pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts, deployed on AWS using Docker, CDK, and GitHub Actions.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. Rather than overengineering the initial pipeline, this project takes a minimalist approach to data ingestion in order to prioritize building an end-to-end system for interacting with SCOTUS OA transcripts using vector representations (text embeddings).

This pipeline supports downstream tasks such as semantic search, clustering, and interactive visualization by transforming transcripts into structured embeddings. The system uses [baai/bge-m3](https://huggingface.co/BAAI/bge-m3) model by default, which generates 1024-dimensional embeddings optimized for semantic retrieval. The embeddings are limited to a maximum of 2000 dimensions to ensure compatibility with pgvector.

---

## System Design
![scotustician](/scotustician-architecture.svg)
```
scotustician/
├── ingest/            	# Containerized task to ingest raw data from Oyez.org API to S3
├── transformers/      	# Containerized task for generating and storing text embeddings in PostgreSQL
├── infrastructure/             	# AWS CDK code defining ECS services and other infrastructure
└── .github/workflows/ 	# CI/CD pipelines via GitHub Actions
```
- AWS CDK (TypeScript) provisions clusters, networking, and ECS tasks using Docker images.
- ECS Fargate task for `ingest` parallelizes ingestion of JSON data from Oyez.org API to S3 using Python, logging 'junk' and other pipeline info to the bucket for audit.
- ECS EC2 task with GPU support for `transformers` (separate tasks available conditional on GPU availability) that also serializes and stores transcript data as XML files on S3.
- Shared infrastructure (e.g., EC2 instance, security groups) for GPU tasks is also conditionally deployed in the above stack.
- GitHub Actions CI/CD wrapping the logic and `cdk` steps for above - after a few prerequisites, outlined below.

Data Pipeline:
1. `ingest` collects and loads SCOTUS metadata and case text from Oyez.org API to S3.
2. Processed text from `ingest` on S3 is read by `transformers`, which uses the baai/bge-m3 model to generate embeddings. 
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

### 3. (Optional) Request GPU Instance Quota

If you want to use GPU acceleration for the transformer tasks, request a service quota increase:

1. Navigate to [AWS Service Quotas](https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas)
2. Search for **"Running On-Demand G and VT instances"**
3. Click on the quota and select **"Request quota increase"**
4. Request at least 1-2 instances (g4dn.xlarge uses 4 vCPUs)
5. Wait for approval (typically a few hours for small increases)

> **Note**: The pipeline will automatically fall back to CPU if GPU quota is not available. This step is only required if you want to enable GPU acceleration.

### 4. Set GitHub Repository Secrets

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

### b. Update `infrastructure/cdk.json`

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
| `ingest.sh` | Runs the data ingestion task to fetch SCOTUS oral arguments from Oyez.org API with incremental load support |
| `embeddings.sh` | Runs the embedding generation task using GPU (NVIDIA NV-Embed-v2) or CPU (MiniLM-L6-v2) models with incremental processing |
| `chunking.sql` | SQL queries for downstream processing of utterance embeddings with various chunking strategies |

### Running Data Ingestion

To ingest oral argument data from the Oyez.org API:

```bash
./scripts/ingest.sh
```

This script will:
- Dynamically retrieve the ECS cluster name and task definition from CloudFormation
- Launch a Fargate task with incremental loading (skips existing files)
- Store raw JSON files in S3 under `s3://scotustician/raw/oa/`
- Display configuration and progress information
- Print sample data for validation after completion

**Note**: The infrastructure stack also creates a scheduled ECS task that automatically runs the ingest process at 10 AM UTC on Mondays and Thursdays. This ensures regular data updates without manual intervention.

You can override environment variables:
```bash
START_TERM=2023 END_TERM=2024 DRY_RUN=true ./scripts/ingest.sh
```

Environment variables with defaults:
- `START_TERM`: 1980
- `END_TERM`: 2025
- `MAX_WORKERS`: 2
- `DRY_RUN`: false
- `S3_BUCKET`: scotustician
- `RAW_PREFIX`: raw/

### Running Embedding Generation

To generate embeddings from ingested data:

```bash
./scripts/embeddings.sh
```

This script will:
- Automatically detect GPU or CPU task definitions using Qwen3-Embedding-0.6B (1024-dim by default)
- Use appropriate security groups for RDS access in private subnets
- Read XML transcript data from S3 and generate both case-level and utterance-level embeddings
- Support incremental processing (skip existing embeddings by default)
- Store embeddings in PostgreSQL with pgvector extension
- Print detailed database validation summary after completion

You can override environment variables:
```bash
MODEL_NAME="all-MiniLM-L6-v2" BATCH_SIZE=16 INCREMENTAL=false ./scripts/embeddings.sh
```

Environment variables with defaults:
- `MODEL_NAME`: Qwen/Qwen3-Embedding-0.6B (supports both GPU and CPU)
- `MODEL_DIMENSION`: 1024 (configurable from 32 to 1024, max 2000 for pgvector compatibility)
- `BATCH_SIZE`: 4 (GPU) or 16 (CPU)
- `MAX_WORKERS`: 2 (GPU) or 4 (CPU)
- `INCREMENTAL`: true
- `S3_BUCKET`: scotustician
- `RAW_PREFIX`: raw/oa

**Database Credentials**: All PostgreSQL connection details (host, username, password, database name) are automatically retrieved from AWS Secrets Manager (`scotustician-db-credentials`) by the ECS task definition.

### SQL Utilities

The `chunking.sql` file provides example queries for downstream processing of utterance embeddings:

- **Fixed-size token windows**: Chunk transcripts into overlapping token windows (e.g., 512 tokens with 128 overlap)
- **Speaker-based chunking**: Group consecutive utterances by the same speaker
- **Time-based chunking**: Create temporal windows if timestamps are available
- **Custom chunking**: Extract embeddings with metadata for algorithmic processing

These queries are useful for building semantic search, clustering, and other downstream applications that require different granularities of text representation.

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

## Scheduled Tasks

The infrastructure automatically creates scheduled ECS tasks:

- **Ingest Task**: Runs at 10 AM UTC on Mondays and Thursdays to fetch new oral argument data from Oyez.org
  - Configured with EventBridge rule in the IngestStack
  - Uses the same task definition as manual runs
  - Environment variables: START_TERM=1980, END_TERM=current year

## To-Do

- Add Semantic Search API CDK stack
- Build and deploy UI (another CDK stack) with search and visualization


---
## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk`.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.