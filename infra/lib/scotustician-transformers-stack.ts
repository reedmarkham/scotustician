import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';

export interface ScotusticianTransformersStackProps extends StackProps {
  vpc: ec2.IVpc;
  cluster: ecs.Cluster;
  ingestTaskDefinitionArn?: string;
}

export class ScotusticianTransformersStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianTransformersStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    const useGpu = scope.node.tryGetContext('useGpu') === 'true';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Configure resources - optimized for transformer workloads
    const taskCpu = 2048; // 2 vCPU for CPU-intensive transformers
    const taskMemory = 8192; // 8 GB for model loading and batch processing

    const postgresSecretName = this.node.tryGetContext('postgresSecretName') || 'scotustician-db-credentials';

    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
          directory: '../transformers',
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
          MODEL_NAME: 'nvidia/NV-Embed-v2',
          MODEL_DIMENSION: '4096',
          BATCH_SIZE: '4',
          MAX_WORKERS: '2',
          INCREMENTAL: 'true'
        },
        secrets: {
          POSTGRES_HOST: ecs.Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: ecs.Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: ecs.Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: ecs.Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        command: ['python', 'batch-embed.py'],
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
          MODEL_NAME: 'all-MiniLM-L6-v2',
          MODEL_DIMENSION: '384',
          BATCH_SIZE: '16',
          MAX_WORKERS: '4',
          INCREMENTAL: 'true'
        },
        secrets: {
          POSTGRES_HOST: ecs.Secret.fromSecretsManager(postgresSecret, 'host'),
          POSTGRES_USER: ecs.Secret.fromSecretsManager(postgresSecret, 'username'),
          POSTGRES_PASS: ecs.Secret.fromSecretsManager(postgresSecret, 'password'),
          POSTGRES_DB: ecs.Secret.fromSecretsManager(postgresSecret, 'dbname'),
        },
        command: ['python', 'batch-embed.py'],
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

    if (props.ingestTaskDefinitionArn) {
      const eventRole = new iam.Role(this, 'TransformersEventRole', {
        assumedBy: new iam.ServicePrincipal('events.amazonaws.com'),
        inlinePolicies: {
          EcsRunTask: new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                actions: ['ecs:RunTask'],
                resources: [taskDefinition.taskDefinitionArn],
              }),
              new iam.PolicyStatement({
                actions: ['iam:PassRole'],
                resources: [
                  taskDefinition.taskRole.roleArn,
                  taskDefinition.executionRole!.roleArn,
                ],
              }),
            ],
          }),
        },
      });

      const ingestCompletionRule = new events.Rule(this, 'IngestCompletionRule', {
        eventPattern: {
          source: ['aws.ecs'],
          detailType: ['ECS Task State Change'],
          detail: {
            lastStatus: ['STOPPED'],
            stopCode: ['TaskCompletedNormally'],
            taskDefinitionArn: [props.ingestTaskDefinitionArn],
          },
        },
        description: 'Trigger transformers when ingest task completes successfully',
      });

      const subnetSelection = useGpu 
        ? { subnetType: ec2.SubnetType.PUBLIC }
        : { subnetType: ec2.SubnetType.PUBLIC };

      // assignPublicIp is only supported for FARGATE tasks, not EC2
      const taskTarget: targets.EcsTaskProps = useGpu 
        ? {
            // GPU tasks use EC2, explicitly disable assignPublicIp
            cluster: props.cluster,
            taskDefinition,
            role: eventRole,
            subnetSelection,
            launchType: ecs.LaunchType.EC2,
            assignPublicIp: false,
          }
        : {
            // Non-GPU tasks use Fargate, can use assignPublicIp
            cluster: props.cluster,
            taskDefinition,
            role: eventRole,
            subnetSelection,
            launchType: ecs.LaunchType.FARGATE,
            assignPublicIp: true,
          };

      ingestCompletionRule.addTarget(new targets.EcsTask(taskTarget));

      new CfnOutput(this, 'TransformersCompletionRuleArn', {
        value: ingestCompletionRule.ruleArn,
      });
    }
  }
}