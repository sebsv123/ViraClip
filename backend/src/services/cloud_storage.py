"""
Cloud Storage Integration Service
Multi-provider cloud storage support for S3, Google Cloud Storage, and Azure.
"""

import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class CloudProvider(Enum):
    """Supported cloud storage providers."""
    AWS_S3 = "aws_s3"
    GOOGLE_CLOUD = "gcs"
    AZURE_BLOB = "azure"


class StorageClass(Enum):
    """Storage tier options."""
    STANDARD = "standard"
    INTELLIGENT_TIERING = "intelligent_tiering"
    STANDARD_IA = "standard_ia"
    GLACIER = "glacier"
    COLDLINE = "coldline"
    ARCHIVE = "archive"


@dataclass
class StorageConfig:
    """Cloud storage configuration."""
    provider: CloudProvider
    bucket_name: str
    region: str
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    endpoint_url: Optional[str] = None  # For S3-compatible services
    project_id: Optional[str] = None  # For GCS
    connection_string: Optional[str] = None  # For Azure


@dataclass
class UploadResult:
    """Upload operation result."""
    success: bool
    file_key: str
    public_url: Optional[str]
    size_bytes: int
    etag: str
    storage_class: StorageClass
    upload_time_ms: int
    error_message: Optional[str]


@dataclass
class StorageObject:
    """Cloud storage object metadata."""
    key: str
    size_bytes: int
    last_modified: datetime
    etag: str
    storage_class: StorageClass
    public_url: Optional[str]
    metadata: Dict[str, str]


class CloudStorageManager:
    """
    Multi-provider cloud storage manager.
    """
    
    def __init__(self, config: Optional[StorageConfig] = None):
        self.config = config
        self._clients: Dict[CloudProvider, Any] = {}
        self._upload_history: List[Dict[str, Any]] = []
    
    def _get_client(self, provider: CloudProvider):
        """Get or create cloud storage client."""
        if provider in self._clients:
            return self._clients[provider]
        
        if provider == CloudProvider.AWS_S3:
            import boto3
            client = boto3.client(
                's3',
                aws_access_key_id=self.config.access_key,
                aws_secret_access_key=self.config.secret_key,
                region_name=self.config.region,
                endpoint_url=self.config.endpoint_url
            )
        
        elif provider == CloudProvider.GOOGLE_CLOUD:
            from google.cloud import storage
            client = storage.Client(
                project=self.config.project_id
            )
        
        elif provider == CloudProvider.AZURE_BLOB:
            from azure.storage.blob import BlobServiceClient
            client = BlobServiceClient.from_connection_string(
                self.config.connection_string
            )
        
        else:
            raise ValueError(f"Unsupported provider: {provider}")
        
        self._clients[provider] = client
        return client
    
    async def upload_file(
        self,
        local_path: Path,
        file_key: str,
        provider: Optional[CloudProvider] = None,
        storage_class: StorageClass = StorageClass.STANDARD,
        public: bool = False,
        metadata: Optional[Dict[str, str]] = None
    ) -> UploadResult:
        """
        Upload file to cloud storage.
        
        Args:
            local_path: Path to local file
            file_key: Destination key/path in bucket
            provider: Cloud provider (uses config default if None)
            storage_class: Storage tier
            public: Make file publicly accessible
            metadata: Custom metadata
        """
        import time
        
        start_time = time.time()
        
        if not local_path.exists():
            return UploadResult(
                success=False,
                file_key=file_key,
                public_url=None,
                size_bytes=0,
                etag="",
                storage_class=storage_class,
                upload_time_ms=0,
                error_message="File not found"
            )
        
        file_size = local_path.stat().st_size
        
        try:
            provider = provider or self.config.provider
            client = self._get_client(provider)
            
            # Calculate ETag
            etag = self._calculate_etag(local_path)
            
            extra_args = {
                'StorageClass': storage_class.value.upper() if provider == CloudProvider.AWS_S3 else storage_class.value,
                'Metadata': metadata or {}
            }
            
            if public:
                extra_args['ACL'] = 'public-read'
            
            # Upload based on provider
            if provider == CloudProvider.AWS_S3:
                client.upload_file(
                    str(local_path),
                    self.config.bucket_name,
                    file_key,
                    ExtraArgs=extra_args
                )
                
                # Generate URL
                public_url = f"https://{self.config.bucket_name}.s3.{self.config.region}.amazonaws.com/{file_key}" if public else None
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                bucket = client.bucket(self.config.bucket_name)
                blob = bucket.blob(file_key)
                
                if metadata:
                    blob.metadata = metadata
                
                blob.upload_from_filename(str(local_path))
                
                if storage_class == StorageClass.COLDLINE:
                    blob.storage_class = "COLDLINE"
                
                if public:
                    blob.make_public()
                    public_url = blob.public_url
                else:
                    public_url = None
            
            elif provider == CloudProvider.AZURE_BLOB:
                container_client = client.get_container_client(self.config.bucket_name)
                blob_client = container_client.get_blob_client(file_key)
                
                with open(local_path, 'rb') as data:
                    blob_client.upload_blob(data, overwrite=True, metadata=metadata)
                
                public_url = blob_client.url if public else None
            
            upload_time = int((time.time() - start_time) * 1000)
            
            result = UploadResult(
                success=True,
                file_key=file_key,
                public_url=public_url,
                size_bytes=file_size,
                etag=etag,
                storage_class=storage_class,
                upload_time_ms=upload_time,
                error_message=None
            )
            
            # Log upload
            self._upload_history.append({
                "timestamp": datetime.now().isoformat(),
                "file_key": file_key,
                "provider": provider.value,
                "size_bytes": file_size,
                "upload_time_ms": upload_time
            })
            
            logger.info(f"Uploaded {file_key} to {provider.value} ({file_size} bytes)")
            return result
            
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return UploadResult(
                success=False,
                file_key=file_key,
                public_url=None,
                size_bytes=file_size,
                etag="",
                storage_class=storage_class,
                upload_time_ms=0,
                error_message=str(e)
            )
    
    def _calculate_etag(self, file_path: Path) -> str:
        """Calculate MD5 ETag for file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    async def download_file(
        self,
        file_key: str,
        local_path: Path,
        provider: Optional[CloudProvider] = None
    ) -> bool:
        """Download file from cloud storage."""
        try:
            provider = provider or self.config.provider
            client = self._get_client(provider)
            
            if provider == CloudProvider.AWS_S3:
                client.download_file(
                    self.config.bucket_name,
                    file_key,
                    str(local_path)
                )
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                bucket = client.bucket(self.config.bucket_name)
                blob = bucket.blob(file_key)
                blob.download_to_filename(str(local_path))
            
            elif provider == CloudProvider.AZURE_BLOB:
                container_client = client.get_container_client(self.config.bucket_name)
                blob_client = container_client.get_blob_client(file_key)
                
                with open(local_path, 'wb') as f:
                    downloader = blob_client.download_blob()
                    f.write(downloader.readall())
            
            logger.info(f"Downloaded {file_key} to {local_path}")
            return True
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False
    
    async def delete_file(
        self,
        file_key: str,
        provider: Optional[CloudProvider] = None
    ) -> bool:
        """Delete file from cloud storage."""
        try:
            provider = provider or self.config.provider
            client = self._get_client(provider)
            
            if provider == CloudProvider.AWS_S3:
                client.delete_object(
                    Bucket=self.config.bucket_name,
                    Key=file_key
                )
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                bucket = client.bucket(self.config.bucket_name)
                blob = bucket.blob(file_key)
                blob.delete()
            
            elif provider == CloudProvider.AZURE_BLOB:
                container_client = client.get_container_client(self.config.bucket_name)
                blob_client = container_client.get_blob_client(file_key)
                blob_client.delete_blob()
            
            logger.info(f"Deleted {file_key} from {provider.value}")
            return True
            
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False
    
    async def list_files(
        self,
        prefix: str = "",
        provider: Optional[CloudProvider] = None
    ) -> List[StorageObject]:
        """List files in cloud storage."""
        objects = []
        
        try:
            provider = provider or self.config.provider
            client = self._get_client(provider)
            
            if provider == CloudProvider.AWS_S3:
                response = client.list_objects_v2(
                    Bucket=self.config.bucket_name,
                    Prefix=prefix
                )
                
                for obj in response.get('Contents', []):
                    objects.append(StorageObject(
                        key=obj['Key'],
                        size_bytes=obj['Size'],
                        last_modified=obj['LastModified'],
                        etag=obj['ETag'].strip('"'),
                        storage_class=StorageClass(obj['StorageClass'].lower()),
                        public_url=None,
                        metadata={}
                    ))
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                bucket = client.bucket(self.config.bucket_name)
                blobs = bucket.list_blobs(prefix=prefix)
                
                for blob in blobs:
                    objects.append(StorageObject(
                        key=blob.name,
                        size_bytes=blob.size,
                        last_modified=blob.updated,
                        etag=blob.etag,
                        storage_class=StorageClass(blob.storage_class.lower()) if blob.storage_class else StorageClass.STANDARD,
                        public_url=blob.public_url if blob.public else None,
                        metadata=blob.metadata or {}
                    ))
            
            elif provider == CloudProvider.AZURE_BLOB:
                container_client = client.get_container_client(self.config.bucket_name)
                blobs = container_client.list_blobs(name_starts_with=prefix)
                
                for blob in blobs:
                    objects.append(StorageObject(
                        key=blob.name,
                        size_bytes=blob.size,
                        last_modified=blob.last_modified,
                        etag=blob.etag,
                        storage_class=StorageClass.STANDARD,
                        public_url=None,
                        metadata=blob.metadata or {}
                    ))
            
        except Exception as e:
            logger.error(f"List files failed: {e}")
        
        return objects
    
    async def generate_presigned_url(
        self,
        file_key: str,
        expiration: int = 3600,
        provider: Optional[CloudProvider] = None
    ) -> Optional[str]:
        """Generate presigned URL for temporary access."""
        try:
            provider = provider or self.config.provider
            client = self._get_client(provider)
            
            if provider == CloudProvider.AWS_S3:
                url = client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.config.bucket_name, 'Key': file_key},
                    ExpiresIn=expiration
                )
                return url
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                bucket = client.bucket(self.config.bucket_name)
                blob = bucket.blob(file_key)
                url = blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=expiration),
                    method="GET"
                )
                return url
            
            elif provider == CloudProvider.AZURE_BLOB:
                container_client = client.get_container_client(self.config.bucket_name)
                blob_client = container_client.get_blob_client(file_key)
                
                from azure.storage.blob import generate_blob_sas, BlobSasPermissions
                
                sas_token = generate_blob_sas(
                    account_name=client.account_name,
                    container_name=self.config.bucket_name,
                    blob_name=file_key,
                    account_key=client.credential.account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.utcnow() + timedelta(seconds=expiration)
                )
                
                return f"{blob_client.url}?{sas_token}"
            
        except Exception as e:
            logger.error(f"Generate presigned URL failed: {e}")
            return None
    
    async def move_to_storage_class(
        self,
        file_key: str,
        new_class: StorageClass,
        provider: Optional[CloudProvider] = None
    ) -> bool:
        """Change storage class of existing object."""
        try:
            provider = provider or self.config.provider
            
            if provider == CloudProvider.AWS_S3:
                client = self._get_client(provider)
                client.copy_object(
                    Bucket=self.config.bucket_name,
                    Key=file_key,
                    CopySource={'Bucket': self.config.bucket_name, 'Key': file_key},
                    StorageClass=new_class.value.upper(),
                    MetadataDirective='COPY'
                )
                return True
            
            elif provider == CloudProvider.GOOGLE_CLOUD:
                client = self._get_client(provider)
                bucket = client.bucket(self.config.bucket_name)
                blob = bucket.blob(file_key)
                blob.patch(storage_class=new_class.value.upper())
                return True
            
            # Azure storage class changes not directly supported via copy
            return False
            
        except Exception as e:
            logger.error(f"Change storage class failed: {e}")
            return False
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get storage usage statistics."""
        if not self._upload_history:
            return {"total_uploads": 0}
        
        total_size = sum(u['size_bytes'] for u in self._upload_history)
        
        return {
            "total_uploads": len(self._upload_history),
            "total_bytes_uploaded": total_size,
            "total_gb_uploaded": total_size / (1024**3),
            "average_file_size_mb": (total_size / len(self._upload_history)) / (1024**2) if self._upload_history else 0,
            "providers_used": list(set(u['provider'] for u in self._upload_history))
        }


class MultiCloudManager:
    """
    Manager for multi-cloud storage strategies.
    """
    
    def __init__(self):
        self._managers: Dict[str, CloudStorageManager] = {}
    
    def add_provider(self, name: str, manager: CloudStorageManager) -> None:
        """Add a cloud storage provider."""
        self._managers[name] = manager
    
    async def upload_to_all(
        self,
        local_path: Path,
        file_key: str,
        storage_class: StorageClass = StorageClass.STANDARD
    ) -> Dict[str, UploadResult]:
        """Upload file to all configured providers."""
        results = {}
        
        for name, manager in self._managers.items():
            result = await manager.upload_file(
                local_path,
                file_key,
                storage_class=storage_class
            )
            results[name] = result
        
        return results
    
    async def download_from_best(
        self,
        file_key: str,
        local_path: Path
    ) -> bool:
        """Download from first available provider."""
        for name, manager in self._managers.items():
            if await manager.download_file(file_key, local_path):
                return True
        
        return False


# Global instance
_cloud_manager: Optional[CloudStorageManager] = None


def get_cloud_storage() -> CloudStorageManager:
    """Get global cloud storage manager."""
    global _cloud_manager
    if _cloud_manager is None:
        # Initialize from environment variables
        import os
        
        provider_str = os.getenv('CLOUD_PROVIDER', 'aws_s3')
        provider = CloudProvider(provider_str)
        
        config = StorageConfig(
            provider=provider,
            bucket_name=os.getenv('CLOUD_BUCKET', 'viraclip-storage'),
            region=os.getenv('CLOUD_REGION', 'us-east-1'),
            access_key=os.getenv('CLOUD_ACCESS_KEY'),
            secret_key=os.getenv('CLOUD_SECRET_KEY'),
            project_id=os.getenv('GCS_PROJECT_ID'),
            connection_string=os.getenv('AZURE_CONNECTION_STRING')
        )
        
        _cloud_manager = CloudStorageManager(config)
    
    return _cloud_manager


# Convenience functions
async def upload_to_cloud(
    local_path: Path,
    file_key: str,
    public: bool = False
) -> UploadResult:
    """Upload file to configured cloud storage."""
    return await get_cloud_storage().upload_file(local_path, file_key, public=public)


async def get_cloud_url(file_key: str, expiration: int = 3600) -> Optional[str]:
    """Get presigned URL for cloud file."""
    return await get_cloud_storage().generate_presigned_url(file_key, expiration)
