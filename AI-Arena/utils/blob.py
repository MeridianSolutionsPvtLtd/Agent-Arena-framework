import os
from io import BytesIO
from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.core.exceptions import AzureError, ResourceNotFoundError
from fastapi import HTTPException
from config import settings


CONNECTION_STRING = settings.BLOB_CONNECTION_STRING
CONTAINER_NAME = settings.CONTAINER_NAME


def get_blob_service_client() -> BlobServiceClient:
    """Create the Blob client only when storage functionality is used."""
    if not CONNECTION_STRING:
        raise HTTPException(
            status_code=503,
            detail="Blob storage is not configured.",
        )

    try:
        return BlobServiceClient.from_connection_string(CONNECTION_STRING)
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Blob storage configuration is invalid.",
        ) from exc


def upload_blob_from_file(file_name: str, file_content: BytesIO, container_name: str = CONTAINER_NAME):
    """
    Uploads a file to Azure Blob Storage and returns the public URL.
    Ensures container exists before uploading.
    """
    blob_service_client = get_blob_service_client()

    try:
        # Ensure container exists
        container_client = blob_service_client.get_container_client(container_name)
        try:
            container_client.get_container_properties()
        except ResourceNotFoundError:
            print(f"Container '{container_name}' not found. Creating...")
            container_client.create_container()

        blob_client = blob_service_client.get_blob_client(container=container_name, blob=file_name)
        blob_client.upload_blob(file_content, overwrite=True)
        print(f"Successfully uploaded: {file_name}")
        return blob_client.url
    except ResourceNotFoundError as e:
        # This catch is for blob-specific not found if needed, 
        # but create_container handles the container-level one above.
        raise HTTPException(status_code=404, detail=f"Resource not found: {e}")
    except AzureError as e:
        print(f"Azure Storage Error: {e}")
        raise HTTPException(status_code=400, detail=f"Blob storage error uploading '{file_name}': {e}")
    except Exception as e:
        print(f"Unexpected error in upload_blob_from_file: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error uploading '{file_name}': {e}")
 
 
def delete_blob(container_name: str, blob_name_or_prefix: str, is_prefix: bool = True):
    """
    Deletes a single blob or all blobs starting with a prefix.
    """
    blob_service_client = get_blob_service_client()

    try:
        container_client = blob_service_client.get_container_client(container_name)
        if is_prefix:
            blobs_to_delete = [b.name for b in container_client.list_blobs() if b.name.startswith(blob_name_or_prefix)]
        else:
            blobs_to_delete = [blob_name_or_prefix]

        if not blobs_to_delete:
            print(f"No blobs found to delete for: {blob_name_or_prefix}")
            return

        for blob_name in blobs_to_delete:
            try:
                container_client.get_blob_client(blob_name).delete_blob()
                print(f"Deleted blob: {blob_name}")
            except ResourceNotFoundError:
                print(f"Blob '{blob_name}' already deleted or not found.")
            except AzureError as e:
                print(f"Error deleting '{blob_name}': {e}")
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found: {e}")
    except AzureError as e:
        raise HTTPException(status_code=400, detail=f"Blob storage error in container '{container_name}': {e}")
    except Exception as e:
        print(f"Unexpected error deleting blobs: {e}")
