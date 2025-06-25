import os
import boto3
from dataclasses import dataclass
from typing import Dict, Optional
from dotenv import load_dotenv
import logging
import asyncio

load_dotenv()
logger = logging.getLogger(__name__)



@dataclass
class AWSCredentials:
   access_key: str 
   secret_key: str
   region: str
   session_token: Optional[str] = None

class AWSConfig:
   # AWS Configuration
   AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
   AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
   AWS_REGION = os.getenv('AWS_REGION', 'ap-south-1')
   
   # App Configuration
   DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
   LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
   JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
   
   # S3 Configuration  
   S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')
   S3_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
   S3_MAX_POOL_CONNECTIONS = 100
   
   # DynamoDB Configuration
   DYNAMO_TABLE_NAME = os.getenv('DYNAMODB_TABLE_NAME')
   DYNAMO_MAX_RETRY_ATTEMPTS = 3
   DYNAMO_MAX_POOL_CONNECTIONS = 100
   
    # Table Names - direct references instead of constructing from DYNAMO_TABLE_NAME
   USERS_TABLE = "test-fm-user-db-table-users"
   SESSIONS_TABLE = "test-fm-user-db-table-sessions"
   PERMISSIONS_TABLE = "test-fm-user-db-table-permissions"
   AUDIT_TABLE = "test-fm-user-db-table-audit"

   # Admin Credentials
   ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
   ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

   @classmethod
   def get_aws_config(cls) -> Dict:
       config = {
           'aws_access_key_id': cls.AWS_ACCESS_KEY,
           'aws_secret_access_key': cls.AWS_SECRET_KEY,
           'region_name': cls.AWS_REGION
       }
       
       if not all([config['aws_access_key_id'], config['aws_secret_access_key'], config['region_name']]):
           raise ValueError("Missing AWS configuration. Check your .env file.")
           
       return config

   @classmethod
   def validate_config(cls) -> None:
       required = [
           'AWS_ACCESS_KEY',
           'AWS_SECRET_KEY', 
           'S3_BUCKET_NAME',
           'DYNAMO_TABLE_NAME',
           'JWT_SECRET_KEY',
           'ADMIN_USERNAME',
           'ADMIN_PASSWORD'
       ]
       missing = [var for var in required if not getattr(cls, var, None)]
       if missing:
           raise ValueError(f"Missing required configuration variables: {missing}")

   @classmethod
   def test_aws_connection(cls):
       try:
           s3_client = boto3.client('s3', **cls.get_aws_config())
           s3_client.list_buckets()
           logging.info("S3 connection successful")

           dynamodb_client = boto3.client('dynamodb', **cls.get_aws_config()) 
           dynamodb_client.list_tables()
           logging.info("DynamoDB connection successful")
           
           return True
       except Exception as e:
           logging.error(f"AWS Connection Test Failed: {str(e)}")
           return False

   @classmethod
   async def initialize_tables(cls):
       """Create DynamoDB tables if they don't exist"""
       try:
           dynamodb = boto3.resource('dynamodb', **cls.get_aws_config())
           
           # Create Users table
           try:
               users_table = dynamodb.create_table(
                   TableName=cls.USERS_TABLE,
                   KeySchema=[
                       {'AttributeName': 'username', 'KeyType': 'HASH'},
                       {'AttributeName': 'sk', 'KeyType': 'RANGE'}
                   ],
                   AttributeDefinitions=[
                       {'AttributeName': 'username', 'AttributeType': 'S'},
                       {'AttributeName': 'sk', 'AttributeType': 'S'}
                   ],
                   ProvisionedThroughput={
                       'ReadCapacityUnits': 5,
                       'WriteCapacityUnits': 5
                   }
               )
               users_table.meta.client.get_waiter('table_exists').wait(TableName=cls.USERS_TABLE)
               logger.info(f"Created table: {cls.USERS_TABLE}")
           except dynamodb.meta.client.exceptions.ResourceInUseException:
               logger.info(f"Table already exists: {cls.USERS_TABLE}")

           # Create Sessions table
           try:
               sessions_table = dynamodb.create_table(
                   TableName=cls.SESSIONS_TABLE,
                   KeySchema=[
                       {'AttributeName': 'session_id', 'KeyType': 'HASH'}
                   ],
                   AttributeDefinitions=[
                       {'AttributeName': 'session_id', 'AttributeType': 'S'}
                   ],
                   ProvisionedThroughput={
                       'ReadCapacityUnits': 5,
                       'WriteCapacityUnits': 5
                   }
               )
               sessions_table.meta.client.get_waiter('table_exists').wait(TableName=cls.SESSIONS_TABLE)
               logger.info(f"Created table: {cls.SESSIONS_TABLE}")
           except dynamodb.meta.client.exceptions.ResourceInUseException:
               logger.info(f"Table already exists: {cls.SESSIONS_TABLE}")

           # Create Permissions table
           try:
               permissions_table = dynamodb.create_table(
                   TableName=cls.PERMISSIONS_TABLE,
                   KeySchema=[
                       {'AttributeName': 'permission_id', 'KeyType': 'HASH'}
                   ],
                   AttributeDefinitions=[
                       {'AttributeName': 'permission_id', 'AttributeType': 'S'}
                   ],
                   ProvisionedThroughput={
                       'ReadCapacityUnits': 5,
                       'WriteCapacityUnits': 5
                   }
               )
               permissions_table.meta.client.get_waiter('table_exists').wait(TableName=cls.PERMISSIONS_TABLE)
               logger.info(f"Created table: {cls.PERMISSIONS_TABLE}")
           except dynamodb.meta.client.exceptions.ResourceInUseException:
               logger.info(f"Table already exists: {cls.PERMISSIONS_TABLE}")

           # Create Audit table
           try:
               audit_table = dynamodb.create_table(
                   TableName=cls.AUDIT_TABLE,
                   KeySchema=[
                       {'AttributeName': 'audit_id', 'KeyType': 'HASH'},
                       {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                   ],
                   AttributeDefinitions=[
                       {'AttributeName': 'audit_id', 'AttributeType': 'S'},
                       {'AttributeName': 'timestamp', 'AttributeType': 'S'}
                   ],
                   ProvisionedThroughput={
                       'ReadCapacityUnits': 5,
                       'WriteCapacityUnits': 5
                   }
               )
               audit_table.meta.client.get_waiter('table_exists').wait(TableName=cls.AUDIT_TABLE)
               logger.info(f"Created table: {cls.AUDIT_TABLE}")
           except dynamodb.meta.client.exceptions.ResourceInUseException:
               logger.info(f"Table already exists: {cls.AUDIT_TABLE}")

           return True
       except Exception as e:
           logger.error(f"Error initializing tables: {str(e)}")
           return False

def get_aws_config() -> Dict:
   return AWSConfig.get_aws_config()