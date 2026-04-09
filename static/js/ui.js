/* static/js/ui.js */
marked.use({ breaks: true });

function formatStep1Info(text) {
    let formatted = text.replace(/🗂/g, '<div class="inline-flex items-center justify-center w-8 h-8 bg-blue-50 text-blue-500 rounded-[40%_60%_70%_30%/40%_50%_60%_50%] mr-3 mb-1"><i class="fas fa-folder-open text-xs"></i></div>');
    formatted = formatted.replace(/✅/g, '<div class="inline-flex items-center justify-center w-8 h-8 bg-green-50 text-green-500 rounded-[60%_40%_30%_70%/60%_30%_70%_40%] mr-3 mb-1"><i class="fas fa-check text-xs"></i></div>');
    formatted = formatted.replace(/🔍/g, '<div class="inline-flex items-center justify-center w-8 h-8 bg-purple-50 text-purple-500 rounded-[50%_50%_20%_80%/25%_25%_75%_75%] mr-3 mb-1"><i class="fas fa-search text-xs"></i></div>');
    
    formatted = formatted.replace(/\*\*(Классификация.*?)\*\*/g, '<strong class="text-brand-dark tracking-wide uppercase text-sm">$1</strong>');
    formatted = formatted.replace(/\*\*(Найденные.*?)\*\*/g, '<strong class="text-brand-dark tracking-wide uppercase text-sm">$1</strong>');
    formatted = formatted.replace(/\*\*(Взяты.*?)\*\*/g, '<strong class="text-brand-dark tracking-wide uppercase text-sm">$1</strong>');
    
    formatted = formatted.replace(/^(Статья\/Пункт.*)$/gm, '<div class="text-sm text-gray-500 bg-gray-50/50 p-2 px-3 rounded-lg mb-2 border border-gray-100 flex items-center before:content-[\'📄\'] before:mr-2">$1</div>');
    formatted = formatted.replace(/^(•.*)$/gm, '<div class="text-sm font-medium text-brand-main bg-brand-lightBg p-2 px-3 rounded-lg inline-block mb-2 mr-2 border border-brand-inputBorder">$1</div>');
    
    return marked.parse(formatted);
}

function toggleTooltip(id) {
    const el = document.getElementById(id);
    if (el) {
        if (el.classList.contains('opacity-0')) {
            document.querySelectorAll('.eval-tooltip').forEach(tooltip => {
                tooltip.classList.add('opacity-0', 'invisible');
                tooltip.classList.remove('pointer-events-auto');
            });
            el.classList.remove('opacity-0', 'invisible');
            el.classList.add('pointer-events-auto');
        } else {
            el.classList.add('opacity-0', 'invisible');
            el.classList.remove('pointer-events-auto');
        }
    }
}

function closeTooltip(id) {
    const el = document.getElementById(id);
    if (el) {
        el.classList.add('opacity-0', 'invisible');
        el.classList.remove('pointer-events-auto');
    }
}

function showError(msg) {
    document.getElementById('loading-state')?.classList.add('hidden');
    document.getElementById('success-state')?.classList.add('hidden');
    const errorState = document.getElementById('error-state');
    if (errorState) {
        errorState.classList.remove('hidden');
    }
    if(msg) {
        const errorMsg = document.getElementById('error-message');
        if (errorMsg) errorMsg.textContent = msg;
    }
}

function downloadDB() {
    window.location.href = '/api/db/download';
}

function downloadTextFile(content, filename) {
    if (!content) return;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}