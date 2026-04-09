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
                document.getElementById('step4-audio-download').href = data.step4_audio_url;
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
                    let clampedWpm = Math.max(105, Math.min(parseInt(origWpm), 180));
                    regenWpm.value = clampedWpm;
                    const regenWpmVal = document.getElementById('regen-wpm-val');
                    if (regenWpmVal) regenWpmVal.innerText = clampedWpm;
                }

                const regenStability = document.getElementById('regen-stability');
                if (regenStability) regenStability.value = origStability;

                const regenSimilarity = document.getElementById('regen-similarity');
                if (regenSimilarity) regenSimilarity.value = origSimilarity;

                const regenStyle = document.getElementById('regen-style');
                if (regenStyle) regenStyle.value = origStyle;

                const regenBoost = document.getElementById('regen-boost');
                if (regenBoost) regenBoost.checked = origBoost === 'true';
                
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
                            </div>
                        `;
                        container.appendChild(div);
                    });
                }
            } else {
                step4AudioPlayerContainer.classList.add('hidden');
            }
        } else {
            step3AudioContainer.classList.add('hidden');
        }

    } catch(e) {
        showError(e.message);
    }
});