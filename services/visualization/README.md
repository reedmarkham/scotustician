# Visualization Service

Interactive web application for exploring Supreme Court case clustering analysis results. This service consumes structured data produced by the clustering service and provides multiple visualization modes for understanding clustering patterns across different Supreme Court terms.

## Overview

This service provides a web-based interface for exploring clustering results through interactive visualizations and detailed case analysis. It operates independently from the clustering computation pipeline, reading pre-computed results from S3 storage to enable real-time exploration without requiring re-analysis.

## Features

- **Single Analysis View**: Explore individual clustering analyses with interactive scatter plots showing t-SNE coordinates and cluster assignments
- **Cluster Representatives**: View representative cases for each cluster along with their 5 most similar cases based on embedding similarity
- **Enhanced Text Overlays**: Representative case names appear in bold text on scatter plots, with fainter text for nearest neighbors that become bold on hover
- **Term-by-Term Comparison**: Compare clustering results across multiple Supreme Court terms with side-by-side visualizations
- **Temporal Trends**: Analyze how clustering patterns evolve over time with trend charts and summary statistics
- **Interactive Data Tables**: Detailed case information with sortable and filterable columns
- **S3 Integration**: Direct reading of clustering results from S3 without local storage requirements
- **Modular Components**: Clean separation of UI components for maintainability

## Architecture

- **Frontend**: Streamlit web application with Plotly visualizations and modular component structure
- **Code Organization**: Separate modules for data loading (`helpers.py`), UI components (`components.py`), and main application (`app.py`)
- **Deployment**: AWS ECS Fargate with Application Load Balancer for reliability and automatic scaling
- **Auto-scaling**: Scales from 0-3 tasks based on traffic, automatically scales down to zero after 1 hour of inactivity
- **Data Source**: S3 bucket containing structured clustering results from the clustering service
- **Infrastructure**: Cost-optimized with Fargate on-demand instances and intelligent scaling

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

### Deployment Features
- **Fast Deployment**: Fargate eliminates EC2 instance provisioning time
- **Reliability**: No spot instance interruptions
- **Automatic Recovery**: ECS automatically replaces failed tasks
- **Zero Downtime**: Rolling updates with health checks

### Monitoring Deployment
After deployment, monitor the service using:
- **CloudWatch Logs**: `/ecs/scotustician-visualization` for application logs
- **ECS Console**: View service status, task health, and scaling activity  
- **ALB Health Checks**: Ensure targets are healthy
- **Custom Metrics**: `Scotustician/Visualization` namespace in CloudWatch

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

## Cost Optimization & Auto-scaling

### Resource Configuration
- **Fargate Resources**: 0.25 vCPU, 512 MB memory (equivalent to t3.micro)
- **Cost**: ~$0.01/hour when running, $0 when scaled to zero
- **Network**: Public subnets for cost optimization (saves ~$45-90/month vs NAT gateway)
- **Storage**: No persistent storage required - reads directly from S3

### Auto-scaling Behavior
- **Scale Up**: Automatically starts new tasks when traffic arrives (3-minute cooldown)
- **Scale Down**: Scales to zero after 1 hour of no requests (cost savings)
- **Capacity**: 0-3 tasks based on demand (10 requests/minute per task target)
- **Cold Start**: ~30-60 seconds for first request after scale-down

### Monitoring & Logging
- **Enhanced Logging**: Separate log groups for application and ECS events
- **Retention**: 2-week log retention for troubleshooting
- **Metrics**: Custom CloudWatch metrics for errors and task startups
- **Alerts**: SNS notifications for high error rates and service outages
- **Health Checks**: Streamlit health endpoint monitoring

## Security

- Runs as non-root user in container
- IAM role with least-privilege S3 read-only access
- Security groups restrict access to necessary ports only
- Health checks ensure service availability