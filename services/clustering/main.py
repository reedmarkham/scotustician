#!/usr/bin/env python3
"""
Cost-effective case-level embedding clustering using AWS Batch.
Computes weighted average embeddings per case, runs t-SNE and clustering,
and exports results to S3 for evaluation with labeled data.
"""
import os, logging
from typing import Dict, Any
from datetime import datetime

from helpers import (
    extract_case_embeddings,
    prepare_embeddings_matrix,
    compute_tsne,
    compute_clusters,
    create_visualizations,
    find_cluster_representatives,
    export_results
)

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class CaseClusteringAnalysis:
    def __init__(self):
        self.s3_client = boto3.client('s3')
        self.bucket = os.getenv("S3_BUCKET", "scotustician")
        self.output_prefix = os.getenv("OUTPUT_PREFIX", "analysis/case-clustering")
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Database connection
        self.db_config = {
            'host': os.getenv("POSTGRES_HOST", "localhost"),
            'user': os.getenv("POSTGRES_USER", "postgres"),
            'password': os.getenv("POSTGRES_PASS", ""),
            'database': os.getenv("POSTGRES_DB", "scotustician")
        }
        
        # Analysis parameters
        self.tsne_perplexity = int(os.getenv("TSNE_PERPLEXITY", "30"))
        self.min_cluster_size = int(os.getenv("MIN_CLUSTER_SIZE", "5"))
        self.random_state = int(os.getenv("RANDOM_STATE", "42"))


    def run_analysis(self) -> Dict[str, Any]:
        """Run complete case clustering analysis."""
        logger.info(f"Starting case clustering analysis - {self.timestamp}")
        
        try:
            # Extract case embeddings
            df = extract_case_embeddings(self.db_config)
            
            if len(df) == 0:
                raise ValueError("No case embeddings found in database")
            
            # Prepare embeddings matrix
            embeddings = prepare_embeddings_matrix(df)
            
            # Compute t-SNE
            tsne_coords = compute_tsne(embeddings, self.tsne_perplexity, self.random_state)
            df['tsne_x'] = tsne_coords[:, 0]
            df['tsne_y'] = tsne_coords[:, 1]
            
            # Compute clusters
            clusters = compute_clusters(embeddings, self.n_clusters, self.min_cluster_size, self.random_state)
            for method, labels in clusters.items():
                df[f'{method}_cluster'] = labels
            
            # Find cluster representatives
            representatives = find_cluster_representatives(df)
            
            # Create visualizations with representative highlighting
            viz_files = create_visualizations(df, self.timestamp, representatives)
            
            # Export results
            analysis_params = {
                'tsne_perplexity': self.tsne_perplexity,
                'n_clusters': self.n_clusters,
                'min_cluster_size': self.min_cluster_size,
                'random_state': self.random_state
            }
            s3_urls = export_results(df, viz_files, self.s3_client, self.bucket, 
                                   self.output_prefix, self.timestamp, analysis_params, representatives)
            
            logger.info("Analysis completed successfully!")
            logger.info("Results exported to S3:")
            for name, url in s3_urls.items():
                logger.info(f"  {name}: {url}")
            
            return {
                'status': 'success',
                'timestamp': self.timestamp,
                'cases_processed': len(df),
                's3_outputs': s3_urls,
                'summary': {
                    'total_cases': len(df),
                    'total_tokens': int(df['total_tokens'].sum()),
                    'avg_sections_per_case': float(df['section_count'].mean()),
                    'hdbscan_clusters': int(len(set(df['hdbscan_cluster'])) - (1 if -1 in df['hdbscan_cluster'].values else 0)) if 'hdbscan_cluster' in df.columns else 0
                }
            }
            
        except Exception as e:
            logger.error(f"Analysis failed: {str(e)}")
            return {
                'status': 'failed',
                'timestamp': self.timestamp,
                'error': str(e)
            }

if __name__ == "__main__":
    analyzer = CaseClusteringAnalysis()
    result = analyzer.run_analysis()
    
    if result['status'] == 'success':
        print(f"Analysis completed successfully!")
        print(f"Processed {result['cases_processed']} cases")
        print(f"Results available at: s3://{analyzer.bucket}/{analyzer.output_prefix}/")
        exit(0)
    else:
        print(f"Analysis failed: {result['error']}")
        exit(1)