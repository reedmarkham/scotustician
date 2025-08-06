import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface ScotusticianIngestStackProps extends StackProps {
  cluster: ecs.Cluster;
  vpc: ec2.IVpc;
}

export class ScotusticianIngestStack extends Stack {
  public readonly taskDefinitionArn: string;

  constructor(scope: Construct, id: string, props: ScotusticianIngestStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'ingest');

    // Reduced for rate-limited ingestion
    const taskCpu = 512;
    const taskMemory = 2048;

    const bucket = s3.Bucket.fromBucketName(this, 'ScotusticianBucket', 'scotustician');

    const image = new ecr_assets.DockerImageAsset(this, 'IngestImage', {
      directory: '../ingest',
    });

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'IngestTaskDef', {
      cpu: taskCpu,
      memoryLimitMiB: taskMemory,
    });

    bucket.grantReadWrite(taskDefinition.taskRole);

    const currentYear = new Date().getFullYear();
    
    const container = taskDefinition.addContainer('IngestContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      cpu: taskCpu,
      memoryLimitMiB: taskMemory,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'ingest' }),
      environment: {
        S3_BUCKET: bucket.bucketName,
        RAW_PREFIX: 'raw/',
        START_TERM: '1980',
        END_TERM: currentYear.toString(),
        MAX_WORKERS: '2', // Reduced from 8 to align with lower resources
      },
    });

    new CfnOutput(this, 'IngestTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });

    new CfnOutput(this, 'IngestContainerName', {
      value: container.containerName,
    });

    const logGroup = new logs.LogGroup(this, 'IngestLogGroup', {
      logGroupName: '/ecs/ingest',
      removalPolicy: RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    const errorFilter = new logs.MetricFilter(this, 'IngestErrorMetricFilter', {
      logGroup,
      metricName: 'IngestErrors',
      metricNamespace: 'Scotustician',
      filterPattern: logs.FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    new cloudwatch.Alarm(this, 'IngestErrorAlarm', {
      metric: errorFilter.metric(),
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the ingest container.',
    });

    const eventRole = new iam.Role(this, 'IngestScheduleRole', {
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

    const scheduleRule = new events.Rule(this, 'IngestScheduleRule', {
      schedule: events.Schedule.cron({
        minute: '00',
        hour: '14',
        weekDay: 'MON,THU',
      }),
      description: 'Schedule ingest task to run at 10 AM ET (14:00 UTC) on Mondays and Thursdays',
    });

    scheduleRule.addTarget(new targets.EcsTask({
      cluster: props.cluster,
      taskDefinition,
      role: eventRole,
      subnetSelection: { subnetType: ec2.SubnetType.PUBLIC },
      launchType: ecs.LaunchType.FARGATE,
      assignPublicIp: true,
    }));

    new CfnOutput(this, 'IngestScheduleRuleArn', {
      value: scheduleRule.ruleArn,
    });

    this.taskDefinitionArn = taskDefinition.taskDefinitionArn;

    new CfnOutput(this, 'IngestTaskArn', {
      value: taskDefinition.taskDefinitionArn,
      description: 'ARN of the ingest task definitions',
    });
  }
}
