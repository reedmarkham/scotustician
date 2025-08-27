# Visualization Service

Interactive web application for exploring Supreme Court case clustering analysis results. This service consumes structured data produced by the clustering service and provides multiple visualization modes for understanding clustering patterns across different Supreme Court terms.

## Overview

This service provides a web-based interface for exploring clustering results through interactive visualizations and detailed case analysis. It operates independently from the clustering computation pipeline, reading pre-computed results from S3 storage to enable real-time exploration without requiring re-analysis.

## Features

- **Single Analysis View**: Explore individual clustering analyses with interactive scatter plots showing t-SNE coordinates and cluster assignments
- **Cluster Representatives**: View representative cases for each cluster along with their 5 most similar cases based on embedding similarity
- **Term-by-Term Comparison**: Compare clustering results across multiple Supreme Court terms with side-by-side visualizations
- **Temporal Trends**: Analyze how clustering patterns evolve over time with trend charts and summary statistics
- **Interactive Data Tables**: Detailed case information with sortable and filterable columns
- **S3 Integration**: Direct reading of clustering results from S3 without local storage requirements

## Architecture

- **Frontend**: Streamlit web application with Plotly visualizations
- **Deployment**: AWS Fargate with Application Load Balancer for cost-effective scaling
- **Data Source**: S3 bucket containing structured clustering results from the clustering service
- **Infrastructure**: Optimized for minimal cost using public subnets and single-instance deployment

## Configuration

The application is configured via environment variables:

- `AWS_DEFAULT_REGION`: AWS region (default: us-east-1)
- `S3_BUCKET`: S3 bucket containing clustering results (default: scotustician)
- `POSTGRES_HOST`: PostgreSQL host (optional for future features)
- `POSTGRES_DB`: PostgreSQL database name
- `POSTGRES_USER`: PostgreSQL username
- `POSTGRES_PASSWORD`: PostgreSQL password

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export S3_BUCKET=scotustician
export AWS_DEFAULT_REGION=us-east-1

# Run locally
streamlit run app.py
```

## Deployment

The visualization service is deployed using AWS CDK as part of the ScotusticianVisualizationStack:

```bash
cd infrastructure
npm run build
npx cdk deploy ScotusticianVisualizationStack
```

## Data Structure

The application expects clustering results in S3 with the following structure:

```
s3://bucket/analysis/case-clustering/
├── case_clustering_results_TIMESTAMP.csv
├── case_clustering_metadata_TIMESTAMP.json
└── visualizations/
    └── *.html

s3://bucket/analysis/case-clustering-by-term/
├── term-1980/
│   ├── case_clustering_results_TIMESTAMP.csv
│   └── case_clustering_metadata_TIMESTAMP.json
├── term-1981/
│   └── ...
```

## Cost Optimization

- Uses minimal Fargate resources (0.25 vCPU, 512 MB memory)
- Deployed in public subnets to avoid NAT gateway costs
- Single instance deployment for development/testing
- CloudWatch logs with 1-week retention

## Security

- Runs as non-root user in container
- IAM role with least-privilege S3 read-only access
- Security groups restrict access to necessary ports only
- Health checks ensure service availability