import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
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
    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', { maxAzs: 2 });

    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });

    // --- GPU ECS AMI ---
    const gpuAmi = ec2.MachineImage.lookup({
      name: 'amzn2-ami-ecs-gpu*',
      owners: ['amazon'],
    });

    // --- Launch Template ---
    const lt = new ec2.CfnLaunchTemplate(this, 'GpuLaunchTemplate', {
      launchTemplateName: 'ScotusticianGpuTemplate',
      launchTemplateData: {
        instanceType: 'g4dn.xlarge',
        imageId: gpuAmi.getImage(this).imageId,
      },
    });

    // --- L1 Auto Scaling Group (MixedInstancesPolicy required) ---
    const asg = new autoscaling.CfnAutoScalingGroup(this, 'GPUFleetASG', {
      vpcZoneIdentifier: this.vpc.privateSubnets.map(subnet => subnet.subnetId),
      minSize: '1',
      maxSize: '1',
      mixedInstancesPolicy: {
        launchTemplate: {
          launchTemplateSpecification: {
            launchTemplateId: lt.ref,
            version: lt.attrLatestVersionNumber,
          },
          overrides: [], // optional, but required by AWS schema
        },
      },
    });

    // 🛠 You can't use AsgCapacityProvider directly with L1 constructs
    // Instead, you can optionally output the Launch Template or ASG ID if needed
    new cdk.CfnOutput(this, 'LaunchTemplateId', { value: lt.ref });
    new cdk.CfnOutput(this, 'ASGName', { value: asg.ref });
  }
}
