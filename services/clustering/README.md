# Clustering Service

Case-level clustering analysis for Supreme Court oral argument embeddings using HDBSCAN and t-SNE dimensionality reduction. This service prepares structured clustering data that is consumed downstream by the visualization service for interactive exploration.

## Overview

This service performs unsupervised clustering of SCOTUS cases based on weighted average embeddings of their oral argument transcripts. It computes t-SNE coordinates and applies HDBSCAN clustering, then exports structured results for downstream visualization and analysis.

## Features

- **Case-level aggregation**: Computes weighted average embeddings per case based on section token counts
- **Term filtering**: Supports filtering by Supreme Court term range (e.g., 1980-2025) or individual terms
- **Dimensionality reduction**: t-SNE for 2D visualization with configurable perplexity
- **HDBSCAN clustering**: Density-based clustering with automatic outlier detection
- **Representative selection**: Identifies prototypical cases for each cluster with 5 nearest neighbors based on embedding similarity
- **Structured export**: CSV and JSON results optimized for downstream visualization service consumption

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | localhost | Database host |
| `POSTGRES_USER` | postgres | Database user |
| `POSTGRES_PASS` | | Database password |
| `POSTGRES_DB` | scotustician | Database name |
| `S3_BUCKET` | scotustician | Output S3 bucket |
| `OUTPUT_PREFIX` | analysis/case-clustering | S3 prefix for results |
| `TSNE_PERPLEXITY` | 30 | t-SNE perplexity parameter |
| `MIN_CLUSTER_SIZE` | 5 | HDBSCAN minimum cluster size |
| `RANDOM_STATE` | 42 | Random seed for reproducibility |
| `START_TERM` | 1980 | Starting Supreme Court term for filtering |
| `END_TERM` | 2025 | Ending Supreme Court term for filtering |

## Output Files

Results are exported to S3 with timestamp for consumption by visualization service:

- `case_clustering_results_{timestamp}.csv`: Complete clustering results with t-SNE coordinates and cluster assignments
- `case_clustering_metadata_{timestamp}.json`: Analysis metadata including cluster representatives, nearest neighbors, and summary statistics

## Dependencies

- **hdbscan**: Density-based clustering (version 0.8.40 for GCC compatibility)
- **scikit-learn**: t-SNE and similarity calculations
- **pandas/numpy**: Data manipulation
- **psycopg2**: PostgreSQL connection
- **boto3**: S3 export

## Database Schema

Expects embeddings table with:
- `case_id`: Unique case identifier
- `section_tokens`: Token count per section
- `embedding`: 1024-dimensional vector (pgvector)

## Usage

```bash
docker build -t clustering .
docker run -e POSTGRES_HOST=host -e POSTGRES_PASS=pass clustering
```

The service runs a complete analysis pipeline and exports structured results to S3 for consumption by the visualization service.

## Data Flow

1. **Input**: Reads case embeddings from PostgreSQL database
2. **Processing**: Filters by term, computes t-SNE, performs clustering, identifies representatives
3. **Output**: Exports CSV and JSON to S3 in structured format
4. **Downstream**: Data consumed by visualization service for interactive exploration

## Deployment Scripts

- `scripts/run-case-clustering.sh`: Run clustering for a term range using AWS Batch
- `scripts/run-term-by-term-clustering.sh`: Run clustering for individual terms in parallel

## Future Work

- **Cluster evaluation metrics**: Implement silhouette analysis and other clustering quality measures
- **Academic validation**: Evaluate clusters against labeled SCOTUS data from academic research to assess legal domain relevance