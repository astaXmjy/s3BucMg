# core/aws/schema.py
from typing import Dict

class DynamoDBSchema:
   USERS_TABLE = {
       'TableName': 'users',
       'KeySchema': [
           {'AttributeName': 'username', 'KeyType': 'HASH'},
           {'AttributeName': 'sk', 'KeyType': 'RANGE'}
       ],
       'AttributeDefinitions': [
           {'AttributeName': 'username', 'AttributeType': 'S'},
           {'AttributeName': 'sk', 'AttributeType': 'S'},
           {'AttributeName': 'role', 'AttributeType': 'S'},
           {'AttributeName': 'email', 'AttributeType': 'S'}
       ],
       'GlobalSecondaryIndexes': [
           {
               'IndexName': 'RoleIndex',
               'KeySchema': [
                   {'AttributeName': 'role', 'KeyType': 'HASH'},
                   {'AttributeName': 'username', 'KeyType': 'RANGE'}
               ],
               'Projection': {'ProjectionType': 'ALL'}
           },
           {
               'IndexName': 'EmailIndex',
               'KeySchema': [
                   {'AttributeName': 'email', 'KeyType': 'HASH'}
               ],
               'Projection': {'ProjectionType': 'ALL'}
           }
       ]
   }

   SESSIONS_TABLE = {
       'TableName': 'sessions',
       'KeySchema': [
           {'AttributeName': 'session_id', 'KeyType': 'HASH'},
           {'AttributeName': 'username', 'KeyType': 'RANGE'}
       ],
       'AttributeDefinitions': [
           {'AttributeName': 'session_id', 'AttributeType': 'S'},
           {'AttributeName': 'username', 'AttributeType': 'S'},
           {'AttributeName': 'created_at', 'AttributeType': 'S'}
       ],
       'GlobalSecondaryIndexes': [
           {
               'IndexName': 'UserSessionsIndex',
               'KeySchema': [
                   {'AttributeName': 'username', 'KeyType': 'HASH'},
                   {'AttributeName': 'created_at', 'KeyType': 'RANGE'}
               ],
               'Projection': {'ProjectionType': 'ALL'}
           }
       ],
       'TimeToLiveSpecification': {
           'AttributeName': 'expiry_time',
           'Enabled': True
       }
   }

   PERMISSIONS_TABLE = {
       'TableName': 'permissions',
       'KeySchema': [
           {'AttributeName': 'resource_id', 'KeyType': 'HASH'},
           {'AttributeName': 'user_id', 'KeyType': 'RANGE'}
       ],
       'AttributeDefinitions': [
           {'AttributeName': 'resource_id', 'AttributeType': 'S'},
           {'AttributeName': 'user_id', 'AttributeType': 'S'},
           {'AttributeName': 'resource_type', 'AttributeType': 'S'}
       ],
       'GlobalSecondaryIndexes': [
           {
               'IndexName': 'UserPermissionsIndex',
               'KeySchema': [
                   {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                   {'AttributeName': 'resource_type', 'KeyType': 'RANGE'}
               ],
               'Projection': {'ProjectionType': 'ALL'}
           }
       ]
   }

   AUDIT_TABLE = {
       'TableName': 'audit_logs',
       'KeySchema': [
           {'AttributeName': 'user_id', 'KeyType': 'HASH'},
           {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
       ],
       'AttributeDefinitions': [
           {'AttributeName': 'user_id', 'AttributeType': 'S'},
           {'AttributeName': 'timestamp', 'AttributeType': 'S'},
           {'AttributeName': 'resource_id', 'AttributeType': 'S'},
           {'AttributeName': 'action', 'AttributeType': 'S'}
       ],
       'GlobalSecondaryIndexes': [
           {
               'IndexName': 'ResourceActionIndex',
               'KeySchema': [
                   {'AttributeName': 'resource_id', 'KeyType': 'HASH'},
                   {'AttributeName': 'action', 'KeyType': 'RANGE'}
               ],
               'Projection': {'ProjectionType': 'ALL'}
           }
       ],
       'TimeToLiveSpecification': {
           'AttributeName': 'retention_period',
           'Enabled': True
       }
   }