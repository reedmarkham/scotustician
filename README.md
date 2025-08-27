# scotustician

[![Deploy scotustician infrastructure and services)](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml/badge.svg)](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml)

**scotustician** is a collection of services used to apply data science - particularly visualizing the results of unsupervised clustering over large text embeddings - to Supreme Court of the United States oral argument (OA) transcripts using AWS infrastructure and GitHub Actions to handle CI/CD across the various services: data ingestion, embedding computation, clustering processing, and visualization UI. The motivation for this approach is to better understand the Court by measuring and showing the semantic distance among all available cases' respective oral argument sessions. This repository also includes AWS CDK stacks to provision the underlying infrastructure for all services involved.

[Oyez.org](https://oyez.org) provides an [undocumented but widely used API](https://github.com/walkerdb/supreme_court_transcripts) for accessing these transcripts as raw text. This project prioritizes building an end-to-end system to enable data-driven interaction with SCOTUS OA transcripts rather than more deeply optimizing some of its components, such as the data ingestor or the embedding service respectively.

The embeddings from this pipeline support downstream tasks such as semantic search, clustering, and interactive visualization. I have chosen to use the [baai/bge-m3](https://huggingface.co/BAAI/bge-m3) model, which generates 1024d text embeddings, due to its strong reputation for similar tasks such as semantic retrieval.

Data Pipeline:
1. `ingest` uses [DLT (data load tool)](https://dlthub.com/) pipeline to collect SCOTUS metadata and case text from Oyez.org API:
   - Declarative, configuration-driven data extraction with incremental loading
   - Automatic rate limiting and error handling via DLT framework
   - Stores raw JSON files and metadata in S3 with built-in state management
2. `transformers` processes the ingested data using distributed GPU computing:
   - AWS Batch manages array jobs on spot GPU instances (g4dn.xlarge) for cost efficiency
   - Each job uses [Ray Data](https://docs.ray.io/en/latest/data/data.html) for parallel file processing with automatic fault tolerance  
   - The `baai/bge-m3` model generates 1024-dimensional embeddings using section-based chunking
   - SQS queues track job progress and provide checkpoint management
   - Built-in idempotency ensures safe re-runs with automatic duplicate detection
   - Assumes database schema is already configured (deployed via scotustician-db repository)
3. `clustering` performs case-level clustering analysis on stored embeddings:
   - Computes weighted average embeddings per case based on section token counts
   - Applies t-SNE dimensionality reduction and HDBSCAN clustering for pattern discovery
   - Exports interactive visualizations and analysis results to S3 for evaluation
4. `visualization` provides an interactive Streamlit web application for exploring clustering results:
   - Deployed automatically via GitHub Actions to AWS ECS on spot instances
   - Reads clustering results from S3 and displays interactive plots and case analysis
   - Access the visualization UI via the URL shown in the latest [deployment summary](https://github.com/reedmarkham/scotustician/actions/workflows/deploy.yml)
5. Embeddings are stored in a [PostgreSQL database with pgvector extension](https://www.github.com/reedmarkham/scotustician-db), which must be deployed separately before running transformers.

```
scotustician/
├── services/          	# Application services
│   ├── ingest/       	# Python code to ingest raw data from Oyez.org API to S3
│   ├── transformers/ 	# Python code to generate and store text embeddings in PostgreSQL
│   └── clustering/    	# Python code to perform case-level clustering analysis on embeddings
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

## Prerequisites

### 1. AWS IAM Credentials

You will need the ARN, access key, and secret access key for an existing AWS IAM user with permissions defined in [`iam-sample.json`](iam-sample.json). This user is used to authenticate CDK deployments via GitHub Actions.

> To-do: define and manage this IAM user in a separate CDK repository.

### 2. Deploy `scotustician-db`

Make sure [`scotustician-db`](https://github.com/reedmarkham/scotustician-db) is deployed first. This provides the S3 and PostgreSQL infrastructure for storage and indexing (via pgvector, up to 2000d vectors). The database schema required by the transformers service is created during the scotustician-db deployment.

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

```
scotustician/
├── services/          	# Application services
│   ├── ingest/       	# Python code to ingest raw data from Oyez.org API to S3
│   ├── transformers/ 	# Python code to generate and store text embeddings in PostgreSQL
│   ├── clustering/    	# Python code to perform case-level clustering analysis on embeddings
│   └── visualization/ 	# Streamlit web app for interactive exploration of clustering results
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

Make sure [`scotustician-db`](https://github.com/reedmarkham/scotustician-db) is deployed first. This provides the S3 and PostgreSQL infrastructure for storage and indexing (via pgvector, up to 2000d vectors). The database schema required by the transformers service is created during the scotustician-db deployment.

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

## Scripts

For detailed instructions on running data ingestion and transformation tasks, see [scripts/README.md](scripts/README.md).



---
## CI/CD

On commits or pull requests to `main` the GitHub Actions workflow (`.github/workflows/deploy.yml`) detects pertinent diffs, builds respective Docker images, and deploys via `cdk`.

---
## Appendix

This project owes many thanks to [@walkerdb](https://github.com/walkerdb/supreme_court_transcripts) for their original repository as well as [Oyez.org](https://oyez.org) for their API and data curation.