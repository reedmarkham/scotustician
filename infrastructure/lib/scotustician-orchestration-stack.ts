import * as cdk from 'aws-cdk-lib';
import * as stepfunctions from 'aws-cdk-lib/aws-stepfunctions';
import * as stepfunctionstasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';

export interface ScotusticianOrchestrationStackProps extends cdk.StackProps {
  readonly ingestClusterArn: string;
  readonly ingestTaskDefinitionArn: string;
  readonly transformersJobQueueArn: string;
  readonly transformersJobDefinitionArn: string;
  readonly clusteringJobQueueArn: string;
  readonly clusteringJobDefinitionArn: string;
  readonly vpcId: string;
  readonly publicSubnetIds: string[];
  readonly privateSubnetIds: string[];
}

export class ScotusticianOrchestrationStack extends cdk.Stack {
  public readonly stateMachine: stepfunctions.StateMachine;
  public readonly notificationTopic: sns.Topic;

  constructor(scope: Construct, id: string, props: ScotusticianOrchestrationStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });

    cdk.Tags.of(this).add('Project', 'scotustician');
    cdk.Tags.of(this).add('Stack', 'orchestration');

    // SNS Topic for notifications
    this.notificationTopic = new sns.Topic(this, 'PipelineNotifications', {
      topicName: 'scotustician-pipeline-notifications',
      displayName: 'Scotustician Pipeline Notifications',
    });

    // Cost tracking Lambda function
    const costTrackingFunction = new lambda.Function(this, 'CostTrackingFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'cost_tracking.handler',
      code: lambda.Code.fromInline(`
import json
import boto3
from datetime import datetime, timedelta
import os

ce_client = boto3.client('ce')
sns_client = boto3.client('sns')

def handler(event, context):
    """Track costs for scotustician project and send notifications"""
    
    # Get date range (today)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    
    try:
        # Get cost by service
        service_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'}
            ]
        )
        
        # Get scotustician project costs
        project_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            Filter={
                'Tags': {
                    'Key': 'Project',
                    'Values': ['scotustician']
                }
            }
        )
        
        # Get component costs
        component_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'TAG', 'Key': 'Stack'}
            ],
            Filter={
                'Tags': {
                    'Key': 'Project',
                    'Values': ['scotustician']
                }
            }
        )
        
        # Format results
        stage = event.get('stage', 'unknown')
        total_cost = '0.00'
        
        if project_costs.get('ResultsByTime'):
            total_cost = project_costs['ResultsByTime'][0]['Total']['BlendedCost']['Amount']
        
        result = {
            'stage': stage,
            'timestamp': datetime.now().isoformat(),
            'total_cost': total_cost,
            'service_breakdown': [],
            'component_breakdown': []
        }
        
        # Process service costs
        if service_costs.get('ResultsByTime'):
            for group in service_costs['ResultsByTime'][0].get('Groups', []):
                cost = group['Metrics']['BlendedCost']['Amount']
                if float(cost) > 0:
                    result['service_breakdown'].append({
                        'service': group['Keys'][0],
                        'cost': cost
                    })
        
        # Process component costs  
        if component_costs.get('ResultsByTime'):
            for group in component_costs['ResultsByTime'][0].get('Groups', []):
                cost = group['Metrics']['BlendedCost']['Amount']
                if float(cost) > 0:
                    result['component_breakdown'].append({
                        'component': group['Keys'][0],
                        'cost': cost
                    })
        
        # Send notification if requested
        topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if topic_arn and event.get('notify', False):
            message = f"""
Scotustician Pipeline - {stage.title()} Cost Report

Total Cost: ${total_cost}
Timestamp: {result['timestamp']}

Top Services:
{chr(10).join([f"  • {s['service']}: ${s['cost']}" for s in result['service_breakdown'][:5]])}

Components:
{chr(10).join([f"  • {c['component']}: ${c['cost']}" for c in result['component_breakdown']])}
"""
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f'Scotustician Pipeline - {stage.title()} Cost Report',
                Message=message
            )
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        print(f"Error tracking costs: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
`),
      timeout: cdk.Duration.minutes(2),
      environment: {
        SNS_TOPIC_ARN: this.notificationTopic.topicArn,
      },
    });

    // Grant cost tracking permissions
    costTrackingFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['ce:GetCostAndUsage'],
      resources: ['*'],
    }));

    this.notificationTopic.grantPublish(costTrackingFunction);

    // Data verification Lambda function
    const dataVerificationFunction = new lambda.Function(this, 'DataVerificationFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'data_verification.handler',
      code: lambda.Code.fromInline(`
import json
import boto3
import psycopg2
import os
from urllib.parse import urlparse

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
        cursor.execute("SELECT COUNT(*) FROM embeddings;")
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
`),
      timeout: cdk.Duration.minutes(5),
    });

    // Grant data verification permissions
    dataVerificationFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        's3:ListBucket',
        's3:GetObject',
        'secretsmanager:GetSecretValue'
      ],
      resources: [
        'arn:aws:s3:::scotustician',
        'arn:aws:s3:::scotustician/*',
        `arn:aws:secretsmanager:${this.region}:${this.account}:secret:scotustician-db-credentials*`
      ],
    }));

    // Create Step Function tasks
    const costBaselineTask = new stepfunctionstasks.LambdaInvoke(this, 'CostBaseline', {
      lambdaFunction: costTrackingFunction,
      payload: stepfunctions.TaskInput.fromObject({
        stage: 'baseline',
        notify: true
      }),
      resultPath: '$.costBaseline',
    });

    const runIngestTask = new stepfunctionstasks.EcsRunTask(this, 'RunIngestTask', {
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      cluster: cdk.aws_ecs.Cluster.fromClusterArn(this, 'IngestCluster', props.ingestClusterArn),
      taskDefinition: cdk.aws_ecs.TaskDefinition.fromTaskDefinitionArn(this, 'IngestTaskDefinition', props.ingestTaskDefinitionArn),
      launchTarget: new stepfunctionstasks.EcsFargateLaunchTarget({
        platformVersion: cdk.aws_ecs.FargatePlatformVersion.LATEST,
      }),
      subnets: {
        subnetType: cdk.aws_ec2.SubnetType.PUBLIC,
      },
      resultPath: '$.ingestResult',
    });

    const verifyS3DataTask = new stepfunctionstasks.LambdaInvoke(this, 'VerifyS3Data', {
      lambdaFunction: dataVerificationFunction,
      payload: stepfunctions.TaskInput.fromObject({
        type: 's3_ingest',
        bucket: 'scotustician',
        prefix: 'raw/oa/'
      }),
      resultPath: '$.s3Verification',
    });

    const runEmbeddingsTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunEmbeddingsTask', {
      jobName: 'scotustician-embeddings-stepfunctions',
      jobQueue: cdk.aws_batch.JobQueue.fromJobQueueArn(this, 'TransformersJobQueue', props.transformersJobQueueArn),
      jobDefinition: cdk.aws_batch.JobDefinition.fromJobDefinitionArn(this, 'TransformersJobDefinition', props.transformersJobDefinitionArn),
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      resultPath: '$.embeddingsResult',
    });

    const verifyEmbeddingsTask = new stepfunctionstasks.LambdaInvoke(this, 'VerifyEmbeddings', {
      lambdaFunction: dataVerificationFunction,
      payload: stepfunctions.TaskInput.fromObject({
        type: 'embeddings'
      }),
      resultPath: '$.embeddingsVerification',
    });

    // Basic case clustering task
    const runBasicClusteringTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunBasicClusteringTask', {
      jobName: 'scotustician-basic-clustering-stepfunctions',
      jobQueue: cdk.aws_batch.JobQueue.fromJobQueueArn(this, 'ClusteringJobQueue', props.clusteringJobQueueArn),
      jobDefinition: cdk.aws_batch.JobDefinition.fromJobDefinitionArn(this, 'ClusteringJobDefinition', props.clusteringJobDefinitionArn),
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      parameters: {
        S3_BUCKET: 'scotustician',
        OUTPUT_PREFIX: 'analysis/case-clustering',
        TSNE_PERPLEXITY: '30',
        MIN_CLUSTER_SIZE: '5',
        START_TERM: '1980',
        END_TERM: '2025'
      },
      resultPath: '$.basicClusteringResult',
    });

    // Term-by-term clustering task  
    const runTermByTermClusteringTask = new stepfunctionstasks.BatchSubmitJob(this, 'RunTermByTermClusteringTask', {
      jobName: 'scotustician-term-clustering-stepfunctions',
      jobQueue: cdk.aws_batch.JobQueue.fromJobQueueArn(this, 'ClusteringJobQueue2', props.clusteringJobQueueArn),
      jobDefinition: cdk.aws_batch.JobDefinition.fromJobDefinitionArn(this, 'ClusteringJobDefinition2', props.clusteringJobDefinitionArn),
      integrationPattern: stepfunctions.IntegrationPattern.RUN_JOB,
      parameters: {
        S3_BUCKET: 'scotustician',
        BASE_OUTPUT_PREFIX: 'analysis/case-clustering-by-term',
        TSNE_PERPLEXITY: '30',
        MIN_CLUSTER_SIZE: '5',
        START_TERM: '1980',
        END_TERM: '2025',
        MAX_CONCURRENT_JOBS: '3'
      },
      resultPath: '$.termByTermClusteringResult',
    });

    // Parallel clustering execution
    const parallelClustering = new stepfunctions.Parallel(this, 'ParallelClustering', {
      resultPath: '$.clusteringResults'
    })
      .branch(runBasicClusteringTask)
      .branch(runTermByTermClusteringTask);

    const finalCostReportTask = new stepfunctionstasks.LambdaInvoke(this, 'FinalCostReport', {
      lambdaFunction: costTrackingFunction,
      payload: stepfunctions.TaskInput.fromObject({
        stage: 'complete',
        notify: true
      }),
      resultPath: '$.finalCostReport',
    });

    // Create failure notification task
    const notifyFailureTask = new stepfunctionstasks.LambdaInvoke(this, 'NotifyFailure', {
      lambdaFunction: costTrackingFunction,
      payload: stepfunctions.TaskInput.fromObject({
        stage: 'failed',
        notify: true,
        'error.$': '$.Error'
      }),
    });

    // Define conditional logic for data verification
    const s3DataCheck = new stepfunctions.Choice(this, 'S3DataCheck')
      .when(
        stepfunctions.Condition.booleanEquals('$.s3Verification.Payload.verified', true),
        runEmbeddingsTask
      )
      .otherwise(
        new stepfunctions.Fail(this, 'S3VerificationFailed', {
          cause: 'S3 data verification failed',
          error: 'DATA_VERIFICATION_ERROR'
        })
      );

    const embeddingsDataCheck = new stepfunctions.Choice(this, 'EmbeddingsDataCheck')
      .when(
        stepfunctions.Condition.booleanEquals('$.embeddingsVerification.Payload.verified', true),
        parallelClustering
      )
      .otherwise(
        new stepfunctions.Fail(this, 'EmbeddingsVerificationFailed', {
          cause: 'Embeddings verification failed',
          error: 'DATA_VERIFICATION_ERROR'
        })
      );

    // Define the state machine
    const definition = costBaselineTask
      .next(runIngestTask)
      .next(verifyS3DataTask)
      .next(s3DataCheck
        .afterwards()
        .next(verifyEmbeddingsTask)
        .next(embeddingsDataCheck
          .afterwards()
          .next(finalCostReportTask)
        )
      );

    // Add error handling
    const errorHandler = notifyFailureTask.next(new stepfunctions.Fail(this, 'PipelineFailed'));
    
    definition.addCatch(errorHandler, {
      errors: ['States.ALL'],
      resultPath: '$.error'
    });

    // Create the state machine
    this.stateMachine = new stepfunctions.StateMachine(this, 'ScotusticianPipeline', {
      definition,
      stateMachineType: stepfunctions.StateMachineType.STANDARD,
      timeout: cdk.Duration.hours(6),
      logs: {
        destination: new logs.LogGroup(this, 'StateMachineLogGroup', {
          logGroupName: '/aws/stepfunctions/scotustician-pipeline',
          retention: logs.RetentionDays.ONE_MONTH,
        }),
        level: stepfunctions.LogLevel.ALL,
      },
    });

    // Grant Step Function permissions
    this.stateMachine.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecs:RunTask',
        'ecs:DescribeTasks',
        'ecs:StopTask',
        'batch:SubmitJob',
        'batch:DescribeJobs',
        'batch:TerminateJob',
        'iam:PassRole'
      ],
      resources: ['*'],
    }));

    // Outputs
    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'Step Functions State Machine ARN',
    });

    new cdk.CfnOutput(this, 'NotificationTopicArn', {
      value: this.notificationTopic.topicArn,
      description: 'SNS Topic ARN for pipeline notifications',
    });
  }
}