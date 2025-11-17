# Australian News PWA

A Progressive Web App (PWA) for Australian news with AI-powered summaries, Reddit discussions, and text-to-speech playback.

## Features

- **Dual Content Sources**: GDELT news articles + Reddit discussions from Australian subreddits
- **AI-Powered Summaries**: Google Gemini generates concise 60-word summaries with Australian relevance filtering
- **Intelligent Filtering**: 3-step LLM validation (paywall detection → AU relevance → content verification)
- **Text-to-Speech**: High-quality audio narration using Google Gemini TTS API (WAV format, 24kHz)
- **Cloud Storage**: TTS audio files stored in pCloud for scalability
- **Progressive Web App**: Install on iOS, Android, and Desktop
- **Offline Support**: Service worker caching for offline access
- **Mobile-Optimized**: Card-based interface with swipe navigation
- **Auto-Play**: Automatically advances to next article after audio ends

## Tech Stack

- **Backend**: Flask (Python)
- **AI**: Google Gemini 2.5 Flash (summaries + TTS)
- **Storage**: pCloud API for TTS audio files
- **Data Sources**:
  - GDELT API for Australian news articles
  - Reddit API (PRAW) for r/australia, r/AustralianPolitics, r/sydney, r/melbourne
- **Frontend**: Vanilla JavaScript, CSS with modern animations
- **PWA**: Service Workers, Web App Manifest

## Setup

### 1. Clone Repository
```bash
git clone https://github.com/pkarcreative/pwa-news-app.git
cd news-cards-pwa-Australia
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_gemini_api_key_here
PCLOUD_USERNAME=your_pcloud_email@example.com
PCLOUD_PASSWORD=your_pcloud_password_here
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=AustralianNewsBot/1.0
```

**Getting API Keys**:
- **Gemini API**: Get free API key at https://aistudio.google.com/app/apikey
- **pCloud**: Create free account at https://www.pcloud.com (10GB free storage)
- **Reddit API**: Create app at https://www.reddit.com/prefs/apps (choose "script" type)

### 4. Run Application
```bash
python app.py
```

Access at: `http://localhost:5000`

### 5. Initial News Fetch
After starting the app, fetch news for the first time:
```bash
curl http://localhost:5000/api/fetch-news
```

Or visit in browser: `http://localhost:5000/api/fetch-news`

**Note**: This takes 2-5 minutes (fetches news, generates summaries, creates TTS, uploads to pCloud)

## Production Deployment

**IMPORTANT**: PWA features (service workers, installation) require HTTPS in production.

### Render.com Deployment

**Start Command** (set in Render dashboard):
```bash
gunicorn --bind 0.0.0.0:$PORT --timeout 600 app:app
```

**Environment Variables** (set in Render dashboard):
```
GEMINI_API_KEY=your_key_here
PCLOUD_USERNAME=your_email
PCLOUD_PASSWORD=your_password
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
REDDIT_USER_AGENT=AustralianNewsBot/1.0
```

**Important**: The 600s timeout allows `/api/fetch-news` endpoint to complete TTS generation.

### Memory Optimization

The app includes memory constraints for free hosting:
- **News**: Currently processes all articles (can be limited in code line 625-627)
- **Reddit**: Limited to 15 discussions (line 756-758)

To adjust limits for production with more memory:
1. Uncomment and modify news limit in `app.py` lines 625-627
2. Increase Reddit limit in `app.py` line 758

## PWA Installation

### iOS (Safari)
1. Open app in Safari
2. Tap Share button
3. Select "Add to Home Screen"
4. Tap "Add"

### Android/Desktop (Chrome)
1. Look for "Install App" button
2. Click and confirm installation

## Cost Estimation

### Google Gemini API Costs

Gemini 2.5 Flash has a generous free tier:
- **Free quota**: 1,500 requests/day
- **Lite model**: Used for summaries (cheaper)
- **TTS model**: Used for audio generation

#### Current Usage (10 articles + 15 Reddit posts per fetch)
- Summarization: ~25 LLM calls
- TTS generation: ~25 audio files
- **Cost per fetch**: ~$0.01-0.03 (if exceeding free tier)
- **Monthly (4x daily)**: ~$1.20-3.60

### pCloud Storage
- **Free tier**: 10GB (sufficient for thousands of TTS files)
- Each TTS file: ~50-150KB (WAV format)
- 25 articles = ~1.25-3.75MB per batch

**Total Monthly Cost (Production)**: $1-4 (Gemini only, pCloud free tier)

## Project Structure

```
.
├── app.py                  # Flask backend with news + Reddit fetching
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not in repo)
├── .env.example           # Environment variables template
├── templates/
│   ├── landing.html       # Landing page (news/reddit selection)
│   ├── index.html         # News viewer
│   └── viewer.html        # Reddit discussions viewer
├── static/
│   ├── style.css          # UI styles
│   ├── sw.js              # Service worker
│   ├── manifest.json      # PWA manifest
│   ├── icons/             # App icons
│   └── tts_audio/         # Temporary TTS storage (deleted after upload)
└── app_backup.py          # Backup of previous version
```

## API Endpoints

### User-Facing Endpoints
- `GET /` - Landing page (select News or Reddit)
- `GET /news` - News articles viewer
- `GET /reddit` - Reddit discussions viewer
- `GET /api/news` - Get cached news data (returns 404 if no cache)
- `GET /api/reddit` - Get cached Reddit discussions (returns 404 if no cache)
- `GET /api/tts/<id>` - Stream TTS audio for specific news article
- `GET /api/reddit-tts/<id>` - Stream TTS audio for specific Reddit discussion

### Admin Endpoints
- `GET /api/fetch-news` - **Fetch fresh news, generate summaries & TTS, upload to pCloud**
  - Takes 2-5 minutes to complete
  - Deletes old pCloud TTS files before generating new ones
  - Should be called via external cron service (e.g., cron-job.org)

- `GET /api/fetch-reddit` - **Fetch Reddit discussions, generate summaries & TTS**
  - Similar to fetch-news but for Reddit content
  - Fetches from r/australia, r/AustralianPolitics, r/sydney, r/melbourne

### TTS Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: /api/fetch-news (Cron Job - Every 6 Hours)         │
├─────────────────────────────────────────────────────────────┤
│ 1. Fetch Australian news from GDELT API                    │
│ 2. Scrape full article text + titles                       │
│ 3. Generate AI summaries (Gemini 2.5 Flash Lite)          │
│    - Check Australian relevance                            │
│    - Detect paywalls                                       │
│    - Generate 60-word summary                              │
│ 4. Generate TTS audio (Gemini 2.5 TTS)                    │
│ 5. Upload WAV files to pCloud storage                     │
│ 6. Create permanent public link: getfilepublink()         │
│    → Returns: CODE (e.g., "XkZy7ABC...") ✓ Never expires! │
│ 7. Cache CODE in DataFrame['tts_code']                    │
└─────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: User Opens App                                      │
├─────────────────────────────────────────────────────────────┤
│ Frontend: GET /api/news                                     │
│ Backend:  Returns news with tts_url: "/api/tts/1"          │
│           (Server endpoint, not direct pCloud URL)          │
└─────────────────────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: User Clicks Play Button                            │
├─────────────────────────────────────────────────────────────┤
│ Frontend: GET /api/tts/1 (our server)                      │
│ Backend:  1. Read CODE from cached DataFrame               │
│           2. Call getpublinkdownload(CODE)                 │
│           3. Get fresh download URL from pCloud            │
│           4. Stream WAV audio → Frontend                   │
└─────────────────────────────────────────────────────────────┘

Benefits:
✅ Permanent link codes never expire
✅ Fresh download URLs generated on-demand
✅ No CORS issues (same-origin requests)
✅ Works on all devices (iPhone, Android, Desktop)
✅ High-quality 24kHz WAV audio
```

### Recommended Cron Schedule
```bash
# Update news every 6 hours
0 */6 * * * curl https://your-domain.com/api/fetch-news

# Update Reddit discussions every 6 hours (offset by 3 hours)
0 3,9,15,21 * * * curl https://your-domain.com/api/fetch-reddit

# Or use a web-based cron service:
# - URL: https://your-domain.com/api/fetch-news
# - Method: GET
# - Interval: Every 6 hours
```

## Key Features in Detail

### 3-Step LLM Filtering
Each article passes through intelligent validation:
1. **Paywall Detection**: Filters articles behind paywalls
2. **Australian Relevance**: Ensures content is relevant to Australia (politics, economy, business, culture, sports, or international with AU angle)
3. **Content Verification**: Validates summary contains actual news facts (names, events, places, numbers)

### Reddit Integration
- Fetches discussions from 4 Australian subreddits
- Includes top 5 comments with each post
- Ranks by upvotes (score) and engagement
- Generates combined summaries of post + comments

### Auto-Advance
When TTS finishes, automatically moves to next card and starts playing.

### Keyboard Navigation
- `Arrow Left` - Previous card
- `Arrow Right` - Next card
- `Space` - Play/Pause

### Touch Gestures
- Swipe left - Next card
- Swipe right - Previous card
- Tap play button - Toggle play/pause

## Browser Support

- iOS Safari 11.3+
- Android Chrome 67+
- Desktop Chrome 67+
- Desktop Edge 79+

## Troubleshooting

### News cards show "Title not available"
- Ensure you've run `/api/fetch-news` at least once
- Check that articles passed the 3-step LLM filter
- Verify GDELT API is returning results for Australia

### TTS audio not playing
- Check that pCloud credentials are correct in `.env`
- Ensure pCloud has available storage space
- Verify TTS files were uploaded (check Flask logs)
- Try refreshing the cache with a new `/api/fetch-news` call

### "No news available" error
- Run `/api/fetch-news` to populate the cache
- Check Flask logs for API errors (Gemini quota, GDELT issues)
- Verify all environment variables are set correctly

## License

MIT License

## Author

PKAr Creative

## Support

For issues and feature requests, please open an issue on GitHub.

---

**Last Updated**: 2025-11-17
