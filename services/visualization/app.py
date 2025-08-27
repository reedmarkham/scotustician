#!/usr/bin/env python3
"""
Streamlit app for SCOTUS case clustering visualization.
Decoupled from clustering computation - reads results from S3.
"""

import logging

import streamlit as st
from helpers import ClusteringDataLoader, ClusteringVisualizer, ClusterDataProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="scotustician case clustering",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)


def main():
    st.title("⚖️ scotustician case clustering")
    st.markdown("Interactive visualization of Supreme Court case clustering results")
    
    data_loader = ClusteringDataLoader()
    visualizer = ClusteringVisualizer()
    processor = ClusterDataProcessor()
    
    # Sidebar configuration
    st.sidebar.header("Configuration")
    
    bucket = st.sidebar.text_input("S3 Bucket", value="scotustician")
    base_prefix = st.sidebar.text_input("Base Prefix", value="analysis/case-clustering")
    
    # Analysis type selection
    analysis_type = st.sidebar.radio(
        "Analysis Type",
        ["Single Analysis", "Term-by-Term Comparison", "Temporal Trends"]
    )
    
    if analysis_type == "Single Analysis":
        st.header("Single Analysis View")
        
        # List available analyses
        analyses = data_loader.list_available_analyses(bucket, base_prefix)
        
        if not analyses:
            st.warning("No clustering analyses found. Please run clustering analysis first.")
            return
        
        # Analysis selection
        analysis_options = {f"{a['display_name']}": a for a in analyses}
        selected_analysis = st.selectbox(
            "Select Analysis",
            list(analysis_options.keys())
        )
        
        if selected_analysis:
            analysis_info = analysis_options[selected_analysis]
            
            # Load and display analysis
            with st.spinner("Loading analysis data..."):
                data = data_loader.load_analysis_data(bucket, analysis_info['prefix'])
            
            if data:
                df = data['data']
                metadata = data['metadata']
                
                # Display metadata
                if metadata:
                    st.subheader("Analysis Summary")
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric("Total Cases", metadata.get('total_cases', len(df)))
                    with col2:
                        st.metric("Clusters Found", 
                                metadata.get('cluster_summary', {}).get('hdbscan_clusters', 'N/A'))
                    with col3:
                        st.metric("Total Tokens", 
                                f"{metadata.get('token_stats', {}).get('total_tokens', 0):,}")
                    with col4:
                        st.metric("Avg Tokens/Case", 
                                f"{metadata.get('token_stats', {}).get('avg_tokens_per_case', 0):.0f}")
                
                # Cluster visualization
                st.subheader("Cluster Visualization")
                
                cluster_methods = [col for col in df.columns if col.endswith('_cluster')]
                if cluster_methods:
                    selected_method = st.selectbox("Cluster Method", cluster_methods)
                    
                    fig_scatter = visualizer.create_cluster_scatter_plot(df, selected_method)
                    st.plotly_chart(fig_scatter, use_container_width=True)
                    
                    # Additional charts
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        fig_sizes = visualizer.create_cluster_size_distribution(df, selected_method)
                        st.plotly_chart(fig_sizes, use_container_width=True)
                    
                    with col2:
                        fig_tokens = visualizer.create_token_distribution_by_cluster(df, selected_method)
                        st.plotly_chart(fig_tokens, use_container_width=True)
                
                # Cluster Representatives and Neighbors
                if metadata and 'cluster_representatives' in metadata:
                    st.subheader("Cluster Representatives & Similar Cases")
                    
                    representatives = metadata['cluster_representatives']
                    method_name = selected_method.replace('_cluster', '')
                    
                    if method_name in representatives:
                        # Create tabs for each cluster
                        cluster_ids = sorted(representatives[method_name].keys())
                        
                        if cluster_ids:
                            cluster_tabs = st.tabs([f"Cluster {cid}" for cid in cluster_ids])
                            
                            for i, cluster_id in enumerate(cluster_ids):
                                with cluster_tabs[i]:
                                    cluster_info = representatives[method_name][cluster_id]
                                    
                                    # Cluster summary
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("Cluster Size", cluster_info['cluster_size'])
                                    with col2:
                                        st.metric("Avg Tokens", f"{cluster_info['cluster_stats']['avg_tokens']:.0f}")
                                    with col3:
                                        st.metric("Avg Sections", f"{cluster_info['cluster_stats']['avg_sections']:.1f}")
                                    
                                    # Create table data with representative + neighbors
                                    table_df = processor.prepare_cluster_representative_table(cluster_info)
                                    
                                    # Display table
                                    if not table_df.empty:
                                        st.dataframe(
                                            table_df,
                                            use_container_width=True,
                                            hide_index=True,
                                            column_config={
                                                'Role': st.column_config.TextColumn('Role', width='small'),
                                                'Case Name': st.column_config.TextColumn('Case Name', width='large'),
                                                'Docket Number': st.column_config.TextColumn('Docket', width='medium'),
                                                'Term': st.column_config.TextColumn('Term', width='small'),
                                                'Tokens': st.column_config.TextColumn('Tokens', width='small'),
                                                'Sections': st.column_config.NumberColumn('Sections', width='small'),
                                                'Similarity': st.column_config.TextColumn('Similarity', width='small'),
                                                'Distance to Centroid': st.column_config.TextColumn('Dist to Center', width='small')
                                            }
                                        )
                
                # Data table
                st.subheader("All Case Data")
                st.dataframe(df, use_container_width=True)
    
    elif analysis_type == "Term-by-Term Comparison":
        st.header("Term-by-Term Comparison")
        
        term_prefix = base_prefix.rstrip('/') + '-by-term'
        term_analyses = data_loader.list_available_analyses(bucket, term_prefix)
        
        if not term_analyses:
            st.warning("No term-by-term analyses found. Please run term-by-term clustering first.")
            return
        
        # Filter for single-term analyses
        single_term_analyses = [a for a in term_analyses if a['type'] == 'single_term']
        
        if not single_term_analyses:
            st.warning("No single-term analyses found.")
            return
        
        # Term selection
        available_terms = [a['term'] for a in single_term_analyses]
        selected_terms = st.multiselect(
            "Select Terms to Compare",
            available_terms,
            default=available_terms[:min(5, len(available_terms))]
        )
        
        if selected_terms:
            # Load data for selected terms
            term_data = {}
            for term in selected_terms:
                term_analysis = next(a for a in single_term_analyses if a['term'] == term)
                with st.spinner(f"Loading data for term {term}..."):
                    data = data_loader.load_analysis_data(bucket, term_analysis['prefix'])
                    if data:
                        term_data[term] = data
            
            if term_data:
                # Create comparison visualizations
                st.subheader("Term Comparison Summary")
                
                # Summary metrics
                summary_df = processor.prepare_term_comparison_summary(term_data)
                st.dataframe(summary_df, use_container_width=True)
                
                # Side-by-side cluster visualizations
                st.subheader("Cluster Visualizations by Term")
                
                cols = st.columns(min(3, len(selected_terms)))
                for i, term in enumerate(selected_terms):
                    with cols[i % len(cols)]:
                        if term in term_data:
                            df = term_data[term]['data']
                            fig = visualizer.create_cluster_scatter_plot(df, 'hdbscan_cluster')
                            fig.update_layout(title=f"Term {term}")
                            st.plotly_chart(fig, use_container_width=True)
    
    elif analysis_type == "Temporal Trends":
        st.header("Temporal Trends Analysis")
        
        term_prefix = base_prefix.rstrip('/') + '-by-term'
        term_analyses = data_loader.list_available_analyses(bucket, term_prefix)
        
        if not term_analyses:
            st.warning("No term-by-term analyses found for temporal analysis.")
            return
        
        # Filter and load all term analyses
        single_term_analyses = [a for a in term_analyses if a['type'] == 'single_term']
        
        # Load metadata for all terms
        term_metadata = []
        for analysis in single_term_analyses:
            with st.spinner(f"Loading metadata for term {analysis['term']}..."):
                data = data_loader.load_analysis_data(bucket, analysis['prefix'])
                if data and data['metadata']:
                    analysis['metadata'] = data['metadata']
                    term_metadata.append(analysis)
        
        if term_metadata:
            # Create temporal trend chart
            fig_trend = visualizer.create_temporal_trend_chart(term_metadata)
            st.plotly_chart(fig_trend, use_container_width=True)
            
            # Summary statistics over time
            st.subheader("Temporal Statistics")
            
            trend_df = processor.prepare_temporal_metadata(term_metadata)
            st.dataframe(trend_df, use_container_width=True)
        else:
            st.warning("No metadata available for temporal analysis.")

if __name__ == "__main__":
    main()