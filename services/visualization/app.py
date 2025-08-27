#!/usr/bin/env python3
import logging

from helpers import ClusteringDataLoader, ClusteringVisualizer, ClusterDataProcessor
from components import (
    render_sidebar, render_single_analysis, render_term_comparison, render_temporal_trends
)

import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="scotustician: oral argument cluster dashboard",
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
    
    st.title("⚖️ scotustician: oral argument cluster dashboard")
    st.markdown("Explore the results of DBSCAN clustering over the scotustician oral argument embeddings, using t-SNE for dimensionality reduction")
    
    data_loader = ClusteringDataLoader()
    visualizer = ClusteringVisualizer()
    processor = ClusterDataProcessor()
    
    config = render_sidebar()
    
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