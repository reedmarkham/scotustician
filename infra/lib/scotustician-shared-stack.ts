import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import { DefaultStackSynthesizer } from 'aws-cdk-lib';

export interface ScotusticianSharedStackProps extends StackProps {}

export class ScotusticianSharedStack extends Stack {
  public readonly vpc: ec2.Vpc;
  public readonly cluster: ecs.Cluster;

  constructor(scope: Construct, id: string, props?: ScotusticianSharedStackProps) {
    const qualifier = scope.node.tryGetContext('bootstrapQualifier') || 'sctstcn';

    super(scope, id, {
      ...props,
      synthesizer: new DefaultStackSynthesizer({
        qualifier: qualifier,
      }),
    });

    this.vpc = new ec2.Vpc(this, 'ScotusticianVpc', {
      maxAzs: 2,
    });

    this.cluster = new ecs.Cluster(this, 'ScotusticianCluster', {
      vpc: this.vpc,
    });
  }
}
