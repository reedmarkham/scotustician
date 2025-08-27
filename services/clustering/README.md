# Clustering Service

Case-level clustering analysis for Supreme Court oral argument embeddings using HDBSCAN and t-SNE dimensionality reduction.

## Overview

This service performs unsupervised clustering of SCOTUS cases based on weighted average embeddings of their oral argument transcripts. It computes t-SNE coordinates for visualization and applies multiple clustering algorithms including HDBSCAN and k-means.

## Features

- **Case-level aggregation**: Computes weighted average embeddings per case based on section token counts
- **Dimensionality reduction**: t-SNE for 2D visualization with configurable perplexity
- **Multiple clustering methods**: HDBSCAN (density-based)
- **Visualization export**: Interactive plots and scatter charts saved to S3
- **Representative selection**: Identifies prototypical cases for each cluster
- **Comprehensive results**: CSV exports with embeddings, coordinates, and cluster assignments

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

## Output Files

Results are exported to S3 with timestamp:

- `case_embeddings_analysis_{timestamp}.csv`: Complete analysis results
- `tsne_visualization_{timestamp}.html`: Interactive t-SNE plot
- `cluster_comparison_{timestamp}.html`: Method comparison charts
- `analysis_metadata_{timestamp}.json`: Configuration and summary statistics

## Dependencies

- **hdbscan**: Density-based clustering (version 0.8.40 for GCC compatibility)
- **scikit-learn**: t-SNE
- **plotly**: Interactive visualizations
- **pandas/numpy**: Data manipulation
- **psycopg2**: PostgreSQL connection

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

The service runs a complete analysis pipeline and exports all results to S3 for downstream evaluation.

## Future Work

- **Cluster evaluation metrics**: Implement silhouette analysis and other clustering quality measures
- **Academic validation**: Evaluate clusters against labeled SCOTUS data from academic research to assess legal domain relevance