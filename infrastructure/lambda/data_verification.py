import json

import boto3, psycopg2

s3_client = boto3.client('s3')
secrets_client = boto3.client('secretsmanager')

def handler(event, context):
    """Verify data at different pipeline stages"""
    
    verification_type = event.get('type', 'unknown')
    
    try:
        if verification_type == 's3_ingest':
            return verify_s3_ingest(event)
        elif verification_type == 'embeddings':
            return verify_embeddings(event)
        else:
            return {
                'statusCode': 400,
                'verified': False,
                'message': f'Unknown verification type: {verification_type}'
            }
    except Exception as e:
        return {
            'statusCode': 500,
            'verified': False,
            'message': str(e)
        }

def verify_s3_ingest(event):
    """Verify S3 data after ingest"""
    bucket = event.get('bucket', 'scotustician')
    prefix = event.get('prefix', 'raw/oa/')
    
    # List objects in S3
    response = s3_client.list_objects_v2(
        Bucket=bucket,
        Prefix=prefix
    )
    
    file_count = response.get('KeyCount', 0)
    
    if file_count > 0:
        # Get some basic statistics
        total_size = sum([obj.get('Size', 0) for obj in response.get('Contents', [])])
        
        return {
            'statusCode': 200,
            'verified': True,
            'message': f'Found {file_count} files in S3',
            'details': {
                'file_count': file_count,
                'total_size_bytes': total_size,
                'bucket': bucket,
                'prefix': prefix
            }
        }
    else:
        return {
            'statusCode': 200,
            'verified': False,
            'message': 'No files found in S3',
            'details': {'bucket': bucket, 'prefix': prefix}
        }

def verify_embeddings(event):
    """Verify embeddings in PostgreSQL"""
    secret_name = 'scotustician-db-credentials'
    
    try:
        # Get database credentials
        secret_response = secrets_client.get_secret_value(SecretId=secret_name)
        secret = json.loads(secret_response['SecretString'])
        
        # Connect to database
        conn = psycopg2.connect(
            host=secret['host'],
            database=secret['dbname'],
            user=secret['username'],
            password=secret['password'],
            port=secret['port']
        )
        
        cursor = conn.cursor()
        
        # Check embeddings table
        cursor.execute("SELECT COUNT(*) FROM scotustician.document_chunk_embeddings;")
        embedding_count = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        if embedding_count > 0:
            return {
                'statusCode': 200,
                'verified': True,
                'message': f'Found {embedding_count} embeddings in database',
                'details': {'embedding_count': embedding_count}
            }
        else:
            return {
                'statusCode': 200,
                'verified': False,
                'message': 'No embeddings found in database'
            }
            
    except Exception as e:
        return {
            'statusCode': 500,
            'verified': False,
            'message': f'Database verification failed: {str(e)}'
        }