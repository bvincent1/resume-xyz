import requests
from unique_names_generator import get_random_name
from unique_names_generator.data import ADJECTIVES, ANIMALS


class ResumeService:
    host = "http://localhost:5173"

    def __init__(self, **kwargs):
        if kwargs.get("username") is None or kwargs.get("password") is None:
            raise ValueError("Missing username or password")

        r = requests.post(
            f"{ResumeService.host}/api/auth/login",
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

    def get_session_headers(self):
        return {"Cookie": f"Authentication={self.auth_token}; "}

    def create(self):
        name = get_random_name(combo=[ADJECTIVES, ADJECTIVES, ANIMALS], separator="-")
        r = requests.post(
            f"{ResumeService.host}/api/resume",
            json={
                "slug": name.lower(),
                "title": name.replace("-", ""),
                "visibility": "private",
            },
            headers=self.get_session_headers(),
        )
        return r.json()["id"]

    def update(self, id, data):
        requests.patch(
            f"{ResumeService.host}/api/resume/{id}",
            json={"data": data},
            headers=self.get_session_headers(),
        )

    def get_pdf_url(self, id):
        r = requests.get(
            f"{ResumeService.host}/api/resume/print/{id}",
            headers=self.get_session_headers(),
        )
        return r.json()["url"]

    def delete(self, id):
        requests.delete(
            f"{ResumeService.host}/api/resume/{id}", headers=self.get_session_headers()
        )

    def logout(self):
        requests.post(
            f"{ResumeService.host}/api/auth/logout", headers=self.get_session_headers()
        )

    def __del__(self):
        self.logout()
