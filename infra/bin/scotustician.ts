import * as cdk from 'aws-cdk-lib';
import { ScotusticianEtlStack } from '../lib/scotustician-etl-stack';
import { ScotusticianTransformersStack } from '../lib/scotustician-transformers-stack';

const app = new cdk.App();

new ScotusticianEtlStack(app, 'ScotusticianEtlStack');
new ScotusticianTransformersStack(app, 'ScotusticianTransformersStack');
