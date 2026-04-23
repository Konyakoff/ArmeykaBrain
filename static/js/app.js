/* static/js/app.js */
let currentPrompts = null;
let allHistory = [];
let isHistoryExpanded = false;
let currentTab = 'text';
window.currentSlug = null;
let currentAbortController = null;
let tabQuestions = { text: '', audio: '', video: '' };

// При загрузке страницы проверяем URL и переключаем на нужную вкладку
document.addEventListener('DOMContentLoaded', () => {
    const hash = window.location.pathname.replace('/', '') || 'text';
    if (['text', 'audio', 'video'].includes(hash)) {
        switchTab(hash, true);
    }
});

function switchTab(tab, initial = false) {
    if (!initial && currentTab === tab) return;
    
    // Сохраняем введенный текст текущей вкладки
    const qInput = document.getElementById('question-input');
    if (qInput && !initial) {
        tabQuestions[currentTab] = qInput.value;
    }
    
    currentTab = tab;
    
    // Меняем URL без перезагрузки
    window.history.pushState(null, '', '/' + tab);
    
    // Если идет генерация, отменяем её
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
    
    // Сбрасываем интерфейс
    resetUI();
    
    // Восстанавливаем текст для новой вкладки
    if (qInput) {
        qInput.value = tabQuestions[tab] || '';
    }

    const tabText = document.getElementById('tab-text');
    const tabAudio = document.getElementById('tab-audio');
    const tabVideo = document.getElementById('tab-video');
    const audioOnlyElements = document.querySelectorAll('.audio-only');
    const videoOnlyElements = document.querySelectorAll('.video-only');
    
    // Сбросим стили вкладок
    const inactiveClass = "px-6 py-2.5 rounded-xl font-bold transition-all text-gray-500 hover:text-brand-main hover:bg-gray-50 flex items-center gap-2";
    const activeClass = "px-6 py-2.5 rounded-xl font-bold transition-all bg-brand-lightBg text-brand-main shadow-sm flex items-center gap-2";
    
    tabText.className = inactiveClass;
    tabAudio.className = inactiveClass;
    if (tabVideo) tabVideo.className = inactiveClass;

    if (tab === 'text') {
        tabText.className = activeClass;
        audioOnlyElements.forEach(el => el.classList.add('hidden'));
        videoOnlyElements.forEach(el => el.classList.add('hidden'));
        
        const styleSelect = document.getElementById('style-select');
        const savedStyleText = localStorage.getItem('selectedStyleText') || 'telegram_yur';
        if (styleSelect.querySelector(`option[value="${savedStyleText}"]`)) {
            styleSelect.value = savedStyleText;
        }
    } else if (tab === 'audio') {
        tabAudio.className = activeClass;
        audioOnlyElements.forEach(el => el.classList.remove('hidden'));
        videoOnlyElements.forEach(el => el.classList.add('hidden'));
        
        const styleSelect = document.getElementById('style-select');
        const savedStyleAudio = localStorage.getItem('selectedStyleAudio') || 'audio_yur';
        if (styleSelect.querySelector(`option[value="${savedStyleAudio}"]`)) {
            styleSelect.value = savedStyleAudio;
        }
    } else if (tab === 'video') {
        if (tabVideo) tabVideo.className = activeClass;
        // Для видео нужны и аудио-настройки (для генерации голоса)
        audioOnlyElements.forEach(el => el.classList.remove('hidden'));
        videoOnlyElements.forEach(el => el.classList.remove('hidden'));
        
        const styleSelect = document.getElementById('style-select');
        const savedStyleAudio = localStorage.getItem('selectedStyleAudio') || 'audio_yur';
        if (styleSelect.querySelector(`option[value="${savedStyleAudio}"]`)) {
            styleSelect.value = savedStyleAudio;
        }
    }
    
    document.getElementById('result-container').classList.add('hidden');
    document.getElementById('result-container').classList.remove('flex');
    
    loadHistory();
}

document.addEventListener('DOMContentLoaded', async () => {
    loadConfig();
    loadHistory();
    _initStep3PromptSelect();
    
    const savedContextThreshold = localStorage.getItem('contextThreshold');
    if (savedContextThreshold) document.getElementById('context-threshold').value = savedContextThreshold;
    document.getElementById('context-threshold').addEventListener('change', (e) => localStorage.setItem('contextThreshold', e.target.value));
    
    const savedMaxLength = localStorage.getItem('maxLength');
    if (savedMaxLength) document.getElementById('max-length').value = savedMaxLength;
    document.getElementById('max-length').addEventListener('change', (e) => localStorage.setItem('maxLength', e.target.value));
    
    const savedAudioDuration = localStorage.getItem('audioDuration');
    if (savedAudioDuration) document.getElementById('audio-duration').value = savedAudioDuration;
    document.getElementById('audio-duration').addEventListener('change', (e) => localStorage.setItem('audioDuration', e.target.value));
    
    const savedAudioWpm = localStorage.getItem('audioWpm');
    if (savedAudioWpm) {
        const wpmElem = document.getElementById('audio-wpm');
        if (wpmElem) {
            let clampedWpm = Math.max(105, Math.min(parseInt(savedAudioWpm), 180));
            wpmElem.value = clampedWpm;
            const wpmValElem = document.getElementById('audio-wpm-val');
            if (wpmValElem) wpmValElem.innerText = clampedWpm;
        }
    }
    document.getElementById('audio-wpm').addEventListener('change', (e) => localStorage.setItem('audioWpm', e.target.value));
    
    const savedElevenlabsModel = localStorage.getItem('elevenlabsModel');
    if (savedElevenlabsModel) document.getElementById('elevenlabs-model').value = savedElevenlabsModel;
    document.getElementById('elevenlabs-model').addEventListener('change', (e) => localStorage.setItem('elevenlabsModel', e.target.value));

    const savedAudioStyle = localStorage.getItem('audioStyle');
    if (savedAudioStyle) document.getElementById('audio-style').value = savedAudioStyle;
    document.getElementById('audio-style').addEventListener('change', (e) => localStorage.setItem('audioStyle', e.target.value));

    const savedAudioStability = localStorage.getItem('audioStability');
    if (savedAudioStability) document.getElementById('audio-stability').value = savedAudioStability;
    document.getElementById('audio-stability').addEventListener('change', (e) => localStorage.setItem('audioStability', e.target.value));

    const savedAudioSimilarity = localStorage.getItem('audioSimilarity');
    if (savedAudioSimilarity) document.getElementById('audio-similarity').value = savedAudioSimilarity;
    document.getElementById('audio-similarity').addEventListener('change', (e) => localStorage.setItem('audioSimilarity', e.target.value));

    const savedSpeakerBoost = localStorage.getItem('useSpeakerBoost');
    if (savedSpeakerBoost !== null) document.getElementById('use-speaker-boost').checked = savedSpeakerBoost === 'true';
    document.getElementById('use-speaker-boost').addEventListener('change', (e) => localStorage.setItem('useSpeakerBoost', e.target.checked));

    const savedVideoFormat = localStorage.getItem('videoFormat');
    if (savedVideoFormat) {
        const vfEl = document.getElementById('video-format');
        if (vfEl) vfEl.value = savedVideoFormat;
    }
    document.getElementById('video-format')?.addEventListener('change', (e) => {
        localStorage.setItem('videoFormat', e.target.value);
        updateAvatarStyleHint('video-format', 'avatar-style', 'avatar-style-hint');
        updateAvatarButtonText('heygen-avatar', 'heygen-avatar-btn', 'video-format');
    });

    const savedHeygenEngine = localStorage.getItem('heygenEngine');
    if (savedHeygenEngine) {
        const engineEl = document.getElementById('heygen-engine');
        if (engineEl) engineEl.value = savedHeygenEngine;
    }
    document.getElementById('heygen-engine')?.addEventListener('change', (e) => localStorage.setItem('heygenEngine', e.target.value));
});

/**
 * Builds grouped voice <option>/<optgroup> HTML for a <select> element.
 * Voices with category "my" are placed in "Мои голоса", the rest in "Публичные".
 * If no "my" voices exist, returns a flat list without optgroups.
 * @param {Array<{voice_id:string, name:string, description:string, category?:string}>} voices
 * @param {string} selectedId
 * @returns {string}
 */
function buildVoiceOptionsHtml(voices, selectedId) {
    const myVoices = voices.filter(v => v.category === 'my');
    const publicVoices = voices.filter(v => v.category !== 'my');

    const optionHtml = (v) =>
        `<option value="${v.voice_id}" ${v.voice_id === selectedId ? 'selected' : ''}>${v.name}${v.description ? ` (${v.description})` : ''}</option>`;

    if (myVoices.length === 0) {
        return publicVoices.map(optionHtml).join('');
    }

    return `<optgroup label="Мои голоса">${myVoices.map(optionHtml).join('')}</optgroup>` +
           `<optgroup label="Публичные">${publicVoices.map(optionHtml).join('')}</optgroup>`;
}

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();
        
        const DEFAULT_MODEL = 'gemini-3.1-pro-preview';

        // Группируем модели по провайдеру — строим общий HTML для переиспользования
        const geminiModels = data.models.filter(m => m.provider === 'gemini' || !m.provider);
        const claudeModels = data.models.filter(m => m.provider === 'claude');
        function buildModelsHtml(selectedId) {
            let html = '';
            if (geminiModels.length > 0) {
                html += `<optgroup label="Gemini (Google)">` +
                    geminiModels.map(m => `<option value="${m.id}" ${m.id === selectedId ? 'selected' : ''}>${m.name}</option>`).join('') +
                    `</optgroup>`;
            }
            if (claudeModels.length > 0) {
                html += `<optgroup label="Claude (Anthropic)">` +
                    claudeModels.map(m => `<option value="${m.id}" ${m.id === selectedId ? 'selected' : ''}>${m.name}</option>`).join('') +
                    `</optgroup>`;
            }
            return html;
        }

        // Три независимых дропдауна — с сохранением в localStorage
        [
            { id: 'model-select-1', lsKey: 'selectedModel1' },
            { id: 'model-select-2', lsKey: 'selectedModel2' },
            { id: 'model-select-3', lsKey: 'selectedModel3' },
        ].forEach(({ id, lsKey }) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const saved = localStorage.getItem(lsKey) || localStorage.getItem('selectedModel') || data.default_model || DEFAULT_MODEL;
            sel.innerHTML = buildModelsHtml(saved);
            sel.addEventListener('change', (e) => localStorage.setItem(lsKey, e.target.value));
        });

        const styleSelect = document.getElementById('style-select');
        const initialSavedStyle = localStorage.getItem(currentTab === 'text' ? 'selectedStyleText' : 'selectedStyleAudio') || (currentTab === 'text' ? 'telegram_yur' : 'audio_yur');
        
        styleSelect.innerHTML = data.styles.map(s => 
            `<option value="${s.id}" ${s.id === initialSavedStyle ? 'selected' : ''}>${s.name}</option>`
        ).join('');
        
        styleSelect.addEventListener('change', (e) => {
            if (currentTab === 'text') {
                localStorage.setItem('selectedStyleText', e.target.value);
            } else {
                localStorage.setItem('selectedStyleAudio', e.target.value);
            }
        });
        
        if (data.voices && data.voices.length > 0) {
            const savedVoice = localStorage.getItem('elevenlabsVoice') || data.default_voice;
            const voiceOptionsHtml = buildVoiceOptionsHtml(data.voices, savedVoice);
            const voiceSelect = document.getElementById('elevenlabs-voice');
            if(voiceSelect) {
                voiceSelect.innerHTML = voiceOptionsHtml;
                voiceSelect.addEventListener('change', (e) => {
                    localStorage.setItem('elevenlabsVoice', e.target.value);
                });
            }
            const regenVoice = document.getElementById('regen-voice');
            if(regenVoice) {
                regenVoice.innerHTML = voiceOptionsHtml;
                regenVoice.value = savedVoice;
                regenVoice.addEventListener('change', (e) => {
                    localStorage.setItem('elevenlabsVoice', e.target.value);
                    if(voiceSelect) voiceSelect.value = e.target.value;
                });
            }
        }
        
        if (data.avatars && data.avatars.length > 0) {
            windowAvatars = data.avatars;
            if (data.private_avatars) windowPrivateAvatars = data.private_avatars;
            const savedAvatar = localStorage.getItem('heygenAvatar') || data.default_avatar;
            updateAvatarButtonText('heygen-avatar', 'heygen-avatar-btn', 'video-format');
            
            const formatElem = document.getElementById('video-format');
            if (formatElem) {
                formatElem.addEventListener('change', () => {
                    updateAvatarButtonText('heygen-avatar', 'heygen-avatar-btn', 'video-format');
                });
            }
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

async function loadHistory() {
    try {
        const response = await fetch(`/api/history?tab=${currentTab}`);
        const data = await response.json();
        allHistory = data.history || [];
        renderHistory();
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

function renderHistory() {
    const list = document.getElementById('history-list');
    const btn = document.getElementById('show-more-history');
    list.innerHTML = '';
    
    if (allHistory.length === 0) {
        list.innerHTML = '<p class="text-gray-500 italic">История пуста</p>';
        btn.classList.add('hidden');
        return;
    }

    const limit = isHistoryExpanded ? allHistory.length : 5;
    const itemsToShow = allHistory.slice(0, limit);

    itemsToShow.forEach(item => {
        const div = document.createElement('div');
        div.className = 'bg-white rounded-xl shadow-sm p-4 border border-gray-100 hover:border-brand-main transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3';
        
        const shortQuestion = item.question.length > 80 ? item.question.substring(0, 80) + '...' : item.question;
        
        div.innerHTML = `
            <div class="flex-1">
                <p class="text-brand-dark font-medium">${shortQuestion}</p>
                <p class="text-xs text-gray-400 mt-1"><i class="far fa-clock mr-1"></i> ${item.timestamp}</p>
            </div>
            <div class="flex-shrink-0">
                <a href="/text/${item.slug}" target="_blank" class="text-sm bg-brand-lightBg text-brand-main border border-brand-inputBorder hover:bg-brand-main hover:text-white px-4 py-2 rounded-lg font-semibold transition-all">
                    /text/${item.slug}
                </a>
            </div>
        `;
        list.appendChild(div);
    });

    if (allHistory.length > 5) {
        btn.classList.remove('hidden');
        btn.innerHTML = isHistoryExpanded ? '<i class="fas fa-chevron-up mr-1"></i> Скрыть' : '<i class="fas fa-chevron-down mr-1"></i> Показать все';
    } else {
        btn.classList.add('hidden');
    }
}

function toggleHistory() {
    isHistoryExpanded = !isHistoryExpanded;
    renderHistory();
}

function showEarlyResultLink(slug) {
    if (!slug) return;
    const box = document.getElementById('early-link-container');
    const a   = document.getElementById('early-link-anchor');
    const t   = document.getElementById('early-link-text');
    
    if (!box || !a || !t) return;
    const url = `/text/${slug}`;
    a.href = url;
    t.textContent = window.location.origin + url;
    box.classList.remove('hidden');
}

function resetUI() {
    const resultContainer = document.getElementById('result-container');
    if (resultContainer) {
        resultContainer.classList.add('hidden');
        resultContainer.classList.remove('flex');
    }
    
    const elementsToHide = [
        'loading-state', 'error-state', 'success-state',
        'card-step1', 'card-step2', 'step3-audio-container',
        'step4-audio-player-container', 'floating-loader',
        'prompts-container', 'result-link-container', 'step5-video-container'
    ];
    
    elementsToHide.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });
    
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        submitBtn.innerHTML = '<i class="far fa-paper-plane text-lg"></i> Отправить запрос';
    }
}

async function sendQuery() {
    const question = document.getElementById('question-input').value.trim();
    if (!question) {
        const qInput = document.getElementById('question-input');
        qInput.classList.add('ring-2', 'ring-red-500', 'border-red-500');
        setTimeout(() => qInput.classList.remove('ring-2', 'ring-red-500', 'border-red-500'), 1000);
        return;
    }

    const model = document.getElementById('model-select-1')?.value || 'gemini-3.1-pro-preview';
    const model2 = document.getElementById('model-select-2')?.value || model;
    const model3 = document.getElementById('model-select-3')?.value || model;
    const style = document.getElementById('style-select').value;
    const threshold = parseInt(document.getElementById('context-threshold').value) || 70;
    const maxLength = parseInt(document.getElementById('max-length').value) || 4000;
    const audioDuration = parseInt(document.getElementById('audio-duration').value) || 60;
    const audioWpm = parseInt(document.getElementById('audio-wpm').value) || 150;
    const elevenlabsModel = document.getElementById('elevenlabs-model') ? document.getElementById('elevenlabs-model').value : 'eleven_v3';
    const elevenlabsVoice = document.getElementById('elevenlabs-voice') ? document.getElementById('elevenlabs-voice').value : 'FGY2WhTYpPnroxEErjIq';
    const audioStyle = document.getElementById('audio-style') ? parseFloat(document.getElementById('audio-style').value) : 0.25;
    const audioStability = document.getElementById('audio-stability') ? parseFloat(document.getElementById('audio-stability').value) : 0.5;
    const audioSimilarity = document.getElementById('audio-similarity') ? parseFloat(document.getElementById('audio-similarity').value) : 0.75;
    const useSpeakerBoost = document.getElementById('use-speaker-boost') ? document.getElementById('use-speaker-boost').checked : true;
    const heygenAvatarId = document.getElementById('heygen-avatar') ? document.getElementById('heygen-avatar').value : 'ef720fad85884cc3b9d3352828f1f7e7';
    const videoFormat = document.getElementById('video-format') ? document.getElementById('video-format').value : '16:9';
    const heygenEngine = document.getElementById('heygen-engine') ? document.getElementById('heygen-engine').value : 'avatar_iv';
    const avatarStyleEl = document.getElementById('avatar-style');
    const avatarStyle = avatarStyleEl ? avatarStyleEl.value : 'auto';
    const sendPrompts = document.getElementById('send-prompts').checked;

    const resultContainer = document.getElementById('result-container');
    const loadingState = document.getElementById('loading-state');
    const errorState = document.getElementById('error-state');
    const successState = document.getElementById('success-state');
    const submitBtn = document.getElementById('submit-btn');

    document.getElementById('additional-audios').innerHTML = '';

    resultContainer.classList.remove('hidden');
    resultContainer.classList.add('flex');
    loadingState.classList.remove('hidden');
    errorState.classList.add('hidden');
    successState.classList.add('hidden');
    successState.classList.remove('flex');
    
    document.getElementById('card-step1').classList.add('hidden');
    document.getElementById('card-step2').classList.add('hidden');
    document.getElementById('step3-audio-container').classList.add('hidden');
    document.getElementById('step4-audio-player-container').classList.add('hidden');
    document.getElementById('floating-loader').classList.add('hidden');
    document.getElementById('prompts-container').classList.add('hidden');
    document.getElementById('result-link-container').classList.add('hidden');
    const earlyLink = document.getElementById('early-link-container');
    if (earlyLink) earlyLink.classList.add('hidden');
    window._earlySlug = null;
    
    document.getElementById('loading-desc').textContent = "Инициализация...";
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin text-lg"></i> Запрос в обработке...';
    submitBtn.classList.add('opacity-80', 'cursor-not-allowed');

    currentAbortController = new AbortController();

    try {
        // Отправляем POST запрос для запуска генерации
        const startResponse = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: currentAbortController.signal,
            body: JSON.stringify({
                question: question,
                model: model,
                model1: model,
                model2: model2,
                model3: model3,
                style: style,
                context_threshold: threshold,
                max_length: maxLength,
                send_prompts: sendPrompts,
                audio_duration: audioDuration,
                audio_wpm: audioWpm,
                tab_type: currentTab,
                elevenlabs_model: elevenlabsModel,
                elevenlabs_voice: elevenlabsVoice,
                audio_style: audioStyle,
                use_speaker_boost: useSpeakerBoost,
                audio_stability: audioStability,
                audio_similarity_boost: audioSimilarity,
                heygen_avatar_id: heygenAvatarId,
                video_format: videoFormat,
                heygen_engine: heygenEngine,
                avatar_style: avatarStyle,
                custom_prompts: peGetCustomPrompts()
            })
        });

        if (!startResponse.ok) {
            let err = "Произошла ошибка сервера";
            try {
                const errData = await startResponse.json();
                err = errData.detail || errData.error || err;
            } catch(e) {}
            throw new Error(err);
        }
        
        const startData = await startResponse.json();
        const slug = startData.slug;
        if (!slug) throw new Error("Не получен slug от сервера");
        
        window._earlySlug = slug;
        showEarlyResultLink(slug);
        
        // Подключаемся к SSE потоку через native EventSource (не буферизуется антивирусами)
        let finalData = null;
        await new Promise((resolve, reject) => {
            const eventSource = new EventSource(`/api/stream_query?slug=${slug}`);
            
            // Если пользователь отменяет запрос
            currentAbortController.signal.addEventListener('abort', () => {
                eventSource.close();
                reject(new Error("Запрос отменен пользователем"));
            });
            
            eventSource.onmessage = function(event) {
                try {
                    const chunk = JSON.parse(event.data);
                    
                    if (chunk.step === "error") {
                        eventSource.close();
                        reject(new Error(chunk.message));
                        return;
                    } else if (chunk.step === "done") {
                        finalData = chunk.result;
                        eventSource.close();
                        resolve();
                        return;
                    } else if (chunk.step === "heartbeat") {
                        if (chunk.message) {
                            const desc = document.getElementById('loading-desc');
                            const fl = document.getElementById('floating-loader-text');
                            if (desc) desc.innerHTML = chunk.message;
                            if (fl) {
                                fl.innerHTML = chunk.message;
                                const flBox = document.getElementById('floating-loader');
                                if (flBox && successState.classList.contains('flex')) flBox.classList.remove('hidden');
                            }
                        }
                    } else if (chunk.step === "partial") {
                        loadingState.classList.add('hidden');
                        successState.classList.remove('hidden');
                        successState.classList.add('flex');

                        if (window._earlySlug) showEarlyResultLink(window._earlySlug);

                        const data = chunk.data;
                        if (data.step1_info) {
                            document.getElementById('step1-info').innerHTML = formatStep1Info(data.step1_info);
                            document.getElementById('card-step1').classList.remove('hidden');
                        }
                        if (data.step1_stats) document.getElementById('step1-stats').innerHTML = formatStats(data.step1_stats, 1);
                        
                        if (data.answer) {
                            document.getElementById('final-answer').innerHTML = marked.parse(data.answer);
                            document.getElementById('card-step2').classList.remove('hidden');
                        }
                        if (data.step2_stats) document.getElementById('step2-stats').innerHTML = formatStats(data.step2_stats, 2);
                        
                        if (data.step3_audio) {
                            document.getElementById('step3-audio-text').innerHTML = marked.parse(data.step3_audio);
                            document.getElementById('step3-audio-container').classList.remove('hidden');
                            
                            const audioDuration = document.getElementById('audio-duration').value;
                            const audioWpm = document.getElementById('audio-wpm').value;
                            document.getElementById('step3-param-duration').textContent = audioDuration;
                            document.getElementById('step3-param-wpm').textContent = audioWpm;
                            document.getElementById('step3-audio-params').classList.remove('hidden');
                        }
                        if (data.step3_stats) document.getElementById('step3-stats').innerHTML = formatStats(data.step3_stats, 3);
                        
                        if (data.step4_audio_url) {
                            if (data.step4_stats) {
                                const badge = document.getElementById('step4-audio-badge');
                                if (badge) badge.classList.add('hidden');
                                document.getElementById('step4-stats').innerHTML = formatStats(data.step4_stats, 4);
                            }
                        }
                        
                        if (data.step5_video_id) {
                            document.getElementById('step5-video-container').classList.remove('hidden');
                            if (data.step5_stats) {
                                document.getElementById('step5-stats').innerHTML = formatStats(data.step5_stats, 5);
                            }
                            document.getElementById('step5-video-content').innerHTML = `
                                <div class="flex flex-col items-center gap-3 w-full">
                                    <div class="bg-gray-100 rounded-xl p-8 flex flex-col items-center justify-center w-full max-w-2xl border-2 border-dashed border-gray-300">
                                        <i class="fas fa-spinner fa-spin text-4xl text-indigo-500 mb-4"></i>
                                        <p class="text-brand-dark font-medium text-center">Видео генерируется...</p>
                                        <p class="text-sm text-gray-500 text-center mt-2">Это может занять несколько минут. Не закрывайте страницу или перейдите по ссылке результата позже.</p>
                                    </div>
                                </div>
                            `;
                        }
                    } else {
                        if (chunk.message) {
                            document.getElementById('loading-desc').innerHTML = chunk.message;
                            const floatingLoader = document.getElementById('floating-loader-text');
                            if (floatingLoader) {
                                floatingLoader.innerHTML = chunk.message;
                                document.getElementById('floating-loader').classList.remove('hidden');
                            }
                        }
                    }
                } catch(e) {
                    console.error("Parse error", e);
                }
            };
            
            eventSource.onerror = function(err) {
                // Ignore transient errors, but log them
                console.warn("EventSource error", err);
            };
        });
        
        if (!finalData) throw new Error("Не удалось получить результат от сервера.");
        
        const data = finalData;
        window.currentSlug = data.slug;

        loadingState.classList.add('hidden');
        successState.classList.remove('hidden');
        successState.classList.add('flex');
        document.getElementById('floating-loader').classList.add('hidden');
        
        document.getElementById('card-step1').classList.remove('hidden');
        document.getElementById('step1-info').innerHTML = formatStep1Info(data.step1_info);
        
        document.getElementById('card-step2').classList.remove('hidden');
        document.getElementById('final-answer').innerHTML = marked.parse(data.answer);

        const step3AudioContainer = document.getElementById('step3-audio-container');
        const step3AudioText = document.getElementById('step3-audio-text');
        const step4AudioPlayerContainer = document.getElementById('step4-audio-player-container');
        const step4AudioPlayer = document.getElementById('step4-audio-player');
        const step4AudioSource = document.getElementById('step4-audio-source');
        const step4AudioBadge = document.getElementById('step4-audio-badge');
        
        if (data.step3_audio) {
            step3AudioContainer.classList.remove('hidden');
            step3AudioText.innerHTML = marked.parse(data.step3_audio);
            
            const audioDuration = document.getElementById('audio-duration').value;
            const audioWpm = document.getElementById('audio-wpm').value;
            document.getElementById('step3-param-duration').textContent = audioDuration;
            document.getElementById('step3-param-wpm').textContent = audioWpm;
            document.getElementById('step3-audio-params').classList.remove('hidden');
            
        if (data.step4_audio_url) {
            step4AudioPlayerContainer.classList.remove('hidden');
            step4AudioSource.src = data.step4_audio_url;
            document.getElementById('step4-audio-download').href = data.step4_audio_url_original || data.step4_audio_url;
            step4AudioPlayer.load();

            // Показываем спиннер таймкодов — Deepgram генерируется фоном
            const tcSpinner = document.getElementById('step4-tc-spinner');
            if (tcSpinner) tcSpinner.classList.remove('hidden');
            // Запускаем поллинг таймкодов по slug
            if (data.slug) _pollTimecodes(data.slug);
            
            // Add video generation block
            const videoBlockId = 'video-upgrade-main';
            let videoBlockContainer = document.getElementById(videoBlockId);
            if (!videoBlockContainer) {
                videoBlockContainer = document.createElement('div');
                videoBlockContainer.id = videoBlockId;
                step4AudioPlayerContainer.appendChild(videoBlockContainer);
            }
            videoBlockContainer.innerHTML = renderVideoUpgradeBlock('main', data.step4_audio_url_original || data.step4_audio_url, true);
            
                
                if (data.step4_stats) {
                    const stats = data.step4_stats;
                    const origModel = stats.model || 'N/A';
                    const origVoiceId = stats.voice_id || 'N/A';
                    const origVoiceName = stats.voice_name || 'N/A';
                    const origWpm = stats.wpm || '150';
                    const origSpeed = stats.speed ? parseFloat(stats.speed).toFixed(2) : '1.00';
                    const origStability = stats.stability !== undefined ? stats.stability : '0.5';
                    const origSimilarity = stats.similarity !== undefined ? stats.similarity : '0.75';
                    const origStyle = stats.style !== undefined ? stats.style : '0.25';
                    const origBoost = stats.speaker_boost !== undefined ? stats.speaker_boost.toString() : 'true';
                    const displayCost = stats.total_cost ? ` | Цена: $${parseFloat(stats.total_cost).toFixed(3)}` : '';
                    
                    const regenModel = document.getElementById('regen-model');
                    if (regenModel && origModel !== 'N/A') regenModel.value = origModel;
                    
                    const regenVoice = document.getElementById('regen-voice');
                    if (regenVoice && origVoiceId !== 'N/A') {
                        if ([...regenVoice.options].some(o => o.value === origVoiceId)) {
                            regenVoice.value = origVoiceId;
                        }
                    }
                    
                    const regenWpm = document.getElementById('regen-wpm');
                    if (regenWpm && origWpm !== 'N/A') {
                        regenWpm.value = origWpm;
                        const regenWpmVal = document.getElementById('regen-wpm-val');
                        if (regenWpmVal) regenWpmVal.innerText = origWpm;
                    }

                    const regenStability = document.getElementById('regen-stability');
                    if (regenStability) regenStability.value = origStability;

                    const regenSimilarity = document.getElementById('regen-similarity');
                    if (regenSimilarity) regenSimilarity.value = origSimilarity;

                    const regenStyle = document.getElementById('regen-style');
                    if (regenStyle) regenStyle.value = origStyle;

                    const regenBoost = document.getElementById('regen-boost');
                    if (regenBoost) regenBoost.checked = origBoost === 'true';
                    
                    if (step4AudioBadge) {
                        step4AudioBadge.innerHTML = `<span class="text-xs font-semibold px-2 py-1 bg-purple-100 text-purple-700 rounded-md block w-fit mb-3 border border-purple-200 shadow-sm">${origModel} | Voice: ${origVoiceName} | ${origWpm} сл/мин | Speed: ${origSpeed} | Stability: ${origStability} | Similarity: ${origSimilarity} | Style: ${origStyle} | Boost: ${origBoost}${displayCost}</span>`;
                    }
                }
                
                if (data.step5_video_id) {
                    const step5VideoContainer = document.getElementById('step5-video-container');
                    const step5VideoContent = document.getElementById('step5-video-content');
                    step5VideoContainer.classList.remove('hidden');
                    
                    // Поллинг статуса видео
                    const pollVideo = async () => {
                        try {
                            const res = await fetch(`/api/video_status?video_id=${data.step5_video_id}`);
                            const stData = await res.json();
                            
                            if (stData.status === "completed" && stData.video_url) {
                                if (data.step5_stats && data.step5_stats.started_at) {
                                    data.step5_stats.generation_time_sec = Math.floor(Date.now() / 1000) - data.step5_stats.started_at;
                                    document.getElementById('step5-stats').innerHTML = formatStats(data.step5_stats, 5);
                                }
                                
                                step5VideoContent.innerHTML = `
                                    <video controls class="max-h-[70vh] w-auto max-w-full mx-auto rounded-xl shadow-lg border-2 border-indigo-200" style="object-fit: contain;">
                                        <source src="${stData.video_url}" type="video/mp4">
                                        Ваш браузер не поддерживает видео.
                                    </video>
                                    <div class="mt-4 flex gap-4">
                                        <a href="${stData.video_url}" download target="_blank" class="bg-indigo-500 hover:bg-indigo-600 text-white font-bold py-2 px-6 rounded-xl transition-all shadow-sm flex items-center justify-center gap-2">
                                            <i class="fas fa-download"></i> Скачать видео
                                        </a>
                                    </div>
                                `;
                                // Обновляем в БД
                                fetch('/api/update_video_result', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ slug: data.slug, video_url: stData.video_url })
                                });
                            } else if (stData.status === "failed" || stData.status === "error") {
                                step5VideoContent.innerHTML = `
                                    <div class="bg-red-50 text-red-600 p-6 rounded-xl w-full max-w-2xl border border-red-200 text-center">
                                        <i class="fas fa-exclamation-triangle text-3xl mb-2"></i>
                                        <p class="font-bold">Ошибка генерации видео</p>
                                        <p class="text-sm mt-1">${stData.error || 'Неизвестная ошибка'}</p>
                                    </div>
                                `;
                            } else {
                                setTimeout(pollVideo, 5000);
                            }
                        } catch (e) {
                            setTimeout(pollVideo, 5000);
                        }
                    };
                    pollVideo();
                } else {
                    document.getElementById('step5-video-container').classList.add('hidden');
                }
            } else {
                step4AudioPlayerContainer.classList.add('hidden');
                document.getElementById('step5-video-container').classList.add('hidden');
            }
        } else {
            step3AudioContainer.classList.add('hidden');
            document.getElementById('step5-video-container').classList.add('hidden');
        }

        if (data.total_stats) {
            document.getElementById('total-stats').innerHTML = formatTotalStats(data.total_stats);
        }

        const resultLinkContainer = document.getElementById('result-link-container');
        if (data.url) {
            const fullUrl = window.location.origin + data.url;
            document.getElementById('result-link').href = data.url;
            document.getElementById('result-link-text').textContent = fullUrl;
            resultLinkContainer.classList.remove('hidden');
            
            allHistory.unshift({
                slug: data.slug,
                question: question,
                timestamp: new Date().toLocaleString('ru-RU').replace(',', ''),
                char_count: data.answer.length
            });
            renderHistory();
        } else {
            resultLinkContainer.classList.add('hidden');
        }

        const promptsContainer = document.getElementById('prompts-container');
        if (data.prompts) {
            currentPrompts = data.prompts;
            promptsContainer.classList.remove('hidden');
            promptsContainer.classList.add('flex');
            
            document.getElementById('btn-prompt1').onclick = () => downloadTextFile(currentPrompts.step1, 'prompt_step1.txt');
            document.getElementById('btn-prompt2').onclick = () => downloadTextFile(currentPrompts.step2, 'prompt_step2.txt');
            
            const btnPrompt3 = document.getElementById('btn-prompt3');
            if (currentPrompts.step3) {
                btnPrompt3.classList.remove('hidden');
                btnPrompt3.onclick = () => downloadTextFile(currentPrompts.step3, 'prompt_step3.txt');
            } else {
                btnPrompt3.classList.add('hidden');
            }
        } else {
            promptsContainer.classList.add('hidden');
            promptsContainer.classList.remove('flex');
            currentPrompts = null;
        }

    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('Fetch aborted because user switched tabs');
            return;
        }
        showError(error.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="far fa-paper-plane text-lg"></i> Отправить запрос';
        submitBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
}

// ═══════════════════════════════════════════════════════════════
// РЕДАКТОР ПРОМПТОВ
// ═══════════════════════════════════════════════════════════════

const PROMPT_PLACEHOLDERS = {
    step2_style: ['{max_length}'],
    step3:       ['[ВСТАВИТЬ ВАШ ИСХОДНЫЙ ТЕКСТ]', '[N]', '[MIN_WORDS]', '[MAX_WORDS]'],
};

// Ключи промптов step3, которые нельзя удалять через UI
const STEP3_SYSTEM_KEYS = new Set(['v1', 'v2', 'evaluation']);

const LS_PROMPTS_KEY = 'pe_custom_prompts';
const LS_EDITOR_OPEN = 'pe_editor_open';

// Состояние редактора
const promptEditor = {
    activeKey: 'step2_style',
    activeStyleKey: null,  // для текущей вкладки — выбранный ключ промпта
    step3Key: 'yur_bud_svoboden', // отдельно отслеживаем выбранный ключ step3
    originals: {},         // с сервера: { step2_style: {name: text, ...}, step3: {default: text, ...} }
    session: {},           // localStorage, только отличия от оригиналов
};

// ──── Утилиты ────────────────────────────────────────────────

function peLoad() {
    const saved = localStorage.getItem(LS_PROMPTS_KEY);
    if (saved) {
        try { promptEditor.session = JSON.parse(saved); } catch (e) { promptEditor.session = {}; }
    }
    const savedStep3Key = localStorage.getItem('pe_step3_key');
    if (savedStep3Key) promptEditor.step3Key = savedStep3Key;
}

function peSave() {
    localStorage.setItem(LS_PROMPTS_KEY, JSON.stringify(promptEditor.session));
    localStorage.setItem('pe_step3_key', promptEditor.step3Key || 'yur_bud_svoboden');
}

function peGetSessionKey() {
    const k = promptEditor.activeKey;
    const sk = promptEditor.activeStyleKey;
    return `${k}:${sk}`;
}

function peGetActiveText() {
    const sessionKey = peGetSessionKey();
    if (promptEditor.session[sessionKey] !== undefined) return promptEditor.session[sessionKey];
    const pool = promptEditor.originals[promptEditor.activeKey] || {};
    return pool[promptEditor.activeStyleKey] || '';
}

function peGetOriginalText() {
    const pool = promptEditor.originals[promptEditor.activeKey] || {};
    return pool[promptEditor.activeStyleKey] || '';
}

function peApplyToSession(text) {
    const sk = peGetSessionKey();
    if (text === peGetOriginalText()) {
        delete promptEditor.session[sk];
    } else {
        promptEditor.session[sk] = text;
    }
}

// ──── UI-рендер ──────────────────────────────────────────────

function peRenderPlaceholders(key) {
    const box = document.getElementById('prompt-placeholders');
    if (!box) return;
    const chips = (PROMPT_PLACEHOLDERS[key] || []).map(ph =>
        `<span class="pe-chip">${ph}</span>`
    ).join('');
    box.innerHTML = chips || '';
}

function peCheckWarning(text, key) {
    const warn = document.getElementById('prompt-missing-warning');
    const warnText = document.getElementById('prompt-missing-text');
    if (!warn || !warnText) return;
    const required = PROMPT_PLACEHOLDERS[key] || [];
    const missing = required.filter(ph => !text.includes(ph));
    if (missing.length > 0) {
        warnText.textContent = `Отсутствуют обязательные плейсхолдеры: ${missing.join(', ')}`;
        warn.classList.remove('hidden');
    } else {
        warn.classList.add('hidden');
    }
}

function peRenderEditor() {
    const textarea = document.getElementById('prompt-editor-text');
    if (!textarea) return;
    textarea.value = peGetActiveText();
    peRenderPlaceholders(promptEditor.activeKey);
    peCheckWarning(textarea.value, promptEditor.activeKey);
}

function peSetStatusMsg(msg, isError = false) {
    const el = document.getElementById('prompt-save-status');
    if (!el) return;
    el.textContent = msg;
    el.className = `text-sm ml-auto ${isError ? 'text-red-500' : 'text-green-600'}`;
    setTimeout(() => { el.textContent = ''; }, 3500);
}

/** Перерисовывает выпадающий список промптов для активной вкладки */
function peRebuildSelector(selectId, pool, currentKey) {
    let sel = document.getElementById(selectId);
    if (!sel) {
        sel = document.createElement('select');
        sel.id = selectId;
        sel.className = 'pe-style-select text-sm border-2 border-gray-200 rounded-lg px-3 py-1.5 text-brand-dark';
        const phBox = document.getElementById('prompt-placeholders');
        if (phBox && phBox.parentNode) phBox.parentNode.insertBefore(sel, phBox);

        sel.addEventListener('change', () => {
            promptEditor.activeStyleKey = sel.value;
            if (promptEditor.activeKey === 'step3') {
                promptEditor.step3Key = sel.value;
            }
            peRenderEditor();
            peUpdateDeleteBtn();
        });
    }
    sel.innerHTML = Object.keys(pool).map(k =>
        `<option value="${k}"${k === currentKey ? ' selected' : ''}>${k}</option>`
    ).join('');
    sel.classList.remove('hidden');
    return sel;
}

function peUpdateTabStyle() {
    document.querySelectorAll('.prompt-tab').forEach(btn => {
        const isActive = btn.dataset.key === promptEditor.activeKey;
        btn.classList.toggle('border-brand-main', isActive);
        btn.classList.toggle('text-brand-main', isActive);
        btn.classList.toggle('bg-brand-lightBg', isActive);
        btn.classList.toggle('border-transparent', !isActive);
        btn.classList.toggle('text-gray-500', !isActive);
    });

    const pool = promptEditor.originals[promptEditor.activeKey] || {};

    // Скрываем все возможные селекторы
    ['pe-style-selector', 'pe-step3-selector'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    if (promptEditor.activeKey === 'step2_style') {
        peRebuildSelector('pe-style-selector', pool, promptEditor.activeStyleKey);
    } else if (promptEditor.activeKey === 'step3') {
        peRebuildSelector('pe-step3-selector', pool, promptEditor.activeStyleKey);
    }

    peUpdateDeleteBtn();
}

/** Показываем/скрываем кнопку Удалить в зависимости от выбранного промпта */
function peUpdateDeleteBtn() {
    const btn = document.getElementById('prompt-delete-btn');
    if (!btn) return;
    const name = promptEditor.activeStyleKey;
    // Нельзя удалять: default (step3), системные ключи
    const protected_ = name === 'default' || STEP3_SYSTEM_KEYS.has(name);
    btn.disabled = protected_;
    btn.title = protected_ ? 'Этот промпт нельзя удалить (системный)' : 'Удалить промпт';
    btn.classList.toggle('opacity-40', protected_);
    btn.classList.toggle('cursor-not-allowed', protected_);
}

// ──── Модалка пароля ─────────────────────────────────────────

/**
 * Открывает модалку с запросом пароля.
 * @param {string} title  — заголовок действия
 * @param {string} desc   — описание
 * @param {boolean} needName — показывать ли поле «имя»
 * @returns {Promise<{password, name}|null>}  null если отмена
 */
function peAskPassword(title, desc, needName = false) {
    return new Promise(resolve => {
        const modal = document.getElementById('pe-password-modal');
        const pwdInput = document.getElementById('pe-pwd-input');
        const nameRow = document.getElementById('pe-pwd-name-row');
        const nameInput = document.getElementById('pe-pwd-name-input');
        const errEl = document.getElementById('pe-pwd-error');
        const confirmBtn = document.getElementById('pe-pwd-confirm');
        const cancelBtn = document.getElementById('pe-pwd-cancel');
        const closeBtn = document.getElementById('pe-pwd-close');

        document.getElementById('pe-pwd-title').textContent = title;
        document.getElementById('pe-pwd-desc').textContent = desc;
        pwdInput.value = '';
        nameInput.value = '';
        errEl.textContent = '';
        errEl.classList.add('hidden');
        nameRow.classList.toggle('hidden', !needName);

        modal.classList.remove('hidden');
        modal.classList.add('flex');
        (needName ? nameInput : pwdInput).focus();

        function cleanup() {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.removeEventListener('click', onConfirm);
            cancelBtn.removeEventListener('click', onCancel);
            closeBtn.removeEventListener('click', onCancel);
            pwdInput.removeEventListener('keydown', onKey);
        }

        function onConfirm() {
            const pwd = pwdInput.value.trim();
            const name = nameInput.value.trim();
            if (!pwd) {
                errEl.textContent = 'Введите пароль';
                errEl.classList.remove('hidden');
                pwdInput.focus();
                return;
            }
            if (needName && !name) {
                errEl.textContent = 'Введите имя промпта';
                errEl.classList.remove('hidden');
                nameInput.focus();
                return;
            }
            cleanup();
            resolve({ password: pwd, name });
        }

        function onCancel() { cleanup(); resolve(null); }

        function onKey(e) { if (e.key === 'Enter') onConfirm(); }

        confirmBtn.addEventListener('click', onConfirm);
        cancelBtn.addEventListener('click', onCancel);
        closeBtn.addEventListener('click', onCancel);
        pwdInput.addEventListener('keydown', onKey);
    });
}

// ──── Инициализация ──────────────────────────────────────────

async function peInitEditor() {
    peLoad();
    try {
        const res = await fetch('/api/prompts');
        const data = await res.json();
        promptEditor.originals = data.prompts || {};
    } catch (e) {
        console.error('Не удалось загрузить промпты', e);
    }

    // Установить первый ключ по умолчанию для каждой вкладки
    const styles = promptEditor.originals['step2_style'] || {};
    const step3 = promptEditor.originals['step3'] || {};

    if (!promptEditor.activeStyleKey || promptEditor.activeKey === 'step2_style') {
        promptEditor.activeStyleKey = Object.keys(styles)[0] || null;
    }
    if (promptEditor.activeKey === 'step3') {
        promptEditor.activeStyleKey = promptEditor.step3Key || Object.keys(step3)[0] || 'default';
    }

    // Если step3Key не был загружен из localStorage — установить дефолт из доступных ключей
    if (!promptEditor.step3Key || !(promptEditor.step3Key in step3)) {
        promptEditor.step3Key = ('yur_bud_svoboden' in step3) ? 'yur_bud_svoboden' : (Object.keys(step3)[0] || 'default');
    }

    // Заполняем внешний дропдаун "Аудио-сценарий (промпт)" в настройках
    const step3Select = document.getElementById('step3-prompt-select');
    if (step3Select && Object.keys(step3).length) {
        step3Select.innerHTML = Object.keys(step3).map(k =>
            `<option value="${k}" ${k === promptEditor.step3Key ? 'selected' : ''}>${k}</option>`
        ).join('');
        step3Select.addEventListener('change', (e) => {
            promptEditor.step3Key = e.target.value;
            localStorage.setItem('pe_step3_key', e.target.value);
            // Синхронизируем PE-редактор если открыт
            if (promptEditor.activeKey === 'step3') {
                promptEditor.activeStyleKey = e.target.value;
                peRenderEditor();
            }
        });
    }

    peRenderEditor();
    peUpdateTabStyle();
}

function peInitUI() {
    const card = document.getElementById('prompt-editor-card');
    const toggle = document.getElementById('prompt-editor-toggle');
    const closeBtn = document.getElementById('prompt-editor-close');
    const textarea = document.getElementById('prompt-editor-text');
    const saveSessionBtn = document.getElementById('prompt-save-session-btn');
    const saveDiskBtn = document.getElementById('prompt-save-disk-btn');
    const createBtn = document.getElementById('prompt-create-btn');
    const deleteBtn = document.getElementById('prompt-delete-btn');
    const resetBtn = document.getElementById('prompt-reset-btn');

    if (!card || !toggle) return;

    // Восстанавливаем состояние
    if (localStorage.getItem(LS_EDITOR_OPEN) === '1') {
        card.classList.remove('hidden');
        peInitEditor();
    }

    toggle.addEventListener('click', () => {
        const isOpen = !card.classList.contains('hidden');
        card.classList.toggle('hidden', isOpen);
        localStorage.setItem(LS_EDITOR_OPEN, isOpen ? '0' : '1');
        if (!isOpen) peInitEditor();
    });

    if (closeBtn) closeBtn.addEventListener('click', () => {
        card.classList.add('hidden');
        localStorage.setItem(LS_EDITOR_OPEN, '0');
    });

    // Переключение вкладок
    document.querySelectorAll('.prompt-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            if (textarea) peApplyToSession(textarea.value);
            promptEditor.activeKey = btn.dataset.key;
            const pool = promptEditor.originals[promptEditor.activeKey] || {};
            promptEditor.activeStyleKey = Object.keys(pool)[0] || null;
            peRenderEditor();
            peUpdateTabStyle();
        });
    });

    // Обновляем предупреждение при вводе
    if (textarea) {
        textarea.addEventListener('input', () => {
            peCheckWarning(textarea.value, promptEditor.activeKey);
        });
    }

    // ── Применить на сессию ──
    if (saveSessionBtn) saveSessionBtn.addEventListener('click', () => {
        if (!textarea) return;
        const text = textarea.value;
        if (!peValidatePlaceholders(text)) return;
        peApplyToSession(text);
        peSave();
        peSetStatusMsg('Применено на текущую сессию ✓');
    });

    // ── Перезаписать на диск ──
    if (saveDiskBtn) saveDiskBtn.addEventListener('click', async () => {
        if (!textarea) return;
        const text = textarea.value;
        if (!peValidatePlaceholders(text)) return;

        const result = await peAskPassword(
            'Перезапись промпта',
            `Промпт «${promptEditor.activeStyleKey}» будет изменён на диске. Это действие необратимо.`
        );
        if (!result) return;

        saveDiskBtn.disabled = true;
        try {
            const body = {
                target: promptEditor.activeKey,
                content: text,
                style_key: promptEditor.activeStyleKey,
                password: result.password,
            };
            const res = await fetch('/api/prompts/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (data.ok) {
                // Обновляем originals локально
                (promptEditor.originals[promptEditor.activeKey] ??= {})[promptEditor.activeStyleKey] = text;
                const sk = peGetSessionKey();
                delete promptEditor.session[sk];
                peSave();
                _promptsCache = null; // сбрасываем кэш для просмотра
                peSetStatusMsg('Перезаписано на диск ✓');
            } else {
                peSetStatusMsg(data.error || 'Ошибка сохранения', true);
            }
        } catch (e) {
            peSetStatusMsg('Ошибка сети', true);
        } finally {
            saveDiskBtn.disabled = false;
        }
    });

    // ── Создать новый промпт ──
    if (createBtn) createBtn.addEventListener('click', async () => {
        if (!textarea) return;
        const text = textarea.value;
        if (!peValidatePlaceholders(text)) return;

        const result = await peAskPassword(
            'Создание нового промпта',
            'Введите имя для нового промпта и подтвердите паролем.',
            true /* needName */
        );
        if (!result) return;

        createBtn.disabled = true;
        try {
            const res = await fetch('/api/prompts/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target: promptEditor.activeKey,
                    name: result.name,
                    content: text,
                    password: result.password,
                }),
            });
            const data = await res.json();
            if (data.ok) {
                // Добавляем в originals и переключаемся на новый
                (promptEditor.originals[promptEditor.activeKey] ??= {})[result.name] = text;
                promptEditor.activeStyleKey = result.name;
                peUpdateTabStyle();
                peRenderEditor();
                _promptsCache = null; // сбрасываем кэш для просмотра
                peSetStatusMsg(`Промпт «${result.name}» создан ✓`);
            } else {
                peSetStatusMsg(data.error || 'Ошибка создания', true);
            }
        } catch (e) {
            peSetStatusMsg('Ошибка сети', true);
        } finally {
            createBtn.disabled = false;
        }
    });

    // ── Удалить промпт ──
    if (deleteBtn) deleteBtn.addEventListener('click', async () => {
        if (deleteBtn.disabled) return;
        const name = promptEditor.activeStyleKey;

        const result = await peAskPassword(
            'Удаление промпта',
            `Промпт «${name}» будет удалён безвозвратно.`
        );
        if (!result) return;

        deleteBtn.disabled = true;
        try {
            const res = await fetch('/api/prompts/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target: promptEditor.activeKey,
                    name,
                    password: result.password,
                }),
            });
            const data = await res.json();
            if (data.ok) {
                const pool = promptEditor.originals[promptEditor.activeKey] || {};
                delete pool[name];
                // Убираем из сессии
                delete promptEditor.session[peGetSessionKey()];
                peSave();
                // Переключаемся на первый оставшийся
                promptEditor.activeStyleKey = Object.keys(pool)[0] || null;
                peUpdateTabStyle();
                peRenderEditor();
                peSetStatusMsg(`Промпт «${name}» удалён ✓`);
            } else {
                peSetStatusMsg(data.error || 'Ошибка удаления', true);
            }
        } catch (e) {
            peSetStatusMsg('Ошибка сети', true);
        } finally {
            deleteBtn.disabled = false;
            peUpdateDeleteBtn();
        }
    });

    // ── Сбросить к оригиналу ──
    if (resetBtn) resetBtn.addEventListener('click', () => {
        delete promptEditor.session[peGetSessionKey()];
        peSave();
        peRenderEditor();
        peSetStatusMsg('Сброшено к оригиналу');
    });
}

function peValidatePlaceholders(text) {
    const required = PROMPT_PLACEHOLDERS[promptEditor.activeKey] || [];
    const missing = required.filter(ph => !text.includes(ph));
    if (missing.length > 0) {
        peSetStatusMsg(`Добавьте плейсхолдеры: ${missing.join(', ')}`, true);
        return false;
    }
    return true;
}

/** Возвращает объект custom_prompts для передачи в API /api/query */
function peGetCustomPrompts() {
    const out = {};
    // Step2 style override (only if edited)
    for (const [sk, val] of Object.entries(promptEditor.session)) {
        if (sk.startsWith('step2_style:')) {
            const styleKey = sk.replace('step2_style:', '');
            const currentStyle = document.getElementById('style-select')?.value;
            if (styleKey === currentStyle) out['step2_style'] = val;
        }
    }
    // Step3: send the selected prompt key name and its text (custom or original)
    const step3Key = promptEditor.step3Key || 'yur_bud_svoboden';
    out['step3_name'] = step3Key;
    // Check if this key has been edited in session
    const sessionKey = `step3:${step3Key}`;
    if (promptEditor.session[sessionKey] !== undefined) {
        out['step3'] = promptEditor.session[sessionKey];
    } else {
        // Use the original server-side text for this named prompt
        const pool = promptEditor.originals['step3'] || {};
        if (pool[step3Key]) out['step3'] = pool[step3Key];
    }
    return Object.keys(out).length ? out : null;
}

// Инициализация при загрузке DOM
document.addEventListener('DOMContentLoaded', () => {
    peInitUI();
});

// ──── Аудио-сценарий (промпт) — внешний дропдаун ─────────────

async function _initStep3PromptSelect() {
    const sel = document.getElementById('step3-prompt-select');
    if (!sel) return;
    try {
        const res = await fetch('/api/prompts');
        const data = await res.json();
        const step3 = (data.prompts || {})['step3'] || {};
        if (!Object.keys(step3).length) return;

        const saved = localStorage.getItem('pe_step3_key') || 'yur_bud_svoboden';
        const defaultKey = (saved in step3) ? saved : (('yur_bud_svoboden' in step3) ? 'yur_bud_svoboden' : Object.keys(step3)[0]);

        sel.innerHTML = Object.keys(step3).map(k =>
            `<option value="${k}" ${k === defaultKey ? 'selected' : ''}>${k}</option>`
        ).join('');

        // Sync promptEditor if it's loaded
        if (typeof promptEditor !== 'undefined') {
            promptEditor.step3Key = defaultKey;
        }

        sel.addEventListener('change', (e) => {
            localStorage.setItem('pe_step3_key', e.target.value);
            if (typeof promptEditor !== 'undefined') {
                promptEditor.step3Key = e.target.value;
                if (promptEditor.activeKey === 'step3') {
                    promptEditor.activeStyleKey = e.target.value;
                    if (typeof peRenderEditor === 'function') peRenderEditor();
                }
            }
        });
    } catch (e) {
        console.error('_initStep3PromptSelect error', e);
    }
}

// ──── Таймкоды Deepgram (главная страница) ────────────────────

let _tcPollTimer = null;

function _applyTimecodes(stats) {
    const jsonLink = document.getElementById('step4-tc-json');
    const vttLink  = document.getElementById('step4-tc-vtt');
    const spinner  = document.getElementById('step4-tc-spinner');
    if (stats.timecodes_json_url && jsonLink && vttLink) {
        jsonLink.href = stats.timecodes_json_url;
        jsonLink.classList.remove('hidden');
        vttLink.href  = stats.timecodes_vtt_url || '#';
        vttLink.classList.remove('hidden');
        if (spinner) spinner.classList.add('hidden');
    }
}

function _pollTimecodes(slug) {
    if (_tcPollTimer) clearInterval(_tcPollTimer);
    let attempts = 0;
    _tcPollTimer = setInterval(async () => {
        attempts++;
        if (attempts > 40) { clearInterval(_tcPollTimer); return; } // макс ~5 мин
        try {
            const r = await fetch(`/api/text/${slug}`);
            if (!r.ok) return;
            const d = await r.json();
            const stats = d.step4_stats || {};
            if (stats.timecodes_json_url) {
                clearInterval(_tcPollTimer);
                _applyTimecodes(stats);
            }
        } catch (e) { /* тихо */ }
    }, 8000);
}

// ──── Просмотр промптов ───────────────────────────────────────

let _promptsCache = null;

async function openPromptPreview(group, key) {
    if (!key) return;
    const modal = document.getElementById('prompt-preview-modal');
    const titleEl = document.getElementById('prompt-preview-title');
    const textEl = document.getElementById('prompt-preview-text');
    if (!modal) return;

    titleEl.textContent = key;
    textEl.textContent = '⏳ Загрузка...';
    modal.classList.remove('hidden');
    modal.classList.add('flex');

    try {
        if (!_promptsCache) {
            const res = await fetch('/api/prompts');
            const data = await res.json();
            _promptsCache = data.prompts || {};
        }
        const text = (_promptsCache[group] || {})[key];
        textEl.textContent = text != null ? text : '(промпт не найден)';
    } catch (e) {
        textEl.textContent = 'Ошибка загрузки промпта.';
    }
}

function closePromptPreview() {
    const modal = document.getElementById('prompt-preview-modal');
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePromptPreview();
});