// Main App Logic
let newsData = [];
let currentCardIndex = 0;
let touchStartX = 0;
let touchEndX = 0;
let deferredPrompt = null;
let isPlaying = false;  // Global play/pause state
let currentAudio = null;  // Current audio element

// DOM Elements
const cardsContainer = document.getElementById('cardsContainer');
const navDots = document.getElementById('navDots');
const loading = document.getElementById('loading');
const newsCount = document.getElementById('newsCount');
const swipeHint = document.getElementById('swipeHint');
const installButton = document.getElementById('installButton');
const iosInstallPrompt = document.getElementById('iosInstallPrompt');
const iosPromptClose = document.getElementById('iosPromptClose');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');

// Initialize App
async function initApp() {
    try {
        // Fetch news data from Flask API
        const response = await fetch('/api/news');

        // Handle 404 - no cached news
        if (response.status === 404) {
            const errorData = await response.json();
            loading.innerHTML = '<div class="loading-content">' +
                '<p class="loading-text">📰 No news available yet</p>' +
                '<p class="loading-subtext">News collection in progress, you can enjoy it soon!</p>' +
                '<p class="loading-subtext" style="margin-top: 20px; font-size: 0.9em; opacity: 0.7;">Refresh this page in a few minutes</p>' +
                '</div>';
            return;
        }

        // Handle other errors
        if (!response.ok) {
            throw new Error('Failed to fetch news');
        }

        newsData = await response.json();

        // Check if response has error property
        if (newsData.error) {
            loading.innerHTML = '<div class="loading-content">' +
                '<p class="loading-text">📰 No news available yet</p>' +
                '<p class="loading-subtext">News collection in progress, you can enjoy it soon!</p>' +
                '</div>';
            return;
        }

        // Check if it's an array and has items
        if (!Array.isArray(newsData) || newsData.length === 0) {
            loading.innerHTML = '<div class="loading-content">' +
                '<p class="loading-text">No news available</p>' +
                '<p class="loading-subtext">Please try again later</p>' +
                '</div>';
            return;
        }

        // Hide loading, show content
        loading.classList.add('hidden');

        // Render cards and navigation
        renderCards();
        renderNavDots();
        updateNewsCount();

        // Show swipe hint for first-time users
        showSwipeHint();

        // Set up event listeners
        setupEventListeners();

        // Check iOS installation prompt
        checkiOSInstallPrompt();

    } catch (error) {
        console.error('Error loading news:', error);
        loading.innerHTML = '<div class="loading-content">' +
            '<p class="loading-text">Error loading news</p>' +
            '<p class="loading-subtext">' + error.message + '</p>' +
            '</div>';
    }
}

// Render News Cards
function renderCards() {
    cardsContainer.innerHTML = '';
    
    newsData.forEach((news, index) => {
        const card = document.createElement('div');
        card.className = `news-card ${index === 0 ? 'active' : ''}`;
        card.dataset.index = index;
        
        card.innerHTML = `
            <div class="card-image-container">
                <img src="${news.image}" 
                     alt="${news.title}" 
                     class="card-image ${isPlaying ? 'animating' : ''}" 
                     onerror="this.src='https://via.placeholder.com/400x250/cccccc/ffffff?text=No+Image'">
                
                <!-- Play/Pause Button Overlay -->
                <div class="play-button-overlay" data-card-index="${index}">
                    <button class="play-pause-btn" data-card-index="${index}">
                        ${isPlaying ? '⏸' : '▶'}
                    </button>
                </div>
            </div>
            
            <div class="card-content">
                <span class="card-category">${news.category || ''}</span>
                <h2 class="card-title">${news.title}</h2>
                <p class="card-summary">${news.summary}</p>
                <div class="card-footer">
                    <span class="card-source">${news.source || ''}</span>
                    <a href="${news.source_url}" target="_blank" class="read-more-btn">
                        Read Full →
                    </a>
                </div>
            </div>
        `;
        
        cardsContainer.appendChild(card);
    });
    
    // Add play/pause click handlers
    setupPlayButtonHandlers();
}

// Setup Play/Pause Button Handlers
function setupPlayButtonHandlers() {
    const playButtons = document.querySelectorAll('.play-button-overlay');
    
    playButtons.forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            e.stopPropagation();
            togglePlayPause();
        });
    });
}

// Toggle Play/Pause
function togglePlayPause() {
    isPlaying = !isPlaying;

    // Update all play buttons
    updateAllPlayButtons();

    // Update animation on current card
    updateCurrentCardAnimation();

    // TTS Integration
    if (isPlaying) {
        startTTS(currentCardIndex);
    } else {
        pauseTTS();
    }
}

// Start TTS for current card
async function startTTS(cardIndex) {
    try {
        // Stop any currently playing audio
        if (currentAudio) {
            currentAudio.pause();
            currentAudio = null;
        }

        const news = newsData[cardIndex];

        // Check if TTS URL is available
        if (!news.tts_url) {
            console.error('No TTS URL available for this news');
            isPlaying = false;
            updateAllPlayButtons();
            updateCurrentCardAnimation();
            return;
        }

        // Use pCloud download URL directly
        currentAudio = new Audio(news.tts_url);

        // Handle audio end
        currentAudio.addEventListener('ended', () => {
            isPlaying = false;
            updateAllPlayButtons();
            updateCurrentCardAnimation();

            // Auto-advance to next card if available
            if (currentCardIndex < newsData.length - 1) {
                setTimeout(() => {
                    nextCard();
                    // Auto-play next card
                    isPlaying = true;
                    updateAllPlayButtons();
                    updateCurrentCardAnimation();
                    startTTS(currentCardIndex);
                }, 500);
            }
        });

        // Handle audio errors
        currentAudio.addEventListener('error', (e) => {
            console.error('Audio playback error:', e);
            isPlaying = false;
            updateAllPlayButtons();
            updateCurrentCardAnimation();
        });

        await currentAudio.play();

    } catch (error) {
        console.error('Error starting TTS:', error);
        isPlaying = false;
        updateAllPlayButtons();
        updateCurrentCardAnimation();
    }
}

// Pause TTS
function pauseTTS() {
    if (currentAudio) {
        currentAudio.pause();
    }
}

// Update All Play Buttons
function updateAllPlayButtons() {
    const playButtons = document.querySelectorAll('.play-pause-btn');
    playButtons.forEach(btn => {
        btn.textContent = isPlaying ? '⏸' : '▶';
    });
}

// Update Current Card Animation
function updateCurrentCardAnimation() {
    const cards = document.querySelectorAll('.news-card');
    const currentCard = cards[currentCardIndex];
    
    if (currentCard) {
        const image = currentCard.querySelector('.card-image');
        if (isPlaying) {
            image.classList.add('animating');
        } else {
            image.classList.remove('animating');
        }
    }
}

// Render Navigation Dots
function renderNavDots() {
    navDots.innerHTML = '';
    
    newsData.forEach((_, index) => {
        const dot = document.createElement('div');
        dot.className = `dot ${index === 0 ? 'active' : ''}`;
        dot.dataset.index = index;
        dot.addEventListener('click', () => goToCard(index));
        navDots.appendChild(dot);
    });
}

// Update News Count (moved to end of file with arrow states)

// Show Swipe Hint
function showSwipeHint() {
    const hasSeenHint = localStorage.getItem('hasSeenSwipeHint');
    
    if (!hasSeenHint) {
        setTimeout(() => {
            swipeHint.classList.add('hidden');
            localStorage.setItem('hasSeenSwipeHint', 'true');
        }, 3000);
    } else {
        swipeHint.classList.add('hidden');
    }
}

// Go to Specific Card
function goToCard(index) {
    if (index < 0 || index >= newsData.length) return;

    const cards = document.querySelectorAll('.news-card');
    const dots = document.querySelectorAll('.dot');

    // Stop current audio when changing cards
    if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
    }

    // Reset play state
    isPlaying = false;
    updateAllPlayButtons();

    // Update cards
    cards.forEach((card, i) => {
        card.classList.remove('active', 'prev', 'next');

        // Remove animation from all cards
        const image = card.querySelector('.card-image');
        image.classList.remove('animating');

        if (i === index) {
            card.classList.add('active');
        } else if (i < index) {
            card.classList.add('prev');
        } else {
            card.classList.add('next');
        }
    });

    // Update dots
    dots.forEach((dot, i) => {
        dot.classList.toggle('active', i === index);
    });

    currentCardIndex = index;
    updateNewsCount();
}

// Navigate to Next Card
function nextCard() {
    if (currentCardIndex < newsData.length - 1) {
        goToCard(currentCardIndex + 1);
    }
}

// Navigate to Previous Card
function prevCard() {
    if (currentCardIndex > 0) {
        goToCard(currentCardIndex - 1);
    }
}

// Setup Event Listeners
function setupEventListeners() {
    // Touch events for swiping
    cardsContainer.addEventListener('touchstart', handleTouchStart, { passive: true });
    cardsContainer.addEventListener('touchend', handleTouchEnd, { passive: true });
    
    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft') prevCard();
        if (e.key === 'ArrowRight') nextCard();
        if (e.key === ' ' || e.key === 'Spacebar') {
            e.preventDefault();
            togglePlayPause();
        }
    });
    
    // PWA Install prompt for Android/Desktop
    window.addEventListener('beforeinstallprompt', (e) => {
        console.log('beforeinstallprompt event fired');
        e.preventDefault();
        deferredPrompt = e;
        if (installButton) {
            installButton.classList.remove('hidden');
            console.log('Install button shown');
        }
    });

    if (installButton) {
        installButton.addEventListener('click', async () => {
            console.log('Install button clicked');
            if (!deferredPrompt) {
                console.log('No deferredPrompt available');
                return;
            }

            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            console.log('User choice:', outcome);

            if (outcome === 'accepted') {
                installButton.classList.add('hidden');
            }

            deferredPrompt = null;
        });
    }

    // Check if already installed
    window.addEventListener('appinstalled', () => {
        console.log('PWA was installed');
        if (installButton) {
            installButton.classList.add('hidden');
        }
        deferredPrompt = null;
    });
}

// Handle Touch Start
function handleTouchStart(e) {
    touchStartX = e.touches[0].clientX;
}


// Handle Touch End
function handleTouchEnd(e) {
    touchEndX = e.changedTouches[0].clientX;
    handleSwipe();
}

// Handle Swipe Gesture
function handleSwipe() {
    const swipeThreshold = 50;
    const difference = touchStartX - touchEndX;
    
    if (Math.abs(difference) > swipeThreshold) {
        if (difference > 0) {
            // Swiped left - next card
            nextCard();
        } else {
            // Swiped right - previous card
            prevCard();
        }
    }
}

// iOS Installation Detection and Prompt
function checkiOSInstallPrompt() {
    // Detect iOS device
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;

    // Check if running in standalone mode (already installed)
    const isStandalone = window.navigator.standalone === true ||
                         window.matchMedia('(display-mode: standalone)').matches;

    // Check if user has seen/dismissed the prompt
    const hasSeenPrompt = localStorage.getItem('iOSInstallPromptSeen');

    console.log('iOS Detection:', {
        isIOS,
        isStandalone,
        hasSeenPrompt,
        userAgent: navigator.userAgent
    });

    if (isIOS && !isStandalone && !hasSeenPrompt) {
        // Show iOS install prompt after 5 seconds
        console.log('Will show iOS install prompt in 5 seconds');
        setTimeout(() => {
            if (iosInstallPrompt) {
                console.log('Showing iOS install prompt');
                iosInstallPrompt.classList.remove('hidden');
            }
        }, 5000);
    } else {
        console.log('iOS install prompt not shown because:', {
            notIOS: !isIOS,
            alreadyStandalone: isStandalone,
            alreadySeen: !!hasSeenPrompt
        });
    }
}

// Close iOS Install Prompt
if (iosPromptClose) {
    iosPromptClose.addEventListener('click', () => {
        console.log('iOS install prompt closed');
        if (iosInstallPrompt) {
            iosInstallPrompt.classList.add('hidden');
        }
        localStorage.setItem('iOSInstallPromptSeen', 'true');
    });
}

// Navigation Arrow Handlers
if (prevBtn) {
    prevBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        prevCard();
    });
}

if (nextBtn) {
    nextBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        nextCard();
    });
}

// Update Arrow Button States
function updateArrowStates() {
    if (prevBtn && nextBtn) {
        prevBtn.disabled = currentCardIndex === 0;
        nextBtn.disabled = currentCardIndex === newsData.length - 1;
    }
}

// Update newsCount display
function updateNewsCount() {
    newsCount.textContent = `${currentCardIndex + 1} / ${newsData.length}`;
    updateArrowStates();
}

// Debug: Function to manually trigger iOS install prompt (for testing)
function showInstallPromptManually() {
    localStorage.removeItem('iOSInstallPromptSeen');
    checkiOSInstallPrompt();
}

// Make it available globally for console testing
window.showInstallPromptManually = showInstallPromptManually;
window.clearInstallPromptFlag = () => {
    localStorage.removeItem('iOSInstallPromptSeen');
    console.log('Install prompt flag cleared. Reload page to see prompt again.');
};

console.log('💡 Debug Commands Available:');
console.log('- window.showInstallPromptManually() - Manually show iOS install prompt');
console.log('- window.clearInstallPromptFlag() - Clear "already seen" flag');

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', initApp);