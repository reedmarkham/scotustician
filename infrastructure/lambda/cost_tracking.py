import json, os
from datetime import datetime, timedelta

import boto3

ce_client = boto3.client('ce')
sns_client = boto3.client('sns')

def handler(event: dict, context) -> dict:
    """Track costs for scotustician project and send notifications"""
    
    # Get date range (today)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=1)
    
    try:
        # Get cost by service
        service_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'}
            ]
        )
        
        # Get scotustician project costs
        project_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            Filter={
                'Tags': {
                    'Key': 'Project',
                    'Values': ['scotustician']
                }
            }
        )
        
        # Get component costs
        component_costs = ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'TAG', 'Key': 'Stack'}
            ],
            Filter={
                'Tags': {
                    'Key': 'Project',
                    'Values': ['scotustician']
                }
            }
        )
        
        # Format results
        stage = event.get('stage', 'unknown')
        total_cost = '0.00'
        
        if project_costs.get('ResultsByTime'):
            total_cost = project_costs['ResultsByTime'][0]['Total']['BlendedCost']['Amount']
        
        result = {
            'stage': stage,
            'timestamp': datetime.now().isoformat(),
            'total_cost': total_cost,
            'service_breakdown': [],
            'component_breakdown': []
        }
        
        # Process service costs
        if service_costs.get('ResultsByTime'):
            for group in service_costs['ResultsByTime'][0].get('Groups', []):
                cost = group['Metrics']['BlendedCost']['Amount']
                if float(cost) > 0:
                    result['service_breakdown'].append({
                        'service': group['Keys'][0],
                        'cost': cost
                    })
        
        # Process component costs  
        if component_costs.get('ResultsByTime'):
            for group in component_costs['ResultsByTime'][0].get('Groups', []):
                cost = group['Metrics']['BlendedCost']['Amount']
                if float(cost) > 0:
                    result['component_breakdown'].append({
                        'component': group['Keys'][0],
                        'cost': cost
                    })
        
        # Send notification if requested
        topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if topic_arn and event.get('notify', False):
            message = f"""
Scotustician Pipeline - {stage.title()} Cost Report

Total Cost: ${result['total_cost']}
Timestamp: {result['timestamp']}

Top Services:
{chr(10).join([f"  • {service['service']}: ${service['cost']}" for service in result['service_breakdown'][:5]])}

Components:
{chr(10).join([f"  • {component['component']}: ${component['cost']}" for component in result['component_breakdown']])}
"""
            sns_client.publish(
                TopicArn=topic_arn,
                Subject=f'Scotustician Pipeline - {stage.title()} Cost Report',
                Message=message
            )
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
        
    except Exception as e:
        print(f"Error tracking costs: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }