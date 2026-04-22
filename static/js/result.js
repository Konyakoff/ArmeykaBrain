/* static/js/result.js */
window.currentSlug = null;

document.addEventListener('DOMContentLoaded', async () => {
    const slug = window.location.pathname.split('/').pop();
    window.currentSlug = slug;
    if (!slug) {
        showError("Не указан идентификатор запроса.");
        return;
    }

    try {
        const configRes = await fetch('/api/config');
        if (configRes.ok) {
            const configData = await configRes.json();
            if (configData.voices && configData.voices.length > 0) {
                const voiceOptions = configData.voices.map(v => 
                    `<option value="${v.voice_id}" ${v.voice_id === configData.default_voice ? 'selected' : ''}>${v.name} (${v.description})</option>`
                ).join('');
                const regenVoice = document.getElementById('regen-voice');
                if (regenVoice) regenVoice.innerHTML = voiceOptions;
                const upgradeVoice = document.getElementById('upgrade-voice');
                if (upgradeVoice) upgradeVoice.innerHTML = voiceOptions;
            }
        }
    } catch(e) { console.error('Failed to load config voices', e); }

    try {
        const res = await fetch(`/api/text/${slug}`);
        if (!res.ok) throw new Error("Результат не найден");
        const data = await res.json();
        
        document.getElementById('loading-state').classList.add('hidden');
        document.getElementById('success-state').classList.remove('hidden');
        document.getElementById('success-state').classList.add('flex');
        
        document.getElementById('res-date').textContent = data.timestamp;
        document.getElementById('res-chars').innerHTML = `<i class="fas fa-text-width mr-1"></i> Символов: ${data.char_count}`;
        document.getElementById('res-question').textContent = data.question;

        document.getElementById('step1-info').innerHTML = formatStep1Info(data.step1_info);
        if (data.step1_stats) document.getElementById('step1-stats').innerHTML = formatStats(data.step1_stats, 1);
        
        document.getElementById('final-answer').innerHTML = marked.parse(data.answer);
        if (data.step2_stats) document.getElementById('step2-stats').innerHTML = formatStats(data.step2_stats, 2);

        if (data.total_stats) document.getElementById('total-stats').innerHTML = formatTotalStats(data.total_stats);

        const step3AudioContainer = document.getElementById('step3-audio-container');
        const step3AudioText = document.getElementById('step3-audio-text');
        const step4AudioPlayerContainer = document.getElementById('step4-audio-player-container');
        const step4AudioPlayer = document.getElementById('step4-audio-player');
        const step4AudioSource = document.getElementById('step4-audio-source');
        const step4AudioBadge = document.getElementById('step4-audio-badge');
        const upgradeAudioContainer = document.getElementById('upgrade-audio-container');
        
        if (data.step3_audio) {
            if (upgradeAudioContainer) upgradeAudioContainer.classList.add('hidden');
            step3AudioContainer.classList.remove('hidden');
            step3AudioText.innerHTML = marked.parse(data.step3_audio);
            if (data.step3_stats) document.getElementById('step3-stats').innerHTML = formatStats(data.step3_stats, 3);
            
            let origWpm = 'N/A';
            let origDuration = 'N/A';
            const m3 = data.answer ? data.answer.match(/Скорость: (.+) \((.+) слов\/мин\)/) : null;
            if (m3) {
                origWpm = m3[2].trim();
            }
            const m_dur = data.answer ? data.answer.match(/Длительность: (\d+) сек/) : null;
            if (m_dur) {
                origDuration = m_dur[1].trim();
            }
            
            // To get duration we can look at the wpm and word count if we want, or just hide if not present.
            // The prompt says "Длительность: X сек". If it's history, we might not have it unless it's stored.
            // But let's check if the element exists and populate it.
            const paramDurationElem = document.getElementById('step3-param-duration');
            const paramWpmElem = document.getElementById('step3-param-wpm');
            const paramContainer = document.getElementById('step3-audio-params');
            
            if (paramDurationElem && paramWpmElem && paramContainer) {
                if (origWpm !== 'N/A' || origDuration !== 'N/A') {
                    paramWpmElem.textContent = origWpm;
                    paramDurationElem.textContent = origDuration;
                    paramContainer.classList.remove('hidden');
                }
            }
            
            if (data.step4_audio_url) {
                step4AudioPlayerContainer.classList.remove('hidden');
                step4AudioSource.src = data.step4_audio_url;
                document.getElementById('step4-audio-download').href = data.step4_audio_url_original || data.step4_audio_url;
                step4AudioPlayer.load();
                
                // Add video generation block
                const videoBlockId = 'video-upgrade-main';
                let videoBlockContainer = document.getElementById(videoBlockId);
                if (!videoBlockContainer) {
                    videoBlockContainer = document.createElement('div');
                    videoBlockContainer.id = videoBlockId;
                    step4AudioPlayerContainer.insertBefore(videoBlockContainer, document.getElementById('evaluation-result-container'));
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
                    
                    const savedModel = localStorage.getItem('elevenlabsModel');
                    const regenModel = document.getElementById('regen-model');
                    if (regenModel) regenModel.value = savedModel || (origModel !== 'N/A' ? origModel : 'eleven_v3');
                    
                    const savedVoice = localStorage.getItem('elevenlabsVoice');
                    const regenVoice = document.getElementById('regen-voice');
                    if (regenVoice) {
                        let vToSet = savedVoice || origVoiceId;
                        if (vToSet !== 'N/A' && [...regenVoice.options].some(o => o.value === vToSet)) {
                            regenVoice.value = vToSet;
                        }
                    }
                    
                    const savedWpm = localStorage.getItem('audioWpm');
                    const regenWpm = document.getElementById('regen-wpm');
                    if (regenWpm) {
                        let wpmToSet = savedWpm || (origWpm !== 'N/A' ? origWpm : '150');
                        let clampedWpm = Math.max(105, Math.min(parseInt(wpmToSet), 180));
                        regenWpm.value = clampedWpm;
                        const regenWpmVal = document.getElementById('regen-wpm-val');
                        if (regenWpmVal) regenWpmVal.innerText = clampedWpm;
                    }

                    const savedStability = localStorage.getItem('audioStability');
                    const regenStability = document.getElementById('regen-stability');
                    if (regenStability) regenStability.value = savedStability || origStability;

                    const savedSimilarity = localStorage.getItem('audioSimilarity');
                    const regenSimilarity = document.getElementById('regen-similarity');
                    if (regenSimilarity) regenSimilarity.value = savedSimilarity || origSimilarity;

                    const savedStyle = localStorage.getItem('audioStyle');
                    const regenStyle = document.getElementById('regen-style');
                    if (regenStyle) regenStyle.value = savedStyle || origStyle;

                    const savedBoost = localStorage.getItem('useSpeakerBoost');
                    const regenBoost = document.getElementById('regen-boost');
                    if (regenBoost) regenBoost.checked = savedBoost !== null ? savedBoost === 'true' : (origBoost === 'true');
                    
                    document.getElementById('step4-stats').innerHTML = formatStats(data.step4_stats, 4);
                    
                    if (step4AudioBadge) {
                        step4AudioBadge.classList.add('hidden'); // hide old badge
                    }
                }
                
                if (data.evaluation_main) {
                    document.getElementById('evaluation-result-container').classList.remove('hidden');
                    document.getElementById('eval-percent').textContent = data.evaluation_main.percent_ideal + '%';
                    document.getElementById('eval-stability').textContent = data.evaluation_main.stability;
                    document.getElementById('eval-similarity').textContent = data.evaluation_main.similarity;
                    document.getElementById('eval-do-better').textContent = data.evaluation_main.do_better || 'Нет рекомендаций';
                    if (data.evaluation_main.cost) {
                        document.getElementById('eval-cost').textContent = `Цена: $${parseFloat(data.evaluation_main.cost).toFixed(3)}`;
                    }
                }
                
                const container = document.getElementById('additional-audios');
                container.innerHTML = '';
                if (data.additional_audios_list && data.additional_audios_list.length > 0) {
                    data.additional_audios_list.forEach(audio => {
                        const div = document.createElement('div');
                        div.className = "bg-white p-4 rounded-xl border border-gray-100 shadow-sm";
                        
                        let addCost = audio.cost ? ` | Цена: $${parseFloat(audio.cost).toFixed(3)}` : '';
                        
                        const voiceSelect = document.getElementById('regen-voice');
                        let voiceName = audio.voice ? audio.voice.substring(0,8) + '...' : 'N/A';
                        if (voiceSelect && audio.voice) {
                            for (let i = 0; i < voiceSelect.options.length; i++) {
                                if (voiceSelect.options[i].value === audio.voice) {
                                    voiceName = voiceSelect.options[i].text.split('-')[0].trim();
                                    break;
                                }
                            }
                        }

                        const uniqueId = Date.now().toString() + Math.floor(Math.random() * 1000).toString();
                        
                        let evalBlock = '';
                        if (audio.evaluation) {
                            evalBlock = `
                                <div id="eval-result-${uniqueId}" class="mt-2 bg-purple-50 border border-purple-100 rounded-xl p-3">
                                    <h4 class="font-bold text-brand-dark mb-2 text-xs flex items-center gap-2"><i class="fas fa-chart-line text-purple-500"></i> Оценка качества (Gemini 3.1 Pro)</h4>
                                    <div class="flex flex-wrap gap-3 text-xs text-brand-dark mb-1">
                                        <div class="flex flex-col relative">
                                            <span class="text-[10px] text-gray-500">Идеальность</span>
                                            <span class="font-bold text-purple-600 cursor-pointer underline decoration-dotted underline-offset-2 hover:text-purple-800" onclick="toggleTooltip('eval-tooltip-${uniqueId}')" id="eval-percent-${uniqueId}">${audio.evaluation.percent_ideal}%</span>
                                            <div class="absolute bottom-full left-0 mb-2 w-80 sm:w-96 md:w-[600px] max-w-[90vw] max-h-[60vh] flex flex-col bg-gray-800 text-white text-[10px] rounded-lg opacity-0 invisible transition-all z-50 shadow-2xl eval-tooltip" id="eval-tooltip-${uniqueId}">
                                                <div class="flex justify-between items-center p-2 border-b border-gray-700 bg-gray-900 rounded-t-lg sticky top-0">
                                                    <span class="font-bold">Рекомендации Gemini</span>
                                                    <button onclick="closeTooltip('eval-tooltip-${uniqueId}')" class="text-gray-400 hover:text-white px-2"><i class="fas fa-times text-sm"></i></button>
                                                </div>
                                                <div class="p-2 overflow-y-auto whitespace-pre-wrap" id="eval-do-better-${uniqueId}">${audio.evaluation.do_better || 'Нет рекомендаций'}</div>
                                            </div>
                                        </div>
                                        <div class="flex flex-col">
                                            <span class="text-[10px] text-gray-500">Рек. Stability</span>
                                            <span class="font-bold" id="eval-stability-${uniqueId}">${audio.evaluation.stability}</span>
                                        </div>
                                        <div class="flex flex-col">
                                            <span class="text-[10px] text-gray-500">Рек. Similarity</span>
                                            <span class="font-bold" id="eval-similarity-${uniqueId}">${audio.evaluation.similarity}</span>
                                        </div>
                                    </div>
                                    <div class="text-[10px] text-gray-500" id="eval-cost-${uniqueId}">Цена: $${parseFloat(audio.evaluation.cost || 0).toFixed(3)}</div>
                                </div>
                            `;
                        } else {
                            evalBlock = `
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
                            `;
                        }
                        
                        div.innerHTML = `
                            <div class="flex flex-col gap-2">
                                <div class="flex items-center justify-between">
                                    <h5 class="font-bold text-sm text-brand-dark">Дополнительный вариант</h5>
                                    <span class="text-xs font-semibold px-2 py-1 bg-purple-100 text-purple-700 rounded-md">${audio.model || 'N/A'} | Voice: ${voiceName} | ${audio.wpm || 'N/A'} сл/мин | Speed: ${audio.speed ? audio.speed.toFixed(2) : 'N/A'}${addCost}</span>
                                </div>
                                <div class="flex items-center gap-3">
                                    <audio controls class="flex-1 h-10">
                                        <source src="${audio.audio_url}" type="audio/mpeg">
                                    </audio>
                                    <a href="${audio.audio_url_original || audio.audio_url}" download class="flex-shrink-0 bg-brand-lightBg text-purple-500 hover:text-white hover:bg-purple-500 border border-purple-200 transition-colors w-10 h-10 flex items-center justify-center rounded-xl shadow-sm" title="Скачать оригинальное аудио">
                                        <i class="fas fa-download"></i>
                                    </a>
                                    <button id="eval-btn-${uniqueId}" onclick="evaluateAdditionalAudio('${uniqueId}', '${audio.audio_url}', '${audio.model}', '${audio.voice}', ${audio.stability !== undefined ? audio.stability : 0.5}, ${audio.similarity_boost !== undefined ? audio.similarity_boost : 0.75}, ${audio.style !== undefined ? audio.style : 0.25}, ${audio.use_speaker_boost !== undefined ? audio.use_speaker_boost : true})" class="flex-shrink-0 bg-brand-lightBg text-purple-500 hover:text-white hover:bg-purple-500 border border-purple-200 transition-colors w-10 h-10 flex items-center justify-center rounded-xl shadow-sm" title="Оценить качество">
                                        <i class="fas fa-star"></i>
                                    </button>
                                </div>
                                <div class="text-xs text-gray-500 flex gap-3">
                                    <span>Stability: ${audio.stability !== undefined ? audio.stability : 'N/A'}</span>
                                    <span>Similarity: ${audio.similarity_boost !== undefined ? audio.similarity_boost : 'N/A'}</span>
                                    <span>Style: ${audio.style !== undefined ? audio.style : 'N/A'}</span>
                                    <span>Boost: ${audio.use_speaker_boost !== undefined ? audio.use_speaker_boost : 'true'}</span>
                                </div>
                                
                                ${evalBlock}
                                
                                <div id="video-wrapper-${uniqueId}">
                                    <!-- Видео блок рендерится здесь -->
                                </div>
                            </div>
                        `;
                        container.appendChild(div);
                        
                        const videoWrapper = document.getElementById(`video-wrapper-${uniqueId}`);
                        if (audio.video_id) {
                            videoWrapper.innerHTML = `
                                <div class="mt-4 pt-4 border-t border-gray-100">
                                    <div id="video-result-container-${uniqueId}"></div>
                                </div>
                            `;
                            const resultContainer = document.getElementById(`video-result-container-${uniqueId}`);
                            if (audio.video_url) {
                                resultContainer.innerHTML = `
                                    <div class="flex flex-col gap-2">
                                        <video controls class="max-h-[50vh] w-auto max-w-full rounded-lg shadow border border-indigo-100" style="object-fit: contain;">
                                            <source src="${audio.video_url}" type="video/mp4">
                                            Ваш браузер не поддерживает видео.
                                        </video>
                                        <a href="${audio.video_url}" download target="_blank" class="mt-2 text-center text-sm font-medium text-indigo-600 hover:text-indigo-800">
                                            <i class="fas fa-download"></i> Скачать видео
                                        </a>
                                    </div>
                                `;
                            } else {
                                resultContainer.innerHTML = `
                                    <div class="flex flex-col items-center gap-3 w-full bg-gray-50 rounded-xl p-6 border border-dashed border-gray-300">
                                        <i class="fas fa-spinner fa-spin text-3xl text-indigo-500 mb-2"></i>
                                        <p class="text-brand-dark font-medium text-sm text-center">Видео генерируется...</p>
                                    </div>
                                `;
                                pollSpecificVideo(audio.video_id, uniqueId, window.currentSlug, false);
                            }
                        } else {
                            videoWrapper.innerHTML = renderVideoUpgradeBlock(uniqueId, audio.audio_url_original || audio.audio_url, false);
                        }
                    });
                }
            } else {
                step4AudioPlayerContainer.classList.add('hidden');
            }
        } else {
            step3AudioContainer.classList.add('hidden');
            if (data.tab_type === 'text') {
                if (upgradeAudioContainer) {
                    upgradeAudioContainer.classList.remove('hidden');
                    
                    const savedDuration = localStorage.getItem('audioDuration');
                    if (savedDuration) document.getElementById('upgrade-duration').value = savedDuration;
                    
                    const savedWpm = localStorage.getItem('audioWpm');
                    const upgradeWpm = document.getElementById('upgrade-wpm');
                    if (upgradeWpm && savedWpm) {
                        let clampedWpm = Math.max(105, Math.min(parseInt(savedWpm), 180));
                        upgradeWpm.value = clampedWpm;
                        const upgradeWpmVal = document.getElementById('upgrade-wpm-val');
                        if (upgradeWpmVal) upgradeWpmVal.innerText = clampedWpm;
                    }

                    const savedModel = localStorage.getItem('elevenlabsModel');
                    if (savedModel) document.getElementById('upgrade-model').value = savedModel;

                    const savedVoice = localStorage.getItem('elevenlabsVoice');
                    const upgradeVoice = document.getElementById('upgrade-voice');
                    if (upgradeVoice && savedVoice && [...upgradeVoice.options].some(o => o.value === savedVoice)) {
                        upgradeVoice.value = savedVoice;
                    }

                    const savedStyle = localStorage.getItem('audioStyle');
                    if (savedStyle) document.getElementById('upgrade-style').value = savedStyle;

                    const savedStability = localStorage.getItem('audioStability');
                    if (savedStability) document.getElementById('upgrade-stability').value = savedStability;

                    const savedSimilarity = localStorage.getItem('audioSimilarity');
                    if (savedSimilarity) document.getElementById('upgrade-similarity').value = savedSimilarity;

                    const savedBoost = localStorage.getItem('useSpeakerBoost');
                    if (savedBoost !== null) document.getElementById('upgrade-boost').checked = savedBoost === 'true';
                    
                    const upgradeVideoCb = document.getElementById('upgrade-video');
                    const upgradeAvatarContainer = document.getElementById('upgrade-avatar-container');
                    if (upgradeVideoCb && upgradeAvatarContainer) {
                        upgradeVideoCb.addEventListener('change', (e) => {
                            if (e.target.checked) {
                                upgradeAvatarContainer.style.display = 'flex';
                            } else {
                                upgradeAvatarContainer.style.display = 'none';
                            }
                        });
                        
                        // Загрузим список аватаров
                        fetch('/api/config').then(res => res.json()).then(cfg => {
                            if (cfg.avatars && cfg.avatars.length > 0) {
                                windowAvatars = cfg.avatars;
                                if (cfg.private_avatars) windowPrivateAvatars = cfg.private_avatars;
                                const savedAvatar = localStorage.getItem('heygenAvatar') || cfg.default_avatar;
                                const savedVideoFormat = localStorage.getItem('videoFormat') || '16:9';
                                
                                const formatElem = document.getElementById('upgrade-video-format');
                                if (formatElem) {
                                    formatElem.value = savedVideoFormat;
                                    formatElem.addEventListener('change', (e) => {
                                        updateAvatarButtonText('upgrade-avatar', 'upgrade-avatar-btn', 'upgrade-video-format');
                                        updateAvatarStyleHint('upgrade-video-format', 'upgrade-avatar-style', 'upgrade-avatar-style-hint');
                                    });
                                }
                                
                                // Восстанавливаем сохранённый стиль кадрирования
                                const savedAvatarStyle = localStorage.getItem('avatarStyle') || 'auto';
                                const upgradeStyleElem = document.getElementById('upgrade-avatar-style');
                                if (upgradeStyleElem) upgradeStyleElem.value = savedAvatarStyle;
                                updateAvatarStyleHint('upgrade-video-format', 'upgrade-avatar-style', 'upgrade-avatar-style-hint');
                                
                                updateAvatarButtonText('upgrade-avatar', 'upgrade-avatar-btn', 'upgrade-video-format');
                                
                                const savedHeygenEngine = localStorage.getItem('heygenEngine');
                                if (savedHeygenEngine) {
                                    const engineElem = document.getElementById('upgrade-heygen-engine');
                                    if (engineElem) engineElem.value = savedHeygenEngine;
                                }
                            }
                        }).catch(e => console.error("Error loading config for upgrade:", e));
                    }
                }
            }
        }
        
        if (data.step5_video_id || data.step5_video_url) {
            const step5VideoContainer = document.getElementById('step5-video-container');
            const step5VideoContent = document.getElementById('step5-video-content');
            if (step5VideoContainer) {
                step5VideoContainer.classList.remove('hidden');
                
                if (data.step5_stats) {
                    document.getElementById('step5-stats').innerHTML = formatStats(data.step5_stats, 5);
                }
                
                if (data.step5_video_url) {
                    step5VideoContent.innerHTML = `
                                    <video controls class="max-h-[70vh] w-auto max-w-full mx-auto rounded-xl shadow-lg border-2 border-indigo-200" style="object-fit: contain;">
                                        <source src="${data.step5_video_url}" type="video/mp4">
                                        Ваш браузер не поддерживает видео.
                                    </video>
                        <div class="mt-4 flex gap-4">
                            <a href="${data.step5_video_url}" download target="_blank" class="bg-indigo-500 hover:bg-indigo-600 text-white font-bold py-2 px-6 rounded-xl transition-all shadow-sm flex items-center justify-center gap-2">
                                <i class="fas fa-download"></i> Скачать видео
                            </a>
                        </div>
                    `;
                } else {
                    // Poll
                    step5VideoContent.innerHTML = `
                        <div class="flex flex-col items-center gap-3 w-full">
                            <div class="bg-gray-100 rounded-xl p-8 flex flex-col items-center justify-center w-full max-w-2xl border-2 border-dashed border-gray-300">
                                <i class="fas fa-spinner fa-spin text-4xl text-indigo-500 mb-4"></i>
                                <p class="text-brand-dark font-medium text-center">Видео генерируется...</p>
                                <p class="text-sm text-gray-500 text-center mt-2">Это может занять несколько минут. Вы можете закрыть страницу и проверить позже по этой же ссылке.</p>
                            </div>
                        </div>
                    `;
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
                                fetch('/api/update_video_result', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ slug: window.currentSlug, video_url: stData.video_url })
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
                }
            }
        }

    } catch(e) {
        showError(e.message);
    }
});

async function upgradeToAudio() {
    const duration = document.getElementById('upgrade-duration').value;
    const wpm = document.getElementById('upgrade-wpm').value;
    const model = document.getElementById('upgrade-model').value;
    const voice = document.getElementById('upgrade-voice').value;
    const style = document.getElementById('upgrade-style').value;
    const stability = document.getElementById('upgrade-stability').value;
    const similarity = document.getElementById('upgrade-similarity').value;
    const boost = document.getElementById('upgrade-boost').checked;
    const generateVideo = document.getElementById('upgrade-video') ? document.getElementById('upgrade-video').checked : false;
    const avatar = document.getElementById('upgrade-avatar') ? document.getElementById('upgrade-avatar').value : 'Abigail_standing_office_front';
    const videoFormat = document.getElementById('upgrade-video-format') ? document.getElementById('upgrade-video-format').value : '16:9';
    const heygenEngine = document.getElementById('upgrade-heygen-engine') ? document.getElementById('upgrade-heygen-engine').value : 'avatar_iv';
    const upgradeAvatarStyleEl = document.getElementById('upgrade-avatar-style');
    const upgradeAvatarStyle = upgradeAvatarStyleEl ? upgradeAvatarStyleEl.value : 'auto';
    
    // Сохраняем в localStorage
    localStorage.setItem('audioDuration', duration);
    localStorage.setItem('audioWpm', wpm);
    localStorage.setItem('elevenlabsModel', model);
    localStorage.setItem('elevenlabsVoice', voice);
    localStorage.setItem('audioStyle', style);
    localStorage.setItem('audioStability', stability);
    localStorage.setItem('audioSimilarity', similarity);
    localStorage.setItem('useSpeakerBoost', boost);
    if(generateVideo) {
        localStorage.setItem('heygenAvatar', avatar);
        localStorage.setItem('videoFormat', videoFormat);
        localStorage.setItem('heygenEngine', heygenEngine);
        localStorage.setItem('avatarStyle', upgradeAvatarStyle);
    }
    
    if (!window.currentSlug) return;
    
    const btn = document.getElementById('btn-upgrade-audio');
    const loadingBlock = document.getElementById('upgrade-loading');
    const statusText = document.getElementById('upgrade-status-text');
    
    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
    loadingBlock.classList.remove('hidden');
    statusText.innerText = "Инициализация...";
    
    try {
        const response = await fetch('/api/upgrade_to_audio', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify({
                slug: window.currentSlug,
                audio_duration: parseInt(duration),
                audio_wpm: parseInt(wpm),
                elevenlabs_model: model,
                elevenlabs_voice: voice,
                audio_style: parseFloat(style),
                audio_stability: parseFloat(stability),
                audio_similarity_boost: parseFloat(similarity),
                use_speaker_boost: boost,
                generate_video: generateVideo,
                heygen_avatar_id: avatar,
                video_format: videoFormat,
                heygen_engine: heygenEngine,
                avatar_style: upgradeAvatarStyle
            })
        });
        
        if (!response.ok) {
            throw new Error(`Ошибка сети: ${response.status}`);
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let done = false;
        let buffer = '';
        
        while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
                buffer += decoder.decode(value, { stream: true });
                const blocks = buffer.split(/\r?\n\r?\n/);
                buffer = blocks.pop(); // Keep incomplete block
                
                for (const block of blocks) {
                    const lines = block.split(/\r?\n/);
                    let dataJson = null;
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const jsonStr = line.substring(6).trim();
                            if (jsonStr) {
                                try {
                                    dataJson = JSON.parse(jsonStr);
                                } catch (e) {
                                    console.error('Ошибка парсинга JSON SSE:', e, jsonStr);
                                }
                            }
                        }
                    }
                    
                    if (dataJson) {
                        if (dataJson.message) {
                            statusText.innerText = dataJson.message;
                        }
                        if (dataJson.step === 'done') {
                            statusText.innerText = "Готово! Обновляю страницу...";
                            setTimeout(() => {
                                window.location.reload();
                            }, 1000);
                        } else if (dataJson.step === 'error') {
                            throw new Error(dataJson.message || "Неизвестная ошибка");
                        }
                    }
                }
            }
        }
    } catch (e) {
        statusText.innerText = "Ошибка: " + e.message;
        statusText.classList.remove('text-purple-700');
        statusText.classList.add('text-red-500');
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
}