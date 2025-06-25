import boto3
import uuid
from datetime import datetime
import sys
import os

# Ensure the script can find the core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.aws.config import AWSConfig

def create_test_data_exchange_table():
    """
    Create a DynamoDB table for test data exchange folder structure
    """
    # Get AWS configuration
    aws_config = AWSConfig.get_aws_config()
    
    # Create DynamoDB client
    dynamodb = boto3.resource('dynamodb', **aws_config)
    
    # Table name
    table_name = 'test-fm-user-db-table-test_data_exchange'
    
    # Folder structure to create
    folder_structure = [
        # Document management folders
        "test_data_exchange/documents/reports/",
        "test_data_exchange/documents/invoices/",
        "test_data_exchange/documents/contracts/",
        
        # Media folders
        "test_data_exchange/media/images/",
        "test_data_exchange/media/videos/",
        "test_data_exchange/media/audio/",
        
        # Project management folders
        "test_data_exchange/projects/active/",
        "test_data_exchange/projects/archived/",
        "test_data_exchange/projects/proposals/",
        
        # Collaboration folders
        "test_data_exchange/shared/team_a/",
        "test_data_exchange/shared/team_b/",
        "test_data_exchange/shared/external_collaborators/",
        
        # Temporary and staging folders
        "test_data_exchange/temp/uploads/",
        "test_data_exchange/temp/downloads/",
        "test_data_exchange/temp/processing/",
        
        # Configuration and logs
        "test_data_exchange/system/configs/",
        "test_data_exchange/system/logs/"
    ]
    
    try:
        # Create the table
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'folder_path', 'KeyType': 'HASH'},
                {'AttributeName': 'sk', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'folder_path', 'AttributeType': 'S'},
                {'AttributeName': 'sk', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        
        # Wait for the table to be created
        table.meta.client.get_waiter('table_exists').wait(TableName=table_name)
        print(f"Table {table_name} created successfully!")
        
        # Get the table
        table = dynamodb.Table(table_name)
        
        # Insert folder entries
        for folder_path in folder_structure:
            try:
                table.put_item(
                    Item={
                        'folder_path': folder_path,
                        'sk': '#FOLDER',
                        'created_at': datetime.utcnow().isoformat(),
                        'metadata': {
                            'type': 'folder',
                            'id': str(uuid.uuid4())
                        }
                    }
                )
                print(f"Added folder entry: {folder_path}")
            except Exception as folder_error:
                print(f"Error adding folder {folder_path}: {folder_error}")
        
        print("Folder structure added to DynamoDB table!")
    
    except dynamodb.meta.client.exceptions.ResourceInUseException:
        print(f"Table {table_name} already exists.")
    except Exception as e:
        print(f"Error creating table: {e}")

def main():
    create_test_data_exchange_table()

if __name__ == '__main__':
    main()