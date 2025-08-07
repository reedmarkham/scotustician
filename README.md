# scotustician

**scotustician** is a data ingestion pipeline and embedding generation service for Supreme Court of the United States (SCOTUS) oral argument (OA) transcripts, deployed on AWS using Docker, CDK, and GitHub Actions. The goal with generating these embeddings is that we can then understand the Court in a more quantitative way.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. This project prioritizes building an end-to-end system to enable data-driven interaction with SCOTUS OA transcripts rather than more deeply optimizing some of its components, such as the data ingestor or the embedding service respectively.

The embeddings from this pipeline support downstream tasks such as semantic search, clustering, and interactive visualization. I have chosen to use the [baai/bge-m3](https://huggingface.co/BAAI/bge-m3) model, which generates 1024d text embeddings, due to its strong reputation for similar tasks such as semantic retrieval.

Data Pipeline:
1. `ingest` (ECS Fargate) uses DLT (data load tool) pipeline to collect SCOTUS metadata and case text from Oyez.org API:
   - Declarative, configuration-driven data extraction with incremental loading
   - Automatic rate limiting and error handling via DLT framework
   - Stores raw JSON files and metadata in S3 with built-in state management
2. `transformers` (AWS Batch + Ray Data) processes the ingested data using distributed GPU computing:
   - AWS Batch manages array jobs on spot GPU instances (g4dn.xlarge) for cost efficiency
   - Each job uses Ray Data for parallel file processing with automatic fault tolerance  
   - The `baai/bge-m3` model generates 1024-dimensional embeddings using section-based chunking
   - SQS queues track job progress and provide checkpoint management
3. Embeddings are stored in a [PostgreSQL database with pgvector extension](https://www.github.com/reedmarkham/scotustician-db), which has been deployed separately.

## Oral Argument Structure

Supreme Court oral arguments follow a structured format that the system preserves through section-based chunking. Using *Plyler v. Doe* (1981) as an example:

**Typical Structure (3 sections):**
- **Petitioner Arguments** (~20-30 min): Opening attorney presents their case
- **Respondent Arguments** (~20-30 min): Opposing attorney presents their case  
- **Petitioner Rebuttal** (~5-10 min): Brief closing response

**Complex Cases (4-5+ sections):**
Cases with multiple attorneys or amicus participants may have additional sections, such as:
- **Multiple Respondent Counsel**: Different attorneys representing various aspects of the case
- **Government Participation**: Solicitor General arguments as separate sections
- **Amicus Arguments**: Third-party advocates in cases of broad public interest

Each section represents a natural break when attorneys change at the podium, making section-based embedding generation ideal for preserving the logical flow of legal arguments. Sections typically range from 1,300-5,500 tokens, optimal for modern embedding models.

```
scotustician/
├── services/          	# Application services
│   ├── ingest/       	# Python code to ingest raw data from Oyez.org API to S3
│   └── transformers/ 	# Python code to generate and store text embeddings in PostgreSQL
├── infrastructure/     # AWS CDK code defining ECS services and other infrastructure for deployment using subdirectories above 
└── .github/workflows/ 	# CI/CD pipelines via GitHub Actions to handle AWS CDK workflow, reading in secrets from repository as needed
```

After tasks complete, the S3 bucket looks like:
```
scotustician/
├── raw/oa/      	  # Raw oral argument JSON files
├── xml/            # Serialized XML for the oral argument transcripts
├── junk/      		  # Raw oral argument JSON files *if* missing key data, malformed, etc.
├── logs/       	  # JSON representations of pipeline metrics, later to be queried in Athena, etc.
```
---
## Prerequisites

### 1. AWS IAM Credentials

You will need the ARN, access key, and secret access key for an existing AWS IAM user with permissions defined in [`iam-sample.json`](iam-sample.json). This user is used to authenticate CDK deployments via GitHub Actions.

> To-do: define and manage this IAM user in a separate CDK repository.

### 2. Deploy `scotustician-db`

Make sure [`scotustician-db`](https://github.com/reedmarkham/scotustician-db) is deployed first. This provides the S3 and PostgreSQL infrastructure for storage and indexing (via pgvector, up to 2000d vectors).

PostgreSQL credentials are managed through AWS Secrets Manager and deployed within the above repository's CDK stack. The database host and secret name are configured via CDK context parameters.

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

For reference, these code snippets in this repository reflect how the bootstrap qualifier is referenced.
### `infrastructure/cdk.json`

```json
{
  "app": "npx ts-node --prefer-ts-exts bin/scotustician.ts",
  "context": {
    "aws:cdk:bootstrap-qualifier": "sctstcn"
  }
}
```

### `infrastructure/lib/scotustician-%-stack.ts`

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

| File | Usage |
|--------|---------|
| `bootstrap.sh` | Gets account ID and region from AWS CLI to run the CDK bootstrap command with the custom qualifier for consistent deployments |
| `chunking.sql` | SQL queries for downstream processing of document chunk embeddings with various chunking strategies and semantic search examples |
| `embeddings.sh` | Submits AWS Batch array jobs for distributed embedding generation using Ray Data with GPU spot instances |
| `ingest.sh` | Runs ECS Fargate tasks to fetch SCOTUS oral arguments from Oyez.org API with incremental load support |


### Running Data Ingestion

To ingest oral argument data from the Oyez.org API to S3:

```bash
./scripts/ingest.sh
```

This script will:
- Dynamically retrieve ECS cluster, task definition, and network configuration from CloudFormation stacks
- Launch a Fargate task in public subnets with internet access to reach Oyez.org API  
- Use incremental loading to skip files that already exist in S3
- Store raw JSON files in S3 under `s3://scotustician/raw/oa/`
- Display real-time configuration and launch progress
- Automatically use default security groups for the VPC

**Note**: The infrastructure stack also creates a scheduled ECS task that automatically runs the ingest process at 10 AM UTC on Mondays and Thursdays. This ensures regular data updates without manual intervention.

You can override environment variables:
```bash
START_TERM=2023 END_TERM=2024 ./scripts/ingest.sh
```

Environment variables with defaults:
- `START_TERM`: 1980
- `END_TERM`: 2025
- `MAX_WORKERS`: 2
- `S3_BUCKET`: scotustician
- `RAW_PREFIX`: raw/

### Running Embedding Generation

To generate embeddings from ingested data using AWS Batch:

```bash
./scripts/embeddings.sh
```

This script will:
- Submit AWS Batch array jobs for distributed processing using Ray Data
- Automatically count files and determine the optimal job array size
- Use GPU spot instances (g4dn.xlarge) for cost-effective embedding generation
- Support incremental processing (skip existing embeddings by default)
- Process files in parallel batches with fault tolerance
- Store embeddings in PostgreSQL with pgvector extension
- Monitor job status and provide real-time progress updates
- Use SQS queues for job tracking and checkpoint management

You can override environment variables:
```bash
MODEL_NAME="all-MiniLM-L6-v2" FILES_PER_JOB=20 INCREMENTAL=false ./scripts/embeddings.sh
```

Environment variables with defaults:
- `STACK_NAME`: ScotusticianTransformersStack
- `FILES_PER_JOB`: 10 (files processed per Batch job)
- `MODEL_NAME`: baai/bge-m3 (Hugging Face org / model)
- `MODEL_DIMENSION`: 1024 (configurable from 32 to 1024, max 2000 for pgvector compatibility)
- `BATCH_SIZE`: 4 (GPU optimized batch size)
- `MAX_WORKERS`: 1 (Ray workers per Batch job)
- `INCREMENTAL`: true
- `S3_BUCKET`: scotustician
- `RAW_PREFIX`: raw/oa

**Infrastructure**: The script uses AWS Batch with GPU spot instances and Ray Data for distributed processing. All PostgreSQL connection details are automatically retrieved from AWS Secrets Manager (`scotustician-db-credentials`).

**Monitoring**: After submission, monitor with:
```bash
# View Batch job logs
aws logs tail /aws/batch/job --follow --region us-east-1

# Check SQS queue status
aws sqs get-queue-attributes --queue-url <PROCESSING_QUEUE_URL> --attribute-names All
```

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
# View real-time logs for ingest tasks (ECS)
aws logs tail /ecs/ingest --follow

# View real-time logs for embedding generation (AWS Batch)
aws logs tail /aws/batch/job --follow

# Check Batch job status
aws batch describe-jobs --jobs <job-id>

# Check ECS task status
aws ecs describe-tasks \
  --cluster <cluster-name> \
  --tasks <task-arn>

# Monitor SQS queues for embedding progress
aws sqs get-queue-attributes \
  --queue-url <queue-url> \
  --attribute-names All
```

### Notes

- The ingest task (ECS) requires public subnet access to reach the Oyez.org API
- The embedding generation uses AWS Batch with GPU spot instances for cost efficiency
- Ray Data provides fault tolerance and distributed processing within each Batch job
- All scripts respect the `AWS_REGION` environment variable (defaults to `us-east-1`)
- SQS queues provide job tracking and checkpoint management for the embedding pipeline

---

## Scheduled Tasks

The infrastructure automatically creates scheduled ECS tasks:

- **Ingest Task**: Runs at 10 AM UTC on Mondays and Thursdays to fetch new oral argument data from Oyez.org
  - Configured with EventBridge rule in the IngestStack
  - Uses the same task definition as manual runs
  - Environment variables: START_TERM=1980, END_TERM=current year

---
## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk`.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.