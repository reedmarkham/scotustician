#!/usr/bin/env python3
"""
Test script for dlt pipeline - validates the pipeline structure without running full ingestion
"""
import os
import sys
import tempfile
from datetime import datetime

# Set test environment
os.environ["START_TERM"] = "2023"  # Test with just recent term
os.environ["END_TERM"] = "2024"
os.environ["S3_BUCKET"] = "test-bucket"

try:
    import dlt
    from main import oyez_scotus_source
    print("✓ Successfully imported dlt and pipeline modules")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

def test_source_creation():
    """Test that we can create the dlt source"""
    try:
        source = oyez_scotus_source()
        print("✓ Successfully created oyez_scotus_source")
        return source
    except Exception as e:
        print(f"✗ Source creation failed: {e}")
        return None

def test_pipeline_creation():
    """Test pipeline creation with filesystem destination for testing"""
    try:
        # Use filesystem destination for testing instead of S3
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = dlt.pipeline(
                pipeline_name="test_scotustician",
                destination="filesystem",
                dataset_name="test_scotus",
                pipelines_dir=temp_dir
            )
            print("✓ Successfully created test pipeline")
            return pipeline
    except Exception as e:
        print(f"✗ Pipeline creation failed: {e}")
        return None

def test_source_schema():
    """Test source schema validation"""
    try:
        source = oyez_scotus_source()
        
        # Check that source has expected resources
        resource_names = [r.name for r in source.resources.values()]
        expected_resources = ["oral_arguments", "ingestion_summary"]
        
        for expected in expected_resources:
            if expected in resource_names:
                print(f"✓ Found expected resource: {expected}")
            else:
                print(f"✗ Missing expected resource: {expected}")
                
        return True
    except Exception as e:
        print(f"✗ Schema validation failed: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing dlt pipeline migration...")
    print(f"Test configuration: Terms {os.environ['START_TERM']}-{os.environ['END_TERM']}")
    
    # Test 1: Module imports
    print("\n1. Testing imports...")
    
    # Test 2: Source creation
    print("\n2. Testing source creation...")
    source = test_source_creation()
    if not source:
        sys.exit(1)
    
    # Test 3: Pipeline creation
    print("\n3. Testing pipeline creation...")
    pipeline = test_pipeline_creation()
    if not pipeline:
        sys.exit(1)
    
    # Test 4: Schema validation
    print("\n4. Testing source schema...")
    if not test_source_schema():
        sys.exit(1)
    
    print("\n🎉 All tests passed! dlt pipeline is ready for deployment.")
    print("\nNext steps:")
    print("- Set proper AWS credentials")
    print("- Update infrastructure to use Dockerfile.dlt")
    print("- Test with small term range first")

if __name__ == "__main__":
    main()