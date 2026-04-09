/* static/js/app.js */
let currentPrompts = null;
let allHistory = [];
let isHistoryExpanded = false;
let currentTab = 'text';
window.currentSlug = null;

function switchTab(tab) {
    currentTab = tab;
    const tabText = document.getElementById('tab-text');
    const tabAudio = document.getElementById('tab-audio');
    const audioOnlyElements = document.querySelectorAll('.audio-only');
    
    if (tab === 'text') {
        tabText.className = "px-6 py-2.5 rounded-xl font-bold transition-all bg-brand-lightBg text-brand-main shadow-sm flex items-center gap-2";
        tabAudio.className = "px-6 py-2.5 rounded-xl font-bold transition-all text-gray-500 hover:text-brand-main hover:bg-gray-50 flex items-center gap-2";
        audioOnlyElements.forEach(el => el.classList.add('hidden'));
        
        const styleSelect = document.getElementById('style-select');
        const savedStyleText = localStorage.getItem('selectedStyleText') || 'telegram_yur';
        if (styleSelect.querySelector(`option[value="${savedStyleText}"]`)) {
            styleSelect.value = savedStyleText;
        }
    } else {
        tabAudio.className = "px-6 py-2.5 rounded-xl font-bold transition-all bg-brand-lightBg text-brand-main shadow-sm flex items-center gap-2";
        tabText.className = "px-6 py-2.5 rounded-xl font-bold transition-all text-gray-500 hover:text-brand-main hover:bg-gray-50 flex items-center gap-2";
        audioOnlyElements.forEach(el => el.classList.remove('hidden'));
        
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

    const savedSpeakerBoost = localStorage.getItem('useSpeakerBoost');
    if (savedSpeakerBoost !== null) document.getElementById('use-speaker-boost').checked = savedSpeakerBoost === 'true';
    document.getElementById('use-speaker-boost').addEventListener('change', (e) => localStorage.setItem('useSpeakerBoost', e.target.checked));
});

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const data = await response.json();
        
        const savedModel = localStorage.getItem('selectedModel') || data.default_model;
        const modelSelect = document.getElementById('model-select');
        modelSelect.innerHTML = data.models.map(m => 
            `<option value="${m.id}" ${m.id === savedModel ? 'selected' : ''}>${m.name}</option>`
        ).join('');
        modelSelect.addEventListener('change', (e) => localStorage.setItem('selectedModel', e.target.value));

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
            const voiceOptions = data.voices.map(v => 
                `<option value="${v.voice_id}" ${v.voice_id === savedVoice ? 'selected' : ''}>${v.name} (${v.description})</option>`
            ).join('');
            const voiceSelect = document.getElementById('elevenlabs-voice');
            if(voiceSelect) {
                voiceSelect.innerHTML = voiceOptions;
                voiceSelect.addEventListener('change', (e) => {
                    localStorage.setItem('elevenlabsVoice', e.target.value);
                });
            }
            const regenVoice = document.getElementById('regen-voice');
            if(regenVoice) {
                regenVoice.innerHTML = voiceOptions;
                regenVoice.value = savedVoice;
                regenVoice.addEventListener('change', (e) => {
                    localStorage.setItem('elevenlabsVoice', e.target.value);
                    if(voiceSelect) voiceSelect.value = e.target.value;
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

async function sendQuery() {
    const question = document.getElementById('question-input').value.trim();
    if (!question) {
        const qInput = document.getElementById('question-input');
        qInput.classList.add('ring-2', 'ring-red-500', 'border-red-500');
        setTimeout(() => qInput.classList.remove('ring-2', 'ring-red-500', 'border-red-500'), 1000);
        return;
    }

    const model = document.getElementById('model-select').value;
    const style = document.getElementById('style-select').value;
    const threshold = parseInt(document.getElementById('context-threshold').value) || 70;
    const maxLength = parseInt(document.getElementById('max-length').value) || 4000;
    const audioDuration = parseInt(document.getElementById('audio-duration').value) || 60;
    const audioWpm = parseInt(document.getElementById('audio-wpm').value) || 150;
    const elevenlabsModel = document.getElementById('elevenlabs-model') ? document.getElementById('elevenlabs-model').value : 'eleven_v3';
    const elevenlabsVoice = document.getElementById('elevenlabs-voice') ? document.getElementById('elevenlabs-voice').value : 'FGY2WhTYpPnroxEErjIq';
    const audioStyle = document.getElementById('audio-style') ? parseFloat(document.getElementById('audio-style').value) : 0.25;
    const useSpeakerBoost = document.getElementById('use-speaker-boost') ? document.getElementById('use-speaker-boost').checked : true;
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
    
    document.getElementById('loading-desc').textContent = "Инициализация...";
    
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin text-lg"></i> Запрос в обработке...';
    submitBtn.classList.add('opacity-80', 'cursor-not-allowed');

    try {
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                model: model,
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
                use_speaker_boost: useSpeakerBoost
            })
        });

        if (!response.ok) {
            let err = "Произошла ошибка сервера";
            try {
                const errData = await response.json();
                err = errData.detail || err;
            } catch(e) {}
            throw new Error(err);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalData = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            
            for (const line of lines) {
                if (!line.trim()) continue;
                try {
                    const chunk = JSON.parse(line);
                    if (chunk.step === "error") {
                        throw new Error(chunk.message);
                    } else if (chunk.step === "done") {
                        finalData = chunk.result;
                    } else if (chunk.step === "partial") {
                        loadingState.classList.add('hidden');
                        successState.classList.remove('hidden');
                        successState.classList.add('flex');
                        
                        const data = chunk.data;
                        if (data.step1_info) {
                            document.getElementById('step1-info').innerHTML = formatStep1Info(data.step1_info);
                            document.getElementById('card-step1').classList.remove('hidden');
                        }
                        if (data.answer) {
                            document.getElementById('final-answer').innerHTML = marked.parse(data.answer);
                            document.getElementById('card-step2').classList.remove('hidden');
                        }
                        if (data.step3_audio) {
                            document.getElementById('step3-audio-text').innerHTML = marked.parse(data.step3_audio);
                            document.getElementById('step3-audio-container').classList.remove('hidden');
                            
                            const audioDuration = document.getElementById('audio-duration').value;
                            const audioWpm = document.getElementById('audio-wpm').value;
                            document.getElementById('step3-param-duration').textContent = audioDuration;
                            document.getElementById('step3-param-wpm').textContent = audioWpm;
                            document.getElementById('step3-audio-params').classList.remove('hidden');
                        }
                    } else {
                        document.getElementById('loading-desc').innerHTML = chunk.message;
                        const floatingLoader = document.getElementById('floating-loader-text');
                        if (floatingLoader) {
                            floatingLoader.innerHTML = chunk.message;
                            document.getElementById('floating-loader').classList.remove('hidden');
                        }
                    }
                } catch(err) {
                    if (err.message !== "Unexpected end of JSON input") throw err;
                }
            }
        }
        
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
                
                let origModel = 'N/A', origVoiceId = 'N/A', origVoiceName = 'N/A', origWpm = 'N/A', origSpeed = 'N/A';
                let origStability = '0.5', origSimilarity = '0.75', origStyle = '0.25', origBoost = 'true';
                const m1 = data.answer.match(/Модель: (.+)/);
                if (m1) origModel = m1[1].trim();
                const m2 = data.answer.match(/Диктор ID: (.+)/);
                if (m2) origVoiceId = m2[1].trim();
                const m_name = data.answer.match(/Диктор Имя: (.+)/);
                if (m_name) {
                    origVoiceName = m_name[1].trim().split('-')[0].trim();
                } else if (origVoiceId !== 'N/A') {
                    origVoiceName = origVoiceId.substring(0,8) + '...';
                }
                const m3 = data.answer.match(/Скорость: (.+) \((.+) слов\/мин\)/);
                if (m3) {
                    origSpeed = m3[1].trim();
                    origWpm = m3[2].trim();
                }
                const m_stab = data.answer.match(/Stability: (.+)/);
                if (m_stab) origStability = m_stab[1].trim();
                const m_sim = data.answer.match(/Similarity: (.+)/);
                if (m_sim) origSimilarity = m_sim[1].trim();
                const m_style = data.answer.match(/Style: (.+)/);
                if (m_style) origStyle = m_style[1].trim();
                const m_boost = data.answer.match(/Speaker Boost: (.+)/);
                if (m_boost) origBoost = m_boost[1].trim();
                
                let displayCost = '';
                const m4 = data.answer.match(/Символов: \d+ \(\$([0-9]+\.[0-9]+)\)/);
                if (m4 && m4[1]) {
                    displayCost = ` | Цена: $${m4[1]}`;
                } else if (data.step4_cost) {
                    displayCost = ` | Цена: $${parseFloat(data.step4_cost).toFixed(3)}`;
                }
                
                if (step4AudioBadge) {
                    step4AudioBadge.innerHTML = `<span class="text-xs font-semibold px-2 py-1 bg-purple-100 text-purple-700 rounded-md block w-fit mb-3 border border-purple-200 shadow-sm">${origModel} | Voice: ${origVoiceName} | ${origWpm} сл/мин | Speed: ${origSpeed} | Stability: ${origStability} | Similarity: ${origSimilarity} | Style: ${origStyle} | Boost: ${origBoost}${displayCost}</span>`;
                }
                
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
            } else {
                step4AudioPlayerContainer.classList.add('hidden');
            }
        } else {
            step3AudioContainer.classList.add('hidden');
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
        showError(error.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="far fa-paper-plane text-lg"></i> Отправить запрос';
        submitBtn.classList.remove('opacity-80', 'cursor-not-allowed');
    }
}