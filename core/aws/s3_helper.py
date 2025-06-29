import asyncio
import boto3
import threading
from typing import Dict, Tuple, List, Optional, Callable
from core.aws.config import AWSConfig
from core.utils.database_manager import DatabaseManager
from core.utils.audit_logger import AuditLogger
from logging import Logger
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class S3Helper:
    def __init__(self, db_manager=None, audit_logger=None, permission_manager=None):
        """Initialize S3 helper

        Args:
            db_manager: Optional database manager instance
            audit_logger: Optional audit logger instance
            permission_manager: Optional permission manager instance
        """
        # Initialize thread-local storage
        self._thread_local = threading.local()

        # Store AWS config
        self._aws_config = AWSConfig.get_aws_config()

        # Use the specified bucket name directly
        self.bucket_name = AWSConfig.S3_BUCKET_NAME
        logger.info(f"S3Helper initialized with bucket: {self.bucket_name}")

        # Initialize managers with lazy imports if not provided
        if db_manager is None:
            from core.utils.database_manager import DatabaseManager

            db_manager = DatabaseManager()

        if audit_logger is None:
            from core.utils.audit_logger import AuditLogger

            audit_logger = AuditLogger(db_manager=db_manager)

        if permission_manager is None:
            from core.auth.permission_manager import PermissionManager

            permission_manager = PermissionManager(db_manager=db_manager)

        self.db_manager = db_manager
        self.audit_logger = audit_logger
        self.permission_manager = permission_manager

    @property
    def s3_client(self):
        """Get thread-local S3 client"""
        if not hasattr(self._thread_local, "s3"):
            self._thread_local.s3 = boto3.client("s3", **self._aws_config)
        return self._thread_local.s3

    @property
    def s3_resource(self):
        """Get thread-local S3 resource"""
        if not hasattr(self._thread_local, "s3_resource"):
            self._thread_local.s3_resource = boto3.resource("s3", **self._aws_config)
        return self._thread_local.s3_resource

    async def list_buckets(self) -> List[Dict]:
        """List all available buckets"""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self.s3_client.list_buckets)
            return response.get("Buckets", [])
        except Exception as e:
            logger.error(f"Failed to list buckets: {str(e)}")
            raise

    async def list_folder_contents(
        self, prefix: str = "", delimiter: str = "/", user_id: Optional[str] = None
    ) -> Tuple[List[str], List[Dict]]:
        """
        List contents of a folder in S3

        Args:
            prefix: Folder path prefix (the folder to list)
            delimiter: Delimiter for folder structure (typically '/')
            user_id: Optional user ID for audit logging and permission check

        Returns:
            tuple: (folders, files) lists
        """
        try:
            # Check folder access permission if user_id is provided
            if (
                user_id
                and hasattr(self, "permission_manager")
                and self.permission_manager
            ):
                has_access = await self.permission_manager.check_folder_access(
                    user_id, prefix, "read"
                )
                if not has_access:
                    logger.warning(f"User {user_id} denied access to folder {prefix}")
                    await self.audit_logger.log_event(
                        action="list_folder_denied",
                        user_id=user_id,
                        resource=prefix,
                        severity="warning",
                        success=False,
                    )
                    return [], []  # Return empty lists if no access

            # Ensure prefix ends with delimiter for folder paths
            if prefix and not prefix.endswith(delimiter) and prefix != "/":
                prefix = f"{prefix}{delimiter}"

            # Handle root path
            if prefix == "/":
                prefix = ""

            loop = asyncio.get_event_loop()

            folders = []
            files = []

            # Run pagination in executor
            async def process_pages():
                paginator = self.s3_client.get_paginator("list_objects_v2")
                pages = paginator.paginate(
                    Bucket=self.bucket_name, Prefix=prefix, Delimiter=delimiter
                )

                for page in await loop.run_in_executor(None, lambda: list(pages)):
                    # Get folders (CommonPrefixes in S3 terminology)
                    for folder in page.get("CommonPrefixes", []):
                        folders.append(folder.get("Prefix"))

                    # Get files (actual objects, excluding "folder" objects)
                    for file in page.get("Contents", []):
                        key = file.get("Key")
                        # Skip the current directory object (empty files with name ending in delimiter)
                        if key != prefix and not key.endswith(delimiter):
                            files.append(
                                {
                                    "key": key,
                                    "size": file.get("Size", 0),
                                    "last_modified": file.get(
                                        "LastModified", datetime.now()
                                    ),
                                }
                            )

            await process_pages()

            # Log the list operation
            if user_id:
                await self.audit_logger.log_event(
                    action="list_folder",
                    user_id=user_id,
                    resource=prefix,
                    details={"folder_count": len(folders), "file_count": len(files)},
                    severity="info",
                    success=True,
                )

            # If no results and prefix is not empty, check if the prefix itself exists
            if not folders and not files and prefix:
                exists = await self._object_exists(prefix)
                if not exists:
                    logger.warning(f"Folder not found: {prefix}")

            return folders, files

        except Exception as e:
            logger.error(f"Failed to list folder contents: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="list_folder_error",
                    user_id=user_id,
                    resource=prefix,
                    severity="error",
                    details={"error": str(e)},
                    success=False,
                )
            # Return empty results on error
            return [], []

        except Exception as e:
            logger.error(f"Failed to list folder contents: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="list_folder_error",
                    user_id=user_id,
                    resource=prefix,
                    severity="error",
                    details={"error": str(e)},
                )
            # Return empty results on error
            return [], []

    async def _object_exists(self, key: str) -> bool:
        """
        Check if an object exists in S3

        Args:
            key: Object key to check

        Returns:
            bool: True if object exists, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.head_object(Bucket=self.bucket_name, Key=key),
            )
            return True
        except Exception:
            return False

    async def upload_file(
        self,
        file_obj,
        s3_path: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        callback: Optional[Callable] = None,
    ) -> bool:
        """
        Upload file to S3 with progress tracking

        Args:
            file_obj: File object to upload (file-like object)
            s3_path: S3 object key (path)
            user_id: Optional user ID for audit logging
            metadata: Optional metadata to add to the object
            callback: Optional callback function for progress tracking

        Returns:
            bool: True if upload successful, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            extra_args = {"Metadata": metadata} if metadata else {}

            # Check if parent folder exists and create if needed
            parent_folder = s3_path.rsplit("/", 1)[0] + "/" if "/" in s3_path else ""
            if parent_folder and not await self._object_exists(parent_folder):
                await self.create_folder(parent_folder, user_id)

            # Get file size for logging (if possible)
            file_size = 0
            try:
                pos = file_obj.tell()
                file_obj.seek(0, 2)  # Seek to end
                file_size = file_obj.tell()
                file_obj.seek(pos)  # Restore position
            except:
                pass  # Some file objects don't support tell/seek

            # Perform upload in executor
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.upload_fileobj(
                    file_obj,
                    self.bucket_name,
                    s3_path,
                    ExtraArgs=extra_args,
                    Callback=callback,
                ),
            )

            # Log successful upload
            if user_id:
                await self.audit_logger.log_event(
                    action="upload_file",
                    user_id=user_id,
                    resource=s3_path,
                    details={"size": file_size},
                )

            logger.info(f"Successfully uploaded file to {s3_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to upload file: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="upload_file_error",
                    user_id=user_id,
                    resource=s3_path,
                    severity="error",
                    details={"error": str(e)},
                )
            raise

    async def download_file(
        self,
        s3_path: str,
        local_path: str,
        user_id: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> bool:
        """
        Download file from S3 with progress tracking

        Args:
            s3_path: S3 object key (path)
            local_path: Local file path to save
            user_id: Optional user ID for audit logging
            callback: Optional callback function for progress tracking

        Returns:
            bool: True if download successful, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()

            # Perform download in executor
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.download_file(
                    self.bucket_name, s3_path, local_path, Callback=callback
                ),
            )

            # Log successful download
            if user_id:
                await self.audit_logger.log_event(
                    action="download_file",
                    user_id=user_id,
                    resource=s3_path,
                    details={"local_path": local_path},
                )

            logger.info(f"Successfully downloaded {s3_path} to {local_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download file: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="download_file_error",
                    user_id=user_id,
                    resource=s3_path,
                    severity="error",
                    details={"error": str(e)},
                )
            raise

    async def _ensure_bucket_exists(self):
        """Check if bucket exists"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self.s3_client.head_bucket(Bucket=self.bucket_name)
            )
            return True
        except Exception as e:
            Logger.error(f"Bucket check error: {str(e)}")
            return False

    async def _run_in_executor(self, func):
        """Run a synchronous function in an executor"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, func)

    async def create_folder(
        self, folder_path: str, user_id: Optional[str] = None
    ) -> bool:
        """
        Create a new folder in S3

        Args:
            folder_path: Folder path (should end with /)
            user_id: Optional user ID for audit logging

        Returns:
            bool: True if creation successful, False otherwise
        """
        try:
            # Ensure folder path ends with /
            if not folder_path.endswith("/"):
                folder_path += "/"

            loop = asyncio.get_event_loop()

            # Create folder in executor (by creating empty object with trailing slash)
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.put_object(
                    Bucket=self.bucket_name, Key=folder_path, Body=b""
                ),
            )

            # Log folder creation
            if user_id:
                await self.audit_logger.log_event(
                    action="create_folder", user_id=user_id, resource=folder_path
                )

            logger.info(f"Created folder: {folder_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to create folder: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="create_folder_error",
                    user_id=user_id,
                    resource=folder_path,
                    severity="error",
                    details={"error": str(e)},
                )
            raise

    async def delete_folder(
        self, folder_path: str, user_id: Optional[str] = None
    ) -> bool:
        """
        Delete a folder and all its contents from S3

        Args:
            folder_path: Folder path to delete
            user_id: Optional user ID for audit logging

        Returns:
            bool: True if deletion successful, False otherwise
        """
        try:
            # Ensure folder path ends with /
            if not folder_path.endswith("/"):
                folder_path += "/"

            loop = asyncio.get_event_loop()
            bucket = self.s3_resource.Bucket(self.bucket_name)

            # Delete all objects in the folder
            def delete_objects():
                objects_to_delete = list(bucket.objects.filter(Prefix=folder_path))
                if objects_to_delete:
                    bucket.delete_objects(
                        Delete={
                            "Objects": [{"Key": obj.key} for obj in objects_to_delete]
                        }
                    )

            # Run deletion in executor
            await loop.run_in_executor(None, delete_objects)

            # Log folder deletion
            if user_id:
                await self.audit_logger.log_event(
                    action="delete_folder", user_id=user_id, resource=folder_path
                )

            logger.info(f"Deleted folder: {folder_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete folder: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="delete_folder_error",
                    user_id=user_id,
                    resource=folder_path,
                    severity="error",
                    details={"error": str(e)},
                )
            raise

    async def delete_file(self, file_path: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a file from S3

        Args:
            file_path: File path to delete
            user_id: Optional user ID for audit logging

        Returns:
            bool: True if deletion successful, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()

            # Delete file in executor
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.delete_object(
                    Bucket=self.bucket_name, Key=file_path
                ),
            )

            # Log file deletion
            if user_id:
                await self.audit_logger.log_event(
                    action="delete_file", user_id=user_id, resource=file_path
                )

            logger.info(f"Deleted file: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete file: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="delete_file_error",
                    user_id=user_id,
                    resource=file_path,
                    severity="error",
                    details={"error": str(e)},
                )
            raise

    async def copy_file(
        self, source_path: str, destination_path: str, user_id: Optional[str] = None
    ) -> bool:
        """
        Copy a file within the same bucket

        Args:
            source_path: Source file path
            destination_path: Destination file path
            user_id: Optional user ID for audit logging

        Returns:
            bool: True if copy successful, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()

            # Copy file in executor
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.copy_object(
                    Bucket=self.bucket_name,
                    CopySource=f"{self.bucket_name}/{source_path}",
                    Key=destination_path,
                ),
            )

            # Log file copy
            if user_id:
                await self.audit_logger.log_event(
                    action="copy_file",
                    user_id=user_id,
                    resource=destination_path,
                    details={"source": source_path},
                )

            logger.info(f"Copied file from {source_path} to {destination_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to copy file: {str(e)}")
            if user_id:
                await self.audit_logger.log_event(
                    action="copy_file_error",
                    user_id=user_id,
                    resource=destination_path,
                    severity="error",
                    details={"source": source_path, "error": str(e)},
                )
            raise

    async def get_bucket_stats(self) -> Dict:
        """
        Get bucket storage statistics

        Returns:
            Dict: Statistics including total size, files, etc.
        """
        try:
            # Validate bucket name
            if not self.bucket_name:
                return {
                    "bucket_exists": False,
                    "total_size": 0,
                    "total_files": 0,
                    "total_size_gb": 0,
                    "usage_percentage": 0,
                }

            # Check if bucket exists
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, lambda: self.s3_client.head_bucket(Bucket=self.bucket_name)
                )
                bucket_exists = True
            except Exception as e:
                logging.Logger.error(f"Bucket check error: {str(e)}")
                bucket_exists = False

            if not bucket_exists:
                return {
                    "bucket_exists": False,
                    "total_size": 0,
                    "total_files": 0,
                    "total_size_gb": 0,
                    "usage_percentage": 0,
                }

            # List all objects in the bucket
            objects = await self._list_all_objects()

            # Calculate total size and count
            total_size = 0
            total_files = 0

            for obj in objects:
                if "Size" in obj:
                    total_size += obj["Size"]
                    total_files += 1

            # Format stats
            stats = {
                "bucket_exists": bucket_exists,
                "bucket_name": self.bucket_name,
                "total_size": total_size,
                "total_files": total_files,
                "total_size_gb": round(total_size / (1024 * 1024 * 1024), 2),
                "usage_percentage": round(
                    (total_size / (50 * 1024 * 1024 * 1024)) * 100, 2
                ),  # Assuming 50GB limit
            }

            # Cache stats in database (if available)
            if self.db_manager:
                await self.db_manager.insert_activity(
                    {
                        "activity_type": "bucket_stats",
                        "timestamp": datetime.now().isoformat(),
                        "details": stats,
                    }
                )

            return stats

        except Exception as e:
            logging.Logger.error(f"Error getting bucket stats: {str(e)}")
            return {
                "bucket_exists": False,
                "total_size": 0,
                "total_files": 0,
                "total_size_gb": 0,
                "usage_percentage": 0,
            }

    async def _list_all_objects(self):
        """List all objects in the bucket"""
        try:
            objects = []
            loop = asyncio.get_event_loop()
            paginator = self.s3_client.get_paginator("list_objects_v2")

            def list_objects():
                result = []
                for page in paginator.paginate(Bucket=self.bucket_name):
                    if "Contents" in page:
                        result.extend(page["Contents"])
                return result

            # Execute the pagination in executor
            objects = await loop.run_in_executor(None, list_objects)
            return objects
        except Exception as e:
            logging.Logger.error(f"Error listing all objects: {str(e)}")
            return []

    def close(self):
        """Clean up resources"""
        if hasattr(self._thread_local, "s3"):
            delattr(self._thread_local, "s3")
        if hasattr(self._thread_local, "s3_resource"):
            delattr(self._thread_local, "s3_resource")
        if self.db_manager:
            self.db_manager.close()
