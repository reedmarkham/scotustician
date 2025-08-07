"""
Junk data handler for dlt pipeline - equivalent to log_junk_to_s3 in original helpers.py
"""
import dlt
import uuid
from datetime import datetime
from typing import Dict, Any, Iterator

@dlt.source
def junk_data_source():
    """Source for handling malformed/junk data"""
    
    @dlt.resource(
        write_disposition="append",
        table_name="junk_data"
    )
    def junk_records() -> Iterator[Dict[str, Any]]:
        """This will be called programmatically to log junk data"""
        # This is a placeholder - actual junk data will be yielded when errors occur
        return iter([])

    return junk_records

def log_junk_data(pipeline, term: int, item: Any, context: str):
    """Log junk data to pipeline - equivalent to original log_junk_to_s3"""
    junk_id = uuid.uuid4().hex
    junk_record = {
        "junk_id": junk_id,
        "term": term,
        "context": context,
        "item": str(item)[:10000],  # Truncate very large items
        "timestamp": datetime.now().isoformat(),
        "_dlt_extracted_at": datetime.now()
    }
    
    # Create a simple source for this single record
    @dlt.source
    def single_junk_record():
        @dlt.resource(write_disposition="append", table_name="junk_data")
        def junk_item():
            yield junk_record
        return junk_item
    
    # Run the junk data pipeline
    try:
        load_info = pipeline.run(single_junk_record())
        print(f"Logged junk data: {context} for term {term}")
    except Exception as e:
        print(f"Failed to log junk data: {e}")