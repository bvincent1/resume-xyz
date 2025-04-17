import requests
from unique_names_generator import get_random_name
from unique_names_generator.data import ADJECTIVES, ANIMALS
import boto3
from botocore.config import Config
import os


class ResumeService:

    def __init__(self, **kwargs):
        self.host = os.getenv("RESUME_SERVICE_HOST")

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
        name = get_random_name(combo=[ADJECTIVES, ADJECTIVES, ANIMALS], separator="-")
        r = requests.post(
            f"{self.host}/api/resume",
            json={
                "slug": name.lower(),
                "title": name.replace("-", ""),
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
            endpoint_url=os.getenv("STORAGE_HOST"),
            region_name=os.getenv("STORAGE_REGION"),
            aws_access_key_id=os.getenv("STORAGE_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("STORAGE_SECRET_KEY"),
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
