import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class ScotusticianSharedStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    const useGpu = scope.node.tryGetContext('useGpu') === 'true';

    super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });

    // --- VPC + Cluster ---
    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
    });

    this.vpc.addInterfaceEndpoint('EcrEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR,
    });

    this.vpc.addInterfaceEndpoint('EcrDkrEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
    });

    this.vpc.addInterfaceEndpoint('LogsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
    });

    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
    });

    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });

    if (useGpu) {
      const instanceRole = new iam.Role(this, 'GpuInstanceRole', {
        assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonEC2ContainerServiceforEC2Role'),
        ],
      });

      const instanceSG = new ec2.SecurityGroup(this, 'GpuInstanceSG', {
        vpc: this.vpc,
        allowAllOutbound: true,
        description: 'ECS GPU instance SG',
      });

      const ami = ecs.EcsOptimizedImage.amazonLinux2().getImage(this).imageId;

      const instance = new ec2.CfnInstance(this, 'GpuSpotInstance', {
        imageId: ami,
        instanceType: 'g4dn.micro',
        subnetId: this.vpc.publicSubnets[0].subnetId,
        securityGroupIds: [instanceSG.securityGroupId],
        iamInstanceProfile: new iam.CfnInstanceProfile(this, 'GpuInstanceProfile', {
          roles: [instanceRole.roleName],
        }).ref,
        tags: [
          { key: 'Name', value: 'ScotusticianGpuSpot' },
          { key: 'AutoStop', value: 'true' },
        ],
        userData: cdk.Fn.base64([
          `#!/bin/bash`,
          `echo "ECS_CLUSTER=${this.cluster.clusterName}" >> /etc/ecs/ecs.config`,
          `echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config`,
          `systemctl enable --now ecs`,
        ].join('\n')),
      } as any); // Force inclusion with `as any` because CDK types don't know this key



      cdk.Tags.of(instance).add('AutoStop', 'true');

      new cdk.CfnOutput(this, 'GpuInstanceId', {
        value: instance.ref,
      });

      new cdk.CfnOutput(this, 'SecurityGroupId', {
        value: instanceSG.securityGroupId,
      });
    }

    new cdk.CfnOutput(this, 'ClusterName', {
      value: this.cluster.clusterName,
    });

    new cdk.CfnOutput(this, 'PublicSubnetId1', {
      value: this.vpc.publicSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'PublicSubnetId2', {
      value: this.vpc.publicSubnets[1].subnetId,
    });

    new cdk.CfnOutput(this, 'PrivateSubnetId1', {
      value: this.vpc.isolatedSubnets[0].subnetId,
    });

    new cdk.CfnOutput(this, 'PrivateSubnetId2', {
      value: this.vpc.isolatedSubnets[1].subnetId,
    });
  }
}