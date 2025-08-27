import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as path from 'path';

export interface ScotusticianVisualizationStackProps extends StackProps {
  vpc: ec2.IVpc;
}

export class ScotusticianVisualizationStack extends Stack {
  public readonly loadBalancerDnsName: string;
  public readonly ecsService: ecs.FargateService;

  constructor(scope: Construct, id: string, props: ScotusticianVisualizationStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    Tags.of(this).add('Project', 'scotustician');
    Tags.of(this).add('Stack', 'visualization');

    const s3BucketName = this.node.tryGetContext('s3BucketName') || 'scotustician';
    const containerPort = 8501; // Streamlit default port
    const cpu = 256; // 0.25 vCPU - minimal for cost savings
    const memoryLimitMiB = 512; // 0.5 GB - minimal for cost savings

    // Create security group for ALB
    const albSecurityGroup = new ec2.SecurityGroup(this, 'VisualizationAlbSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ALB',
    });

    albSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(80),
      'HTTP access from internet'
    );

    albSecurityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS access from internet'
    );

    // Create security group for ECS service
    const ecsSecurityGroup = new ec2.SecurityGroup(this, 'VisualizationEcsSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ECS service',
    });

    ecsSecurityGroup.addIngressRule(
      albSecurityGroup,
      ec2.Port.tcp(containerPort),
      'Access from ALB'
    );

    // Create ECS cluster for visualization
    const cluster = new ecs.Cluster(this, 'VisualizationCluster', {
      vpc: props.vpc,
      clusterName: 'scotustician-visualization',
      containerInsights: true,
    });

    // Create Launch Template for spot instances
    const launchTemplate = new ec2.LaunchTemplate(this, 'VisualizationLaunchTemplate', {
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.SMALL),
      machineImage: ecs.EcsOptimizedImage.amazonLinux2(),
      securityGroup: ecsSecurityGroup,
      userData: ec2.UserData.forLinux(),
      spotOptions: {
        maxPrice: 0.01, // Max spot price per hour
        requestType: ec2.SpotRequestType.ONE_TIME,
      },
    });

    // Add ECS cluster configuration to user data
    launchTemplate.userData?.addCommands(
      `echo ECS_CLUSTER=${cluster.clusterName} >> /etc/ecs/ecs.config`
    );

    // Add EC2 capacity provider with spot instances using Launch Template
    const asg = new autoscaling.AutoScalingGroup(this, 'VisualizationSpotASG', {
      vpc: props.vpc,
      launchTemplate: launchTemplate,
      minCapacity: 0,
      maxCapacity: 2,
      desiredCapacity: 1,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
      autoScalingGroupName: 'scotustician-visualization-spot-asg',
    });

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'SpotCapacityProvider', {
      autoScalingGroup: asg,
    });
    cluster.addAsgCapacityProvider(capacityProvider);

    // Create task execution role
    const taskExecutionRole = new iam.Role(this, 'VisualizationTaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Create task role with S3 permissions
    const taskRole = new iam.Role(this, 'VisualizationTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Add S3 read permissions for clustering results
    taskRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:ListBucket',
      ],
      resources: [
        `arn:aws:s3:::${s3BucketName}`,
        `arn:aws:s3:::${s3BucketName}/*`,
      ],
    }));

    // Create CloudWatch log group
    const logGroup = new logs.LogGroup(this, 'VisualizationLogGroup', {
      logGroupName: '/ecs/scotustician-visualization',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Build Docker image from the visualization service
    const image = new ecr_assets.DockerImageAsset(this, 'VisualizationImage', {
      directory: path.join(__dirname, '../../services/visualization'),
    });

    // Create EC2 task definition for spot instances
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'VisualizationTaskDefinition', {
      networkMode: ecs.NetworkMode.BRIDGE,
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    // Add container to task definition
    const container = taskDefinition.addContainer('visualization', {
      image: ecs.ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: memoryLimitMiB,
      cpu: cpu,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'ecs',
        logGroup: logGroup,
      }),
      environment: {
        AWS_DEFAULT_REGION: this.region,
        S3_BUCKET: s3BucketName,
      },
      portMappings: [
        {
          containerPort: containerPort,
          hostPort: 0, // Dynamic port mapping for EC2
          protocol: ecs.Protocol.TCP,
        },
      ],
      healthCheck: {
        command: ['CMD-SHELL', 'curl -f http://localhost:8501/_stcore/health || exit 1'],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(60),
      },
    });

    // Create Application Load Balancer in public subnets for cost optimization
    const loadBalancer = new elbv2.ApplicationLoadBalancer(this, 'VisualizationLoadBalancer', {
      vpc: props.vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: ec2.SubnetType.PUBLIC,
      },
      securityGroup: albSecurityGroup,
    });

    // Create target group
    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'VisualizationTargetGroup', {
      vpc: props.vpc,
      port: containerPort,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.INSTANCE,
      healthCheck: {
        path: '/',
        healthyHttpCodes: '200',
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
      },
    });

    // Create listener
    const listener = loadBalancer.addListener('VisualizationListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    // Create EC2 service on spot instances
    this.ecsService = new ecs.Ec2Service(this, 'VisualizationService', {
      cluster: cluster,
      taskDefinition: taskDefinition,
      desiredCount: 1, // Single instance for cost savings
    });

    // Attach service to target group
    this.ecsService.attachToApplicationTargetGroup(targetGroup);

    this.loadBalancerDnsName = loadBalancer.loadBalancerDnsName;

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
  }
}