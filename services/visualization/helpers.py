#!/usr/bin/env python3

import json, logging
from io import StringIO
from typing import Dict, List, Optional

import boto3, pandas as pd, streamlit as st
import plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)

class ClusteringDataLoader:
    """Handles loads from S3 and caching for Streamlit best practice."""
    
    def __init__(self):
        self.s3_client = boto3.client('s3')
        
    @st.cache_data(ttl=300)  # Cache for 5 minutes
    def list_available_analyses(self, bucket: str, prefix: str) -> List[Dict]:
        """List available clustering analyses from S3."""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                Delimiter='/'
            )
            
            analyses = []
            if 'CommonPrefixes' in response:
                for obj in response['CommonPrefixes']:
                    analysis_prefix = obj['Prefix']
                    if 'term-' in analysis_prefix:
                        # Term-specific analysis
                        term = analysis_prefix.split('term-')[-1].rstrip('/')
                        analyses.append({
                            'type': 'single_term',
                            'term': term,
                            'prefix': analysis_prefix,
                            'display_name': f"Term {term}"
                        })
                    else:
                        # Check if it's a date-based analysis
                        try:
                            # Look for metadata to determine analysis type
                            metadata_objects = self.s3_client.list_objects_v2(
                                Bucket=bucket,
                                Prefix=analysis_prefix,
                                MaxKeys=10
                            )
                            
                            for obj in metadata_objects.get('Contents', []):
                                if 'metadata' in obj['Key'] and obj['Key'].endswith('.json'):
                                    # Extract timestamp from filename
                                    timestamp = obj['Key'].split('_')[-1].split('.')[0]
                                    analyses.append({
                                        'type': 'multi_term',
                                        'timestamp': timestamp,
                                        'prefix': analysis_prefix,
                                        'display_name': f"Multi-term Analysis {timestamp}",
                                        'last_modified': obj['LastModified']
                                    })
                                    break
                        except Exception as e:
                            logger.warning(f"Could not parse analysis info from {analysis_prefix}: {e}")
            
            return sorted(analyses, key=lambda x: x.get('term', x.get('timestamp', '')))
        
        except Exception as e:
            logger.error(f"Failed to list analyses: {e}")
            return []
    
    @st.cache_data(ttl=600)  # Cache for 10 minutes
    def load_analysis_data(self, bucket: str, prefix: str) -> Optional[Dict]:
        """Load clustering analysis data from S3."""
        try:
            # Find the CSV results file and metadata
            response = self.s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix
            )
            
            csv_key = None
            metadata_key = None
            
            for obj in response.get('Contents', []):
                if obj['Key'].endswith('.csv') and 'results' in obj['Key']:
                    csv_key = obj['Key']
                elif obj['Key'].endswith('.json') and 'metadata' in obj['Key']:
                    metadata_key = obj['Key']
            
            if not csv_key:
                logger.error(f"No results CSV found in {prefix}")
                return None
            
            # Load CSV data
            csv_obj = self.s3_client.get_object(Bucket=bucket, Key=csv_key)
            df = pd.read_csv(StringIO(csv_obj['Body'].read().decode('utf-8')))
            
            # Load metadata if available
            metadata = {}
            if metadata_key:
                metadata_obj = self.s3_client.get_object(Bucket=bucket, Key=metadata_key)
                metadata = json.loads(metadata_obj['Body'].read().decode('utf-8'))
            
            return {
                'data': df,
                'metadata': metadata,
                'csv_key': csv_key
            }
            
        except Exception as e:
            logger.error(f"Failed to load analysis data: {e}")
            return None


class ClusteringVisualizer:
    """Generates visualizations for clustering data."""
    
    @staticmethod
    def create_cluster_scatter_plot(df: pd.DataFrame, cluster_method: str = 'hdbscan_cluster') -> go.Figure:
        """Create interactive scatter plot of clusters."""
        if cluster_method not in df.columns:
            logger.warning(f"Cluster method '{cluster_method}' not found in data")
            return go.Figure()
        
        # Create color mapping for clusters
        unique_clusters = sorted(df[cluster_method].unique())
        color_discrete_map = {}
        colors = px.colors.qualitative.Set3
        
        for i, cluster in enumerate(unique_clusters):
            if cluster == -1:  # Noise cluster
                color_discrete_map[cluster] = '#888888'
            else:
                color_discrete_map[cluster] = colors[i % len(colors)]
        
        fig = px.scatter(
            df,
            x='tsne_x',
            y='tsne_y',
            color=cluster_method,
            hover_data=['case_id', 'docket_number', 'total_tokens', 'section_count'],
            title=f"Case Clustering: {cluster_method.replace('_', ' ').title()}",
            labels={'tsne_x': 't-SNE Dimension 1', 'tsne_y': 't-SNE Dimension 2'},
            color_discrete_map=color_discrete_map
        )
        
        fig.update_traces(marker=dict(size=8, opacity=0.7))
        fig.update_layout(height=600, width=800)
        
        return fig
    
    @staticmethod
    def create_cluster_size_distribution(df: pd.DataFrame, cluster_method: str = 'hdbscan_cluster') -> go.Figure:
        """Create cluster size distribution chart."""
        if cluster_method not in df.columns:
            return go.Figure()
        
        cluster_sizes = df[cluster_method].value_counts().sort_index()
        
        fig = px.bar(
            x=cluster_sizes.index,
            y=cluster_sizes.values,
            labels={'x': 'Cluster ID', 'y': 'Number of Cases'},
            title=f"Cluster Size Distribution ({cluster_method.replace('_', ' ').title()})"
        )
        
        fig.update_layout(height=400)
        return fig
    
    @staticmethod
    def create_token_distribution_by_cluster(df: pd.DataFrame, cluster_method: str = 'hdbscan_cluster') -> go.Figure:
        """Create token distribution by cluster."""
        if cluster_method not in df.columns:
            return go.Figure()
        
        fig = px.box(
            df,
            x=cluster_method,
            y='total_tokens',
            title=f"Token Distribution by Cluster ({cluster_method.replace('_', ' ').title()})",
            labels={cluster_method: 'Cluster', 'total_tokens': 'Total Tokens'}
        )
        
        fig.update_layout(height=400)
        return fig
    
    @staticmethod
    def create_temporal_trend_chart(term_analyses: List[Dict]) -> go.Figure:
        """Create temporal trend chart showing cluster counts over time."""
        if not term_analyses:
            return go.Figure()
        
        terms, cluster_counts, total_cases = [], [], []
        
        for analysis in term_analyses:
            if 'metadata' in analysis and 'cluster_summary' in analysis['metadata']:
                terms.append(int(analysis['term']))
                cluster_counts.append(analysis['metadata']['cluster_summary'].get('hdbscan_clusters', 0))
                total_cases.append(analysis['metadata'].get('total_cases', 0))
        
        if not terms:
            return go.Figure()
        
        # Create subplot with secondary y-axis
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        fig.add_trace(
            go.Scatter(
                x=terms,
                y=cluster_counts,
                mode='lines+markers',
                name='Number of Clusters',
                line=dict(color='blue', width=2),
                marker=dict(size=6)
            ),
            secondary_y=False
        )
        
        fig.add_trace(
            go.Scatter(
                x=terms,
                y=total_cases,
                mode='lines+markers',
                name='Total Cases',
                line=dict(color='red', width=2, dash='dash'),
                marker=dict(size=6)
            ),
            secondary_y=True
        )
        
        fig.update_xaxes(title_text="Term Year")
        fig.update_yaxes(title_text="Number of Clusters", secondary_y=False)
        fig.update_yaxes(title_text="Total Cases", secondary_y=True)
        fig.update_layout(title_text="Clustering Trends Over Time", height=500)
        
        return fig


class ClusterDataProcessor:
    """Processes clustering data for display."""
    
    @staticmethod
    def prepare_cluster_representative_table(cluster_info: Dict) -> pd.DataFrame:
        """Prepare representative case and neighbors data for table display."""
        rep_case = cluster_info['representative_case']
        neighbors = cluster_info.get('nearest_neighbors', [])
        
        table_data = []
        
        # Add representative case
        table_data.append({
            'Role': 'Representative',
            'Case Name': rep_case.get('case_name', 'N/A'),
            'Docket Number': rep_case['docket_number'],
            'Term': rep_case.get('term', 'N/A'),
            'Tokens': f"{rep_case['total_tokens']:,}",
            'Sections': rep_case['section_count'],
            'Similarity': '1.000',
            'Distance to Centroid': f"{rep_case['distance_to_centroid']:.3f}"
        })
        
        # Add neighbor cases
        for j, neighbor in enumerate(neighbors, 1):
            table_data.append({
                'Role': f'Neighbor {j}',
                'Case Name': neighbor.get('case_name', 'N/A'),
                'Docket Number': neighbor['docket_number'],
                'Term': neighbor.get('term', 'N/A'),
                'Tokens': f"{neighbor['total_tokens']:,}",
                'Sections': neighbor['section_count'],
                'Similarity': f"{neighbor['similarity_to_representative']:.3f}",
                'Distance to Centroid': f"{neighbor['distance_to_centroid']:.3f}"
            })
        
        return pd.DataFrame(table_data)
    
    @staticmethod
    def prepare_term_comparison_summary(term_data: Dict) -> pd.DataFrame:
        """Prepare summary data for term-by-term comparison."""
        summary_data = []
        
        for term, data in term_data.items():
            metadata = data['metadata']
            df = data['data']
            
            cluster_count = 0
            if 'hdbscan_cluster' in df.columns:
                cluster_count = len(set(df['hdbscan_cluster'])) - (1 if -1 in df['hdbscan_cluster'].values else 0)
            
            summary_data.append({
                'Term': term,
                'Total Cases': len(df),
                'Clusters': cluster_count,
                'Total Tokens': metadata.get('token_stats', {}).get('total_tokens', 0),
                'Avg Tokens/Case': metadata.get('token_stats', {}).get('avg_tokens_per_case', 0)
            })
        
        return pd.DataFrame(summary_data)
    
    @staticmethod
    def prepare_temporal_metadata(term_metadata: List[Dict]) -> pd.DataFrame:
        """Prepare temporal trend metadata for display."""
        trend_data = []
        
        for analysis in sorted(term_metadata, key=lambda x: int(x['term'])):
            metadata = analysis['metadata']
            trend_data.append({
                'Term': analysis['term'],
                'Cases': metadata.get('total_cases', 0),
                'Clusters': metadata.get('cluster_summary', {}).get('hdbscan_clusters', 0),
                'Total Tokens': metadata.get('token_stats', {}).get('total_tokens', 0),
                'Avg Sections/Case': metadata.get('token_stats', {}).get('avg_sections_per_case', 0)
            })
        
        return pd.DataFrame(trend_data)