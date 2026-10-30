# Firebase + Google Verified-Contacts Setup

This guide wires Keys.ai to your Google account so it can CONFIRM contacts
(identity verified through Google) and, on that basis, send messages.
All networking is pure REST (`requests`) — no Firebase SDK to install.

## What this unlocks

- `google_account` tool: `sign_in | sign_out | status | add_contact |
  list_contacts | verify_contact | confirm_contact | remove_contact |
  find_contact`
- `send_message` with `require_verified=true` → refuses to send to contacts not
  confirmed via Google.
- **Real contact lookup** — when you ask to message a NAME, Keys.ai
  resolves it to the person's actual phone/email from your **Google/mobile
  contacts** (People API) and your Windows `Contacts` folder, so the message
  reaches the right person.
- **Email reading** — `list_emails` / `read_email` let Keys.ai read your Gmail
  inbox ("read my emails", "check my inbox", "read email #2").

---

## Part 1 — Firebase console (console.firebase.google.com)

1. **Create a project** — "Add project" → name it (e.g. `keysai-contacts`) →
   Create. (You can keep Google Analytics off.)

2. **Enable Google sign-in provider**
   - Left sidebar → **Build → Authentication → Get started**.
   - Tab **Sign-in method** → **Google** → toggle **Enable** → Save.
   - Firebase will ask you to configure the **OAuth consent screen** and add a
     support email. If prompted, pick **External** user type.

3. **Create the Firestore database**
   - Left sidebar → **Build → Firestore Database → Create database**.
   - Location: keep the default (or nearest region) → **Next**.
   - **Production mode** → Create.

4. **Set the security rules** (critical — this is how contacts stay private)
   - Firestore → **Rules** tab → replace everything with:

   ```js
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       // Each signed-in user can only read/write their own contacts.
       match /users/{userId}/contacts/{contactId} {
         allow read, write: if request.auth != null && request.auth.uid == userId;
       }
       match /users/{userId} {
         allow read, write: if request.auth != null && request.auth.uid == userId;
       }
     }
   }
   ```

5. **Copy the Web API key + Project ID**
   - Project settings (gear icon) → **General** → **Your apps** → click the
     **`</>` (Web)** icon → register an app (name: `keysai-desktop`) →
     copy the config object. You need exactly:
     - `apiKey`   → `firebase_api_key`
     - `projectId` → `firebase_project_id`

   You do NOT need `authDomain`/`appId` for the REST flow.

---

## Part 2 — Google Cloud console (console.cloud.google.com)

The Firebase project lives inside Google Cloud, so the OAuth client for
"Sign in with Google" is created here.

1. **Open the right project** — top bar → select the project you created in
   Part 1 (it appears automatically).

2. **Configure the OAuth consent screen** (first time only)
   - **APIs & Services → OAuth consent screen** (newer consoles: **Google Auth
     Platform → Branding**).
   - User type **External** → Create.
   - App name: `Keys.ai`, support email: your email → Save.
   - **Scopes** — this is the important part:
     add all **five**: `openid`, `email`, `profile`, **and**
     `https://www.googleapis.com/auth/contacts.readonly` (real mobile contacts)
     **and** `https://www.googleapis.com/auth/gmail.readonly` (read emails).
     Both are 🔒 scopes, but they work while the app is in **Testing** status
     with your Gmail added as a test user — no full Google verification needed
     for personal use. (`gmail.readonly` is a **restricted** scope; it works in
     Testing with test users, and only needs a security assessment if you later
     publish the app to Production.)
   - **Audience**: set your own email as a **Test user** (while the app is in
     Testing mode, only test users can sign in — add your Gmail here).
   - Publish the app when you're ready (from Testing → Production). Note:
     refresh tokens in Testing mode can expire after ~7 days; if contact lookup
     suddenly stops working, just say "sign in with Google" again.

3. **Enable the Google APIs** (needed for contacts + email)
   - **People API**: `https://console.cloud.google.com/apis/library/people.googleapis.com` → **Enable**.
   - **Gmail API**: `https://console.cloud.google.com/apis/library/gmail.googleapis.com` → **Enable**.
   - (Newer consoles: Google Auth Platform has no Library link — use the URLs above.)

4. **Create a Desktop OAuth client**
   - **APIs & Services → Credentials → + Create credentials → OAuth client ID**.
   - Application type: **Desktop app** → name `KeysAI Desktop` → Create.
   - Copy the **Client ID** and **Client Secret**.
   - The localhost loopback redirect (`http://127.0.0.1:<port>/`) is
     auto-allowed for Desktop clients — **no redirect URI needs to be
     registered**. Just don't add a non-loopback redirect.

---

## Part 3 — Put the credentials into Keys.ai

Open `config/api_keys.json` (the same file that holds your Gemini key) and add
exactly these four keys:

```json
{
  "gemini_api_key": "…existing…",
  "google_oauth_client_id": "XXXX.apps.googleusercontent.com",
  "google_oauth_client_secret": "GOCSPX-…",
  "firebase_api_key": "AIza…",
  "firebase_project_id": "keysai-contacts"
}
```

No other files need touching. After this, just say:

- **"sign in with Google"** → a browser tab opens, you approve, Keys.ai stores
  the session (auto-refreshes; no repeated approvals).
- **"add contact Papa with Google account papa@gmail.com"** → Papa is added to
  YOUR Firestore contacts (private to you).
- **"confirm contact Papa"** → Papa is marked Google-confirmed.
- **"send a message to Papa on WhatsApp saying hi, only verified contacts"**
  → send_message gates on the verified contact.
- **"read my emails"** → list_emails shows your recent inbox; **"read email #2"**
  → read_email opens that message.

  ⚠️ After adding `gmail.readonly` to the consent screen, **sign out and sign
  in again** (or re-run "sign in with Google") so the new permission is granted
  — old sessions only carry the scopes approved at the time.

---

## How it works under the hood (no SDK)

1. **Google OAuth** — Keys.ai starts a tiny loopback server on
   `127.0.0.1:<random-port>`, opens your browser to Google's consent screen.
   Google redirects back with an authorization `code`.
2. **Exchange** — `POST https://oauth2.googleapis.com/token` → Google
   `id_token` + `refresh_token`.
3. **Firebase session** — `POST identitytoolkit.googleapis.com/v1/accounts:
   signInWithIdp?key=API_KEY` with `postBody: id_token=…&providerId=google.com`
   → Firebase `idToken` + `refreshToken` + `uid`.
4. **Refresh** — `POST securetoken.googleapis.com/v1/token?key=API_KEY` with
   `grant_type=refresh_token` keeps the session alive without re-approval.
5. **Firestore** — `firestore.googleapis.com/v1/projects/{project}/databases/
   (default)/documents/users/{uid}/contacts/{name}` with
   `Authorization: Bearer <firebase idToken>` — add / list / verify / confirm /
   remove contacts.
6. **People API** — `people.googleapis.com/v1/people:searchContacts?query=…&
   readMask=names,emailAddresses,phoneNumbers` with
   `Authorization: Bearer <google access token>` (Google's own token, refreshed
   via the stored `google_refresh_token`) — searches your real mobile contacts
   by name/phone/email.
7. **Gmail API** — `gmail.googleapis.com/gmail/v1/users/me/messages`
   (list/batchGet/read) with the same Google access token — reads your inbox.
7. **Lookup order** — `find_contact` checks ① your verified Firestore contacts,
   ② your real Google/mobile contacts (People API), ③ `.vcf` files in your
   Windows `Contacts` folder. The best match's phone/email is then used as the
   search target when messaging a spoken name.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Sign-in timed out" | The browser didn't get the redirect. Retry; make sure nothing else occupies the loopback port (Keys.ai picks a random free one). |
| `redirect_uri_mismatch` | You created the wrong client type. It must be **Desktop app** (loopback is auto-allowed). |
| "Firebase sign-in failed (HTTP 400): GOOGLE_SIGNIN_NOT_ENABLED" | The **Google sign-in provider is not enabled** in Firebase. Go to **Build → Authentication → Sign-in method → Google → Enable → Save** (Part 1 step 2). This is the #1 cause of the 400. |
| "Firebase sign-in failed (HTTP 400): API_KEY_NOT_VALID" or `CONFIGURATION_NOT_FOUND` | The `firebase_api_key` doesn't belong to the project where Google sign-in is enabled. Re-copy the Web API key from **that** project's Project settings (Part 1 step 5). |
| "Firebase sign-in failed (HTTP 400): OPERATION_NOT_ALLOWED / INVALID_IDP_RESPONSE" | The Google provider isn't fully configured, or the `requestUri` mismatches. Re-check Part 1 step 2 and re-run "sign in with Google". |
| "Firebase sign-in failed (HTTP 400): …" (other) | Read the code at the end of the message and look it up; the fix is now shown instead of a blind "400 Bad Request". Most codes point to the Google provider (enable it) or the API key (wrong project). |
| "Firebase sign-in failed: …" (no HTTP code) | Google provider not enabled, or the consent screen has no test users / isn't published. Go back to Part 1 step 2 and Part 2 step 2. |
| Firestore returns 403 | Security rules. Re-check Part 1 step 4 — the rules must allow the signed-in user's own `/users/{uid}/contacts`. |
| `400` on refresh | The Firebase refresh token expired (max ~1 year, or after password change). Just say "sign in with Google" again. |
| Contacts empty after reinstall | Contacts live in Firestore (cloud), but your session is local. Re-run "sign in with Google" to reconnect. |
| People API returns 403 "Access Not Configured" | You didn't enable the People API (Part 2 step 3). |
| People API returns 403 "Request had insufficient auth / deleted client" | Testing-mode refresh token expired (~7 days) or the consent screen lacks `contacts.readonly`. Add the scope, re-run "sign in with Google". |
| Gmail returns 403 "Access Not Configured" | You didn't enable the Gmail API (Part 2 step 3). |
| Gmail returns 403 "Request had insufficient auth" | The signed-in session predates `gmail.readonly`. Add the scope in the consent screen, then sign out and sign in again. |
| Contact lookup finds nothing but you know they're in your phone | Your phone contacts only sync to Google if you use a Google account on the phone (Android) or sync via the Google Contacts app (iOS/PC). Open contacts.google.com to confirm they're there. |

## Security notes

- Only the signed-in user can read/write their own contacts (rules above).
- The OAuth client secret + Firebase API key are only used on your machine —
  they are safe to keep in `config/api_keys.json` (don't commit them to a
  public repo).
- `send_message` defaults to requiring verified contacts only
  when Google sign-in is configured; without configuration it behaves exactly
  as before.
