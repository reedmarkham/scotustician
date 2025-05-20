import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, Duration } from 'aws-cdk-lib';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as logs from 'aws-cdk-lib/aws-logs';

export interface ScotusticianTransformersStackProps extends StackProps {
  vpc: ec2.IVpc;
  cluster: ecs.Cluster;
}

export class ScotusticianTransformersStack extends Stack {
  constructor(scope: Construct, id: string, props: ScotusticianTransformersStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    const { vpc, cluster } = props;

    // --- Look up latest ECS-optimized GPU AMI ---
    const ecsGpuAmi = ec2.MachineImage.lookup({
      name: 'amzn2-ami-ecs-gpu*',
      owners: ['amazon'],
    });

    // --- EC2 ASG with GPU Instances ---
    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'GPUFleet', {
      vpc,
      instanceType: new ec2.InstanceType('g4dn.xlarge'),
      machineImage: ecsGpuAmi,
      minCapacity: 1,
    });

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'AsgCapacityProvider', {
      autoScalingGroup,
    });

    cluster.addAsgCapacityProvider(capacityProvider);

    // --- Docker Image Asset (builds ../transformers) ---
    const image = new ecr_assets.DockerImageAsset(this, 'TransformersImage', {
      directory: '../transformers',
    });

    // --- ECS Task Definition (EC2 + GPU) ---
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TransformersTaskDef', {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });

    const container = taskDefinition.addContainer('TransformersContainer', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: 8192,
      cpu: 1024,
      gpuCount: 1,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'transformers' }),
      environment: {
        OPENSEARCH_HOST: process.env.OPENSEARCH_HOST || 'https://scotusticianope-x0u0hjgyswq0.us-east-1.es.amazonaws.com',
        S3_BUCKET: 'scotustician',
        MAX_WORKERS: '4',
      },
      command: ['python', 'batch_embed.py'],
    });

    container.addUlimits({
      name: ecs.UlimitName.NOFILE,
      softLimit: 65536,
      hardLimit: 65536,
    });

    // --- IAM Permissions for S3 + OpenSearch ---
    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['es:ESHttpPost', 'es:ESHttpPut', 'es:ESHttpGet', 'es:ESHttpHead'],
      resources: [`arn:aws:es:us-east-1:${this.account}:domain/scotusticianope-x0u0hjgyswq0/*`],
    }));

    taskDefinition.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:ListBucket', 's3:PutObject'],
      resources: ['arn:aws:s3:::scotustician', 'arn:aws:s3:::scotustician/*'],
    }));

    // --- Outputs ---
    new CfnOutput(this, 'TransformersTaskDefinitionArn', {
      value: taskDefinition.taskDefinitionArn,
    });

    new CfnOutput(this, 'TransformersContainerName', {
      value: container.containerName,
    });

    // --- CloudWatch Alarms / Metrics ---
    const logGroup = new logs.LogGroup(this, 'TransformersLogGroup', {
      logGroupName: `/ecs/transformers`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      retention: logs.RetentionDays.ONE_WEEK,
    });

    const errorFilter = new logs.MetricFilter(this, 'ErrorMetricFilter', {
      logGroup,
      metricName: 'TransformerErrors',
      metricNamespace: 'Scotustician',
      filterPattern: logs.FilterPattern.stringValue('$.level', '=', 'ERROR'),
      metricValue: '1',
    });

    const errorMetric = errorFilter.metric();

    new cloudwatch.Alarm(this, 'TransformerErrorAlarm', {
      metric: errorMetric,
      threshold: 1,
      evaluationPeriods: 1,
      datapointsToAlarm: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Alarm if any ERROR-level logs are detected in the transformers container.',
    });
  }
}