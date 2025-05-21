import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import { Construct } from 'constructs';

export class ScotusticianSharedStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });

    // --- VPC + Cluster ---
    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
    });

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });

    // --- IAM Role ---
    const instanceRole = new iam.Role(this, 'GpuInstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonEC2ContainerServiceforEC2Role'),
      ],
    });

    // --- Security Group ---
    const instanceSG = new ec2.SecurityGroup(this, 'GpuInstanceSG', {
      vpc: this.vpc,
      allowAllOutbound: true,
      description: 'ECS GPU instance SG',
    });

    // --- GPU EC2 Instance ---
    const instance = new ec2.Instance(this, 'GpuInstance', {
      vpc: this.vpc,
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.G4DN, ec2.InstanceSize.MICRO),
      machineImage: ecs.EcsOptimizedImage.amazonLinux2(),
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      role: instanceRole,
      securityGroup: instanceSG,
    });

    instance.userData.addCommands(
      `echo "ECS_CLUSTER=${this.cluster.clusterName}" >> /etc/ecs/ecs.config`,
      'echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config',
      'systemctl enable --now ecs'
    );

    const stopInstancesFn = new lambda.Function(this, 'StopTaggedInstancesFn', {
      runtime: lambda.Runtime.NODEJS_18_X,
      handler: 'index.handler',
      code: lambda.Code.fromInline(`
        const AWS = require('aws-sdk');
        const ec2 = new AWS.EC2();

        exports.handler = async () => {
          const instances = await ec2.describeInstances({
            Filters: [
              { Name: 'tag:AutoStop', Values: ['true'] },
              { Name: 'instance-state-name', Values: ['running'] },
            ],
          }).promise();

          const instanceIds = instances.Reservations.flatMap(r => r.Instances.map(i => i.InstanceId));
          if (instanceIds.length > 0) {
            console.log('Stopping instances:', instanceIds);
            await ec2.stopInstances({ InstanceIds: instanceIds }).promise();
          } else {
            console.log('No instances to stop.');
          }
        };
      `),
      timeout: cdk.Duration.seconds(60),
      initialPolicy: [
        new iam.PolicyStatement({
          actions: ['ec2:DescribeInstances', 'ec2:StopInstances'],
          resources: ['*'],
        }),
      ],
    });

    new events.Rule(this, 'StopInstancesNightlyRule', {
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '23', // UTC 23 == 7 PM ET (UTC-4)
        weekDay: '*',
        month: '*',
        year: '*',
      }),
      targets: [new targets.LambdaFunction(stopInstancesFn)],
    });

    // --- CDK Outputs ---
    new cdk.CfnOutput(this, 'GpuInstanceId', {
      value: instance.instanceId,
    });

    new cdk.CfnOutput(this, 'ClusterName', {
      value: this.cluster.clusterName,
    });

    new cdk.CfnOutput(this, 'PublicSubnetId1', {
      value: this.vpc.publicSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'PrivateSubnetId', {
      value: this.vpc.privateSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'SecurityGroupId', {
      value: instanceSG.securityGroupId,
    });
  }
}
