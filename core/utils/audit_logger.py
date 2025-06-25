import sqlite3
import uuid
import json
import os
import asyncio
import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any, Optional
if TYPE_CHECKING:
   from core.aws.dynamo_manager import DynamoManager

from .database_manager import DatabaseManager

logger = logging.getLogger(__name__)

class AuditLogger:
   """
   Thread-safe audit logging system for S3 file manager
   Handles logging of system events, user actions, and security-related activities
   """
   
   def __init__(self, dynamo_manager: Optional['DynamoManager'] = None, db_manager: Optional[DatabaseManager] = None):
       """Initialize audit logger with database connections"""
       self.dynamo_manager = dynamo_manager
       self.db_manager = db_manager or DatabaseManager()
       self._thread_local = threading.local()
       self._ensure_log_directory()

   def _ensure_log_directory(self):
       """Create log directory if it doesn't exist"""
       log_dir = os.path.join(os.getcwd(), 'logs', 'audit')
       os.makedirs(log_dir, exist_ok=True)

   @property
   def _get_db_manager(self):
       """Get thread-local database manager"""
       if not hasattr(self._thread_local, 'db_manager'):
           self._thread_local.db_manager = DatabaseManager()
       return self._thread_local.db_manager

   async def log_event(
       self, 
       action: str, 
       user_id: Optional[str] = None, 
       resource: Optional[str] = None, 
       details: Optional[Dict[str, Any]] = None, 
       severity: str = 'info',
       success: bool = True
   ) -> str:
       """Log a system event with comprehensive details"""
       try:
           valid_severities = ['info', 'warning', 'error', 'critical']
           if severity not in valid_severities:
               severity = 'info'
           
           log_id = str(uuid.uuid4())
           
           log_entry = {
               'id': log_id,
               'timestamp': datetime.now().isoformat(),
               'action': action,
               'user_id': user_id,
               'resource': resource,
               'details': details or {},
               'severity': severity,
               'ip_address': self._get_client_ip(),
               'success': success
           }
           
           loop = asyncio.get_event_loop()
           
           await asyncio.gather(
               loop.run_in_executor(None, lambda: self._save_to_local_db(log_entry)),
               loop.run_in_executor(None, lambda: self._save_to_dynamodb(log_entry)) if self.dynamo_manager else asyncio.sleep(0),
               loop.run_in_executor(None, lambda: self._save_to_file(log_entry))
           )
           
           return log_id

       except Exception as e:
           logger.error(f"Error logging event: {str(e)}")
           return str(uuid.uuid4())

   def _save_to_local_db(self, log_entry: Dict[str, Any]):
    """Save log entry to local SQLite database using direct SQL"""
    try:
        # Get direct connection to the database
        conn = sqlite3.connect(os.path.join(os.getcwd(), 'data', 'audit_logs.db'))
        cursor = conn.cursor()
        
        # Simplify the data we're storing to avoid type issues
        log_id = log_entry.get('id', str(uuid.uuid4()))
        timestamp = log_entry.get('timestamp', datetime.now().isoformat())
        user_id = log_entry.get('user_id', 'unknown')
        action = log_entry.get('action', 'unknown')
        severity = log_entry.get('severity', 'info')
        success = 1 if log_entry.get('success', True) else 0
        
        # Use a simpler INSERT with fewer fields to avoid type issues
        cursor.execute('''
            INSERT INTO audit_logs 
            (log_id, timestamp, user_id, action, severity, success)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (log_id, timestamp, user_id, action, severity, success))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving to local DB: {str(e)}")

   def _save_to_dynamodb(self, log_entry: Dict[str, Any]):
       """Save log entry to DynamoDB"""
       try:
           if self.dynamo_manager:
               self.dynamo_manager.users_table.put_item(Item=log_entry)
       except Exception as e:
           logger.error(f"Error saving to DynamoDB: {str(e)}")

   def _save_to_file(self, log_entry: Dict[str, Any]):
       """Save log entry to a JSON log file with thread safety"""
       try:
           log_dir = os.path.join(os.getcwd(), 'logs', 'audit')
           log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}_audit.log")
           
           with open(log_file, 'a') as f:
               json.dump(log_entry, f)
               f.write('\n')
       except Exception as e:
           logger.error(f"Error saving to file: {str(e)}")

   def _get_client_ip(self) -> str:
       """Retrieve client IP address"""
       return 'Unknown'

   async def log_login(self, user_id: str, success: bool):
       """Log user login attempts"""
       action = 'user_login_success' if success else 'user_login_failed'
       severity = 'info' if success else 'warning'
       
       return await self.log_event(
           action=action,
           user_id=user_id,
           severity=severity,
           success=success,
           details={'login_result': 'success' if success else 'failed'}
       )

   async def log_file_operation(
       self, 
       user_id: str, 
       operation: str, 
       file_path: str, 
       success: bool,
       details: Optional[Dict[str, Any]] = None
   ) -> str:
       """Log S3 file operations with additional details"""
       severity = 'info' if success else 'error'
       action = f's3_{operation}'
       
       operation_details = {
           'operation': operation,
           'result': 'success' if success else 'failed'
       }
       if details:
           operation_details.update(details)
       
       return await self.log_event(
           action=action,
           user_id=user_id,
           resource=file_path,
           severity=severity,
           success=success,
           details=operation_details
       )

   async def get_recent_logs(self, limit: int = 50) -> list:
       """Retrieve most recent audit logs"""
       try:
           loop = asyncio.get_event_loop()
           return await loop.run_in_executor(
               None,
               lambda: self._get_db_manager.get_audit_logs(limit=limit)
           )
       except Exception as e:
           logger.error(f"Error getting recent logs: {str(e)}")
           return []

   async def search_logs(
       self, 
       start_date: Optional[datetime] = None, 
       end_date: Optional[datetime] = None, 
       user_id: Optional[str] = None,
       severity: Optional[str] = None,
       action: Optional[str] = None
   ) -> list:
       """Search audit logs with multiple filters"""
       try:
           loop = asyncio.get_event_loop()
           return await loop.run_in_executor(
               None,
               lambda: self._get_db_manager.get_audit_logs(
                   start_date=start_date,
                   end_date=end_date,
                   user_id=user_id,
                   severity=severity,
                   action=action
               )
           )
       except Exception as e:
           logger.error(f"Error searching logs: {str(e)}")
           return []

   def close(self):
       """Clean up resources"""
       if hasattr(self._thread_local, 'db_manager'):
           self._thread_local.db_manager.close()
           delattr(self._thread_local, 'db_manager')