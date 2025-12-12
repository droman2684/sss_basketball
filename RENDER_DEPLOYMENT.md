# Deploying Basketball 2026 to Render

## Prerequisites
- GitHub account (free)
- Render account (free tier available at https://render.com)
- Your Neon database is already set up ✓

## Step 1: Push Your Code to GitHub

1. **Create a new repository on GitHub:**
   - Go to https://github.com/new
   - Name it: `basketball2026` (or whatever you prefer)
   - Make it Public or Private
   - **DO NOT** initialize with README, .gitignore, or license
   - Click "Create repository"

2. **Push your local code to GitHub:**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/basketball2026.git
   git branch -M main
   git push -u origin main
   ```
   Replace `YOUR_USERNAME` with your actual GitHub username

## Step 2: Create a Render Account

1. Go to https://render.com
2. Click "Get Started" or "Sign Up"
3. Sign up with GitHub (recommended) or email
4. Verify your email if needed

## Step 3: Deploy on Render

1. **From Render Dashboard:**
   - Click "New +" button (top right)
   - Select "Web Service"

2. **Connect Your Repository:**
   - Click "Connect account" to link GitHub
   - Find and select your `basketball2026` repository
   - Click "Connect"

3. **Configure Your Web Service:**

   **Name:** `basketball2026` (or your preferred name)

   **Region:** Choose closest to you (e.g., `Oregon (US West)`)

   **Branch:** `main`

   **Root Directory:** (leave blank)

   **Runtime:** `Python 3`

   **Build Command:**
   ```
   pip install -r requirements.txt
   ```

   **Start Command:**
   ```
   gunicorn app:app
   ```

   **Instance Type:** `Free` (for testing)

4. **Add Environment Variables:**

   Click "Advanced" → "Add Environment Variable"

   Add these variables one by one:

   | Key | Value |
   |-----|-------|
   | `DB_NAME` | `neondb` |
   | `DB_USER` | `neondb_owner` |
   | `DB_PASSWORD` | `npg_lcxoET8Ory5I` |
   | `DB_HOST` | `ep-late-breeze-adynrcbm-pooler.c-2.us-east-1.aws.neon.tech` |
   | `SECRET_KEY` | `8f42a7305491794b8865174974718299` |
   | `PYTHON_VERSION` | `3.11.0` |

5. **Create Web Service:**
   - Click "Create Web Service"
   - Render will start building and deploying your app
   - This takes 2-5 minutes

## Step 4: Monitor Deployment

- Watch the build logs in real-time
- Look for "Build successful" message
- Then "Starting service..."
- Finally "Your service is live"

## Step 5: Access Your App

Once deployed, Render gives you a URL like:
```
https://basketball2026.onrender.com
```

Click it to view your live app!

## Troubleshooting

### Build Fails
- Check the logs for errors
- Verify `requirements.txt` has all dependencies
- Make sure Python version is compatible

### App Crashes on Start
- Check "Logs" tab in Render dashboard
- Verify environment variables are set correctly
- Make sure database credentials are correct

### Database Connection Issues
- Verify Neon database is active
- Check that `sslmode=require` is set in code
- Confirm environment variables match Neon credentials

### App is Slow to Start
- Free tier services spin down after 15 minutes of inactivity
- First request after sleep takes ~30 seconds to wake up
- Upgrade to paid tier for always-on service

## Important Notes

1. **Free Tier Limitations:**
   - Services spin down after 15 min of inactivity
   - 750 hours/month of usage
   - Slower performance than paid tiers

2. **Custom Domain (Optional):**
   - Go to Settings → Custom Domain
   - Add your domain
   - Follow DNS setup instructions

3. **Auto-Deploy:**
   - Every `git push` to main branch triggers new deployment
   - Takes 2-5 minutes to redeploy

4. **Logs:**
   - Click "Logs" tab to see real-time application logs
   - Useful for debugging issues

## Updating Your App

To make changes and redeploy:

```bash
# Make your changes to code
git add .
git commit -m "Description of changes"
git push
```

Render automatically redeploys!

## Next Steps

- [ ] Test all features on live site
- [ ] Set up custom domain (optional)
- [ ] Monitor logs for errors
- [ ] Consider upgrading to paid tier for better performance

---

Need help? Check Render docs: https://render.com/docs
