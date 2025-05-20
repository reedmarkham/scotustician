import * as cdk from 'aws-cdk-lib';
import { ScotusticianSharedStack } from '../lib/scotustician-shared-stack';
import { ScotusticianIngestStack } from '../lib/scotustician-ingest-stack';
import { ScotusticianTransformersStack } from '../lib/scotustician-transformers-stack';

process.env.CDK_BOOTSTRAP_QUALIFIER = process.env.CDK_BOOTSTRAP_QUALIFIER || 'sctstcn';

const app = new cdk.App();
const shared = new ScotusticianSharedStack(app, 'ScotusticianSharedStack');
new ScotusticianIngestStack(app, 'ScotusticianIngestStack', {
  cluster: shared.cluster,
  vpc: shared.vpc,
});
new ScotusticianTransformersStack(app, 'ScotusticianTransformersStack', {
  cluster: shared.cluster,
  vpc: shared.vpc,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});
