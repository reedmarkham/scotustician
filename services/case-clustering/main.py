#!/usr/bin/env python3
"""
Cost-effective case-level embedding clustering using AWS Batch.
Computes weighted average embeddings per case, runs t-SNE and clustering,
and exports results to S3 for evaluation with labeled data.
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import psycopg2
import pandas as pd
import numpy as np
import boto3
from sklearn.manifold import TSNE
from sklearn.cluster import KMeans, HDBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import plot

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
        self.n_clusters = int(os.getenv("N_CLUSTERS", "8"))
        self.min_cluster_size = int(os.getenv("MIN_CLUSTER_SIZE", "5"))
        self.random_state = int(os.getenv("RANDOM_STATE", "42"))

    def extract_case_embeddings(self) -> pd.DataFrame:
        """Extract weighted average embeddings per case from document chunks."""
        query = """
        WITH case_embeddings AS (
            SELECT 
                case_id,
                -- Extract docket info from case_id
                SPLIT_PART(case_id, '_', 1) as term_year,
                REPLACE(
                    SUBSTRING(case_id FROM POSITION('_' IN case_id) + 1), 
                    '-', '_'
                ) as docket_name,
                
                -- Compute length-weighted average embedding
                SUM(vector * token_count::float) / SUM(token_count::float) as case_embedding,
                SUM(token_count) as total_tokens,
                COUNT(*) as section_count,
                AVG(token_count) as avg_tokens_per_section,
                MIN(created_at) as first_processed,
                MAX(created_at) as last_processed
                
            FROM scotustician.document_chunk_embeddings 
            WHERE vector IS NOT NULL 
              AND token_count > 0
            GROUP BY case_id
            HAVING COUNT(*) >= 2  -- Only cases with multiple sections
        )
        SELECT 
            case_id,
            term_year || '_' || docket_name as docket_number,
            case_embedding,
            total_tokens,
            section_count,
            avg_tokens_per_section,
            first_processed,
            last_processed
        FROM case_embeddings
        ORDER BY case_id;
        """
        
        logger.info("Extracting case-level embeddings from database...")
        with psycopg2.connect(**self.db_config) as conn:
            df = pd.read_sql(query, conn)
        
        logger.info(f"Extracted {len(df)} cases with embeddings")
        logger.info(f"Total tokens across all cases: {df['total_tokens'].sum():,}")
        logger.info(f"Average sections per case: {df['section_count'].mean():.1f}")
        
        return df

    def prepare_embeddings_matrix(self, df: pd.DataFrame) -> np.ndarray:
        """Convert embedding vectors to numpy matrix."""
        logger.info("Converting embeddings to matrix format...")
        
        # Extract embeddings from the vector column (assuming it's a list/array)
        embeddings = []
        for idx, row in df.iterrows():
            embedding = row['case_embedding']
            if isinstance(embedding, str):
                # Handle string representation of array
                embedding = json.loads(embedding)
            embeddings.append(np.array(embedding))
        
        embeddings_matrix = np.vstack(embeddings)
        logger.info(f"Created embeddings matrix: {embeddings_matrix.shape}")
        
        return embeddings_matrix

    def compute_tsne(self, embeddings: np.ndarray) -> np.ndarray:
        """Compute t-SNE coordinates."""
        logger.info(f"Computing t-SNE with perplexity={self.tsne_perplexity}...")
        
        # Standardize embeddings first
        scaler = StandardScaler()
        embeddings_scaled = scaler.fit_transform(embeddings)
        
        # Adjust perplexity if we have too few samples
        n_samples = embeddings.shape[0]
        perplexity = min(self.tsne_perplexity, max(5, n_samples // 4))
        
        if perplexity != self.tsne_perplexity:
            logger.warning(f"Adjusted perplexity to {perplexity} due to sample size ({n_samples})")
        
        tsne = TSNE(
            n_components=2, 
            perplexity=perplexity,
            random_state=self.random_state,
            n_jobs=1  # Single-threaded for reproducibility
        )
        
        coords = tsne.fit_transform(embeddings_scaled)
        logger.info("t-SNE computation completed")
        
        return coords

    def compute_clusters(self, embeddings: np.ndarray) -> Dict[str, np.ndarray]:
        """Compute different clustering algorithms."""
        logger.info("Computing clusters...")
        
        # Standardize for clustering
        scaler = StandardScaler()
        embeddings_scaled = scaler.fit_transform(embeddings)
        
        results = {}
        
        # K-means clustering
        n_clusters = min(self.n_clusters, embeddings.shape[0] // 2)
        if n_clusters >= 2:
            kmeans = KMeans(n_clusters=n_clusters, random_state=self.random_state)
            kmeans_labels = kmeans.fit_predict(embeddings_scaled)
            results['kmeans'] = kmeans_labels
            
            # Compute silhouette score
            if len(np.unique(kmeans_labels)) > 1:
                silhouette = silhouette_score(embeddings_scaled, kmeans_labels)
                logger.info(f"K-means silhouette score: {silhouette:.3f}")
        
        # HDBSCAN clustering
        min_cluster_size = min(self.min_cluster_size, max(2, embeddings.shape[0] // 10))
        hdbscan = HDBSCAN(min_cluster_size=min_cluster_size)
        hdbscan_labels = hdbscan.fit_predict(embeddings_scaled)
        results['hdbscan'] = hdbscan_labels
        
        n_clusters_hdbscan = len(set(hdbscan_labels)) - (1 if -1 in hdbscan_labels else 0)
        logger.info(f"HDBSCAN found {n_clusters_hdbscan} clusters")
        
        return results

    def create_visualizations(self, df: pd.DataFrame) -> List[str]:
        """Create interactive visualizations."""
        logger.info("Creating visualizations...")
        
        viz_files = []
        
        # t-SNE scatter plot colored by clusters
        for cluster_method in ['kmeans_cluster', 'hdbscan_cluster']:
            if cluster_method in df.columns:
                fig = px.scatter(
                    df,
                    x='tsne_x',
                    y='tsne_y',
                    color=cluster_method,
                    hover_data=['case_id', 'docket_number', 'total_tokens', 'section_count'],
                    title=f"Case Clustering: {cluster_method.replace('_', ' ').title()}",
                    labels={'tsne_x': 't-SNE Dimension 1', 'tsne_y': 't-SNE Dimension 2'}
                )
                
                fig.update_traces(marker=dict(size=8, opacity=0.7))
                fig.update_layout(height=600, width=800)
                
                viz_file = f"case_clustering_{cluster_method}_{self.timestamp}.html"
                plot(fig, filename=viz_file, auto_open=False)
                viz_files.append(viz_file)
        
        # Token distribution by cluster
        if 'kmeans_cluster' in df.columns:
            fig = px.box(
                df,
                x='kmeans_cluster',
                y='total_tokens',
                title="Token Distribution by K-means Cluster",
                labels={'kmeans_cluster': 'Cluster', 'total_tokens': 'Total Tokens'}
            )
            fig.update_layout(height=400, width=800)
            
            viz_file = f"token_distribution_{self.timestamp}.html"
            plot(fig, filename=viz_file, auto_open=False)
            viz_files.append(viz_file)
        
        logger.info(f"Created {len(viz_files)} visualization files")
        return viz_files

    def export_results(self, df: pd.DataFrame, viz_files: List[str]) -> Dict[str, str]:
        """Export results to S3."""
        logger.info("Exporting results to S3...")
        
        s3_urls = {}
        
        # Export main results CSV
        csv_file = f"case_clustering_results_{self.timestamp}.csv"
        df.to_csv(csv_file, index=False)
        
        csv_key = f"{self.output_prefix}/{csv_file}"
        self.s3_client.upload_file(csv_file, self.bucket, csv_key)
        s3_urls['results_csv'] = f"s3://{self.bucket}/{csv_key}"
        
        # Export metadata
        metadata = {
            'timestamp': self.timestamp,
            'total_cases': len(df),
            'parameters': {
                'tsne_perplexity': self.tsne_perplexity,
                'n_clusters': self.n_clusters,
                'min_cluster_size': self.min_cluster_size,
                'random_state': self.random_state
            },
            'cluster_summary': {
                'kmeans_clusters': int(df['kmeans_cluster'].nunique()) if 'kmeans_cluster' in df.columns else 0,
                'hdbscan_clusters': int(len(set(df['hdbscan_cluster'])) - (1 if -1 in df['hdbscan_cluster'].values else 0)) if 'hdbscan_cluster' in df.columns else 0
            },
            'token_stats': {
                'total_tokens': int(df['total_tokens'].sum()),
                'avg_tokens_per_case': float(df['total_tokens'].mean()),
                'avg_sections_per_case': float(df['section_count'].mean())
            }
        }
        
        metadata_file = f"case_clustering_metadata_{self.timestamp}.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        metadata_key = f"{self.output_prefix}/{metadata_file}"
        self.s3_client.upload_file(metadata_file, self.bucket, metadata_key)
        s3_urls['metadata'] = f"s3://{self.bucket}/{metadata_key}"
        
        # Export visualizations
        for viz_file in viz_files:
            viz_key = f"{self.output_prefix}/visualizations/{viz_file}"
            self.s3_client.upload_file(viz_file, self.bucket, viz_key)
            s3_urls[f'viz_{viz_file}'] = f"s3://{self.bucket}/{viz_key}"
        
        # Create SQL query for joining with labels
        sql_template = f"""
        -- Query to join case clustering results with your labeled data
        -- Replace 'your_labels_table' with your actual labels table name
        
        WITH clustering_results AS (
            SELECT 
                case_id,
                '{self.timestamp}' as analysis_timestamp,
                tsne_x,
                tsne_y,
                kmeans_cluster,
                hdbscan_cluster
            FROM (VALUES
                {','.join([f"('{row['case_id']}', {row['tsne_x']:.6f}, {row['tsne_y']:.6f}, {row.get('kmeans_cluster', 'NULL')}, {row.get('hdbscan_cluster', 'NULL')})" for _, row in df.iterrows()])}
            ) AS t(case_id, tsne_x, tsne_y, kmeans_cluster, hdbscan_cluster)
        )
        SELECT 
            cr.*,
            labels.outcome,
            labels.issue_area,
            labels.decision_direction,
            labels.vote_majority,
            labels.vote_minority
        FROM clustering_results cr
        LEFT JOIN your_labels_table labels 
            ON SPLIT_PART(cr.case_id, '_', 1) || '_' || 
               REPLACE(SUBSTRING(cr.case_id FROM POSITION('_' IN cr.case_id) + 1), '-', '_') 
               = labels.docket_number
        ORDER BY cr.case_id;
        """
        
        sql_file = f"join_with_labels_{self.timestamp}.sql"
        with open(sql_file, 'w') as f:
            f.write(sql_template)
        
        sql_key = f"{self.output_prefix}/{sql_file}"
        self.s3_client.upload_file(sql_file, self.bucket, sql_key)
        s3_urls['join_sql'] = f"s3://{self.bucket}/{sql_key}"
        
        # Cleanup local files
        for f in [csv_file, metadata_file, sql_file] + viz_files:
            if os.path.exists(f):
                os.remove(f)
        
        return s3_urls

    def run_analysis(self) -> Dict[str, Any]:
        """Run complete case clustering analysis."""
        logger.info(f"Starting case clustering analysis - {self.timestamp}")
        
        try:
            # Extract case embeddings
            df = self.extract_case_embeddings()
            
            if len(df) == 0:
                raise ValueError("No case embeddings found in database")
            
            # Prepare embeddings matrix
            embeddings = self.prepare_embeddings_matrix(df)
            
            # Compute t-SNE
            tsne_coords = self.compute_tsne(embeddings)
            df['tsne_x'] = tsne_coords[:, 0]
            df['tsne_y'] = tsne_coords[:, 1]
            
            # Compute clusters
            clusters = self.compute_clusters(embeddings)
            for method, labels in clusters.items():
                df[f'{method}_cluster'] = labels
            
            # Create visualizations
            viz_files = self.create_visualizations(df)
            
            # Export results
            s3_urls = self.export_results(df, viz_files)
            
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
                    'kmeans_clusters': int(df['kmeans_cluster'].nunique()) if 'kmeans_cluster' in df.columns else 0,
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
        print(f"✅ Analysis completed successfully!")
        print(f"📊 Processed {result['cases_processed']} cases")
        print(f"📁 Results available at: s3://{analyzer.bucket}/{analyzer.output_prefix}/")
        exit(0)
    else:
        print(f"❌ Analysis failed: {result['error']}")
        exit(1)