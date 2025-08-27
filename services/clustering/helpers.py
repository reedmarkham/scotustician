#!/usr/bin/env python3
"""
Helper functions for case clustering analysis.
Contains database operations, data processing, visualization, and export utilities.
"""
import os, json, logging
from typing import List, Dict, Any

import psycopg2, pandas as pd, numpy as np, plotly.express as px, plotly.graph_objects as go
from plotly.offline import plot
from sklearn.manifold import TSNE
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)

def extract_case_embeddings(db_config: Dict[str, str]) -> pd.DataFrame:
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
    with psycopg2.connect(**db_config) as conn:
        df = pd.read_sql(query, conn)
    
    logger.info(f"Extracted {len(df)} cases with embeddings")
    logger.info(f"Total tokens across all cases: {df['total_tokens'].sum():,}")
    logger.info(f"Average sections per case: {df['section_count'].mean():.1f}")
    
    return df

def prepare_embeddings_matrix(df: pd.DataFrame) -> np.ndarray:
    """Convert embedding vectors to numpy matrix."""
    logger.info("Converting embeddings to matrix format...")
    
    embeddings = []
    for _, row in df.iterrows():
        embedding = row['case_embedding']
        if isinstance(embedding, str):
            embedding = json.loads(embedding)
        embeddings.append(np.array(embedding))
    
    embeddings_matrix = np.vstack(embeddings)
    logger.info(f"Created embeddings matrix: {embeddings_matrix.shape}")
    
    return embeddings_matrix

def compute_tsne(embeddings: np.ndarray, perplexity: int, random_state: int) -> np.ndarray:
    """Compute t-SNE coordinates."""
    logger.info(f"Computing t-SNE with perplexity={perplexity}...")
    
    scaler = StandardScaler()
    embeddings_scaled = scaler.fit_transform(embeddings)
    
    n_samples = embeddings.shape[0]
    perplexity = min(perplexity, max(5, n_samples // 4))
    
    if perplexity != perplexity:
        logger.warning(f"Adjusted perplexity to {perplexity} due to sample size ({n_samples})")
    
    tsne = TSNE(
        n_components=2, 
        perplexity=perplexity,
        random_state=random_state,
        n_jobs=1
    )
    
    coords = tsne.fit_transform(embeddings_scaled)
    logger.info("t-SNE computation completed")
    
    return coords

def compute_clusters(embeddings: np.ndarray, n_clusters: int, min_cluster_size: int, random_state: int) -> Dict[str, np.ndarray]:
    """Compute HDBSCAN clustering algorithm."""
    logger.info("Computing clusters...")
    
    scaler = StandardScaler()
    embeddings_scaled = scaler.fit_transform(embeddings)
    
    results = {}
    
    # HDBSCAN clustering
    min_cluster_size = min(min_cluster_size, max(2, embeddings.shape[0] // 10))
    hdbscan = HDBSCAN(min_cluster_size=min_cluster_size)
    hdbscan_labels = hdbscan.fit_predict(embeddings_scaled)
    results['hdbscan'] = hdbscan_labels
    
    n_clusters_hdbscan = len(set(hdbscan_labels)) - (1 if -1 in hdbscan_labels else 0)
    logger.info(f"HDBSCAN found {n_clusters_hdbscan} clusters")
    
    return results

def create_visualizations(df: pd.DataFrame, timestamp: str, representatives: Dict[str, Dict] = None) -> List[str]:
    """Create interactive visualizations."""
    logger.info("Creating visualizations...")
    
    viz_files = []
    
    # t-SNE scatter plot colored by clusters
    for cluster_method in ['hdbscan_cluster']:
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
            
            # Add representative cases as highlighted points with text annotations
            if representatives:
                method_name = cluster_method.replace('_cluster', '')
                if method_name in representatives:
                    for cluster_id, cluster_info in representatives[method_name].items():
                        rep_case = cluster_info['representative_case']
                        
                        # Add bold marker for representative
                        fig.add_trace(go.Scatter(
                            x=[rep_case['tsne_coords']['x']],
                            y=[rep_case['tsne_coords']['y']],
                            mode='markers+text',
                            marker=dict(
                                size=12,
                                color='black',
                                line=dict(width=2, color='white'),
                                symbol='circle'
                            ),
                            text=[rep_case['docket_number']],
                            textposition='top center',
                            textfont=dict(size=10, color='black'),
                            name=f'Representative (Cluster {cluster_id})',
                            showlegend=False,
                            hovertemplate=f"<b>Representative Case</b><br>" +
                                        f"Cluster: {cluster_id}<br>" +
                                        f"Case: {rep_case['case_id']}<br>" +
                                        f"Docket: {rep_case['docket_number']}<br>" +
                                        f"Distance to centroid: {rep_case['distance_to_centroid']:.3f}<br>" +
                                        f"Tokens: {rep_case['total_tokens']:,}<extra></extra>"
                        ))
            
            fig.update_layout(height=600, width=800)
            
            viz_file = f"case_clustering_{cluster_method}_{timestamp}.html"
            plot(fig, filename=viz_file, auto_open=False)
            viz_files.append(viz_file)
    
    # Token distribution by cluster
    if 'hdbscan_cluster' in df.columns:
        fig = px.box(
            df,
            x='hdbscan_cluster',
            y='total_tokens',
            title="Token Distribution by HDBSCAN Cluster",
            labels={'hdbscan_cluster': 'Cluster', 'total_tokens': 'Total Tokens'}
        )
        fig.update_layout(height=400, width=800)
        
        viz_file = f"token_distribution_{timestamp}.html"
        plot(fig, filename=viz_file, auto_open=False)
        viz_files.append(viz_file)
    
    logger.info(f"Created {len(viz_files)} visualization files")
    return viz_files

def find_cluster_representatives(df: pd.DataFrame) -> Dict[str, Dict]:
    """Find the case closest to each cluster centroid in t-SNE space."""
    logger.info("Computing cluster centroids and finding representative cases...")
    
    representatives = {}
    
    for cluster_method in ['hdbscan_cluster']:
        if cluster_method not in df.columns:
            continue
            
        method_name = cluster_method.replace('_cluster', '')
        representatives[method_name] = {}
        
        # Get unique clusters (excluding noise cluster -1 for HDBSCAN)
        clusters = df[cluster_method].unique()
        clusters = clusters[clusters != -1]  # Remove noise cluster
        
        for cluster_id in clusters:
            cluster_data = df[df[cluster_method] == cluster_id]
            
            if len(cluster_data) == 0:
                continue
                
            # Compute centroid in t-SNE space
            centroid_x = cluster_data['tsne_x'].mean()
            centroid_y = cluster_data['tsne_y'].mean()
            
            # Find closest case to centroid
            distances = np.sqrt(
                (cluster_data['tsne_x'] - centroid_x)**2 + 
                (cluster_data['tsne_y'] - centroid_y)**2
            )
            closest_idx = distances.idxmin()
            closest_case = cluster_data.loc[closest_idx]
            
            representatives[method_name][int(cluster_id)] = {
                'centroid': {'x': float(centroid_x), 'y': float(centroid_y)},
                'representative_case': {
                    'case_id': closest_case['case_id'],
                    'docket_number': closest_case['docket_number'],
                    'distance_to_centroid': float(distances.loc[closest_idx]),
                    'total_tokens': int(closest_case['total_tokens']),
                    'section_count': int(closest_case['section_count']),
                    'tsne_coords': {'x': float(closest_case['tsne_x']), 'y': float(closest_case['tsne_y'])}
                },
                'cluster_size': len(cluster_data),
                'cluster_stats': {
                    'avg_tokens': float(cluster_data['total_tokens'].mean()),
                    'avg_sections': float(cluster_data['section_count'].mean()),
                    'token_std': float(cluster_data['total_tokens'].std()),
                    'sections_std': float(cluster_data['section_count'].std())
                }
            }
    
    total_representatives = sum(len(method_reps) for method_reps in representatives.values())
    logger.info(f"Found {total_representatives} cluster representatives")
    
    return representatives

def export_results(df: pd.DataFrame, viz_files: List[str], s3_client, bucket: str, 
                  output_prefix: str, timestamp: str, analysis_params: Dict[str, Any], 
                  representatives: Dict[str, Dict] = None) -> Dict[str, str]:
    """Export results to S3."""
    logger.info("Exporting results to S3...")
    
    s3_urls = {}
    
    # Export main results CSV
    csv_file = f"case_clustering_results_{timestamp}.csv"
    df.to_csv(csv_file, index=False)
    
    csv_key = f"{output_prefix}/{csv_file}"
    s3_client.upload_file(csv_file, bucket, csv_key)
    s3_urls['results_csv'] = f"s3://{bucket}/{csv_key}"
    
    # Export metadata
    metadata = {
        'timestamp': timestamp,
        'total_cases': len(df),
        'parameters': analysis_params,
        'cluster_summary': {
            'hdbscan_clusters': int(len(set(df['hdbscan_cluster'])) - (1 if -1 in df['hdbscan_cluster'].values else 0)) if 'hdbscan_cluster' in df.columns else 0
        },
        'token_stats': {
            'total_tokens': int(df['total_tokens'].sum()),
            'avg_tokens_per_case': float(df['total_tokens'].mean()),
            'avg_sections_per_case': float(df['section_count'].mean())
        }
    }
    
    # Add cluster representatives if provided
    if representatives:
        metadata['cluster_representatives'] = representatives
    
    metadata_file = f"case_clustering_metadata_{timestamp}.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    metadata_key = f"{output_prefix}/{metadata_file}"
    s3_client.upload_file(metadata_file, bucket, metadata_key)
    s3_urls['metadata'] = f"s3://{bucket}/{metadata_key}"
    
    # Export visualizations
    for viz_file in viz_files:
        viz_key = f"{output_prefix}/visualizations/{viz_file}"
        s3_client.upload_file(viz_file, bucket, viz_key)
        s3_urls[f'viz_{viz_file}'] = f"s3://{bucket}/{viz_key}"
    
    # Cleanup local files
    for f in [csv_file, metadata_file] + viz_files:
        if os.path.exists(f):
            os.remove(f)
    
    return s3_urls