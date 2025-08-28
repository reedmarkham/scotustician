import { Construct } from 'constructs';
import * as path from 'path';

import { Stack, StackProps, DefaultStackSynthesizer, CfnOutput, RemovalPolicy, Tags, Duration } from 'aws-cdk-lib';
import { AutoScalingGroup, SpotAllocationStrategy } from 'aws-cdk-lib/aws-autoscaling';
import { DockerImageAsset } from 'aws-cdk-lib/aws-ecr-assets';
import { Role, ServicePrincipal, ManagedPolicy, InstanceProfile, PolicyStatement, Effect } from 'aws-cdk-lib/aws-iam';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { ApplicationLoadBalancer, ApplicationTargetGroup, ApplicationProtocol, TargetType } from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import { ScalableTarget, ServiceNamespace, AdjustmentType } from 'aws-cdk-lib/aws-applicationautoscaling';
import { 
  Cluster, FargateService, Ec2Service, AsgCapacityProvider, EcsOptimizedImage, Protocol, Ec2TaskDefinition, NetworkMode, ContainerImage, LogDrivers 
} from 'aws-cdk-lib/aws-ecs';
import { 
  IVpc, SecurityGroup, Peer, Port, LaunchTemplate, InstanceType, InstanceClass, InstanceSize, SubnetType, UserData 
} from 'aws-cdk-lib/aws-ec2';

export interface ScotusticianVisualizationStackProps extends StackProps {
  vpc: IVpc;
}

export class ScotusticianVisualizationStack extends Stack {
  public readonly loadBalancerDnsName: string;
  public readonly ecsService: Ec2Service;

  constructor(scope: Construct, id: string, props: ScotusticianVisualizationStackProps) {
    const qualifier = scope.node.tryGetContext('@aws-cdk:bootstrap-qualifier') || 'sctstcn';

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
    const albSecurityGroup = new SecurityGroup(this, 'VisualizationAlbSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ALB',
    });

    albSecurityGroup.addIngressRule(
      Peer.anyIpv4(),
      Port.tcp(80),
      'HTTP access from internet'
    );

    albSecurityGroup.addIngressRule(
      Peer.anyIpv4(),
      Port.tcp(443),
      'HTTPS access from internet'
    );

    // Create security group for ECS service
    const ecsSecurityGroup = new SecurityGroup(this, 'VisualizationEcsSecurityGroup', {
      vpc: props.vpc,
      allowAllOutbound: true,
      description: 'Security group for visualization ECS service',
    });

    ecsSecurityGroup.addIngressRule(
      albSecurityGroup,
      Port.tcp(containerPort),
      'Access from ALB'
    );

    // Create ECS cluster for visualization
    const cluster = new Cluster(this, 'VisualizationCluster', {
      vpc: props.vpc,
      clusterName: 'scotustician-visualization',
      containerInsights: true,
    });

    // Create instance role for ECS instances
    const ecsInstanceRole = new Role(this, 'VisualizationEcsInstanceRole', {
      assumedBy: new ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonEC2ContainerServiceforEC2Role'),
      ],
    });

    // Create instance profile for the role
    const instanceProfile = new InstanceProfile(this, 'VisualizationInstanceProfile', {
      role: ecsInstanceRole,
    });

    // Create Launch Template for use with Mixed Instances Policy
    // Note: spotOptions removed because they conflict with mixedInstancesPolicy
    const launchTemplate = new LaunchTemplate(this, 'VisualizationLaunchTemplate', {
      instanceType: InstanceType.of(InstanceClass.T3, InstanceSize.SMALL),
      machineImage: EcsOptimizedImage.amazonLinux2(),
      securityGroup: ecsSecurityGroup,
      userData: UserData.forLinux(),
      role: ecsInstanceRole,
    });

    // Add comprehensive ECS cluster configuration to user data
    launchTemplate.userData?.addCommands(
      `echo ECS_CLUSTER=${cluster.clusterName} >> /etc/ecs/ecs.config`,
      'echo ECS_ENABLE_CONTAINER_METADATA=true >> /etc/ecs/ecs.config',
      'systemctl enable ecs --now'
    );

    // Add EC2 capacity provider with spot instances using Mixed Instances Policy
    const asg = new AutoScalingGroup(this, 'VisualizationSpotASG', {
      vpc: props.vpc,
      mixedInstancesPolicy: {
        launchTemplate: launchTemplate,
        instancesDistribution: {
          onDemandPercentageAboveBaseCapacity: 0, // 100% spot instances
          spotAllocationStrategy: SpotAllocationStrategy.LOWEST_PRICE,
          spotMaxPrice: '0.005', // Maximum spot price per hour
        },
        launchTemplateOverrides: [
          { instanceType: InstanceType.of(InstanceClass.T3, InstanceSize.SMALL) },
          { instanceType: InstanceType.of(InstanceClass.T3, InstanceSize.MICRO) },
          { instanceType: InstanceType.of(InstanceClass.T3A, InstanceSize.SMALL) },
          { instanceType: InstanceType.of(InstanceClass.T3A, InstanceSize.MICRO) },
        ],
      },
      minCapacity: 0,
      maxCapacity: 2,
      desiredCapacity: 1,
      vpcSubnets: {
        subnetType: SubnetType.PUBLIC,
        availabilityZones: ['us-east-1a', 'us-east-1c', 'us-east-1d', 'us-east-1f'], // Exclude us-east-1b
      },
      autoScalingGroupName: 'scotustician-visualization-spot-asg',
    });

    const capacityProvider = new AsgCapacityProvider(this, 'SpotCapacityProvider', {
      autoScalingGroup: asg,
      enableManagedScaling: true,
      enableManagedTerminationProtection: false,
      canContainersAccessInstanceRole: true,
    });
    cluster.addAsgCapacityProvider(capacityProvider);

    // Create task execution role
    const taskExecutionRole = new Role(this, 'VisualizationTaskExecutionRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Create task role with S3 permissions
    const taskRole = new Role(this, 'VisualizationTaskRole', {
      assumedBy: new ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Add S3 read permissions for clustering results
    taskRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
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
    const logGroup = new LogGroup(this, 'VisualizationLogGroup', {
      logGroupName: '/ecs/scotustician-visualization',
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Build Docker image from the visualization service
    const image = new DockerImageAsset(this, 'VisualizationImage', {
      directory: path.join(__dirname, '../../services/visualization'),
    });

    // Create EC2 task definition for spot instances
    const taskDefinition = new Ec2TaskDefinition(this, 'VisualizationTaskDefinition', {
      networkMode: NetworkMode.BRIDGE,
      executionRole: taskExecutionRole,
      taskRole: taskRole,
    });

    // Add container to task definition
    const container = taskDefinition.addContainer('visualization', {
      image: ContainerImage.fromDockerImageAsset(image),
      memoryLimitMiB: memoryLimitMiB,
      cpu: cpu,
      logging: LogDrivers.awsLogs({
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
          protocol: Protocol.TCP,
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
    const loadBalancer = new ApplicationLoadBalancer(this, 'VisualizationLoadBalancer', {
      vpc: props.vpc,
      internetFacing: true,
      vpcSubnets: {
        subnetType: SubnetType.PUBLIC,
      },
      securityGroup: albSecurityGroup,
    });

    // Create target group
    const targetGroup = new ApplicationTargetGroup(this, 'VisualizationTargetGroup', {
      vpc: props.vpc,
      port: containerPort,
      protocol: ApplicationProtocol.HTTP,
      targetType: TargetType.INSTANCE,
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
    const listener = loadBalancer.addListener('VisualizationListener', {
      port: 80,
      protocol: ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    // Create EC2 service on spot instances
    this.ecsService = new Ec2Service(this, 'VisualizationService', {
      cluster: cluster,
      taskDefinition: taskDefinition,
      desiredCount: 1, // Keep at least one instance running
      capacityProviderStrategies: [
        {
          capacityProvider: capacityProvider.capacityProviderName,
          weight: 1,
        },
      ],
    });

    // Attach service to target group
    this.ecsService.attachToApplicationTargetGroup(targetGroup);

    // Configure Application Auto Scaling for ECS service
    const scalableTarget = new ScalableTarget(this, 'VisualizationScalableTarget', {
      serviceNamespace: ServiceNamespace.ECS,
      scalableDimension: 'ecs:service:DesiredCount',
      resourceId: `service/${cluster.clusterName}/${this.ecsService.serviceName}`,
      minCapacity: 1, // Always keep at least one instance running
      maxCapacity: 3,
    });

    // Add scaling policy that responds to ALB traffic - more conservative scaling
    scalableTarget.scaleOnMetric('VisualizationRequestScaling', {
      metric: targetGroup.metricRequestCount({
        statistic: 'Sum',
      }),
      scalingSteps: [
        { upper: 10, change: 0 },   // No change for low traffic
        { lower: 50, change: +1 },  // Scale up for higher traffic
      ],
      adjustmentType: AdjustmentType.CHANGE_IN_CAPACITY,
      cooldown: Duration.seconds(300), // 5 minute cooldown for stability
      evaluationPeriods: 2, // More stable evaluation
    });

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