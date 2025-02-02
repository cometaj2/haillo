document.querySelector('.chat-input').addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = (this.scrollHeight) + 'px';
});

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
                        // Removed 'line-numbers' class
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

document.addEventListener('DOMContentLoaded', formatCodeBlocks);

const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        if (mutation.addedNodes.length) {
            formatCodeBlocks();
        }
    });
});

document.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.querySelector('.main-content'), {
        childList: true,
        subtree: true
    });
});
