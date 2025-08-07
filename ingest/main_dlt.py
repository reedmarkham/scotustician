import os
import logging
from datetime import datetime
from typing import Iterator, Dict, Any, Optional
import dlt
from dlt.sources.helpers import requests
from dlt.common.typing import TDataItem

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
    def oral_arguments() -> Iterator[Dict[str, Any]]:
        """Extract oral arguments from Oyez API with incremental loading"""
        
        session = requests.Session()
        # dlt automatically handles rate limiting
        session.headers.update({'User-Agent': 'scotustician-dlt/1.0'})
        
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
                        
                        # Enrich with metadata
                        oa_data.update({
                            "term": term,
                            "case_id": case.get('ID'),
                            "docket_number": docket_number,
                            "session": idx,
                            "_dlt_extracted_at": datetime.now().isoformat()
                        })
                        
                        yield oa_data
                        logger.info(f"Processed OA {oa_id} for case {docket_number}")
                        
                    except Exception as e:
                        logger.error(f"Failed to process OA {oa_id}: {e}")
                        continue

    return oral_arguments

def main():
    """Main pipeline execution"""
    logger.info("Starting dlt-based Oyez ingestion pipeline")
    
    # Configure S3 destination - uses .dlt/config.toml and .dlt/secrets.toml
    pipeline = dlt.pipeline(
        pipeline_name="scotustician_ingest",
        destination="s3",
        dataset_name="scotustician_raw"
    )
    
    try:
        # Load data
        source = oyez_scotus_source()
        load_info = pipeline.run(source)
        
        # Print summary
        logger.info(f"Pipeline completed successfully")
        logger.info(f"Loaded {load_info.dataset_name} with tables: {list(load_info.load_packages[0].schema_update.keys())}")
        
        # Print load statistics
        for package in load_info.load_packages:
            for table_name, table_info in package.schema_update.items():
                logger.info(f"Table {table_name}: loaded {len(table_info)} records")
                
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()