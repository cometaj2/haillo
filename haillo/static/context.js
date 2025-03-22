function scrollToBottom() {
    const messagesContainer = document.querySelector('.messages-container');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
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

// Observer for content changes
const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        if (mutation.addedNodes.length) {
            formatCodeBlocks();
            setTimeout(scrollToBottom, 100);
        }
    });
});

document.addEventListener('DOMContentLoaded', () => {
    formatCodeBlocks();
    scrollToBottom();
    document.querySelector(".chat-input").focus();

    // Restore button state from localStorage
    const savedButtonState = localStorage.getItem('vibeButtonState') || 'vibe';
    const button = document.getElementById('vibe-toggle-button');
    button.textContent = savedButtonState === 'stop' ? 'Stop' : 'Vibe';
    button.setAttribute('data-state', savedButtonState);

    // Initial update and periodic check
    updateMessages();
    setInterval(startVibeUpdates, 3000); // Check every 3 seconds when vibing

    // Start observing content changes
    observer.observe(document.querySelector('.messages-container'), {
        childList: true,
        subtree: true
    });

    // Common submit function
    function submitForm(e) {
        e.preventDefault();
        document.querySelector('.loading-indicator').style.display = 'block';
        document.querySelector('#chat-form').submit();
        setTimeout(scrollToBottom, 100);
    }

    // Handle Send button click
    document.querySelector('.send-button').addEventListener('click', submitForm);

    // Handle Enter key
    document.querySelector('.chat-input').addEventListener('keydown', function(e) {
        if (e.keyCode === 13 && !e.shiftKey) {
            e.preventDefault();
            submitForm(e);
        }
    });
});

async function getVibeStatus() {
    const response = await fetch('/vibe_status');
    const text = await response.text();
    return text.trim() !== '';
}

async function startVibeUpdates() {
    const loadingIndicator = document.querySelector('.loading-indicator');
    if (await getVibeStatus()) {
        loadingIndicator.style.display = 'block';
        updateMessages();
    } else {
        loadingIndicator.style.display = 'none';
    }
}

async function toggleVibe() {
    const button = document.getElementById('vibe-toggle-button');
    const currentState = button.getAttribute('data-state');
    const loadingIndicator = document.querySelector('.loading-indicator');
    button.disabled = true;
    loadingIndicator.style.display = 'block';
    const endpoint = currentState === 'vibe' ? '/vibestart' : '/vibestop';

    await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
    const newState = currentState === 'vibe' ? 'stop' : 'vibe';
    button.textContent = newState === 'vibe' ? 'Vibe' : 'Stop';
    button.setAttribute('data-state', newState);
    localStorage.setItem('vibeButtonState', newState);
    updateMessages();
    loadingIndicator.style.display = (await getVibeStatus()) ? 'block' : 'none';
    button.disabled = false;
}

async function updateMessages() {
    const response = await fetch('/');
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const newMessagesContainer = doc.querySelector('.messages-container');
    const currentMessagesContainer = document.querySelector('.messages-container');
    if (newMessagesContainer && currentMessagesContainer) {
        currentMessagesContainer.innerHTML = newMessagesContainer.innerHTML;
        formatCodeBlocks();
        scrollToBottom();
    }
    const button = document.getElementById('vibe-toggle-button');
    const savedState = localStorage.getItem('vibeButtonState');
    button.textContent = savedState === 'stop' ? 'Stop' : 'Vibe';
    button.setAttribute('data-state', savedState);
    document.querySelector('.loading-indicator').style.display = (await getVibeStatus()) ? 'block' : 'none';
    button.disabled = false;
}
