/* static/js/api.js */
async function evaluateMainAudio() {
    const btn = document.getElementById('step4-audio-evaluate-btn');
    const audioSourceEl = document.getElementById('step4-audio-source');
    if (!audioSourceEl || !audioSourceEl.src) return;
    const audioSource = audioSourceEl.src;
    
    const model = document.getElementById('regen-model')?.value || 'eleven_v3';
    const voice = document.getElementById('regen-voice')?.value || 'FGY2WhTYpPnroxEErjIq';
    const stability = parseFloat(document.getElementById('regen-stability')?.value) || 0.5;
    const similarity = parseFloat(document.getElementById('regen-similarity')?.value) || 0.75;
    const style = document.getElementById('regen-style') ? parseFloat(document.getElementById('regen-style').value) : 0.25;
    const boost = document.getElementById('regen-boost') ? document.getElementById('regen-boost').checked : true;
    
    const step3Element = document.getElementById('step3-audio-text');
    const text = step3Element ? (step3Element.innerText || step3Element.textContent) : '';
    
    let relativeAudioUrl;
    try {
        relativeAudioUrl = new URL(audioSource).pathname;
    } catch(e) {
        relativeAudioUrl = audioSource;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
    btn.classList.add('opacity-80', 'cursor-not-allowed');
    
    try {
        const response = await fetch('/api/evaluate_audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                audio_url: relativeAudioUrl,
                text: text,
                elevenlabs_model: model,
                elevenlabs_voice: voice,
                stability: stability,
                similarity_boost: similarity,
                style: style,
                use_speaker_boost: boost,
                slug: window.currentSlug || null,
                is_main: true
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || data.detail || 'Ошибка оценки');
        }
        
        document.getElementById('evaluation-result-container').classList.remove('hidden');
        document.getElementById('eval-percent').textContent = data.percent_ideal + '%';
        document.getElementById('eval-stability').textContent = data.stability;
        document.getElementById('eval-similarity').textContent = data.similarity;
        document.getElementById('eval-do-better').textContent = data.do_better || 'Нет рекомендаций';
        if (data.cost) {
            document.getElementById('eval-cost').textContent = `Цена: $${parseFloat(data.cost).toFixed(3)}`;
        }
        
    } catch (error) {
        alert("Ошибка: " + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-star"></i>';
        btn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
}

async function evaluateAdditionalAudio(id, audioUrl, model, voice, stability, similarity, style, boost) {
    const btn = document.getElementById('eval-btn-' + id);
    
    const step3Element = document.getElementById('step3-audio-text');
    const text = step3Element ? (step3Element.innerText || step3Element.textContent) : '';
    
    let relativeAudioUrl;
    try {
        relativeAudioUrl = new URL(audioUrl, window.location.origin).pathname;
    } catch(e) {
        relativeAudioUrl = audioUrl;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
    btn.classList.add('opacity-80', 'cursor-not-allowed');
    
    try {
        const response = await fetch('/api/evaluate_audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                audio_url: relativeAudioUrl,
                text: text,
                elevenlabs_model: model,
                elevenlabs_voice: voice,
                stability: stability || 0.5,
                similarity_boost: similarity || 0.75,
                style: style !== undefined ? style : 0.25,
                use_speaker_boost: boost !== undefined ? boost : true,
                slug: window.currentSlug || null,
                is_main: false
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || data.detail || 'Ошибка оценки');
        }
        
        document.getElementById('eval-result-' + id).classList.remove('hidden');
        document.getElementById('eval-percent-' + id).textContent = data.percent_ideal + '%';
        document.getElementById('eval-stability-' + id).textContent = data.stability;
        document.getElementById('eval-similarity-' + id).textContent = data.similarity;
        document.getElementById('eval-do-better-' + id).textContent = data.do_better || 'Нет рекомендаций';
        if (data.cost) {
            document.getElementById('eval-cost-' + id).textContent = `Цена: $${parseFloat(data.cost).toFixed(3)}`;
        }
        
    } catch (error) {
        alert("Ошибка: " + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-star"></i>';
        btn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
}

async function generateAdditionalAudio() {
    const btn = document.getElementById('regen-audio-btn');
    const model = document.getElementById('regen-model').value;
    const voice = document.getElementById('regen-voice') ? document.getElementById('regen-voice').value : 'FGY2WhTYpPnroxEErjIq';
    const wpm = parseInt(document.getElementById('regen-wpm').value) || 175;
    const stability = parseFloat(document.getElementById('regen-stability').value) || 0.5;
    const similarity = parseFloat(document.getElementById('regen-similarity').value) || 0.75;
    const style = document.getElementById('regen-style') ? parseFloat(document.getElementById('regen-style').value) : 0.25;
    const boost = document.getElementById('regen-boost') ? document.getElementById('regen-boost').checked : true;
    
    const step3Element = document.getElementById('step3-audio-text');
    let text = step3Element ? (step3Element.innerText || step3Element.textContent) : '';
    
    if (!text || text.trim() === '') {
        alert("Нет текста для озвучки!");
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Генерация...';
    btn.classList.add('opacity-80', 'cursor-not-allowed');
    
    try {
        const response = await fetch('/api/generate_audio_only', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                elevenlabs_model: model,
                elevenlabs_voice: voice,
                audio_wpm: wpm,
                stability: stability,
                similarity_boost: similarity,
                style: style,
                use_speaker_boost: boost,
                slug: window.currentSlug || null
            })
        });
        
        const data = await response.json();
        
        if (!response.ok || !data.success) {
            throw new Error(data.error || data.detail || 'Ошибка генерации');
        }
        
        const container = document.getElementById('additional-audios');
        const div = document.createElement('div');
        div.className = "bg-white p-4 rounded-xl border border-gray-100 shadow-sm";
        
        let addCost = data.cost ? ` | Цена: $${parseFloat(data.cost).toFixed(3)}` : '';
        
        const voiceSelect = document.getElementById('regen-voice');
        let voiceName = data.voice.substring(0,8) + '...';
        if (voiceSelect) {
            for (let i = 0; i < voiceSelect.options.length; i++) {
                if (voiceSelect.options[i].value === data.voice) {
                    voiceName = voiceSelect.options[i].text.split('-')[0].trim();
                    break;
                }
            }
        }
        
        const uniqueId = Date.now().toString() + Math.floor(Math.random() * 1000).toString();
        
        div.innerHTML = `
            <div class="flex flex-col gap-2">
                <div class="flex items-center justify-between">
                    <h5 class="font-bold text-sm text-brand-dark">Дополнительный вариант</h5>
                    <span class="text-xs font-semibold px-2 py-1 bg-purple-100 text-purple-700 rounded-md">${data.model} | Voice: ${voiceName} | ${data.wpm} сл/мин | Speed: ${data.speed.toFixed(2)}${addCost}</span>
                </div>
                <div class="flex items-center gap-3">
                    <audio controls class="flex-1 h-10">
                        <source src="${data.audio_url}" type="audio/mpeg">
                    </audio>
                    <a href="${data.audio_url}" download class="flex-shrink-0 bg-brand-lightBg text-purple-500 hover:text-white hover:bg-purple-500 border border-purple-200 transition-colors w-10 h-10 flex items-center justify-center rounded-xl shadow-sm" title="Скачать аудио">
                        <i class="fas fa-download"></i>
                    </a>
                    <button id="eval-btn-${uniqueId}" onclick="evaluateAdditionalAudio('${uniqueId}', '${data.audio_url}', '${data.model}', '${data.voice}', ${stability}, ${similarity}, ${style}, ${boost})" class="flex-shrink-0 bg-brand-lightBg text-purple-500 hover:text-white hover:bg-purple-500 border border-purple-200 transition-colors w-10 h-10 flex items-center justify-center rounded-xl shadow-sm" title="Оценить качество">
                        <i class="fas fa-star"></i>
                    </button>
                </div>
                <div class="text-xs text-gray-500 flex gap-3">
                    <span>Stability: ${stability}</span>
                    <span>Similarity: ${similarity}</span>
                    <span>Style: ${style}</span>
                    <span>Boost: ${boost ? 'true' : 'false'}</span>
                </div>
                
                <div id="eval-result-${uniqueId}" class="hidden mt-2 bg-purple-50 border border-purple-100 rounded-xl p-3">
                    <h4 class="font-bold text-brand-dark mb-2 text-xs flex items-center gap-2"><i class="fas fa-chart-line text-purple-500"></i> Оценка качества (Gemini 3.1 Pro)</h4>
                    <div class="flex flex-wrap gap-3 text-xs text-brand-dark mb-1">
                        <div class="flex flex-col relative">
                            <span class="text-[10px] text-gray-500">Идеальность</span>
                            <span class="font-bold text-purple-600 cursor-pointer underline decoration-dotted underline-offset-2 hover:text-purple-800" onclick="toggleTooltip('eval-tooltip-${uniqueId}')" id="eval-percent-${uniqueId}"></span>
                            <div class="absolute bottom-full left-0 mb-2 w-80 sm:w-96 md:w-[600px] max-w-[90vw] max-h-[60vh] flex flex-col bg-gray-800 text-white text-[10px] rounded-lg opacity-0 invisible transition-all z-50 shadow-2xl eval-tooltip" id="eval-tooltip-${uniqueId}">
                                <div class="flex justify-between items-center p-2 border-b border-gray-700 bg-gray-900 rounded-t-lg sticky top-0">
                                    <span class="font-bold">Рекомендации Gemini</span>
                                    <button onclick="closeTooltip('eval-tooltip-${uniqueId}')" class="text-gray-400 hover:text-white px-2"><i class="fas fa-times text-sm"></i></button>
                                </div>
                                <div class="p-2 overflow-y-auto whitespace-pre-wrap" id="eval-do-better-${uniqueId}"></div>
                            </div>
                        </div>
                        <div class="flex flex-col">
                            <span class="text-[10px] text-gray-500">Рек. Stability</span>
                            <span class="font-bold" id="eval-stability-${uniqueId}"></span>
                        </div>
                        <div class="flex flex-col">
                            <span class="text-[10px] text-gray-500">Рек. Similarity</span>
                            <span class="font-bold" id="eval-similarity-${uniqueId}"></span>
                        </div>
                    </div>
                    <div class="text-[10px] text-gray-500" id="eval-cost-${uniqueId}"></div>
                </div>
            </div>
        `;
        container.prepend(div);
        
    } catch (error) {
        alert("Ошибка: " + error.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-magic"></i> Сгенерировать еще вариант';
        btn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
}
