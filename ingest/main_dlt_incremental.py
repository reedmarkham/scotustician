import os
import logging
from datetime import datetime
from typing import Iterator, Dict, Any, Optional
import dlt
from dlt.sources.helpers import requests
from dlt.extract.incremental import Incremental

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BUCKET = os.getenv("S3_BUCKET", "scotustician")
START_TERM = int(os.getenv("START_TERM", 1980))
END_TERM = int(os.getenv("END_TERM", 2025))

OYEZ_CASES_TERM_PREFIX = 'https://api.oyez.org/cases?per_page=0&filter=term:'
OYEZ_API_BASE = 'https://api.oyez.org'

@dlt.source
def oyez_scotus_source():
    """dlt source for Supreme Court oral arguments from Oyez.org"""
    
    @dlt.resource(
        write_disposition="append",
        primary_key="id"
    )
    def oral_arguments(
        updated_at: dlt.sources.incremental[datetime] = dlt.sources.incremental("_dlt_extracted_at")
    ) -> Iterator[Dict[str, Any]]:
        """Extract oral arguments from Oyez API with incremental loading based on extraction timestamp"""
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'scotustician-dlt/1.0'})
        
        # Rate limiting is handled automatically by dlt
        for term in range(START_TERM, END_TERM):
            logger.info(f"Processing term {term}")
            
            # Get cases for this term
            cases_url = f"{OYEZ_CASES_TERM_PREFIX}{term}"
            try:
                cases_response = session.get(cases_url)
                cases_response.raise_for_status()
                cases = cases_response.json()
            except Exception as e:
                logger.error(f"Failed to get cases for term {term}: {e}")
                continue
            
            if not isinstance(cases, list):
                logger.warning(f"Unexpected response format for term {term}")
                continue
            
            processed_count = 0
            for case in cases:
                if not isinstance(case, dict):
                    continue
                    
                docket_number = case.get("docket_number")
                if not docket_number:
                    continue
                
                # Get full case details
                case_url = f"{OYEZ_API_BASE}/cases/{term}/{docket_number}"
                try:
                    case_response = session.get(case_url)
                    case_response.raise_for_status()
                    case_full = case_response.json()
                except Exception as e:
                    logger.error(f"Failed to get case details for {docket_number}: {e}")
                    continue
                
                # Check for oral arguments
                oral_argument_audio = case_full.get('oral_argument_audio', [])
                if not oral_argument_audio:
                    continue
                
                logger.info(f"Found {len(oral_argument_audio)} oral argument(s) for case {docket_number}")
                
                # Process each oral argument
                for idx, oa in enumerate(oral_argument_audio):
                    oa_href = oa.get('href')
                    oa_id = oa.get('id')
                    
                    if not oa_href or not oa_id:
                        continue
                    
                    try:
                        # Get oral argument details
                        oa_response = session.get(oa_href)
                        oa_response.raise_for_status()
                        oa_data = oa_response.json()
                        
                        # Add metadata for tracking and compatibility
                        current_time = datetime.now()
                        oa_data.update({
                            "id": oa_id,  # Ensure ID is present for primary key
                            "term": term,
                            "case_id": case.get('ID'),
                            "docket_number": docket_number,
                            "session": idx,
                            "_dlt_extracted_at": current_time,
                            "_dlt_load_id": f"{term}_{docket_number}_{oa_id}",
                            "scotus_metadata": {
                                "extraction_timestamp": current_time.isoformat(),
                                "source": "oyez_api",
                                "version": "dlt_v1"
                            }
                        })
                        
                        processed_count += 1
                        yield oa_data
                        logger.info(f"Processed OA {oa_id} for case {docket_number} (term {term})")
                        
                    except Exception as e:
                        logger.error(f"Failed to process OA {oa_id}: {e}")
                        continue
            
            logger.info(f"Completed term {term}: processed {processed_count} oral arguments")

    @dlt.resource(
        write_disposition="append",
        table_name="ingestion_summary"
    )
    def ingestion_summary() -> Iterator[Dict[str, Any]]:
        """Create ingestion summary similar to the original pipeline"""
        
        timestamp = datetime.now()
        summary = {
            "timestamp": timestamp.strftime('%Y%m%d_%H%M%S'),
            "extraction_start": timestamp.isoformat(),
            "source": "oyez_api",
            "pipeline": "dlt_migration",
            "start_term": START_TERM,
            "end_term": END_TERM,
            "incremental_load": True,
            "_dlt_extracted_at": timestamp
        }
        
        yield summary

    return [oral_arguments, ingestion_summary]

def main():
    """Main pipeline execution"""
    logger.info("Starting dlt-based Oyez ingestion pipeline with incremental loading")
    
    # Create pipeline - configuration loaded from .dlt/ directory
    pipeline = dlt.pipeline(
        pipeline_name="scotustician_ingest",
        destination="s3",
        dataset_name="scotustician"
    )
    
    try:
        # Run the pipeline
        source = oyez_scotus_source()
        load_info = pipeline.run(source)
        
        # Print results
        logger.info("Pipeline completed successfully!")
        logger.info(f"Dataset: {load_info.dataset_name}")
        
        # Print table statistics
        for package in load_info.load_packages:
            logger.info(f"Load package: {package.load_id}")
            if hasattr(package, 'jobs') and package.jobs:
                for job in package.jobs:
                    if job.job_file_info:
                        table_name = job.job_file_info.table_name
                        logger.info(f"  Table '{table_name}': {job.job_file_info.file_size} bytes")
        
        # Show pipeline state info
        logger.info(f"Pipeline state keys: {list(pipeline.state.keys())}")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()