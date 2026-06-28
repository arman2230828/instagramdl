document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('processForm');
    if (!form) return;

    const submitBtn = document.getElementById('submitBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader');
    
    const resultSection = document.getElementById('resultSection');
    const successCard = document.getElementById('successCard');
    const errorCard = document.getElementById('errorCard');
    
    const mediaTitle = document.getElementById('mediaTitle');
    const processTime = document.getElementById('processTime');
    const errorMsg = document.getElementById('errorMsg');
    const retryBtn = document.getElementById('retryBtn');

    let currentMode = 'reel';
    const mediaUrlInput = document.getElementById('mediaUrl');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const urlInput = mediaUrlInput.value;
        
        if (!urlInput) {
            showToast('Please enter a URL', 'error');
            return;
        }

        // UI Loading state
        setLoadingState(true);
        resultSection.classList.add('hidden');
        successCard.classList.add('hidden');
        errorCard.classList.add('hidden');

        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}/api/process`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url: urlInput, mode: currentMode })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                // Populate Success Card
                mediaTitle.textContent = data.media_title || 'Media Processed';
                
                if (data.timestamp) {
                    const date = new Date(data.timestamp);
                    processTime.textContent = `Processed on: ${date.toLocaleString()}`;
                }

                const carouselContainer = document.getElementById('carouselContainer');
                const template = document.getElementById('mediaItemTemplate');
                carouselContainer.innerHTML = ''; // Clear previous items

                const itemsToRender = data.items && data.items.length > 0 ? data.items : [];
                
                // Fallback for single item from old API schema
                if (itemsToRender.length === 0 && data.action_url) {
                    itemsToRender.push({
                        thumbnail_url: data.thumbnail_url,
                        action_url: data.action_url,
                        is_video: true
                    });
                }

                itemsToRender.forEach((item, index) => {
                    const clone = template.content.cloneNode(true);
                    const mediaThumbnail = clone.querySelector('.media-thumb');
                    const thumbnailSkeleton = clone.querySelector('.skeleton-loader');
                    const thumbnailFallback = clone.querySelector('.thumbnail-fallback');
                    const fallbackText = clone.querySelector('.fallback-text');
                    const actionBtn = clone.querySelector('.item-download-btn');

                    if (item.thumbnail_url) {
                        mediaThumbnail.classList.add('hidden');
                        thumbnailFallback.classList.add('hidden');
                        thumbnailSkeleton.classList.remove('hidden');
                        
                        const proxiedUrl = `${CONFIG.API_BASE_URL}/api/proxy-image?url=${encodeURIComponent(item.thumbnail_url)}`;
                        const img = new Image();
                        img.onload = () => {
                            mediaThumbnail.src = proxiedUrl;
                            mediaThumbnail.classList.remove('hidden');
                            thumbnailSkeleton.classList.add('hidden');
                        };
                        img.onerror = () => {
                            thumbnailSkeleton.classList.add('hidden');
                            thumbnailFallback.classList.remove('hidden');
                            fallbackText.textContent = "Failed to load preview";
                        };
                        img.src = proxiedUrl;
                    } else {
                        mediaThumbnail.classList.add('hidden');
                        thumbnailSkeleton.classList.add('hidden');
                        thumbnailFallback.classList.remove('hidden');
                        fallbackText.textContent = "No preview available";
                    }
                    
                    if (item.action_url) {
                        const safeTitle = encodeURIComponent((data.media_title || 'instadl_media').substring(0, 30).replace(/[^a-zA-Z0-9]/g, '_')) + (itemsToRender.length > 1 ? `_${index+1}` : '');
                        const ext = item.is_video ? 'mp4' : 'jpg';
                        
                        actionBtn.href = `${CONFIG.API_BASE_URL}/api/proxy-download?url=${encodeURIComponent(item.action_url)}&title=${safeTitle}&ext=${ext}`;
                        actionBtn.target = '_self'; 
                        actionBtn.removeAttribute('target');
                        actionBtn.removeAttribute('rel');
                        actionBtn.setAttribute('download', 'media');
                        actionBtn.textContent = `Download ${item.is_video ? 'Video' : 'Image'}`;
                    } else {
                        actionBtn.classList.add('hidden');
                    }

                    carouselContainer.appendChild(clone);
                });

                resultSection.classList.remove('hidden');
                successCard.classList.remove('hidden');
                showToast('URL processed successfully!', 'success');
            } else {
                throw new Error(data.detail || data.message || 'Failed to process URL');
            }
        } catch (error) {
            errorMsg.textContent = error.message;
            resultSection.classList.remove('hidden');
            errorCard.classList.remove('hidden');
            showToast(error.message, 'error');
        } finally {
            setLoadingState(false);
        }
    });

    retryBtn.addEventListener('click', () => {
        resultSection.classList.add('hidden');
        document.getElementById('mediaUrl').focus();
    });

    function setLoadingState(isLoading) {
        if (isLoading) {
            submitBtn.disabled = true;
            btnText.classList.add('hidden');
            loader.classList.remove('hidden');
        } else {
            submitBtn.disabled = false;
            btnText.classList.remove('hidden');
            loader.classList.add('hidden');
        }
    }
});

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        if (container.contains(toast)) {
            container.removeChild(toast);
        }
    }, 3500);
}
