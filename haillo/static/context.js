// Simple solution for message refreshing and loading indicators
let isVibing = false;
let refreshTimer = null;
// Add a transition lock to prevent indicator flashing during vibe toggle
let isVibingTransition = false;

function scrollToBottom() {
    const messagesContainer = document.querySelector('.messages-container');
    if (messagesContainer) {
        // Force layout calculation before scrolling
        const height = messagesContainer.scrollHeight;
        messagesContainer.scrollTop = height;

        // Double-check scrolling happened (some browsers need extra push)
        if (messagesContainer.scrollTop < height - messagesContainer.clientHeight) {
            messagesContainer.scrollTop = height;
        }
    }
}

function formatCodeBlocks() {
    const messages = document.querySelectorAll('.message-content');
    messages.forEach(message => {
        if (!message.dataset.formatted) {
            const content = message.innerHTML;
            let result = '';
            let codeBlock = '';
            let language = '';
            let isInCodeBlock = false;
            const lines = content.split('\n');
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                if (line.trim().startsWith('```')) {
                    if (!isInCodeBlock) {
                        isInCodeBlock = true;
                        language = line.trim().slice(3).trim();
                        codeBlock = '';
                    } else {
                        isInCodeBlock = false;
                        result += `<div class="language">${language || 'plaintext'}</div><pre><code class="language-${language || 'plaintext'}">${codeBlock.trim()}</code></pre>`;
                    }
                } else {
                    if (isInCodeBlock) {
                        codeBlock += line + '\n';
                    } else {
                        result += line + '\n';
                    }
                }
            }
            message.innerHTML = result;
            message.dataset.formatted = 'true';
            Prism.highlightAllUnder(message);
        }
    });
}

// Auto-resize textarea and adjust messages padding
document.querySelector('.chat-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';

    // Update messages container padding
    const inputContainer = document.querySelector('.input-container');
    const messagesContainer = document.querySelector('.messages-container');
    const totalInputHeight = inputContainer.offsetHeight + 20; // Add extra padding
    messagesContainer.style.paddingBottom = `${totalInputHeight}px`;
});

// Check vibe status more reliably
async function getVibeStatus() {
    try {
        const response = await fetch('/vibe_status');
        const text = await response.text();
        isVibing = text.trim() !== '';
        return isVibing;
    } catch (error) {
        console.error('Error checking vibe status:', error);
        return false;
    }
}

// Simplified refresh mechanism
function startRefresh() {
    // Clear any existing timer
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }

    // Immediately check status and update indicator
    updateLoadingIndicator();

    // Set a reasonable interval - 2 seconds is a good balance
    refreshTimer = setInterval(() => {
        updateLoadingIndicator();
    }, 2000);
}

// Separate function to update loading indicator
async function updateLoadingIndicator() {
    try {
        const vibeStatus = await getVibeStatus();

        // Always create a new loading indicator to ensure it's properly displayed
        let loadingIndicator = document.querySelector('.loading-indicator');

        // If no loading indicator exists, create one
        if (!loadingIndicator) {
            const messagesContainer = document.querySelector('.messages-container');
            if (messagesContainer) {
                loadingIndicator = document.createElement('div');
                loadingIndicator.className = 'loading-indicator';
                loadingIndicator.innerHTML = '<div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
                messagesContainer.appendChild(loadingIndicator);
            }
        }

        if (loadingIndicator) {
            // Force display style update - don't hide indicator during vibe transition
            const shouldShow = vibeStatus || isVibingTransition || window.waitingForResponse;
            if (shouldShow) {
                loadingIndicator.style.display = 'block';
            } else {
                loadingIndicator.style.display = 'none';
            }
        }

        if (vibeStatus) {
            // Only refresh content when vibing
            updateMessages();
        }
    } catch (error) {
        console.error('Error updating loading indicator:', error);
    }
}

async function updateMessages() {
    try {
        const shouldShowIndicator = window.waitingForResponse || isVibing || isVibingTransition;

        const response = await fetch('/');
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');
        const newMessagesContainer = doc.querySelector('.messages-container');

        if (newMessagesContainer) {
            const currentMessagesContainer = document.querySelector('.messages-container');
            if (currentMessagesContainer) {
                // Find existing loading indicator
                let loadingIndicator = currentMessagesContainer.querySelector('.loading-indicator');

                // Create a fragment for new messages
                const fragment = document.createDocumentFragment();
                Array.from(newMessagesContainer.children).forEach(child => {
                    if (!child.classList.contains('loading-indicator')) {
                        fragment.appendChild(child.cloneNode(true));
                    }
                });

                // Clear current messages except loading indicator
                Array.from(currentMessagesContainer.children).forEach(child => {
                    if (!child.classList.contains('loading-indicator')) {
                        child.remove();
                    }
                });

                // Insert new messages before the loading indicator if it exists
                if (loadingIndicator) {
                    currentMessagesContainer.insertBefore(fragment, loadingIndicator);
                } else {
                    currentMessagesContainer.appendChild(fragment);
                }

                // Ensure loading indicator is present and correctly visible
                ensureLoadingIndicator(shouldShowIndicator);

                formatCodeBlocks();
                setTimeout(scrollToBottom, 100);
            }
        }
    } catch (error) {
        console.error('Error updating messages:', error);
    }
}

// Toggle vibe state - Fixed version with transition lock
async function toggleVibe() {
    const button = document.getElementById('vibe-toggle-button');
    if (!button) return;

    button.disabled = true;

    // Set transition state to prevent indicator flashing
    isVibingTransition = true;

    // Show loading indicator immediately for better feedback
    ensureLoadingIndicator(true);

    try {
        // Simple toggle based on current button text
        const startingVibe = button.textContent === 'Vibe';

        if (startingVibe) {
            // Start vibing
            await fetch('/vibestart', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' } 
            });
            button.textContent = 'Stop';
            button.setAttribute('data-state', 'stop');
            localStorage.setItem('vibeButtonState', 'stop');
            isVibing = true;
        } else {
            // Stop vibing
            await fetch('/vibestop', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' } 
            });
            button.textContent = 'Vibe';
            button.setAttribute('data-state', 'vibe');
            localStorage.setItem('vibeButtonState', 'vibe');
            isVibing = false;
        }

        // Keep indicator visible until we're sure the vibe status has been properly updated
        ensureLoadingIndicator(true);

        // Force immediate message update after toggling
        await updateMessages();

        // For better UX, add a small delay before checking final status
        await new Promise(resolve => setTimeout(resolve, 1000));

        // Final status check
        const finalStatus = await getVibeStatus();

        // Only now release the transition lock
        isVibingTransition = false;

        // Final update of indicator based on actual status
        ensureLoadingIndicator(finalStatus || window.waitingForResponse);

        // If we just started vibing, set waiting flag
        if (startingVibe && finalStatus) {
            window.waitingForResponse = true;
            ensureLoadingIndicator(true);
        }
    } catch (error) {
        console.error('Error toggling vibe:', error);
        // Release transition lock on error
        isVibingTransition = false;
        ensureLoadingIndicator(isVibing || window.waitingForResponse);
    } finally {
        button.disabled = false;
    }
}

// Form submission
function submitForm(e) {
    e.preventDefault();

    // Show loading indicator immediately
    ensureLoadingIndicator(true);

    // Submit the form
    const form = document.querySelector('#chat-form');
    if (form) {
        form.submit();
    }

    const inputField = document.querySelector('.chat-input');
    if (inputField) { inputField.value = ''; }

    // Set a flag to indicate we're waiting for a response
    window.waitingForResponse = true;

    // Schedule multiple updates with forced loading indicators
    for (let delay of [500, 1000, 2000, 3000, 5000]) {
        setTimeout(() => {
            if (window.waitingForResponse) {
                ensureLoadingIndicator(true);
                updateMessages();
            }
        }, delay);
    }

    // Add extra scroll attempts
    setTimeout(scrollToBottom, 1100);
    setTimeout(scrollToBottom, 3100);
}

// Helper function to ensure loading indicator exists and is visible
function ensureLoadingIndicator(visible) {
    let loadingIndicator = document.querySelector('.loading-indicator');
    const messagesContainer = document.querySelector('.messages-container');

    if (!messagesContainer) return;

    // Create indicator if it doesn't exist
    if (!loadingIndicator) {
        loadingIndicator = document.createElement('div');
        loadingIndicator.className = 'loading-indicator';
        loadingIndicator.innerHTML = '<div class="dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>';
        messagesContainer.appendChild(loadingIndicator);
    }

    // Set visibility
    if (loadingIndicator) {
        loadingIndicator.style.display = visible ? 'block' : 'none';
    }
}

// Initialize everything when page loads
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize global state
    window.waitingForResponse = false;
    isVibingTransition = false;

    formatCodeBlocks();
    scrollToBottom();
    document.querySelector(".chat-input").focus();

    // Restore button state but verify with actual status
    const status = await getVibeStatus();
    const button = document.getElementById('vibe-toggle-button');
    if (button) {
        button.textContent = status ? 'Stop' : 'Vibe';
        button.setAttribute('data-state', status ? 'stop' : 'vibe');
    }

    // Update loading indicator based on status
    ensureLoadingIndicator(status);

    // Start regular refresh
    startRefresh();

    // Set up content change observer
    const observer = new MutationObserver(() => {
        formatCodeBlocks();
        scrollToBottom();
    });

    const messagesContainer = document.querySelector('.messages-container');
    if (messagesContainer) {
        observer.observe(messagesContainer, {
            childList: true,
            subtree: true
        });
    }

    // Button event listeners
    document.querySelector('.send-button')?.addEventListener('click', submitForm);
    document.querySelector('.chat-input')?.addEventListener('keydown', function(e) {
        if (e.keyCode === 13 && !e.shiftKey) {
            e.preventDefault();
            submitForm(e);
        }
    });
});

// Expose toggle function for HTML
window.toggleVibe = toggleVibe;
