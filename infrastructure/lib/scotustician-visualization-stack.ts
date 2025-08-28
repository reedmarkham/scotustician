import { Construct } from 'constructs';
import * as path from 'path';

import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags, Duration } from 'aws-cdk-lib';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import { Role, ServicePrincipal, ManagedPolicy, PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays, MetricFilter, FilterPattern } from 'aws-cdk-lib/aws-logs';
import { Alarm, ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import { SnsAction } from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { ApplicationLoadBalancer, ApplicationTargetGroup, ApplicationProtocol, TargetType } from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import { 
  Cluster, FargateService, FargateTaskDefinition, ContainerImage, LogDrivers, ContainerInsights 
} from 'aws-cdk-lib/aws-ecs';
import { 
  IVpc, SecurityGroup, Peer, Port, SubnetType 
} from 'aws-cdk-lib/aws-ec2';

export interface ScotusticianVisualizationStackProps extends StackProps {
  vpc: IVpc;
}

export class ScotusticianVisualizationStack extends Stack {
  public readonly loadBalancerDnsName: string;
  public readonly ecsService: FargateService;

  constructor(scope: Construct, id: string, props: ScotusticianVisualizationStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'visualization');

    const s3BucketName = this.node.tryGetContext('s3BucketName') || 'scotustician';
    const containerPort = 8501;

    // Create enhanced CloudWatch log groups
    const containerLogGroup = new LogGroup(this, 'VisualizationContainerLogGroup', {
      logGroupName: '/ecs/scotustician-visualization',
      retention: RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const ecsLogGroup = new LogGroup(this, 'VisualizationEcsLogGroup', {
      logGroupName: '/aws/ecs/scotustician-visualization-cluster',
      retention: RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // SNS topic for alerts
    const alertTopic = new Topic(this, 'VisualizationAlerts', {
      topicName: 'scotustician-visualization-alerts',
      displayName: 'Visualization Infrastructure Alerts',
    });

    // Security groups
    const albSecurityGroup = new SecurityGroup(this, 'VisualizationAlbSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ALB',
    });

    albSecurityGroup.addIngressRule(Peer.anyIpv4(), Port.tcp(80), 'HTTP access from internet');
    albSecurityGroup.addIngressRule(Peer.anyIpv4(), Port.tcp(443), 'HTTPS access from internet');

    const ecsSecurityGroup = new SecurityGroup(this, 'VisualizationEcsSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ECS service',
    });

    ecsSecurityGroup.addIngressRule(albSecurityGroup, Port.tcp(containerPort), 'Access from ALB');

    // Create Fargate cluster for simplicity and faster deployment
    const cluster = new Cluster(this, 'VisualizationCluster', {
      vpc: props.vpc,
      clusterName: 'scotustician-visualization',
      containerInsightsV2: ContainerInsights.ENABLED,
    });

    // Task execution and task roles
    const taskExecutionRole = new Role(this, 'VisualizationTaskExecutionRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    const taskRole = new Role(this, 'VisualizationTaskRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Add S3 read permissions
    taskRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['s3:GetObject', 's3:ListBucket'],
      resources: [`arn:aws:s3:::${s3BucketName}`, `arn:aws:s3:::${s3BucketName}/*`],
    }));

    // Add CloudWatch permissions for custom metrics
    taskRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['cloudwatch:PutMetricData'],
      resources: ['*'],
    }));

    // Build Docker image
    const image = new DockerImageAsset(this, 'VisualizationImage', {
      directory: path.join(__dirname, '../../services/visualization'),
    });

    // Create Fargate task definition for on-demand t3.micro equivalent
    const taskDefinition = new FargateTaskDefinition(this, 'VisualizationTaskDefinition', {
      cpu: 256, // 0.25 vCPU (t3.micro equivalent)
      memoryLimitMiB: 512, // 0.5 GB
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    // Add container
    const container = taskDefinition.addContainer('visualization', {
      image: ContainerImage.fromDockerImageAsset(image),
      logging: LogDrivers.awsLogs({
        streamPrefix: 'visualization-app',
        logGroup: containerLogGroup,
        datetimeFormat: '%Y-%m-%d %H:%M:%S',
      }),
      environment: {
        AWS_DEFAULT_REGION: this.region,
        S3_BUCKET: s3BucketName,
      },
      portMappings: [{
        containerPort: containerPort,
        protocol: 'tcp' as any,
      }],
      healthCheck: {
        command: ['CMD-SHELL', 'curl -f http://localhost:8501/_stcore/health || exit 1'],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(60),
      },
    });

    // Create Application Load Balancer
    const loadBalancer = new ApplicationLoadBalancer(this, 'VisualizationLoadBalancer', {
      vpc: props.vpc,
      internetFacing: true,
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      securityGroup: albSecurityGroup,
    });

    // Create target group
    const targetGroup = new ApplicationTargetGroup(this, 'VisualizationTargetGroup', {
      vpc: props.vpc,
      port: containerPort,
      protocol: ApplicationProtocol.HTTP,
      targetType: TargetType.IP, // Fargate uses IP targets
      healthCheck: {
        path: '/_stcore/health',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
    });

    // Create listener
    loadBalancer.addListener('VisualizationListener', {
      port: 80,
      protocol: ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    // Create always-on Fargate service with single task (t3.micro equivalent)
    this.ecsService = new FargateService(this, 'VisualizationService', {
      cluster: cluster,
      taskDefinition: taskDefinition,
      desiredCount: 1, // Always maintain 1 instance
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      securityGroups: [ecsSecurityGroup],
      assignPublicIp: true, // Required for Fargate in public subnets
    });

    // Attach service to target group
    this.ecsService.attachToApplicationTargetGroup(targetGroup);

    this.loadBalancerDnsName = loadBalancer.loadBalancerDnsName;

    // Enhanced monitoring
    const errorMetricFilter = new MetricFilter(this, 'ErrorMetricFilter', {
      logGroup: containerLogGroup,
      metricNamespace: 'Scotustician/Visualization',
      metricName: 'ApplicationErrors',
      filterPattern: FilterPattern.anyTerm('ERROR', 'Exception', 'Failed'),
      metricValue: '1',
    });

    // Task startup metric filter for future monitoring
    new MetricFilter(this, 'TaskStartupMetricFilter', {
      logGroup: ecsLogGroup,
      metricNamespace: 'Scotustician/Visualization',
      metricName: 'TaskStartups',
      filterPattern: FilterPattern.literal('[timestamp, requestId, level="INFO", message="Task started", ...]'),
      metricValue: '1',
    });

    // Alarms
    const highErrorRateAlarm = new Alarm(this, 'HighErrorRateAlarm', {
      metric: errorMetricFilter.metric({
        statistic: 'Sum',
        period: Duration.minutes(5),
      }),
      threshold: 10,
      evaluationPeriods: 2,
      comparisonOperator: ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.NOT_BREACHING,
      alarmDescription: 'High error rate in visualization application',
    });

    const serviceDownAlarm = new Alarm(this, 'ServiceDownAlarm', {
      metric: targetGroup.metrics.healthyHostCount({
        statistic: 'Average',
        period: Duration.minutes(5),
      }),
      threshold: 1,
      evaluationPeriods: 2,
      comparisonOperator: ComparisonOperator.LESS_THAN_THRESHOLD,
      treatMissingData: TreatMissingData.BREACHING,
      alarmDescription: 'Visualization service has no healthy targets',
    });

    // Add SNS actions
    const snsAction = new SnsAction(alertTopic);
    highErrorRateAlarm.addAlarmAction(snsAction);
    serviceDownAlarm.addAlarmAction(snsAction);

    // Outputs
    new CfnOutput(this, 'VisualizationUrl', {
      value: `http://${loadBalancer.loadBalancerDnsName}`,
      description: 'URL for the visualization application',
    });

    new CfnOutput(this, 'VisualizationClusterName', {
      value: cluster.clusterName,
      description: 'Name of the visualization ECS cluster',
    });

    new CfnOutput(this, 'VisualizationServiceName', {
      value: this.ecsService.serviceName,
      description: 'Name of the visualization ECS service',
    });

    new CfnOutput(this, 'LoadBalancerDnsName', {
      value: loadBalancer.loadBalancerDnsName,
      description: 'DNS name of the load balancer',
    });

    new CfnOutput(this, 'ContainerLogGroup', {
      value: containerLogGroup.logGroupName,
      description: 'CloudWatch log group for application containers',
    });

    new CfnOutput(this, 'EcsLogGroup', {
      value: ecsLogGroup.logGroupName,
      description: 'CloudWatch log group for ECS cluster logs',
    });

    new CfnOutput(this, 'AlertTopicArn', {
      value: alertTopic.topicArn,
      description: 'SNS topic for visualization infrastructure alerts',
    });

    new CfnOutput(this, 'ServiceInfo', {
      value: 'Always-on single Fargate task (t3.micro equivalent: 0.25 vCPU, 0.5 GB RAM)',
      description: 'Service configuration',
    });

    new CfnOutput(this, 'CostOptimization', {
      value: 'Fargate on-demand pricing: ~$0.01/hour for continuous availability',
      description: 'Cost information',
    });
  }
}