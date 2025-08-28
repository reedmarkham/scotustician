# scotustician

[![CI/CD](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml/badge.svg)](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml)

**scotustician** is a collection of services used to apply data science - particularly visualizing the results of unsupervised clustering over large text embeddings - to Supreme Court of the United States oral argument (OA) transcripts using AWS infrastructure and GitHub Actions to handle CI/CD across the various services: data ingestion, embedding computation, clustering processing, and visualization UI. The motivation for this approach is to better understand the Court by measuring and showing the semantic distance among all available cases' respective oral argument sessions. This repository also includes AWS CDK stacks to provision the underlying infrastructure for all services involved. To start generating embeddings I have chosen without much (any) evaluation to use the [baai/bge-m3](https://huggingface.co/BAAI/bge-m3) model, which generates 1024d embeddings and is well-regarded on Hugging Face for tasks such as information retrieval. Future research can implement and evaluate multiple models for the clustering task, as well as regressions for justice votes and other applications in the realm of legal studies.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. This project prioritizes building an end-to-end system to enable data-driven interaction with SCOTUS OA transcripts rather than more deeply optimizing some of its components, such as the data ingestor or the embedding service respectively.


## Pipeline Orchestration

The scotustician pipeline supports both historical data processing and ongoing current-year updates:

### Current Year Processing (Automated)

**Scheduled Execution**: Step Functions automatically runs twice weekly (Monday/Thursday 10 AM ET) during the Supreme Court's active term (October through July) to process current year SCOTUS data.

**Manual Current Year**: For immediate current year processing:

```bash
./scripts/run.sh
```

### Historical Data Backfill (One-time)

For processing all historical SCOTUS data from 1980-2025:

```bash
./scripts/backfill.sh
```

### Pipeline Features

Both execution modes provide:
- **Serverless**: No laptop required - close your computer and let AWS handle everything  
- **Parallel Processing**: Basic and term-by-term clustering run simultaneously
- **Cost Tracking**: Automated cost reports at pipeline start and completion
- **Error Recovery**: Automatic retries and SNS notifications for failures
- **Visual Monitoring**: Real-time progress in AWS Console

### Step Functions Workflow

All executions follow the same orchestrated workflow:
1. **Parameter extraction** - Parse input terms and execution mode
2. **Cost baseline** - Measure AWS costs before processing
3. **Data ingestion** - Collect SCOTUS data via ECS Fargate
4. **Data verification** - Validate S3 storage
5. **Embedding generation** - Create text embeddings via AWS Batch
6. **Embedding verification** - Validate PostgreSQL storage
7. **Parallel clustering** - Run analysis via AWS Batch
   - Basic case clustering
   - Term-by-term clustering  
8. **Final cost report** - Calculate total processing costs

### Manual Component Execution

For granular control, run individual pipeline components using the scripts in [`scripts/README.md`](scripts/README.md).

## Data Pipeline Components

1. **`ingest`** - Collect SCOTUS data from Oyez.org API:
   - [DLT (data load tool)](https://dlthub.com/) for declarative data extraction
   - Incremental loading with automatic rate limiting
   - Stores raw JSON files in S3 with built-in state management

2. **`transformers`** - Generate embeddings using distributed computing:
   - AWS Batch with spot GPU instances (g4dn.xlarge) for cost efficiency
   - [Ray Data](https://docs.ray.io/en/latest/data/data.html) for parallel processing with fault tolerance  
   - `baai/bge-m3` model generates 1024-dimensional embeddings
   - Section-based chunking preserves oral argument structure

3. **`clustering`** - Analyze embeddings for case similarities:
   - Weighted average embeddings per case based on section token counts
   - t-SNE dimensionality reduction and HDBSCAN clustering
   - Both basic clustering and term-by-term analysis
   - Interactive visualizations exported to S3

4. **`visualization`** - Streamlit web app for exploring results:
   - Interactive plots and case analysis
   - Deployed automatically via GitHub Actions to AWS ECS
   - Access via URL in [deployment summary](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml)

5. **Database** - PostgreSQL with pgvector extension for embeddings and dbt for analytics (integrated in shared stack)

```
scotustician/
├── services/          	# Application services
│   ├── ingest/       	# Python code to ingest raw data from Oyez.org API to S3
│   ├── transformers/ 	# Python code to generate and store text embeddings in PostgreSQL
│   ├── clustering/    	# Python code to perform case-level clustering analysis on embeddings
│   └── visualization/  # Streamlit web app for exploring clustering results
├── database/          	# Database infrastructure and analytics
│   ├── lambda/        	# Database initialization functions
│   └── dbt/           	# Data transformation models (bronze/silver/gold)
├── infrastructure/     # AWS CDK code defining all infrastructure components
└── .github/workflows/ 	# CI/CD pipelines via GitHub Actions
```

After tasks complete, the S3 bucket looks like:
```
scotustician/
├── raw/oa/      	  # Raw oral argument JSON files
├── xml/            # Serialized XML for the oral argument transcripts
├── junk/      		  # Raw oral argument JSON files *if* missing key data, malformed, etc.
├── logs/       	  # JSON representations of pipeline metrics, later to be queried in Athena, etc.
```

## Prerequisites

### 1. AWS IAM Credentials

You will need the ARN, access key, and secret access key for an existing AWS IAM user with permissions defined in [`iam-sample.json`](iam-sample.json). This user is used to authenticate CDK deployments via GitHub Actions.

> To-do: define and manage this IAM user in a separate CDK repository.

### 2. Database Infrastructure

The PostgreSQL database with pgvector extension is automatically deployed as part of the shared stack. Database schema initialization and dbt analytics models are included. PostgreSQL credentials are managed through AWS Secrets Manager.

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

Each section represents a natural break when attorneys change at the podium, making section-based embedding generation an intuitive choice for preserving the logical flow of legal arguments. Sections typically range from 1,300-5,500 tokens, optimal for modern embedding models.

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

## Scripts

For detailed instructions on running data ingestion and transformation tasks, see [scripts/README.md](scripts/README.md).



---
## Infrastructure

The project deploys six AWS CDK stacks via GitHub Actions:

1. **ScotusticianSharedStack** - VPC, ECS clusters, PostgreSQL database, and dbt infrastructure
2. **ScotusticianIngestStack** - ECS task definition for data ingestion
3. **ScotusticianTransformersStack** - AWS Batch for embedding generation
4. **ScotusticianClusteringStack** - AWS Batch for clustering analysis
5. **ScotusticianVisualizationStack** - ECS service for Streamlit web app
6. **ScotusticianOrchestrationStack** - Step Functions workflow with Lambda functions for cost tracking and data verification

**Database Components (in shared stack):**
- PostgreSQL 16.4 with pgvector extension for embeddings storage
- Automated schema initialization via Lambda
- dbt on ECS Fargate for weekly analytics transformations
- Bronze/Silver/Gold medallion architecture for data analytics

## CI/CD

On commits to `main`, GitHub Actions (`.github/workflows/deploy.yml`) detects changes and deploys the affected stacks automatically.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.