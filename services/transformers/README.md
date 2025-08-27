# Scotustician Transformers Service

## Overview

The transformers service processes ingested Supreme Court oral argument data to generate embeddings using machine learning models. It provides a distributed, fault-tolerant pipeline for converting text transcripts into high-dimensional vector representations suitable for semantic search, clustering, and analysis.

## Architecture

### Processing Pipeline

1. **Data Input**: Reads JSON transcript files from S3 (`raw/oa/` prefix)
2. **Section-based Chunking**: Splits transcripts by natural argument sections (petitioner, respondent, rebuttal)
3. **Embedding Generation**: Uses `baai/bge-m3` model to generate 1024-dimensional embeddings
4. **Database Storage**: Stores embeddings and utterances in PostgreSQL with pgvector extension
5. **Idempotency**: Supports safe re-runs with automatic duplicate detection

### Key Components

- **`main.py`** - Entry point supporting both single document and batch processing modes
- **`processors.py`** - Ray Data integration for distributed processing and AWS Batch coordination
- **`helpers.py`** - Core processing functions including embedding generation and database operations

## Idempotency and Data Integrity

The service implements robust idempotency to ensure safe re-processing:

### Deterministic ID Generation
- **Utterances**: `{case_id}_utterance_{utterance_index}` 
- **Embeddings**: `{case_id}_section_{section_id}`

### Duplicate Handling
- Graceful detection of existing records using unique constraint violations
- Individual transaction isolation prevents partial failures
- Detailed logging with insert/skip counts for monitoring

### Schema Alignment
- Explicit ID management aligns with dbt schema constraints
- Connection management with automatic cleanup via context managers
- Proper rollback handling for failed insertions

## Environment Variables

### Required
- `POSTGRES_HOST` - Database hostname
- `POSTGRES_USER` - Database username  
- `POSTGRES_PASS` - Database password
- `POSTGRES_DB` - Database name (default: scotustician)
- `S3_BUCKET` - Source bucket for transcript files (default: scotustician)

### Processing Configuration
- `MODEL_NAME` - Hugging Face model identifier (default: baai/bge-m3)
- `MODEL_DIMENSION` - Embedding dimension (default: 1024)
- `BATCH_SIZE` - Processing batch size (default: 24)
- `MAX_WORKERS` - Parallel workers per job (default: 1)
- `FILES_PER_JOB` - Files per AWS Batch array job (default: 10)

### Operational Settings
- `RAW_PREFIX` - S3 prefix for input files (default: raw/oa)
- `INCREMENTAL` - Skip already processed files (default: true)
- `INPUT_KEY` - Single file mode: specific S3 key to process

## Usage Modes

### Single Document Processing
```bash
export INPUT_KEY="raw/oa/transcript_12345.json"
python main.py
```

### Batch Processing (AWS Batch)
```bash
# Runs automatically via AWS Batch array jobs
# Triggered by scripts/embeddings.sh
python main.py
```

## Database Schema

### Tables Created

#### oa_text
Stores individual utterances with speakers and timing:
- `id` (Primary Key) - Deterministic utterance identifier
- `case_id`, `oa_id`, `utterance_index` - Business keys
- `speaker_name`, `text` - Content fields
- `word_count`, `token_count` - Metrics
- `start_time_ms`, `end_time_ms` - Timing data

#### document_chunk_embeddings  
Stores section-level embeddings:
- `id` (Primary Key) - Deterministic chunk identifier
- `case_id`, `oa_id`, `section_id` - Business keys
- `chunk_text` - Section content
- `vector` - 1024-dimensional embedding
- `embedding_model`, `embedding_dimension` - Model metadata

## Processing Logic

### Section-Based Chunking
Supreme Court oral arguments follow structured formats:
- **Petitioner Arguments** (~20-30 min)
- **Respondent Arguments** (~20-30 min) 
- **Petitioner Rebuttal** (~5-10 min)

Each section becomes a chunk, preserving the logical flow of legal arguments while creating optimal sizes for embedding models (1,300-5,500 tokens).

### Incremental Processing
The service supports incremental runs by:
1. Querying existing `source_key` values from `document_chunk_embeddings`
2. Filtering out already processed files from the batch
3. Processing only new or updated transcripts

## Ray Data Integration

For distributed processing, the service uses Ray Data:
- **Fault Tolerance**: Automatic retry of failed tasks
- **Memory Management**: Efficient handling of large datasets
- **Parallel Processing**: Concurrent embedding generation
- **Progress Tracking**: Real-time monitoring of batch progress

## Error Handling

### Malformed Data
- Invalid JSON files are moved to `junk/` S3 prefix
- Processing continues with remaining valid files
- Detailed error logging for debugging

### Database Failures
- Individual transaction isolation prevents batch failures
- Automatic rollback on constraint violations
- Connection cleanup via context managers

### Resource Management
- GPU memory optimization for embedding generation
- Automatic CPU fallback if GPU unavailable
- Proper cleanup of model resources

## Monitoring and Observability

### Logging
- Progress bars for embedding generation
- Insert/skip counts for database operations
- Error details with file context
- Performance metrics (tokens/second)

### Metrics Available
- Files processed per batch job
- Embedding generation time
- Database insertion rates
- Memory usage patterns

## Development

### Local Testing
```bash
# Set test environment
export POSTGRES_HOST=localhost
export S3_BUCKET=test-bucket
export INPUT_KEY=raw/oa/sample.json

python main.py
```

### Adding New Models
1. Update `MODEL_NAME` environment variable
2. Adjust `MODEL_DIMENSION` to match model output
3. Test with small dataset before full deployment
4. Update database schema if dimension changes

### Schema Migrations
When updating database schemas:
1. Test changes with `helpers.py` functions
2. Verify ID generation patterns remain consistent
3. Update dbt schema definitions in scotustician-db repository
4. Deploy database changes before service updates

## Performance Tuning

### GPU Optimization
- Batch size: 4-24 depending on GPU memory
- Model loading: Single model instance per worker
- Memory management: Automatic cleanup after processing

### Database Performance
- Individual transactions for idempotency
- Bulk operations where possible
- Connection pooling via context managers
- Index optimization for frequent queries

### AWS Batch Configuration
- Spot instances for cost efficiency (g4dn.xlarge)
- Array jobs for parallel processing
- SQS integration for job tracking
- Automatic scaling based on queue depth

## Troubleshooting

### Common Issues

#### Memory Errors
- Reduce `BATCH_SIZE` for embedding generation
- Use smaller model or reduce `MODEL_DIMENSION`
- Check available GPU memory

#### Database Connection Issues
- Verify PostgreSQL credentials in Secrets Manager
- Check VPC security group configurations
- Ensure database schema exists (scotustician-db deployment)

#### Processing Failures
- Check S3 bucket permissions and file availability
- Verify Ray cluster initialization
- Monitor CloudWatch logs for detailed errors

#### Idempotency Issues
- If duplicates appear, check ID generation logic
- Verify unique constraints exist in database schema
- Review transaction isolation settings

### Performance Optimization
- Monitor embedding generation rate (tokens/second)
- Adjust worker count based on available resources
- Use incremental processing for large datasets
- Consider model quantization for faster inference

## Dependencies

### Core ML Libraries
- `sentence-transformers` - Embedding model framework
- `transformers` - Tokenization and model utilities
- `torch` - PyTorch backend for model inference

### Data Processing
- `ray[data]` - Distributed processing framework
- `psycopg2` - PostgreSQL database adapter
- `boto3` - AWS SDK for S3 operations

### Infrastructure
- AWS Batch for job orchestration
- AWS Secrets Manager for credential management
- CloudWatch for logging and monitoring

## Contributing

When modifying the transformers service:

1. **Test Idempotency**: Ensure duplicate detection works correctly
2. **Verify Schema Alignment**: Check compatibility with dbt models
3. **Monitor Performance**: Test with representative datasets
4. **Update Documentation**: Reflect changes in README and code comments
5. **Database Compatibility**: Coordinate with scotustician-db repository updates