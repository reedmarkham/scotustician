import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags, Duration, Size } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as batch from 'aws-cdk-lib/aws-batch';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sqs from 'aws-cdk-lib/aws-sqs';

export interface ScotusticianTransformersStackProps extends StackProps {
  vpc: ec2.IVpc;
  cluster: ecs.Cluster;
  ingestTaskDefinitionArn?: string;
}

export class ScotusticianTransformersStack extends Stack {
  public readonly jobQueueArn: string;
  public readonly jobDefinitionArn: string;

  constructor(scope: Construct, id: string, props: ScotusticianTransformersStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    const useGpu = scope.node.tryGetContext('useGpu') === 'true';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'transformers');

    // Create SQS queue for job tracking and failure handling
    const processingQueue = new sqs.Queue(this, 'EmbeddingProcessingQueue', {
      queueName: 'scotustician-embedding-processing',
      visibilityTimeout: props.vpc ? Duration.minutes(30) : Duration.minutes(15), // Longer timeout for GPU processing
      retentionPeriod: Duration.days(7),
      deadLetterQueue: {
        queue: new sqs.Queue(this, 'EmbeddingProcessingDLQ', {
          queueName: 'scotustician-embedding-processing-dlq',
          retentionPeriod: Duration.days(14),
        }),
        maxReceiveCount: 3, // Retry limit as requested
      },
    });

    // Create checkpoint table for progress tracking
    const checkpointQueue = new sqs.Queue(this, 'EmbeddingCheckpointQueue', {
      queueName: 'scotustician-embedding-checkpoints',
      retentionPeriod: Duration.days(3),
    });

    // Configure resources - optimized for transformer workloads
    const taskCpu = 2048; // 2 vCPU for CPU-intensive transformers
    const taskMemory = 8192; // 8 GB for model loading and batch processing

    const postgresSecretName = this.node.tryGetContext('postgresSecretName') || 'scotustician-db-credentials';

    // Create security group for Batch tasks
    const batchSecurityGroup = new ec2.SecurityGroup(this, 'BatchSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: false,
      description: 'Security group for Batch tasks accessing RDS',
    });

    // Allow HTTPS outbound for S3/ECR/API access
    batchSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS for S3/ECR/API access'
    );

    // Allow PostgreSQL outbound for database access
    batchSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'PostgreSQL database access'
    );

    // Create Batch compute environment for spot instances (GPU or CPU based on context)
    const spotComputeEnvironment = new batch.ManagedEc2EcsComputeEnvironment(this, 'SpotComputeEnvironment', {
      vpc: props.vpc,
      spot: true,
      instanceTypes: useGpu 
        ? [ec2.InstanceType.of(ec2.InstanceClass.G4DN, ec2.InstanceSize.XLARGE)]
        : [ec2.InstanceType.of(ec2.InstanceClass.C5, ec2.InstanceSize.XLARGE2)],
      minvCpus: 0,
      maxvCpus: useGpu ? 4 : 8, // Scale to zero when no jobs, max capacity for workloads
      computeEnvironmentName: useGpu ? 'scotustician-spot-gpu' : 'scotustician-spot-cpu',
      securityGroups: [batchSecurityGroup],
    });

    // Create job queue for embedding processing
    const jobQueue = new batch.JobQueue(this, 'EmbeddingJobQueue', {
      computeEnvironments: [
        {
          computeEnvironment: spotComputeEnvironment,
          order: 1,
        },
      ],
      jobQueueName: useGpu ? 'scotustician-embedding-gpu-queue' : 'scotustician-embedding-cpu-queue',
      priority: 1,
    });

    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
          directory: '../services/transformers',
          buildArgs: {
            BUILDKIT_INLINE_CACHE: '1',
            BUILD_DATE: new Date().toISOString(),
          },
        });

    // Create security group for Fargate tasks
    const fargateSecurityGroup = new ec2.SecurityGroup(this, 'FargateSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: false,
      description: 'Security group for Fargate tasks accessing RDS',
    });

    // Allow HTTPS outbound for S3/ECR/API access
    fargateSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS for S3/ECR/API access'
    );

    // Allow PostgreSQL outbound for database access
    fargateSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(props.vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'PostgreSQL database access'
    );

    // Reference the PostgreSQL secret from Secrets Manager
    const postgresSecret = secretsmanager.Secret.fromSecretNameV2(this, 'PostgresSecret', postgresSecretName);

    let taskDefinition: ecs.TaskDefinition;
    let container: ecs.ContainerDefinition;

    // Received from CI/CD: based on AWS GPU quota decide whether to use GPU or CPU downstream
    if (useGpu) {
      // GPU tasks need more memory but same CPU
      const gpuTaskMemory = 6144; // Keep higher for GPU workloads
      
      taskDefinition = new ecs.Ec2TaskDefinition(this, 'TransformersGpuTaskDef', {
        networkMode: ecs.NetworkMode.AWS_VPC,
      });

      container = taskDefinition.addContainer('TransformersGpuContainer', {
        image: ecs.ContainerImage.fromDockerImageAsset(image),
        memoryLimitMiB: gpuTaskMemory,
        cpu: taskCpu,
        gpuCount: 1,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
        environment: {
          S3_BUCKET: 'scotustician',
          RAW_PREFIX: 'raw/oa',
          MODEL_NAME: 'baai/bge-m3',
          MODEL_DIMENSION: '1024',
          BATCH_SIZE: '4',
          MAX_WORKERS: '2',
          INCREMENTAL: 'true',
          PROCESSING_QUEUE_URL: processingQueue.queueUrl,
          CHECKPOINT_QUEUE_URL: checkpointQueue.queueUrl,
          CHECKPOINT_FREQUENCY: '5', // Save checkpoint every 5 files
          BATCH_MODE: 'true'
        },
        secrets: {
          POSTGRES_HOST: ecs.Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: ecs.Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: ecs.Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: ecs.Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        command: ['python', 'main.py'],
      });
    } else {
      const fargateTask = new ecs.FargateTaskDefinition(this, 'TransformersCpuTaskDef', {
        cpu: taskCpu,
        memoryLimitMiB: taskMemory,
      });
      taskDefinition = fargateTask;

      container = fargateTask.addContainer('TransformersCpuContainer', {
        image: ecs.ContainerImage.fromDockerImageAsset(image),
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
        environment: {
          S3_BUCKET: 'scotustician',
          RAW_PREFIX: 'raw/oa',
          MODEL_NAME: 'baai/bge-m3',
          MODEL_DIMENSION: '1024',
          BATCH_SIZE: '16',
          MAX_WORKERS: '4',
          INCREMENTAL: 'true',
          PROCESSING_QUEUE_URL: processingQueue.queueUrl,
          CHECKPOINT_QUEUE_URL: checkpointQueue.queueUrl,
          CHECKPOINT_FREQUENCY: '5', // Save checkpoint every 5 files
          BATCH_MODE: 'true'
        },
        secrets: {
          POSTGRES_HOST: ecs.Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: ecs.Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: ecs.Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: ecs.Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        command: ['python', 'main.py'],
      });
    }

    container.addUlimits({
      name: ecs.UlimitName.NOFILE,
      softLimit: 65536,
      hardLimit: 65536,
    });

    // Grant access to Secrets Manager for PostgreSQL credentials
    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [postgresSecret.secretArn],
    }));

    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:ListBucket', 's3:PutObject'],
      resources: ['arn:aws:s3:::scotustician', 'arn:aws:s3:::scotustician/*'],
    }));

    // Grant SQS permissions for job tracking and checkpointing
    processingQueue.grantConsumeMessages(taskDefinition.taskRole);
    processingQueue.grantSendMessages(taskDefinition.taskRole);
    checkpointQueue.grantSendMessages(taskDefinition.taskRole);

    // Restrict ECS task execution to root user only
    const accountId = this.account;
    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      effect: iam.Effect.DENY,
      actions: ['ecs:RunTask', 'ecs:StartTask'],
      resources: ['*'],
      conditions: {
        StringNotEquals: {
          'aws:userid': `${accountId}:root`
        }
      }
    }));

    taskDefinition.addToExecutionRolePolicy(new iam.PolicyStatement({
      actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: ['*'],
    }));

    new CfnOutput(this, useGpu ? 'TransformersGpuTaskDefinitionArn' : 'TransformersCpuTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });

    new CfnOutput(this, useGpu ? 'TransformersGpuContainerName' : 'TransformersCpuContainerName', {
      value: container.containerName,
    });

    // Output the security group ID for RDS configuration
    new CfnOutput(this, 'FargateSecurityGroupId', {
      value: fargateSecurityGroup.securityGroupId,
      description: 'Security group ID for Fargate tasks - allow this in RDS security group',
    });

    // Create Batch job definition for processing (GPU or CPU based on context)
    const batchJobDefinition = new batch.EcsJobDefinition(this, 'EmbeddingJobDefinition', {
      jobDefinitionName: useGpu ? 'scotustician-embedding-gpu' : 'scotustician-embedding-cpu',
      container: new batch.EcsEc2ContainerDefinition(this, 'EmbeddingJobContainer', {
        image: ecs.ContainerImage.fromDockerImageAsset(image),
        memory: useGpu ? Size.mebibytes(6144) : Size.mebibytes(8192),
        cpu: 2048,
        gpu: useGpu ? 1 : 0,
        environment: {
          S3_BUCKET: 'scotustician',
          RAW_PREFIX: 'raw/oa',
          MODEL_NAME: 'baai/bge-m3',
          MODEL_DIMENSION: '1024',
          BATCH_SIZE: useGpu ? '4' : '16',
          MAX_WORKERS: useGpu ? '1' : '4',
          INCREMENTAL: 'true',
          PROCESSING_QUEUE_URL: processingQueue.queueUrl,
          CHECKPOINT_QUEUE_URL: checkpointQueue.queueUrl,
          CHECKPOINT_FREQUENCY: '5',
          BATCH_MODE: 'true'
        },
        secrets: {
          POSTGRES_HOST: ecs.Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: ecs.Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: ecs.Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: ecs.Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        jobRole: taskDefinition.taskRole,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'batch-embedding' }),
      }),
      retryAttempts: 2, // AWS Batch retry limit as requested
    });

    // Assign to class properties for orchestration stack
    this.jobQueueArn = jobQueue.jobQueueArn;
    this.jobDefinitionArn = batchJobDefinition.jobDefinitionArn;

    // Output Batch resources
    new CfnOutput(this, 'BatchJobQueueArn', {
      value: jobQueue.jobQueueArn,
      description: 'ARN of the Batch job queue for embedding processing',
    });

    new CfnOutput(this, 'BatchJobDefinitionArn', {
      value: batchJobDefinition.jobDefinitionArn,
      description: 'ARN of the Batch job definition for embedding processing',
    });

    new CfnOutput(this, 'ProcessingQueueUrl', {
      value: processingQueue.queueUrl,
      description: 'URL of the SQS queue for processing job tracking',
    });

    new CfnOutput(this, 'CheckpointQueueUrl', {
      value: checkpointQueue.queueUrl,
      description: 'URL of the SQS queue for checkpoint tracking',
    });

    const logGroup = new logs.LogGroup(this, 'TransformersLogGroup', {
      logGroupName: '/ecs/transformers',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    const errorFilter = new logs.MetricFilter(this, 'ErrorMetricFilter', {
      logGroup,
      metricName: 'TransformerErrors',
      metricNamespace: 'Scotustician',
      filterPattern: logs.FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    new cloudwatch.Alarm(this, 'TransformerErrorAlarm', {
      metric: errorFilter.metric(),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the transformers container.',
    });

  }
}