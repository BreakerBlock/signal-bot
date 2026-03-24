# SIGNAL Bot — Railway Deployment

## Files in this repo
- `signal_bot.py` — the bot
- `requirements.txt` — Python dependencies
- `Procfile` — tells Railway to run it as a worker

## Deploy in 5 minutes

### 1. Put these files on GitHub
- Go to github.com → New repository → name it `signal-bot` → Public
- Upload all 3 files (signal_bot.py, requirements.txt, Procfile)

### 2. Deploy on Railway
- Go to railway.app → Login with GitHub
- Click "New Project" → "Deploy from GitHub repo"
- Select your `signal-bot` repo
- Railway auto-detects and starts deploying

### 3. Add your environment variables
In Railway, go to your project → Variables tab → add these 3:

| Variable             | Value                                              |
|----------------------|----------------------------------------------------|
| ANTHROPIC_API_KEY    | sk-ant-... (from console.anthropic.com/keys)       |
| TELEGRAM_BOT_TOKEN   | 8387459980:AAGNPljMdN_acR_YbMXZ8qWEs6wjUjOr9SI   |
| TELEGRAM_CHAT_ID     | 1072645054                                         |

### 4. Done
Railway restarts the bot automatically. You'll get a Telegram message
within 30 seconds, then every 2 hours forever.
