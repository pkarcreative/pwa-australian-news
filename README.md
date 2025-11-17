# বাংলা খবর - Bengali News PWA

A Progressive Web App (PWA) for Bengali news with AI-powered summaries and text-to-speech playback.

## Features

- **AI-Powered Summaries**: GPT-4o-mini generates concise 60-word Bengali summaries
- **Text-to-Speech**: Listen to news articles with OpenAI's gpt-4o-mini-tts
- **Cloud Storage**: TTS audio files stored in pCloud for scalability
- **Progressive Web App**: Install on iOS, Android, and Desktop
- **Offline Support**: Service worker caching for offline access
- **Luxurious Design**: Gold & navy color theme with smooth animations
- **Mobile-Optimized**: Card-based interface with swipe navigation
- **Auto-Play**: Automatically advances to next article after audio ends
- **Cron-Ready**: Separate endpoint for scheduled news updates

## Tech Stack

- **Backend**: Flask (Python)
- **AI**: OpenAI API (GPT-4o-mini for summaries, gpt-4o-mini-tts for audio)
- **Storage**: pCloud API for TTS audio files
- **Data Source**: GDELT API for Bengali news
- **Frontend**: Vanilla JavaScript, CSS with modern animations
- **PWA**: Service Workers, Web App Manifest

## Setup

### 1. Clone Repository
```bash
git clone https://github.com/pkarcreative/pwa-news-app.git
cd pwa-news-app
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env` file in the root directory (copy from `.env.example`):
```env
OPENAI_API_KEY=your_openai_api_key_here
PCLOUD_USERNAME=your_pcloud_email@example.com
PCLOUD_PASSWORD=your_pcloud_password_here
```

**Note**: Create a free pCloud account at https://www.pcloud.com and use your credentials above.

### 4. Run Application
```bash
python app.py
```

Access at: `http://localhost:5000`

### 5. Initial News Fetch
After starting the app, fetch news for the first time:
```bash
curl -X POST http://localhost:5000/api/fetch-news
```

Or visit in browser: `http://localhost:5000/api/fetch-news`

**Note**: This takes 2-5 minutes (fetches news, generates summaries, creates TTS, uploads to pCloud)

## Production Deployment

**IMPORTANT**: PWA features (service workers, installation) require HTTPS in production.

### Render.com Deployment

**Start Command** (set in Render dashboard):
```bash
gunicorn --config gunicorn.conf.py app:app
```

Note: The config file automatically detects Render's `$PORT` environment variable.

**Environment Variables** (set in Render dashboard):
```
OPENAI_API_KEY=your_key_here
PCLOUD_USERNAME=your_email
PCLOUD_PASSWORD=your_password
```

**Important**: The `gunicorn.conf.py` file sets a 10-minute timeout for `/api/fetch-news` endpoint.

See [PRODUCTION_SETUP.md](PRODUCTION_SETUP.md) for detailed deployment instructions including:
- Removing testing limitations
- HTTPS setup options
- Icon requirements
- Performance optimization
- Cost estimation
- Security considerations

## PWA Installation

### iOS (Safari)
1. Open app in Safari
2. Tap Share button
3. Select "Add to Home Screen"
4. Tap "Add"

### Android/Desktop (Chrome)
1. Look for "Install App" button
2. Click and confirm installation

For troubleshooting, see [PWA_INSTALL_DEBUG.md](PWA_INSTALL_DEBUG.md)

## Testing Mode

Currently limited to 3 news articles to reduce API costs and fit Render's memory constraints.

**Location**: [app.py:387-390](app.py#L387-L390)

To increase for production:
1. Upgrade Render plan for more memory
2. Or optimize TTS generation further
3. Update the limit in code

## Cost Estimation

### OpenAI API Costs

#### Current (3 articles on Render free tier)
- ~$0.01-0.02 per fetch
- Monthly (4x daily): ~$1.20-2.40

#### Production (50 articles with upgraded hosting)
- ~$0.20-$0.30 per fetch
- Monthly cost (4x daily): ~$24-36

### pCloud Storage
- **Free tier**: 10GB (sufficient for thousands of TTS files)
- Each TTS file: ~50-100KB
- 50 articles = ~2.5-5MB per batch

**Total Monthly Cost (Production)**: $24-36 (OpenAI only, pCloud free tier)

## Project Structure

```
.
├── app.py                  # Flask backend
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not in repo)
├── templates/
│   └── index.html         # Main HTML template
├── static/
│   ├── app.js             # Frontend JavaScript
│   ├── style.css          # Luxurious UI styles
│   ├── sw.js              # Service worker
│   ├── manifest.json      # PWA manifest
│   └── icons/             # App icons
├── random testing/        # Development testing files
└── .env.example           # Environment variables template

```

## API Endpoints

### User-Facing Endpoints
- `GET /` - Main app interface
- `GET /api/news` - Get cached news data (returns 404 if no cache)
- `GET /api/tts/<id>` - Stream TTS audio for specific news article
- `GET /api/status` - Check cache status and info
- `GET /api/stats` - View visitor statistics by country

### Cron/Admin Endpoints
- `POST /api/fetch-news` - **Fetch fresh news, generate summaries & TTS, upload to pCloud**
  - This is the ONLY endpoint that fetches new news
  - Takes 2-5 minutes to complete
  - Deletes old pCloud TTS files before generating new ones
  - Should be called via external cron service (e.g., cron-job.org, EasyCron)

### TTS Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: /api/fetch-news (Cron Job - Every 6 Hours)         │
├─────────────────────────────────────────────────────────────┤
│ 1. Fetch Bengali news from GDELT API                       │
│ 2. Generate AI summaries (GPT-4o-mini)                     │
│ 3. Generate TTS audio (OpenAI TTS)                         │
│ 4. Upload to pCloud storage                                │
│ 5. Create permanent public link: getfilepublink()          │
│    → Returns: CODE (e.g., "XkZy7ABC...") ✓ Never expires!  │
│ 6. Cache CODE in DataFrame['tts_code']                     │
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
│ Backend:  1. Read CODE from DataFrame                      │
│           2. Call getpublinkdownload(CODE)                  │
│           3. Get fresh download URL from pCloud             │
│           4. Stream audio → Frontend                        │
└─────────────────────────────────────────────────────────────┘

Benefits:
✅ Permanent link codes never expire
✅ Fresh download URLs generated on-demand
✅ No CORS issues (same-origin requests)
✅ Works on all devices (iPhone, Android, Desktop)
✅ Server-side streaming (efficient, cacheable)
```

### Recommended Cron Schedule
```bash
# Update news every 6 hours
0 */6 * * * curl -X POST https://your-domain.com/api/fetch-news

# Or use a web-based cron service:
# - URL: https://your-domain.com/api/fetch-news
# - Method: POST
# - Interval: Every 6 hours
```

## Features in Detail

### Ken Burns Effect
Images in news cards have dynamic panning/zooming animation when audio is playing.

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

## License

MIT License

## Author

PKAr Creative

## Support

For issues and feature requests, please open an issue on GitHub.

---

**Last Updated**: 2025-10-18
