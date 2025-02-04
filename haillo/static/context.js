function scrollToBottom() {
    const messagesContainer = document.querySelector('.messages-container');
    const inputContainer = document.querySelector('.input-container');
    const viewportHeight = window.innerHeight;

    // Calculate position to scroll to
    const scrollPosition = document.body.scrollHeight - viewportHeight + inputContainer.offsetHeight + 100;

    window.scrollTo({
        top: scrollPosition,
        behavior: 'smooth'
    });
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
                        result += `<pre><code class="language-${language || 'plaintext'}">${codeBlock.trim()}</code></pre>\n`;
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

// Auto-resize textarea
document.querySelector('.chat-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
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

    // Start observing content changes
    observer.observe(document.querySelector('.main-content'), {
        childList: true,
        subtree: true
    });

    // Common submit function
    function submitForm(e) {
        e.preventDefault();
        document.querySelector('.loading-indicator').style.display = 'block';  // Ensure indicator shows
        document.querySelector('#chat-form').submit();
        setTimeout(scrollToBottom, 100);
    }

    // Handle Send button click
    document.querySelector('.send-button').addEventListener('click', submitForm);

    // Handle Enter key - using same submitForm function
    document.querySelector('.chat-input').addEventListener('keydown', function(e) {
        if (e.keyCode === 13 && !e.shiftKey) {
            e.preventDefault();  // Prevent default here too
            submitForm(e);
        }
    });
});
