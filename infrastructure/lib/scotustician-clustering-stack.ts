import { Construct } from 'constructs';

import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags, Size } from 'aws-cdk-lib';
import { IVpc, SecurityGroup, Peer, Port, InstanceType, InstanceClass, InstanceSize } from 'aws-cdk-lib/aws-ec2';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Secret as SMSecret } from 'aws-cdk-lib/aws-secretsmanager';
import { 
  Cluster, FargateTaskDefinition, ContainerImage, LogDrivers, Secret 
} from 'aws-cdk-lib/aws-ecs';
import { 
  ManagedEc2EcsComputeEnvironment, JobQueue, EcsJobDefinition, EcsEc2ContainerDefinition 
} from 'aws-cdk-lib/aws-batch';

export interface ScotusticianClusteringStackProps extends StackProps {
  vpc: IVpc;
  cluster: Cluster;
}

export class ScotusticianClusteringStack extends Stack {
  public readonly jobQueueArn: string;
  public readonly jobDefinitionArn: string;

  constructor(scope: Construct, id: string, props: ScotusticianClusteringStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'clustering');

    const postgresSecretName = this.node.tryGetContext('postgresSecretName') || 'scotustician-db-credentials';

    // Reference the PostgreSQL secret from Secrets Manager
  const postgresSecret = SMSecret.fromSecretNameV2(this, 'PostgresSecret', postgresSecretName);

    // Create security group for clustering tasks
    const clusteringSecurityGroup = new SecurityGroup(this, 'ClusteringSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: false,
      description: 'Security group for case clustering tasks accessing RDS',
    });

    // Allow HTTPS outbound for S3/ECR/API access
    clusteringSecurityGroup.addEgressRule(
      Peer.anyIpv4(),
      Port.tcp(443),
      'HTTPS for S3/ECR/API access'
    );

    // Allow PostgreSQL outbound for database access
    clusteringSecurityGroup.addEgressRule(
      Peer.ipv4(props.vpc.vpcCidrBlock),
      Port.tcp(5432),
      'PostgreSQL database access'
    );

    // Case Clustering Docker Image
  const clusteringImage = new DockerImageAsset(this, 'ClusteringImage', {
      directory: '../services/clustering',
      buildArgs: {
        BUILDKIT_INLINE_CACHE: '1',
        BUILD_DATE: new Date().toISOString(),
      },
    });

    // ECS Task Definition for manual runs
    const clusteringTaskDefinition = new FargateTaskDefinition(this, 'ClusteringTaskDef', {
      cpu: 2048, // 2 vCPU for numerical computations
      memoryLimitMiB: 8192, // 8 GB for scikit-learn and large datasets
    });

    const clusteringContainer = clusteringTaskDefinition.addContainer('ClusteringContainer', {
      image: ContainerImage.fromDockerImageAsset(clusteringImage),
      logging: LogDrivers.awsLogs({ streamPrefix: 'clustering' }),
      environment: {
        S3_BUCKET: 'scotustician',
        OUTPUT_PREFIX: 'analysis/clustering',
        TSNE_PERPLEXITY: '30',
        N_CLUSTERS: '8',
        MIN_CLUSTER_SIZE: '5',
        RANDOM_STATE: '42'
      },
      secrets: {
        POSTGRES_HOST: Secret.fromSecretsManager(postgresSecret, 'host'),
        POSTGRES_USER: Secret.fromSecretsManager(postgresSecret, 'username'),
        POSTGRES_PASS: Secret.fromSecretsManager(postgresSecret, 'password'),
        POSTGRES_DB: Secret.fromSecretsManager(postgresSecret, 'dbname'),
      },
    });

    // Grant S3 access for clustering results export
  clusteringTaskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      actions: ['s3:GetObject', 's3:ListBucket', 's3:PutObject'],
      resources: ['arn:aws:s3:::scotustician', 'arn:aws:s3:::scotustician/*'],
    }));

    // Grant access to Secrets Manager
  clusteringTaskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [postgresSecret.secretArn],
    }));

  clusteringTaskDefinition.addToExecutionRolePolicy(new PolicyStatement({
      actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: ['*'],
    }));

    // Create Batch compute environment for spot instances (CPU-only for clustering)
  const clusteringComputeEnvironment = new ManagedEc2EcsComputeEnvironment(this, 'ClusteringComputeEnvironment', {
      vpc: props.vpc,
      spot: true, // Use spot instances for cost optimization
  instanceTypes: [InstanceType.of(InstanceClass.C5, InstanceSize.LARGE)],
      minvCpus: 0, // Scale to zero when idle
      maxvCpus: 4, // Limited capacity for ad-hoc analysis
      computeEnvironmentName: 'scotustician-clustering-spot',
      securityGroups: [clusteringSecurityGroup],
    });

    // Create job queue for clustering analysis
  const clusteringJobQueue = new JobQueue(this, 'ClusteringJobQueue', {
      computeEnvironments: [
        {
          computeEnvironment: clusteringComputeEnvironment,
          order: 1,
        },
      ],
      jobQueueName: 'scotustician-clustering-queue',
      priority: 1,
    });

    // Create Batch job definition for case clustering
    const clusteringJobDefinition = new EcsJobDefinition(this, 'ClusteringJobDefinition', {
      jobDefinitionName: 'scotustician-clustering',
      container: new EcsEc2ContainerDefinition(this, 'ClusteringJobContainer', {
        image: ContainerImage.fromDockerImageAsset(clusteringImage),
        memory: Size.mebibytes(8192),
        cpu: 2048,
        environment: {
          S3_BUCKET: 'scotustician',
          OUTPUT_PREFIX: 'analysis/clustering',
          TSNE_PERPLEXITY: '30',
          N_CLUSTERS: '8',
          MIN_CLUSTER_SIZE: '5',
          RANDOM_STATE: '42'
        },
        secrets: {
          POSTGRES_HOST: Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        jobRole: clusteringTaskDefinition.taskRole,
        logging: LogDrivers.awsLogs({ streamPrefix: 'batch-clustering' }),
      }),
      retryAttempts: 1, // No retries needed for analysis jobs
    });

    // Create log group for clustering tasks
    const clusteringLogGroup = new LogGroup(this, 'ClusteringLogGroup', {
      logGroupName: '/ecs/case-clustering',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: RetentionDays.ONE_WEEK,
    });

    // Outputs for easy access
    new CfnOutput(this, 'ClusteringTaskDefinitionArn', {
      value: clusteringTaskDefinition.taskDefinitionArn,
      description: 'ARN of the ECS task definition for case clustering',
    });

    // Assign to class properties for orchestration stack
    this.jobQueueArn = clusteringJobQueue.jobQueueArn;
    this.jobDefinitionArn = clusteringJobDefinition.jobDefinitionArn;

    new CfnOutput(this, 'ClusteringContainerName', {
      value: clusteringContainer.containerName,
      description: 'Name of the clustering container for ECS task runs',
    });

    new CfnOutput(this, 'ClusteringJobQueueArn', {
      value: clusteringJobQueue.jobQueueArn,
      description: 'ARN of the Batch job queue for case clustering',
    });

    new CfnOutput(this, 'ClusteringJobDefinitionArn', {
      value: clusteringJobDefinition.jobDefinitionArn,
      description: 'ARN of the Batch job definition for case clustering',
    });

    new CfnOutput(this, 'ClusteringSecurityGroupId', {
      value: clusteringSecurityGroup.securityGroupId,
      description: 'Security group ID for clustering tasks',
    });

    new CfnOutput(this, 'ClusteringImageUri', {
      value: clusteringImage.imageUri,
      description: 'Docker image URI for case clustering',
    });
  }
}