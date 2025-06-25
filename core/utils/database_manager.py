import os
import sqlite3
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import json
from datetime import datetime, timedelta
import uuid
import logging
import threading
import asyncio
from functools import partial

class DatabaseManager:
    """
    Thread-safe SQLite database manager for storing and managing audit logs
    Provides a local persistence layer for audit and activity tracking
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager
        
        Args:
            db_path (str, optional): Path to the SQLite database file
        """
        # Create data directory if it doesn't exist
        app_data_dir = os.path.join(os.getcwd(), 'data')
        os.makedirs(app_data_dir, exist_ok=True)
        
        # Default database path
        self.db_path = db_path or os.path.join(app_data_dir, 'audit_logs.db')
        self.logger = logging.getLogger(__name__)
        
        # Thread-local storage for connections
        self._local = threading.local()
        
        # Create tables on initialization
        self._create_tables()

    def _get_connection(self):
        """Get a thread-local database connection"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def _create_tables(self):
        """Create necessary database tables"""
        create_tables_sql = '''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id TEXT UNIQUE,
                timestamp DATETIME,
                user_id TEXT,
                action TEXT,
                resource TEXT,
                details TEXT,
                severity TEXT,
                ip_address TEXT,
                success INTEGER DEFAULT 1
            );
            
            CREATE TABLE IF NOT EXISTS user_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT UNIQUE,
                user_id TEXT,
                timestamp DATETIME,
                activity_type TEXT,
                operation_type TEXT,
                resource_path TEXT,
                details TEXT,
                session_id TEXT,
                ip_address TEXT,
                duration REAL,
                status TEXT,
                error_message TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_activities_timestamp ON user_activities(timestamp);
        '''
        
        try:
            conn = self._get_connection()
            conn.executescript(create_tables_sql)
            conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Error creating tables: {str(e)}")
            raise

    async def initialize_database(self):
        """
        Asynchronous method to initialize the database
        Ensures tables are created and any necessary setup is performed
        """
        def _initialize():
            try:
                # Recreate tables if needed
                self._create_tables()
                
                # Optional: Add any initial setup or migration logic here
                # For example, creating initial admin user or default configurations
                
                return True
            except Exception as e:
                self.logger.error(f"Database initialization error: {str(e)}")
                return False

        # Use run_in_executor to run synchronous initialization in a thread
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _initialize)

    def insert_audit_log_sync(self, log_data: Dict[str, Any]) -> str:
        """
        Insert an audit log entry synchronously

        Args:
            log_data (dict): Audit log details

        Returns:
            str: Log entry ID
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            log_id = log_data.get('id', str(uuid.uuid4()))
            timestamp = log_data.get('timestamp', datetime.now().isoformat())

            # Make sure details is properly serialized to JSON
            details = log_data.get('details', {})
            if not isinstance(details, str):
                details = json.dumps(details)

            cursor.execute('''
                INSERT INTO audit_logs 
                (log_id, timestamp, user_id, action, resource, details, 
                 severity, ip_address, success)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                log_id,
                timestamp,
                log_data.get('user_id'),
                log_data.get('action'),
                log_data.get('resource'),
                details,  # Now guaranteed to be a string
                log_data.get('severity', 'info'),
                log_data.get('ip_address'),
                1 if log_data.get('success', True) else 0
            ))

            conn.commit()
            return log_id

        except sqlite3.Error as e:
            self.logger.error(f"Error inserting audit log: {str(e)}")
            return str(uuid.uuid4())
    
    async def insert_audit_log(self, log_data: Dict[str, Any]) -> str:
        """
        Insert an audit log entry asynchronously
        
        Args:
            log_data (dict): Audit log details
        
        Returns:
            str: Log entry ID
        """
        def _insert():
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                log_id = log_data.get('id', str(uuid.uuid4()))
                timestamp = log_data.get('timestamp', datetime.now().isoformat())
                details = json.dumps(log_data.get('details', {}))
                
                cursor.execute('''
                    INSERT INTO audit_logs 
                    (log_id, timestamp, user_id, action, resource, details, 
                     severity, ip_address, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    log_id,
                    timestamp,
                    log_data.get('user_id'),
                    log_data.get('action'),
                    log_data.get('resource'),
                    details,
                    log_data.get('severity', 'info'),
                    log_data.get('ip_address'),
                    1 if log_data.get('success', True) else 0
                ))
                
                conn.commit()
                return log_id
                
            except sqlite3.Error as e:
                self.logger.error(f"Error inserting audit log: {str(e)}")
                raise

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _insert)

    async def get_audit_logs(
        self, 
        start_date: Optional[datetime] = None, 
        end_date: Optional[datetime] = None, 
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Retrieve audit logs asynchronously with filtering options
        
        Args:
            start_date (datetime, optional): Start of date range
            end_date (datetime, optional): End of date range
            user_id (str, optional): Filter by specific user
            action (str, optional): Filter by action type
            severity (str, optional): Filter by severity level
            limit (int, optional): Maximum number of logs to retrieve
        
        Returns:
            List of audit log entries
        """
        def _get_logs():
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                query = "SELECT * FROM audit_logs WHERE 1=1"
                params = []
                
                if start_date:
                    query += " AND timestamp >= ?"
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += " AND timestamp <= ?"
                    params.append(end_date.isoformat())
                
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                
                if action:
                    query += " AND action = ?"
                    params.append(action)
                
                if severity:
                    query += " AND severity = ?"
                    params.append(severity)
                
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                
                logs = []
                for row in cursor.fetchall():
                    log = dict(row)
                    log['details'] = json.loads(log['details']) if log['details'] else {}
                    log['success'] = bool(log['success'])
                    logs.append(log)
                
                return logs
                
            except sqlite3.Error as e:
                self.logger.error(f"Error retrieving audit logs: {str(e)}")
                return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get_logs)

    async def insert_activity(self, activity_data: Dict[str, Any]) -> str:
        """
        Insert a user activity record asynchronously
        
        Args:
            activity_data (dict): Activity details
            
        Returns:
            str: Activity ID
        """
        def _insert():
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                activity_id = activity_data.get('activity_id', str(uuid.uuid4()))
                details = json.dumps(activity_data.get('details', {}))
                
                cursor.execute('''
                    INSERT INTO user_activities
                    (activity_id, user_id, timestamp, activity_type, operation_type,
                     resource_path, details, session_id, ip_address, duration,
                     status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    activity_id,
                    activity_data.get('user_id'),
                    activity_data.get('timestamp', datetime.now().isoformat()),
                    activity_data.get('activity_type'),
                    activity_data.get('operation_type'),
                    activity_data.get('resource_path'),
                    details,
                    activity_data.get('session_id'),
                    activity_data.get('ip_address'),
                    activity_data.get('duration'),
                    activity_data.get('status'),
                    activity_data.get('error_message')
                ))
                
                conn.commit()
                return activity_id
                
            except sqlite3.Error as e:
                self.logger.error(f"Error inserting activity: {str(e)}")
                raise

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _insert)

    async def cleanup_old_logs(self, days: int = 30):
        """
        Delete logs older than specified number of days asynchronously
        
        Args:
            days (int): Number of days to retain logs
        """
        def _cleanup():
            try:
                conn = self._get_connection()
                cursor = conn.cursor()
                
                cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
                
                cursor.execute('DELETE FROM audit_logs WHERE timestamp < ?', (cutoff_date,))
                cursor.execute('DELETE FROM user_activities WHERE timestamp < ?', (cutoff_date,))
                
                conn.commit()
                
            except sqlite3.Error as e:
                self.logger.error(f"Error cleaning up old logs: {str(e)}")
                raise

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _cleanup)

    def close(self):
        """Close the database connection for the current thread"""
        if hasattr(self._local, 'connection'):
            try:
                self._local.connection.close()
                delattr(self._local, 'connection')
            except sqlite3.Error as e:
                self.logger.error(f"Error closing database connection: {str(e)}")

    def __del__(self):
        """Cleanup when the object is deleted"""
        self.close()