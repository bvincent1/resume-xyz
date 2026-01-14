import requests
import boto3
from botocore.config import Config
import os
import uuid


class ResumeService:

    def __init__(self, **kwargs):
        self.host = kwargs.get("resume_service_host", os.getenv("RESUME_SERVICE_HOST"))

        if kwargs.get("username") is None or kwargs.get("password") is None:
            raise ValueError("Missing username or password")

        r = requests.post(
            f"{self.host}/api/auth/login",
            json={
                "identifier": kwargs.get("username"),
                "password": kwargs.get("password"),
            },
        )

        self.user_id = r.json()["user"]["id"]
        self.auth_token = list(
            filter(
                lambda s: s.startswith("Authentication"),
                r.headers["set-cookie"].split("; "),
            )
        )[0].replace("Authentication=", "")

    def _get_session_headers(self):
        return {"Cookie": f"Authentication={self.auth_token}; "}

    def create(self):
        name = uuid.uuid4()
        r = requests.post(
            f"{self.host}/api/resume",
            json={
                "slug": str(name),
                "title": str(name).replace("-", ""),
                "visibility": "private",
            },
            headers=self._get_session_headers(),
        )
        return r.json()["id"]

    def update(self, id: str, data: dict):
        requests.patch(
            f"{self.host}/api/resume/{id}",
            json={"data": data},
            headers=self._get_session_headers(),
        )

    def get_pdf_url(self, id: str) -> str | None:
        try:
            r = requests.get(
                f"{self.host}/api/resume/print/{id}",
                headers=self._get_session_headers(),
            )
            return r.json()["url"]
        except KeyError:
            return None

    def delete(self, id: str):
        requests.delete(
            f"{self.host}/api/resume/{id}", headers=self._get_session_headers()
        )

    def logout(self):
        requests.post(
            f"{self.host}/api/auth/logout", headers=self._get_session_headers()
        )

    def __del__(self):
        self.logout()


class FileService:
    def __init__(self, **kwargs):
        self.client = boto3.client(
            "s3",
            endpoint_url=kwargs.get("storage_host", os.getenv("STORAGE_HOST")),
            region_name=kwargs.get("storage_region", os.getenv("STORAGE_REGION")),
            aws_access_key_id=kwargs.get(
                "storage_access_key", os.getenv("STORAGE_ACCESS_KEY")
            ),
            aws_secret_access_key=kwargs.get(
                "storage_secret_key", os.getenv("STORAGE_SECRET_KEY")
            ),
            aws_session_token=None,
            config=Config(signature_version="s3v4"),
            verify=False,
        )
        self.bucket = kwargs.get("bucket", "default")

    def open(self, file_path):
        return (
            self.client.get_object(Bucket=self.bucket, Key=file_path)["Body"]
            .read()
            .decode("utf-8")
        )

    def upload_file(self, file_name, object_name=None):
        """Upload a file to an S3 bucket

        :param file_name: File to upload
        :param bucket: Bucket to upload to
        :param object_name: S3 object name. If not specified then file_name is used
        :return: True if file was uploaded, else False
        """

        # If S3 object_name was not specified, use file_name
        if object_name is None:
            object_name = os.path.basename(file_name)

        # Upload the file
        return self.client.upload_file(file_name, self.bucket, object_name)
