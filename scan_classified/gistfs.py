import json
import os
import requests


# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()
 
BASE_URL = "https://api.github.com/gists/{}"
 
 
def get_data(gist_id: str, gist_filename: str) -> dict:
    """Reads the JSON file inside the gist."""

    smtp_host = os.environ.get("SMTP_HOST")
    sender_username = os.environ.get("SMTP_USERNAME")

    response = requests.get(BASE_URL.format(gist_id))
    response.raise_for_status()
    gist = response.json()
    return json.loads(gist["files"][gist_filename]["content"])
 
 
def set_data(gist_id:str, gist_filename: str, data: dict) -> dict:
    """Writes data back into the gist."""

    TOKEN = os.environ.get("GITHUB_TOKEN")
    if not TOKEN:
        raise ValueError("GITHUB_TOKEN environment variable must be set")
    
    payload = {
        "files": {
            gist_filename: {
                "content": json.dumps(data),
            }
        }
    }
    response = requests.patch(
        BASE_URL.format(gist_id),
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=payload,
    )
    response.raise_for_status()
    return response.json()
 
 
if __name__ == "__main__":
    # Example usage
    current = get_data()
    print("Current data:", current)
 
    current["last_updated"] = "2026-03-14"
    result = set_data(current)
    print("Updated gist URL:", result.get("html_url"))
