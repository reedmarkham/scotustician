import json
from pathlib import Path

import boto3, psycopg2

def handler(event, context):
    """Lambda function to initialize the RDS database"""
    
    # Get parameters from event - handle both direct invocation and CloudFormation custom resource format
    resource_properties = event.get('ResourceProperties', event)
    
    secret_arn = resource_properties['SecretArn']
    db_endpoint = resource_properties['DbEndpoint']  
    db_port = resource_properties.get('DbPort', '5432')
    db_name = resource_properties.get('DbName', 'scotustician')
    
    # Initialize AWS clients
    secrets_client = boto3.client('secretsmanager')
    
    try:
        # Retrieve database credentials
        print(f"Retrieving credentials from Secrets Manager...")
        secret_response = secrets_client.get_secret_value(SecretId=secret_arn)
        credentials = json.loads(secret_response['SecretString'])
        
        username = credentials['username']
        password = credentials['password']
        
        # Connect to the database
        print(f"Connecting to database at {db_endpoint}:{db_port}...")
        conn = psycopg2.connect(
            host=db_endpoint,
            port=db_port,
            database=db_name,
            user=username,
            password=password
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        # Execute initialization scripts
        # Create pgvector extension and schema
        print("Creating pgvector extension and schema...")
        
        # Create extension first
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            print("Successfully created vector extension")
        except Exception as e:
            print(f"Warning: Could not create vector extension: {e}")
            print("Continuing without vector extension - vector columns will fail")
        
        # Create schema and set search path
        cursor.execute("""
            CREATE SCHEMA IF NOT EXISTS scotustician;
            SET search_path TO scotustician, public;
        """)
        
        # Read and execute the schema file
        schema_file = Path(__file__).parent / 'schema.sql'
        if schema_file.exists():
            print(f"Reading schema from {schema_file}...")
            with open(schema_file, 'r') as f:
                schema_sql = f.read()
            
            print("Executing schema creation...")
            # Split by semicolons to handle multiple statements
            # Filter out empty statements and comments
            statements = [s.strip() for s in schema_sql.split(';') 
                         if s.strip() and not s.strip().startswith('--')]
            
            for i, statement in enumerate(statements):
                if statement:
                    print(f"Executing statement {i+1}/{len(statements)}: {statement[:100]}...")
                    try:
                        cursor.execute(statement)
                        print(f"Successfully executed statement {i+1}")
                    except psycopg2.errors.DuplicateTable as e:
                        print(f"Table already exists (skipping): {e}")
                    except psycopg2.errors.DuplicateObject as e:
                        print(f"Object already exists (skipping): {e}")
                    except Exception as e:
                        print(f"Error executing statement {i+1}: {e}")
                        print(f"Statement was: {statement}")
                        raise e
        else:
            print("Warning: schema.sql file not found, skipping table creation")
        
        # Verify tables were created successfully
        print("Verifying table creation...")
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'scotustician' AND table_name = 'transcript_embeddings';")
        table_count = cursor.fetchone()[0]
        if table_count == 0:
            raise Exception("Failed to verify transcript_embeddings table creation")
        print(f"Successfully verified transcript_embeddings table exists")
        
        cursor.close()
        conn.close()
        
        print("Database initialization completed successfully!")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Database initialized successfully',
                'endpoint': db_endpoint
            })
        }
        
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        raise e