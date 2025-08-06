import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class ScotusticianSharedStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly ingestCluster: ecs.Cluster;
  public readonly transformersCpuCluster: ecs.Cluster;
  public readonly transformersGpuCluster?: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';
    const useGpu = scope.node.tryGetContext('useGpu') === 'true';

    super(scope, id, {
      ...props,
      synthesizer: new cdk.DefaultStackSynthesizer({ qualifier }),
    });

    // Apply resource tags to entire stack
    cdk.Tags.of(this).add('Project', 'scotustician');
    cdk.Tags.of(this).add('ManagedBy', 'root-user');
    cdk.Tags.of(this).add('Environment', props?.env?.account ? 'production' : 'development');
    cdk.Tags.of(this).add('Stack', 'shared');

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

    // Create separate clusters for different workloads
    this.ingestCluster = new ecs.Cluster(this, 'IngestCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-ingest',
    });

    // Always create CPU cluster for transformers
    this.transformersCpuCluster = new ecs.Cluster(this, 'TransformersCpuCluster', {
      vpc: this.vpc,
      clusterName: 'scotustician-transformers-cpu',
    });

    // Only create GPU cluster if GPU is available
    if (useGpu) {
      this.transformersGpuCluster = new ecs.Cluster(this, 'TransformersGpuCluster', {
        vpc: this.vpc,
        clusterName: 'scotustician-transformers-gpu',
      });
    }

    // Only attempt to create GPU instance if useGpu context variable, which is set by the GitHub Actions workflow step that runs an AWS CLI command to assess the respective AWS account quota for GPU instances
    if (useGpu) {
      const instanceRole = new iam.Role(this, 'GpuInstanceRole', {
        assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonEC2ContainerServiceforEC2Role'),
        ],
      });

      const instanceSG = new ec2.SecurityGroup(this, 'GpuInstanceSG', {
        vpc: this.vpc,
        allowAllOutbound: false,
        description: 'ECS GPU instance SG',
      });

      // Allow HTTPS outbound for ECR/S3/API access
      instanceSG.addEgressRule(
        ec2.Peer.anyIpv4(),
        ec2.Port.tcp(443),
        'HTTPS for ECR/S3/API access'
      );

      // Allow PostgreSQL outbound for database access
      instanceSG.addEgressRule(
        ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
        ec2.Port.tcp(5432),
        'PostgreSQL database access'
      );

      const ami = ecs.EcsOptimizedImage.amazonLinux2().getImage(this).imageId;

      const instance = new ec2.CfnInstance(this, 'GpuSpotInstance', {
        imageId: ami,
        instanceType: 'g4dn.xlarge',
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
          `echo "ECS_CLUSTER=${this.transformersGpuCluster!.clusterName}" >> /etc/ecs/ecs.config`,
          `echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config`,
          `echo "ECS_SPOT_INSTANCE_DRAINING_ENABLED=true" >> /etc/ecs/ecs.config`,
          `systemctl enable --now ecs`,
        ].join('\n')),
        instanceMarketOptions: {
          marketType: 'spot',
          spotOptions: {
            spotInstanceType: 'one-time',
            instanceInterruptionBehavior: 'terminate',
          },
        },
      } as any); // Using 'as any' to include instanceMarketOptions for spot instance configuration



      cdk.Tags.of(instance).add('AutoStop', 'true');

      new cdk.CfnOutput(this, 'GpuInstanceId', {
        value: instance.ref,
      });

      new cdk.CfnOutput(this, 'GpuSecurityGroupId', {
        value: instanceSG.securityGroupId,
      });
    }

    // Always create CPU instance for transformer workloads
    const cpuInstanceRole = new iam.Role(this, 'CpuInstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonEC2ContainerServiceforEC2Role'),
      ],
    });

    const cpuInstanceSG = new ec2.SecurityGroup(this, 'CpuInstanceSG', {
      vpc: this.vpc,
      allowAllOutbound: false,
      description: 'ECS CPU instance SG for transformers',
    });

    // Allow HTTPS outbound for ECR/S3/API access
    cpuInstanceSG.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS for ECR/S3/API access'
    );

    // Allow PostgreSQL outbound for database access
    cpuInstanceSG.addEgressRule(
      ec2.Peer.ipv4(this.vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'PostgreSQL database access'
    );

    const cpuAmi = ecs.EcsOptimizedImage.amazonLinux2().getImage(this).imageId;

    // Use larger instance type for CPU-based transformer workloads
    const cpuInstance = new ec2.CfnInstance(this, 'CpuSpotInstance', {
      imageId: cpuAmi,
      instanceType: 'c5.2xlarge', // 8 vCPU, 16 GB RAM for better CPU performance
      subnetId: this.vpc.publicSubnets[0].subnetId,
      securityGroupIds: [cpuInstanceSG.securityGroupId],
      iamInstanceProfile: new iam.CfnInstanceProfile(this, 'CpuInstanceProfile', {
        roles: [cpuInstanceRole.roleName],
      }).ref,
      tags: [
        { key: 'Name', value: 'ScotusticianTransformersCpuSpot' },
        { key: 'AutoStop', value: 'true' },
      ],
      userData: cdk.Fn.base64([
        `#!/bin/bash`,
        `echo "ECS_CLUSTER=${this.transformersCpuCluster.clusterName}" >> /etc/ecs/ecs.config`,
        `echo "ECS_SPOT_INSTANCE_DRAINING_ENABLED=true" >> /etc/ecs/ecs.config`,
        `systemctl enable --now ecs`,
      ].join('\n')),
      instanceMarketOptions: {
        marketType: 'spot',
        spotOptions: {
          spotInstanceType: 'one-time',
          instanceInterruptionBehavior: 'terminate',
        },
      },
    } as any); // Using 'as any' to include instanceMarketOptions for spot instance configuration

    cdk.Tags.of(cpuInstance).add('AutoStop', 'true');

    new cdk.CfnOutput(this, 'CpuInstanceId', {
      value: cpuInstance.ref,
    });

    new cdk.CfnOutput(this, 'CpuSecurityGroupId', {
      value: cpuInstanceSG.securityGroupId,
    });

    new cdk.CfnOutput(this, 'IngestClusterName', {
      value: this.ingestCluster.clusterName,
    });

    new cdk.CfnOutput(this, 'TransformersCpuClusterName', {
      value: this.transformersCpuCluster.clusterName,
    });

    if (useGpu) {
      new cdk.CfnOutput(this, 'TransformersGpuClusterName', {
        value: this.transformersGpuCluster!.clusterName,
      });
    }

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