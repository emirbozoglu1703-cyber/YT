"""BİR KEZ, kendi bilgisayarınızda çalıştırın. Tarayıcı açılır, kanal hesabınızla giriş yapıp izin verirsiniz.
Çıktıdaki 3 değeri GitHub > Settings > Secrets and variables > Actions'a ekleyin.

  pip install google-auth-oauthlib
  python scripts/get_youtube_token.py client_secret.json
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]

path = sys.argv[1] if len(sys.argv) > 1 else "client_secret.json"
flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
cfg = json.load(open(path))["installed"]
print("\nGitHub Secrets'a ekleyin:\n")
print("YT_CLIENT_ID     =", cfg["client_id"])
print("YT_CLIENT_SECRET =", cfg["client_secret"])
print("YT_REFRESH_TOKEN =", creds.refresh_token)
