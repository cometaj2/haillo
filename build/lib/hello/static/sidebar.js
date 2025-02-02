document.querySelector('.model-selector').addEventListener('change', function() {
    this.closest('form').submit();
});
async function deleteContext(contextId) {
    if (confirm('Are you sure you want to delete this chat?')) {
        try {
            const response = await fetch(`/context/${contextId}`, {
                method: 'POST',
            });
            if (response.ok) {
                window.location.reload();
            } else {
                alert('Failed to delete chat');
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Failed to delete chat');
        }
    }
}
