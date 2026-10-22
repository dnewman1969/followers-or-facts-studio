# YouTube upload setup (free, one time)

The Upload stage uses the YouTube Data API. It needs an OAuth client file
from Google Cloud. No billing is involved.

1. Go to https://console.cloud.google.com/ and create a project (e.g. "Followers or Facts Studio").
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen** → External → fill in the app name and your email.
   Add yourself as a **Test user**.
4. **Credentials → Create credentials → OAuth client ID → Desktop app**. Download the JSON.
5. Save it as `F:\AI\fof-data\youtube-client.json`, and put that path in
   Settings → youtube → `client_secrets`.
6. The first upload opens your browser to sign in. The login is saved in `fof-data\youtube-token.json`.

## Things to know

- **Uploads are private until Google audits your project.** That's fine: the Studio uploads
  as private anyway, and you flip it public in YouTube Studio after checking it.
- **About six uploads a day** fit in the free quota (an upload costs ~1,600 of 10,000 units).
- **While the consent screen is in "Testing" mode, the login expires after 7 days.** The
  Studio just asks you to sign in again.
- **Custom thumbnails need a phone-verified channel.** If it isn't, the upload still works
  and the log says to set the thumbnail in YouTube Studio.
- Every upload is marked as containing altered or synthetic content, as YouTube requires
  for realistic AI imagery.
