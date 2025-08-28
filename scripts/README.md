# Scripts

The `scripts/` directory provides tools for both automated pipeline execution and manual component control.

## Prerequisites

1. Ensure AWS CLI is configured with appropriate credentials
2. Verify that all CDK stacks have been successfully deployed
3. Make scripts executable: `chmod +x scripts/*.sh`

## Pipeline Execution Scripts

### Automated Pipeline Orchestration

| File | Usage | Description |
|------|-------|-------------|
| `run.sh` | Current year processing | Step Functions orchestration for current year SCOTUS data |
| `backfill.sh` | Historical data processing | Step Functions orchestration for 1980-2025 historical backfill |

### Individual Component Scripts

For granular control over individual pipeline components:

| File | Usage | Description |
|------|-------|-------------|
| `bootstrap.sh` | CDK environment setup | Configures CDK bootstrap with custom qualifier |
| `ingest.sh` | Manual data ingestion | Runs ECS Fargate tasks to fetch SCOTUS data from Oyez.org API |
| `embeddings.sh` | Manual embedding generation | Submits AWS Batch jobs for distributed embedding generation |


## Running Data Ingestion

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

## Pipeline Scheduling

**Automated Processing**: The system automatically processes current year data via Step Functions:
- **Schedule**: Twice weekly (Monday/Thursday 10 AM ET) during Supreme Court term (October-July)
- **Scope**: Current year data only
- **Trigger**: EventBridge rule in ScotusticianOrchestrationStack

**Manual Options**:
- **Current year**: `./run.sh` - processes current year only
- **Historical backfill**: `./backfill.sh` - processes all data from 1980-2025
- **Individual components**: Use scripts below for granular control

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

## Running Embedding Generation

To generate embeddings from ingested data using AWS Batch:

```bash
./scripts/embeddings.sh
```

This script will:
- Submit AWS Batch array jobs for distributed processing using [Ray Data](https://docs.ray.io/en/latest/data/data.html)
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
- `MAX_WORKERS`: 1 ([Ray](https://docs.ray.io/) workers per Batch job)
- `INCREMENTAL`: true
- `S3_BUCKET`: scotustician
- `RAW_PREFIX`: raw/oa

**Infrastructure**: The script uses AWS Batch with GPU spot instances and [Ray Data](https://docs.ray.io/en/latest/data/data.html) for distributed processing. All PostgreSQL connection details are automatically retrieved from AWS Secrets Manager (`scotustician-db-credentials`).

**Monitoring**: After submission, monitor with:
```bash
# View Batch job logs
aws logs tail /aws/batch/job --follow --region us-east-1

# Check SQS queue status
aws sqs get-queue-attributes --queue-url <PROCESSING_QUEUE_URL> --attribute-names All
```


## Monitoring Task Execution

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

## Notes

- The ingest task (ECS) requires public subnet access to reach the Oyez.org API
- The embedding generation uses AWS Batch with GPU spot instances for cost efficiency
- [Ray Data](https://docs.ray.io/en/latest/data/data.html) provides fault tolerance and distributed processing within each Batch job
- All scripts respect the `AWS_REGION` environment variable (defaults to `us-east-1`)
- SQS queues provide job tracking and checkpoint management for the embedding pipeline