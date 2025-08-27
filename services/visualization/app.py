#!/usr/bin/env python3
"""
Streamlit app for SCOTUS case clustering visualization.
Decoupled from clustering computation - reads results from S3.
"""

import logging

import streamlit as st
from helpers import ClusteringDataLoader, ClusteringVisualizer, ClusterDataProcessor
from components import (
    render_sidebar, render_single_analysis, render_term_comparison, render_temporal_trends
)

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
    # Add CSS to disable spell checking on text inputs
    st.markdown("""
    <style>
    .stTextInput input {
        spellcheck: false !important;
        -webkit-spellcheck: false !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    st.title("⚖️ scotustician case clustering")
    st.markdown("Explore the results of DBSCAN clustering over the scotustician oral argument embeddings, using t-SNE to reduce dimensionality for visualization")
    
    # Initialize components
    data_loader = ClusteringDataLoader()
    visualizer = ClusteringVisualizer()
    processor = ClusterDataProcessor()
    
    # Render sidebar and get configuration
    config = render_sidebar(data_loader)
    
    # Route to appropriate view based on analysis type
    if config['analysis_type'] == "Single Analysis":
        render_single_analysis(data_loader, visualizer, processor, 
                              config['bucket'], config['base_prefix'])
    
    elif config['analysis_type'] == "Term-by-Term Comparison":
        render_term_comparison(data_loader, visualizer, processor, 
                             config['bucket'], config['base_prefix'])
    
    elif config['analysis_type'] == "Temporal Trends":
        render_temporal_trends(data_loader, visualizer, processor, 
                             config['bucket'], config['base_prefix'])


if __name__ == "__main__":
    main()