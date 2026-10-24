# YouTube sign-in and upload (free, one time, about 10 minutes)

The Studio uploads with the free YouTube Data API. You make a small "app" in Google Cloud that only
you use, download its sign-in file, and sign in once from the Studio. No billing, no card.

## Set it up

1. Go to https://console.cloud.google.com/ and make a **New project** (call it "FoF Studio").
2. **APIs & Services → Library** → search **YouTube Data API v3** → **Enable**.
3. **Google Auth Platform** (it used to be called "OAuth consent screen"):
   - **Branding:** app name "FoF Studio", your email as the support email.
   - **Audience:** choose **External**, and add your own Gmail as a **test user**.
4. **Data access → Add or remove scopes:** tick `.../auth/youtube.upload` and `.../auth/youtube.force-ssl`
   (upload, thumbnail, captions, and reading your channel's name).
5. **Clients → Create client → Desktop app** → **Create** → **Download JSON**.
6. **Audience → Publish app** → confirm. This moves it to **In production**. Without this step Google
   signs you out every 7 days. Google doesn't need to review an app only you use (under 100 users).
7. In the Studio: **Settings → YouTube → Choose client file...** and pick the JSON you downloaded. (If you
   just leave the downloaded `client_secret_....json` in your Downloads folder, on the Desktop or in
   `F:\AI\fof-data`, the Studio finds it by itself.)
8. **Sign in to YouTube.** A browser tab opens. Pick the Google account that owns the channel (or its
   Brand Account). Google warns "Google hasn't verified this app": that's expected for your own app.
   Click **Advanced → Go to FoF Studio (unsafe)**, allow access, and close the tab.
9. Settings now says **Signed in as <your channel>**. The sign-in is kept in `fof-data\youtube-token.json`.

## First upload: one quick check

Upload a short test video first (any finished episode will do) as **Private**. Then open it in YouTube
Studio and try switching it to **Unlisted**. If YouTube says **"Locked as private"**, Google is
applying an old rule to new, unaudited projects; you can still publish by uploading from YouTube Studio
yourself, or fill in Google's free API audit form. Google's own pages disagree about whether the lock
still applies in 2026, so this test is the way to find out.

## Uploading from the Publish page

Press **Upload to YouTube (private)**. The line under the button shows what's ready: the YouTube packages,
your client file, and whether you're signed in. If you're not signed in, a browser tab opens to sign in
and the upload starts when you come back. If the video hasn't been written up yet, it's written up and
uploaded in one go.

## Automatic upload after the final render

With Settings → YouTube → **Upload automatically** ticked (the default), every final render (not a
preview) is written up and uploaded straight away as **Private**: title, description with every
source link and the AI disclosure, tags (trimmed to YouTube's 500-character limit), category and the
thumbnail. When it's done the Studio opens the video in **YouTube Studio** so you can see YouTube's
checks (copyright, ad suitability) before you make it public. The Publish page keeps both links.
If something in the write-up needs your attention (a blocked check), it stops before uploading and
the Publish page says what to fix.

## Good to know

- **Uploads are private by default** (Settings → YouTube → Upload as). Check the video, pin the
  comment with the proof links, then make it public in YouTube Studio.
- **Plenty of uploads per day.** Since June 2026 uploads have their own quota (about 100 a day).
- **Custom thumbnails need a phone-verified channel.** If yours isn't, the upload still works and the
  log says to set the thumbnail in YouTube Studio (files up to 50 MB are accepted since September 2026).
- **AI disclosure:** every upload is marked "contains altered or synthetic content", and the
  description says the illustrations are AI and labelled on screen. Caricatures get an extra line.
- **Subscribers aren't notified** of the private upload; they'll see it when you make it public.
- If an upload says the sign-in ran out, go to Settings → YouTube → **Sign in again**. A job never opens
  a browser by itself in the middle of an upload.
