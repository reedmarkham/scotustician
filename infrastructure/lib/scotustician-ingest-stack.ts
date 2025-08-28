import { Construct } from 'constructs';

import type { IVpc } from 'aws-cdk-lib/aws-ec2';

import { Bucket } from 'aws-cdk-lib/aws-s3';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import { LogGroup, MetricFilter, FilterPattern, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Alarm, ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags } from 'aws-cdk-lib';
import { Cluster, FargateTaskDefinition, ContainerImage, LogDrivers } from 'aws-cdk-lib/aws-ecs';
import { Role, ServicePrincipal, PolicyStatement, PolicyDocument, Effect } from 'aws-cdk-lib/aws-iam';

interface ScotusticianIngestStackProps extends StackProps {
  cluster: Cluster;
  vpc: IVpc;
}

export class ScotusticianIngestStack extends Stack {
  public readonly taskDefinitionArn: string;

  constructor(scope: Construct, id: string, props: ScotusticianIngestStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'ingest');

    // Optimized for c5.large (2 vCPUs, 4GB RAM) - DLT-based ingestion
    const taskCpu = 1024;  // 1 vCPU for DLT pipeline
    const taskMemory = 3072;  // 3GB memory, leaving 1GB for system overhead

  const bucket = Bucket.fromBucketName(this, 'ScotusticianBucket', 'scotustician');

    const image = new DockerImageAsset(this, 'IngestImage', {
      directory: '../services/ingest',
      file: 'Dockerfile',
      buildArgs: {
        BUILD_TIMESTAMP: Date.now().toString()
      },
    });

    const taskDefinition = new FargateTaskDefinition(this, 'IngestTaskDef', {
      cpu: taskCpu,
      memoryLimitMiB: taskMemory,
    });

    bucket.grantReadWrite(taskDefinition.taskRole);

    // Restrict ECS task execution to root user only
    const accountId = this.account;
    taskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      effect: Effect.DENY,
      actions: ['ecs:RunTask', 'ecs:StartTask'],
      resources: ['*'],
      conditions: {
        StringNotEquals: {
          'aws:userid': `${accountId}:root`
        }
      }
    }));

    const currentYear = new Date().getFullYear();
    
    const container = taskDefinition.addContainer('IngestContainer', {
      image: ContainerImage.fromDockerImageAsset(image),
      cpu: taskCpu,
      memoryLimitMiB: taskMemory,
      logging: LogDrivers.awsLogs({ streamPrefix: 'ingest' }),
      environment: {
        S3_BUCKET: bucket.bucketName,
        START_TERM: currentYear.toString(),
        END_TERM: currentYear.toString(),
        DLT_PROJECT_DIR: '/code',
        DLT_PIPELINE_DIR: '/code/.dlt',
        AWS_DEFAULT_REGION: 'us-east-1',
        // c5.large optimizations
        MAX_WORKERS: '2',
        BATCH_SIZE: '5',
        REQUEST_TIMEOUT: '30',
        MAX_RETRIES: '3',
        MEMORY_LIMIT_MB: '3072',
        MODE: 'ingest',
      },
    });

    new CfnOutput(this, 'IngestTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });

    new CfnOutput(this, 'IngestContainerName', {
      value: container.containerName,
    });

    const logGroup = new LogGroup(this, 'IngestLogGroup', {
      logGroupName: '/ecs/ingest',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: RetentionDays.ONE_WEEK,
    });

    const errorFilter = new MetricFilter(this, 'IngestErrorMetricFilter', {
      logGroup,
      metricName: 'IngestErrors',
      metricNamespace: 'Scotustician',
      filterPattern: FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    new Alarm(this, 'IngestErrorAlarm', {
      metric: errorFilter.metric(),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the ingest container.',
    });

    const eventRole = new Role(this, 'IngestScheduleRole', {
      assumedBy: new ServicePrincipal('events.amazonaws.com'),
      inlinePolicies: {
        EcsRunTask: new PolicyDocument({
          statements: [
            new PolicyStatement({
              actions: ['ecs:RunTask'],
              resources: [taskDefinition.taskDefinitionArn],
            }),
            new PolicyStatement({
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

    this.taskDefinitionArn = taskDefinition.taskDefinitionArn;

    new CfnOutput(this, 'IngestTaskArn', {
      value: taskDefinition.taskDefinitionArn,
      description: 'ARN of the ingest task definitions',
    });
  }
}
