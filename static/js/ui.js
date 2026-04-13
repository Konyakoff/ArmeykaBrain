/* static/js/ui.js */
marked.use({ breaks: true });

let windowAvatars = [];
let windowPrivateAvatars = [];   // личные аватары (talking photos)

let currentAvatarTargetInput = null;
let currentAvatarTargetBtn = null;
let _avatarModalTab = 'public';  // 'public' | 'private'

/** Превью с нашего бэкенда: корректный Content-Type, без блокировок HeyGen и без Tailwind в строках. */
function avatarPreviewUrl(avatarId) {
    return '/api/avatar-preview/' + encodeURIComponent(avatarId);
}

function isAvatarFriendly(a, format) {
    if (format === '9:16') return a.is_vertical_friendly;
    if (format === '1:1') return a.is_square_friendly;
    return a.is_horizontal_friendly;
}

/**
 * Показывает подсказку и при auto-режиме переключает стиль кадрирования
 * в зависимости от выбранного формата видео.
 */
function updateAvatarStyleHint(formatSelectId, styleSelectId, hintId) {
    const format = getVideoFormatValue(formatSelectId);
    const styleEl = document.getElementById(styleSelectId);
    const hintEl = document.getElementById(hintId);
    
    if (!styleEl) return;
    
    const isPortrait = format === '9:16' || format === '1:1';
    
    // Если стоит auto — меняем хинт но не трогаем значение (авто сам разберётся на сервере)
    if (hintEl) {
        if (isPortrait && styleEl.value === 'auto') {
            hintEl.classList.remove('hidden');
        } else {
            hintEl.classList.add('hidden');
        }
    }
}

function getVideoFormatValue(formatSelectId) {
    const el = document.getElementById(formatSelectId);
    return el && el.value ? el.value : '16:9';
}

/**
 * @param formatSelectId — id элемента <select> формата (на значение .value), например 'video-format'
 */
function updateAvatarButtonText(inputId, btnId, formatSelectId) {
    const input = document.getElementById(inputId);
    const btn   = document.getElementById(btnId);
    if (!input || !btn) return;

    // Ищем сначала в публичных, потом в приватных
    const allKnown = [...windowAvatars, ...windowPrivateAvatars];
    if (allKnown.length === 0) return;

    const format  = getVideoFormatValue(formatSelectId);
    const savedId = input.value || localStorage.getItem('heygenAvatar');
    let   avatar  = allKnown.find(a => a.avatar_id === savedId);

    if (!avatar) {
        // Нет сохранённого → выбираем первый подходящий публичный
        let friendly = windowAvatars.filter(a => isAvatarFriendly(a, format));
        if (friendly.length === 0) friendly = windowAvatars;
        avatar = friendly[0] || null;
        if (avatar) input.value = avatar.avatar_id;
    }

    btn.replaceChildren();
    const SPAN_CSS = 'font-size:13px;color:#374151;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    if (avatar) {
        // Используем /static напрямую (без API-прокси) — так же как карточки в SSR
        const thumbDiv = document.createElement('div');
        thumbDiv.style.cssText = 'width:24px;height:24px;border-radius:50%;flex-shrink:0;'
            + 'border:1px solid #e5e7eb;display:inline-block;'
            + "background:url('/static/img/avatars/" + avatar.avatar_id + ".webp') top center/cover;";
        const span = document.createElement('span');
        span.style.cssText = SPAN_CSS;
        span.textContent = avatar.avatar_name || avatar.avatar_id;
        btn.appendChild(thumbDiv);
        btn.appendChild(span);
    } else {
        const i = document.createElement('i');
        i.className = 'fas fa-user-circle';
        i.style.cssText = 'color:#9ca3af;font-size:1.25rem;';
        btn.appendChild(i);
        const span = document.createElement('span');
        span.style.cssText = SPAN_CSS;
        span.textContent = 'Выбрать аватар...';
        btn.appendChild(span);
    }
}

/**
 * LEGACY — оставлено для справки, но НЕ вызывается.
 * Заменено SSR-подходом: /api/avatars-html + innerHTML.
 */
function _buildAvatarGrid(avatarList, currentSelectedId, format) {
    const frag = document.createDocumentFragment();
    const FMT = {
        '16:9': { key: 'is_horizontal_friendly', label: '16:9', color: '#4f46e5' },
        '9:16': { key: 'is_vertical_friendly',   label: '9:16', color: '#059669' },
        '1:1':  { key: 'is_square_friendly',     label: '1:1',  color: '#d97706' }
    };
    const fmt = FMT[format] || FMT['16:9'];

    avatarList.forEach(a => {
        const isSel = a.avatar_id === currentSelectedId;
        const isGood = !!a[fmt.key];

        // ── Cell (div, not button — avoids Tailwind button reset) ──
        const cell = document.createElement('div');
        cell.setAttribute('role', 'button');
        cell.setAttribute('tabindex', '0');
        cell.style.cssText = 'display:flex;flex-direction:column;margin:0;padding:0;'
            + 'border-radius:12px;cursor:pointer;overflow:hidden;min-width:0;'
            + 'background:#fff;transition:border-color .15s,box-shadow .15s;'
            + 'border:2px solid ' + (isSel ? '#F47920' : '#e5e7eb') + ';'
            + 'box-shadow:' + (isSel ? '0 0 0 3px rgba(244,121,32,.35)' : '0 1px 3px rgba(0,0,0,.06)') + ';';
        cell.onmouseenter = function() { this.style.borderColor = '#F47920'; };
        cell.onmouseleave = function() { if (!isSel) this.style.borderColor = '#e5e7eb'; };

        // ── Thumb (background-image, фиксированная высота в px) ──
        const thumb = document.createElement('div');
        thumb.style.cssText = 'width:100%;height:140px;min-height:140px;'
            + 'background-color:#e5e7eb;position:relative;overflow:hidden;'
            + "background-image:url('" + avatarPreviewUrl(a.avatar_id) + "');"
            + 'background-size:cover;background-position:top center;';

        // ── Format badge ──
        const badge = document.createElement('div');
        badge.textContent = (isGood ? '✓ ' : '~ ') + fmt.label;
        badge.style.cssText = 'position:absolute;top:4px;right:4px;'
            + 'font-size:9px;font-weight:700;line-height:1;'
            + 'padding:2px 5px;border-radius:4px;color:#fff;letter-spacing:.3px;'
            + 'background:' + (isGood ? fmt.color : '#6b7280') + ';';
        thumb.appendChild(badge);

        // ── Label ──
        const label = document.createElement('div');
        label.textContent = a.avatar_name || a.avatar_id;
        label.style.cssText = 'padding:8px 6px;font-size:11px;font-weight:600;'
            + 'line-height:1.25;color:#374151;text-align:center;'
            + 'min-height:2.75em;display:flex;align-items:center;justify-content:center;';

        cell.appendChild(thumb);
        cell.appendChild(label);
        cell.addEventListener('click', () => selectAvatarFromModal(a.avatar_id));
        frag.appendChild(cell);
    });
    return frag;
}

// ─── SSR Avatar Modal ────────────────────────────────────────────────────────
// Карточки генерируются на сервере (/api/avatars-html) с inline-стилями.
// JS только делает fetch → innerHTML → подсветка выбранного.
// Это полностью устраняет конфликты с Tailwind CDN preflight.
// ─────────────────────────────────────────────────────────────────────────────

let _avatarHtmlCache = {};  // key: "tab:format:showAll" → html string

function openAvatarModal(formatSelectId, inputId, btnId) {
    currentAvatarTargetInput = inputId;
    currentAvatarTargetBtn   = btnId;

    const format  = getVideoFormatValue(formatSelectId);
    const input   = document.getElementById(inputId);
    const selId   = input ? (input.value || '') : '';

    const modal   = document.getElementById('avatar-modal');
    const content = document.getElementById('avatar-modal-content');
    const grid    = document.getElementById('avatar-modal-grid');
    if (!modal || !content || !grid) return;

    // Сбрасываем гендерный фильтр при каждом открытии
    _currentGender = 'all';

    // Event delegation — навешиваем один раз, живёт весь сеанс
    if (!grid.dataset.delegated) {
        grid.addEventListener('click', e => {
            // Клик по иконке предпросмотра
            const previewBtn = e.target.closest('[data-preview-id]');
            if (previewBtn) {
                e.stopPropagation();
                _showAvatarPreview(previewBtn.dataset.previewId, previewBtn);
                return;
            }
            // Клик по строке — выбор аватара
            const card = e.target.closest('[data-avatar-id]');
            if (card) selectAvatarFromModal(card.dataset.avatarId);
        });
        grid.dataset.delegated = '1';
    }

    // Tab bar
    let tabBar = document.getElementById('avatar-tab-bar');
    if (!tabBar) {
        tabBar = document.createElement('div');
        tabBar.id = 'avatar-tab-bar';
        grid.parentNode.insertBefore(tabBar, grid);
    }
    _renderAvatarTabs(tabBar, format, selId);

    // Filter bar (только для public)
    let filterBar = document.getElementById('avatar-modal-filter');
    if (!filterBar) {
        filterBar = document.createElement('div');
        filterBar.id = 'avatar-modal-filter';
        grid.parentNode.insertBefore(filterBar, grid);
    }
    _updateFilterBar(filterBar, format, selId, false);

    // Загружаем карточки с сервера
    _loadAvatarGrid(grid, filterBar, format, selId, _avatarModalTab, false);

    // Показываем модал
    modal.classList.remove('hidden');
    modal.style.display = 'flex';
    modal.style.zIndex  = '9999';
    void modal.offsetWidth;
    modal.classList.remove('opacity-0');
    content.classList.remove('scale-95');
    document.body.style.overflow = 'hidden';
}

/** Загружает HTML аватаров с сервера (или из кэша), вставляет через innerHTML */
function _loadAvatarGrid(grid, filterBar, format, selId, tab, showAll) {
    // Контейнер: разный CSS для текстового списка (public) и карточек (private)
    if (tab === 'private') {
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));'
            + 'gap:12px;padding:16px;overflow-y:auto;flex:1 1 auto;min-height:0;'
            + 'max-height:min(72vh,640px);background:#f9fafb;-webkit-overflow-scrolling:touch;';
    } else {
        grid.style.cssText = 'display:flex;flex-direction:column;overflow-y:auto;'
            + 'flex:1 1 auto;min-height:0;max-height:min(72vh,640px);background:#fff;';
    }

    const cacheKey = tab + ':' + format + ':' + (showAll ? '1' : '0');

    const inject = html => {
        grid.innerHTML = html;
        _highlightSelected(grid, selId, tab);
        if (tab === 'public') _applyGenderFilter(grid, _currentGender);
    };

    if (_avatarHtmlCache[cacheKey]) { inject(_avatarHtmlCache[cacheKey]); return; }

    const spinner = tab === 'private'
        ? 'grid-column:1/-1;padding:48px;text-align:center;'
        : 'padding:48px;text-align:center;';
    grid.innerHTML = '<div style="' + spinner + 'color:#9ca3af;font-size:13px;">'
        + '<i class="fas fa-spinner fa-spin" style="margin-right:8px;"></i>Загрузка...</div>';

    fetch('/api/avatars-html?format=' + encodeURIComponent(format)
            + '&tab=' + encodeURIComponent(tab)
            + '&show_all=' + (showAll ? '1' : '0'))
        .then(r => r.text())
        .then(html => { _avatarHtmlCache[cacheKey] = html; inject(html); })
        .catch(() => {
            grid.innerHTML = '<div style="padding:48px;text-align:center;color:#ef4444;font-size:13px;">'
                + '<i class="fas fa-exclamation-triangle" style="margin-right:8px;"></i>Ошибка загрузки</div>';
        });
}

/** Подсвечивает выбранный аватар: фон для текстовых строк, рамка для карточек */
function _highlightSelected(grid, selId, tab) {
    if (!selId) return;
    grid.querySelectorAll('[data-avatar-id]').forEach(el => {
        const isSel = el.dataset.avatarId === selId;
        if (tab === 'public') {
            el.style.background = isSel ? '#fff7ed' : '#fff';
            el.dataset.sel = isSel ? '1' : '';
            el.querySelectorAll('span').forEach(s => {
                if (s.style.flex === '1') s.style.color = isSel ? '#F47920' : '#374151';
            });
        } else {
            el.style.borderColor = isSel ? '#F47920' : '#e5e7eb';
            el.style.boxShadow   = isSel ? '0 0 0 3px rgba(244,121,32,.35)' : '0 1px 3px rgba(0,0,0,.06)';
        }
    });
}

// Текущий гендерный фильтр ('all' | 'female' | 'male')
let _currentGender = 'all';

/** Применяет гендерный фильтр к строкам в гриде */
function _applyGenderFilter(grid, gender) {
    _currentGender = gender;
    grid.querySelectorAll('[data-gender]').forEach(row => {
        const ok = gender === 'all' || row.dataset.gender === gender;
        row.style.display = ok ? '' : 'none';
    });
}

/**
 * Показывает всплывающую карточку с фото аватара.
 * Всплывашка позиционируется по viewport через position:fixed.
 */
function _showAvatarPreview(avatarId, triggerEl) {
    let popup = document.getElementById('ab-avatar-preview-popup');
    if (!popup) {
        popup = document.createElement('div');
        popup.id = 'ab-avatar-preview-popup';
        popup.style.cssText = 'position:fixed;z-index:11000;width:220px;background:#fff;'
            + 'border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.28);overflow:hidden;display:none;';
        document.body.appendChild(popup);

        // Закрываем по клику снаружи
        document.addEventListener('click', e => {
            if (!popup.contains(e.target) && !e.target.closest('[data-preview-id]')) {
                popup.style.display = 'none';
            }
        }, true);
    }

    // Если уже открыт для того же аватара — закрываем (toggle)
    if (popup.style.display !== 'none' && popup.dataset.aid === avatarId) {
        popup.style.display = 'none';
        return;
    }
    popup.dataset.aid = avatarId;

    const imgUrl = '/static/img/avatars/' + avatarId + '.webp';
    const row    = triggerEl.closest('[data-avatar-id]');
    const nameEl = row ? row.querySelector('[style*="flex:1"]') : null;
    const name   = nameEl ? nameEl.textContent.trim() : avatarId;

    popup.innerHTML =
        '<div style="position:relative;">'
        + '<img src="' + imgUrl + '" '
        + 'style="width:100%;height:240px;object-fit:cover;object-position:top center;display:block;" '
        + 'onerror="this.parentNode.parentNode.style.display=\'none\'">'
        + '<button onclick="document.getElementById(\'ab-avatar-preview-popup\').style.display=\'none\'" '
        + 'style="position:absolute;top:8px;right:8px;width:26px;height:26px;border-radius:50%;'
        + 'background:rgba(0,0,0,.55);border:none;cursor:pointer;color:#fff;font-size:13px;'
        + 'display:flex;align-items:center;justify-content:center;line-height:1;">✕</button>'
        + '</div>'
        + '<div style="padding:10px 12px;font-size:12px;font-weight:600;color:#374151;'
        + 'text-align:center;line-height:1.4;">' + name + '</div>';

    // Позиционируем справа от иконки, корректируем чтобы не вышло за край экрана
    popup.style.display = 'block';
    const rect = triggerEl.getBoundingClientRect();
    const pw = 220, ph = popup.offsetHeight || 290;
    let left = rect.right + 10;
    let top  = rect.top + rect.height / 2 - ph / 2;

    if (left + pw > window.innerWidth - 8) left = rect.left - pw - 10;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    if (top + ph > window.innerHeight - 8) top = window.innerHeight - ph - 8;

    popup.style.left = left + 'px';
    popup.style.top  = top  + 'px';
}

/** Строит инфо-строку с фильтрами: кол-во рекомендованных + гендер + «показать все» */
function _updateFilterBar(filterBar, format, selId, showAll) {
    if (_avatarModalTab === 'private') { filterBar.style.display = 'none'; return; }

    filterBar.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;'
        + 'padding:6px 14px;font-size:12px;color:#6b7280;flex-shrink:0;'
        + 'border-bottom:1px solid #f3f4f6;background:#fafafa;';
    filterBar.innerHTML = '';

    // ── Гендерный фильтр ───────────────────────────────────────────────────
    const genders = [['all','Все'],['female','♀ Жен'],['male','♂ Муж']];
    genders.forEach(([g, label]) => {
        const btn = document.createElement('div');
        btn.setAttribute('role', 'button');
        btn.textContent = label;
        const active = _currentGender === g;
        btn.style.cssText = 'padding:2px 10px;border-radius:20px;cursor:pointer;font-size:11px;font-weight:600;'
            + 'border:1px solid ' + (active ? '#F47920' : '#e5e7eb') + ';'
            + 'background:' + (active ? '#F47920' : '#fff') + ';'
            + 'color:' + (active ? '#fff' : '#6b7280') + ';';
        btn.onclick = () => {
            const grid = document.getElementById('avatar-modal-grid');
            if (grid) _applyGenderFilter(grid, g);
            _updateFilterBar(filterBar, format, selId, showAll);
        };
        filterBar.appendChild(btn);
    });

    if (windowAvatars.length === 0) return;

    // ── Разделитель ────────────────────────────────────────────────────────
    const sep = document.createElement('span');
    sep.style.cssText = 'flex:1;';
    filterBar.appendChild(sep);

    // ── Счётчик + «Показать все» ───────────────────────────────────────────
    let rec;
    if (format === '9:16')     rec = windowAvatars.filter(a => a.is_vertical_friendly);
    else if (format === '1:1') rec = windowAvatars.filter(a => a.is_square_friendly);
    else                       rec = windowAvatars.filter(a => a.is_horizontal_friendly);
    if (rec.length === 0) rec = windowAvatars;

    const recCnt = rec.length, totalCnt = windowAvatars.length;

    const countSpan = document.createElement('span');
    countSpan.textContent = showAll ? 'Все: ' + totalCnt : 'Рек. ' + format + ': ' + recCnt;
    filterBar.appendChild(countSpan);

    if (!showAll && recCnt < totalCnt) {
        const allBtn = document.createElement('div');
        allBtn.setAttribute('role', 'button');
        allBtn.textContent = 'Показать все (' + totalCnt + ')';
        allBtn.style.cssText = 'color:#F47920;cursor:pointer;font-weight:600;text-decoration:underline;margin-left:6px;';
        allBtn.onclick = () => {
            const grid = document.getElementById('avatar-modal-grid');
            if (grid) { _updateFilterBar(filterBar, format, selId, true); _loadAvatarGrid(grid, filterBar, format, selId, 'public', true); }
        };
        filterBar.appendChild(allBtn);
    }
}

/** Вкладки «Публичные» / «Мои аватары» */
function _renderAvatarTabs(tabBar, format, selId) {
    tabBar.innerHTML = '';
    tabBar.style.cssText = 'display:flex;gap:4px;padding:10px 12px 0;'
        + 'flex-shrink:0;border-bottom:1px solid #f1f5f9;';

    const makeTab = (text, icon, active, onClick) => {
        const el = document.createElement('div');
        el.setAttribute('role', 'button');
        el.innerHTML = '<i class="fas ' + icon + '"></i> ' + text;
        el.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:8px 16px;'
            + 'border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;font-weight:600;'
            + 'user-select:none;border:1px solid transparent;border-bottom:none;'
            + (active
                ? 'background:#fff;color:#F47920;border-color:#f1f5f9;margin-bottom:-1px;padding-bottom:9px;'
                : 'background:transparent;color:#6b7280;');
        if (!active) {
            el.onmouseenter = function () { this.style.color = '#374151'; this.style.background = '#f9fafb'; };
            el.onmouseleave = function () { this.style.color = '#6b7280'; this.style.background = 'transparent'; };
        }
        el.onclick = onClick;
        return el;
    };

    tabBar.appendChild(makeTab('Публичные', 'fa-users', _avatarModalTab === 'public', () => {
        _avatarModalTab = 'public';
        const grid      = document.getElementById('avatar-modal-grid');
        const filterBar = document.getElementById('avatar-modal-filter');
        _renderAvatarTabs(tabBar, format, selId);
        _updateFilterBar(filterBar, format, selId, false);
        _loadAvatarGrid(grid, filterBar, format, selId, 'public', false);
    }));

    const cnt = windowPrivateAvatars.length;
    tabBar.appendChild(makeTab('Мои аватары' + (cnt ? ' (' + cnt + ')' : ''), 'fa-user-circle', _avatarModalTab === 'private', () => {
        _avatarModalTab = 'private';
        const grid      = document.getElementById('avatar-modal-grid');
        const filterBar = document.getElementById('avatar-modal-filter');
        _renderAvatarTabs(tabBar, format, selId);
        _updateFilterBar(filterBar, format, selId, false);
        _loadAvatarGrid(grid, filterBar, format, selId, 'private', false);
    }));
}

function closeAvatarModal() {
    const modal = document.getElementById('avatar-modal');
    const content = document.getElementById('avatar-modal-content');

    // Закрываем попап предпросмотра если открыт
    const popup = document.getElementById('ab-avatar-preview-popup');
    if (popup) popup.style.display = 'none';

    modal.classList.add('opacity-0');
    content.classList.add('scale-95');

    setTimeout(() => {
        modal.classList.add('hidden');
        modal.style.display = '';
        modal.style.zIndex = '';
        const grid = document.getElementById('avatar-modal-grid');
        if (grid) grid.replaceChildren();
        document.body.style.overflow = '';
    }, 300);
}

function resolveFormatSelectId(btnId) {
    if (!btnId) return 'video-format';
    if (btnId === 'upgrade-avatar-btn' || btnId.indexOf('upgrade') !== -1) return 'upgrade-video-format';
    if (btnId.indexOf('video-avatar-btn-') === 0) {
        const uid = btnId.replace('video-avatar-btn-', '');
        return 'video-format-' + uid;
    }
    return 'video-format';
}

function selectAvatarFromModal(avatarId) {
    if (currentAvatarTargetInput) {
        const inp = document.getElementById(currentAvatarTargetInput);
        if (inp) {
            inp.value = avatarId;
            if (currentAvatarTargetInput === 'heygen-avatar') {
                localStorage.setItem('heygenAvatar', avatarId);
            }
        }
    }

    if (currentAvatarTargetBtn && currentAvatarTargetInput) {
        const formatSelectId = resolveFormatSelectId(currentAvatarTargetBtn);
        updateAvatarButtonText(currentAvatarTargetInput, currentAvatarTargetBtn, formatSelectId);
    }

    closeAvatarModal();
}

function formatStats(stats, step) {
    if (!stats) return '';
    if (stats.error) {
        return `<div class="text-xs text-red-500 mt-2 p-2 bg-red-50 rounded-lg border border-red-100"><i class="fas fa-exclamation-triangle mr-1"></i>Ошибка: ${stats.error}</div>`;
    }
    
    let html = `<div class="text-[11px] text-gray-400 mt-3 p-2 bg-gray-50/50 rounded-lg border border-gray-100 flex flex-wrap gap-x-4 gap-y-1">`;
    
    if (stats.model) html += `<span><i class="fas fa-robot mr-1 text-gray-300"></i>${stats.model}</span>`;
    
    if (step === 1 || step === 2 || step === 3) {
        if (stats.in_tokens) html += `<span title="Входящие токены"><i class="fas fa-sign-in-alt mr-1 text-gray-300"></i>${stats.in_tokens} tk</span>`;
        if (stats.out_tokens) html += `<span title="Исходящие токены"><i class="fas fa-sign-out-alt mr-1 text-gray-300"></i>${stats.out_tokens} tk</span>`;
    }
    
    if (step === 4) {
        if (stats.voice_name) html += `<span><i class="fas fa-microphone-alt mr-1 text-gray-300"></i>${stats.voice_name}</span>`;
        if (stats.duration_sec) html += `<span><i class="fas fa-clock mr-1 text-gray-300"></i>${stats.duration_sec}s</span>`;
        if (stats.wpm) html += `<span><i class="fas fa-tachometer-alt mr-1 text-gray-300"></i>${stats.wpm} wpm</span>`;
        if (stats.char_count) html += `<span><i class="fas fa-font mr-1 text-gray-300"></i>${stats.char_count} chars</span>`;
    }

    if (step === 5) {
        if (stats.avatar_id) html += `<span><i class="fas fa-user-circle mr-1 text-gray-300"></i>${stats.avatar_id}</span>`;
        if (stats.video_id) html += `<span title="Video ID"><i class="fas fa-fingerprint mr-1 text-gray-300"></i>${stats.video_id}</span>`;
    }
    
    if (stats.generation_time_sec !== undefined) {
        html += `<span title="Время генерации"><i class="fas fa-stopwatch mr-1 text-gray-300"></i>${stats.generation_time_sec}s</span>`;
    }
    
    // Add total cost for this step
    if (stats.total_cost !== undefined) {
        html += `<span class="font-semibold text-gray-500 ml-auto"><i class="fas fa-dollar-sign mr-1 text-gray-300"></i>${parseFloat(stats.total_cost).toFixed(3)}</span>`;
    } else if (stats.cost !== undefined) {
        html += `<span class="font-semibold text-gray-500 ml-auto"><i class="fas fa-dollar-sign mr-1 text-gray-300"></i>${parseFloat(stats.cost).toFixed(3)}</span>`;
    }
    
    html += `</div>`;
    return html;
}

function formatTotalStats(totalStats) {
    if (!totalStats || totalStats.total_cost === undefined) return '';
    return `
        <div class="bg-gradient-to-r from-gray-50 to-gray-100 rounded-[16px] shadow-sm p-4 border border-gray-200 mt-8 mb-4 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 bg-white rounded-full flex items-center justify-center text-green-500 shadow-sm border border-gray-100">
                    <i class="fas fa-receipt"></i>
                </div>
                <span class="font-bold text-gray-700 text-sm">Итоговая стоимость генерации (API):</span>
            </div>
            <span class="font-black text-green-600 text-lg">$${parseFloat(totalStats.total_cost).toFixed(3)}</span>
        </div>
    `;
}

function formatStep1Info(data) {
    if (!data || typeof data === 'string') return marked.parse(data); // Fallback for old history data
    
    let html = '';
    
    // Category
    html += `
        <div class="mb-4">
            <strong class="text-brand-dark tracking-wide uppercase text-sm flex items-center mb-2">
                <div class="inline-flex items-center justify-center w-8 h-8 bg-blue-50 text-blue-500 rounded-[40%_60%_70%_30%/40%_50%_60%_50%] mr-3 mb-1"><i class="fas fa-folder-open text-xs"></i></div>
                Классификация вопроса: ${data.query_category}
            </strong>
        </div>
    `;

    // Articles
    if (data.articles && data.articles.length > 0) {
        html += `
            <div class="mb-4">
                <strong class="text-brand-dark tracking-wide uppercase text-sm flex items-center mb-2">
                    <div class="inline-flex items-center justify-center w-8 h-8 bg-green-50 text-green-500 rounded-[60%_40%_30%_70%/60%_30%_70%_40%] mr-3 mb-1"><i class="fas fa-check text-xs"></i></div>
                    Найденные статьи (ТОП-15):
                </strong>
                <div class="flex flex-col gap-2">
        `;
        data.articles.forEach(a => {
            html += `<div class="text-sm text-gray-500 bg-gray-50/50 p-2 px-3 rounded-lg border border-gray-100 flex items-center before:content-['📄'] before:mr-2">Статья/Пункт ${a.item_number} - ${a.file_name} - ${a.percent}%</div>`;
        });
        html += `</div></div>`;
    }

    // Used IDs
    if (data.used_ids && data.used_ids.length > 0) {
        html += `
            <div class="mb-4">
                <strong class="text-brand-dark tracking-wide uppercase text-sm flex items-center mb-2">
                    <div class="inline-flex items-center justify-center w-8 h-8 bg-purple-50 text-purple-500 rounded-[50%_50%_20%_80%/25%_25%_75%_75%] mr-3 mb-1"><i class="fas fa-search text-xs"></i></div>
                    Взяты в работу:
                </strong>
                <div class="flex flex-wrap gap-2">
        `;
        data.used_ids.forEach(uid => {
            html += `<div class="text-sm font-medium text-brand-main bg-brand-lightBg p-2 px-3 rounded-lg border border-brand-inputBorder">#${uid}</div>`;
        });
        html += `</div></div>`;
    }

    return html;
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

function renderVideoUpgradeBlock(uniqueId, audioUrl, isMain) {
    const savedAvatar = localStorage.getItem('heygenAvatar') || 'Abigail_standing_office_front';
    const savedFormat = localStorage.getItem('videoFormat') || '16:9';
    const savedEngine = localStorage.getItem('heygenEngine') || 'avatar_iv';
    const savedAvatarStyle = localStorage.getItem('avatarStyle') || 'auto';
    
    return `
        <div class="mt-4 border border-indigo-100 rounded-xl overflow-hidden bg-indigo-50/30">
            <button onclick="toggleVideoAccordion('${uniqueId}')" class="w-full flex items-center justify-between p-3 text-indigo-700 hover:bg-indigo-50 transition-colors">
                <div class="flex items-center gap-2 font-bold text-sm">
                    <i class="fas fa-video"></i> Создать видео из этого аудио
                </div>
                <i id="video-arrow-${uniqueId}" class="fas fa-chevron-down transition-transform"></i>
            </button>
            <div id="video-accordion-${uniqueId}" class="hidden p-4 border-t border-indigo-100 bg-white">
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                    <div class="flex flex-col">
                        <label class="text-xs font-semibold text-gray-600 mb-1">Версия движка (HeyGen)</label>
                        <select id="video-engine-${uniqueId}" class="rounded-lg p-2 border border-gray-200 text-sm">
                            <option value="avatar_iv" ${savedEngine === 'avatar_iv' ? 'selected' : ''}>Avatar IV (Digital Twins & Studio Avatars)</option>
                            <option value="avatar_iii" ${savedEngine === 'avatar_iii' ? 'selected' : ''}>Avatar III (Standard Talking Heads)</option>
                        </select>
                    </div>
                    <div class="flex flex-col">
                        <label class="text-xs font-semibold text-gray-600 mb-1">Формат видео</label>
                        <select id="video-format-${uniqueId}" onchange="updateAvatarStyleHint('video-format-${uniqueId}', 'video-style-${uniqueId}', 'video-style-hint-${uniqueId}')" class="rounded-lg p-2 border border-gray-200 text-sm">
                            <option value="9:16" ${savedFormat === '9:16' ? 'selected' : ''}>Вертикальный (9:16)</option>
                            <option value="16:9" ${savedFormat === '16:9' ? 'selected' : ''}>Горизонтальный (16:9)</option>
                            <option value="1:1" ${savedFormat === '1:1' ? 'selected' : ''}>Квадратный (1:1)</option>
                        </select>
                    </div>
                    <div class="flex flex-col">
                        <label class="text-xs font-semibold text-gray-600 mb-1">Стиль кадрирования</label>
                        <select id="video-style-${uniqueId}" class="rounded-lg p-2 border border-gray-200 text-sm">
                            <option value="auto" ${savedAvatarStyle === 'auto' ? 'selected' : ''}>Авто (по формату)</option>
                            <option value="normal" ${savedAvatarStyle === 'normal' ? 'selected' : ''}>Нормальный (весь кадр)</option>
                            <option value="closeUp" ${savedAvatarStyle === 'closeUp' ? 'selected' : ''}>Крупный план (лицо)</option>
                            <option value="circle" ${savedAvatarStyle === 'circle' ? 'selected' : ''}>Круг</option>
                        </select>
                        <p id="video-style-hint-${uniqueId}" class="text-xs text-indigo-600 mt-1 hidden"><i class="fas fa-info-circle"></i> Для 9:16 рекомендуется «Крупный план»</p>
                    </div>
                </div>
                
                <div class="flex flex-col mb-4">
                    <label class="text-xs font-semibold text-gray-600 mb-1">Аватар (HeyGen)</label>
                    <button type="button" id="video-avatar-btn-${uniqueId}" onclick="openAvatarModal('video-format-${uniqueId}', 'video-avatar-${uniqueId}', 'video-avatar-btn-${uniqueId}')" class="w-full bg-white border border-gray-200 text-gray-900 text-sm rounded-lg p-2 flex items-center justify-start gap-2 hover:bg-gray-50 transition-colors text-left shadow-sm">
                        <i class="fas fa-user-circle text-gray-400"></i> Выбрать аватар...
                    </button>
                    <input type="hidden" id="video-avatar-${uniqueId}" value="${savedAvatar}">
                </div>
                
                <div class="flex items-center gap-3">
                    <button id="btn-create-video-${uniqueId}" onclick="generateVideoFromAudio('${uniqueId}', '${audioUrl}', ${isMain})" class="bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2 px-6 rounded-lg transition-colors text-sm flex items-center gap-2 shadow-sm">
                        <i class="fas fa-film"></i> Создать видео
                    </button>
                    <span id="video-status-${uniqueId}" class="text-xs font-medium text-gray-500"></span>
                </div>
                
                <div id="video-result-container-${uniqueId}" class="hidden mt-4 pt-4 border-t border-gray-100">
                    <!-- Здесь появится видео и статистика -->
                </div>
            </div>
        </div>
    `;
}

function toggleVideoAccordion(uniqueId) {
    const accordion = document.getElementById(`video-accordion-${uniqueId}`);
    const arrow = document.getElementById(`video-arrow-${uniqueId}`);
    
    if (accordion.classList.contains('hidden')) {
        accordion.classList.remove('hidden');
        arrow.classList.add('rotate-180');
        
        // Загружаем список аватаров, если еще не загружен
        const input = document.getElementById(`video-avatar-${uniqueId}`);
        const formatSelect = document.getElementById(`video-format-${uniqueId}`);
        
        if (!input.dataset.loaded) {
            fetch('/api/config').then(res => res.json()).then(cfg => {
                if (cfg.avatars && cfg.avatars.length > 0) {
                    windowAvatars = cfg.avatars;
                    if (cfg.private_avatars) windowPrivateAvatars = cfg.private_avatars;
                    updateAvatarButtonText(`video-avatar-${uniqueId}`, `video-avatar-btn-${uniqueId}`, `video-format-${uniqueId}`);
                    input.dataset.loaded = 'true';
                    
                    if (formatSelect) {
                        formatSelect.addEventListener('change', () => {
                            updateAvatarButtonText(`video-avatar-${uniqueId}`, `video-avatar-btn-${uniqueId}`, `video-format-${uniqueId}`);
                        });
                    }
                }
            }).catch(e => console.error(e));
        }
    } else {
        accordion.classList.add('hidden');
        arrow.classList.remove('rotate-180');
    }
}

async function generateVideoFromAudio(uniqueId, audioUrl, isMain) {
    const btn = document.getElementById(`btn-create-video-${uniqueId}`);
    const status = document.getElementById(`video-status-${uniqueId}`);
    const resultContainer = document.getElementById(`video-result-container-${uniqueId}`);
    
    const engine = document.getElementById(`video-engine-${uniqueId}`).value;
    const format = document.getElementById(`video-format-${uniqueId}`).value;
    const avatar = document.getElementById(`video-avatar-${uniqueId}`).value;
    const avatarStyleEl = document.getElementById(`video-style-${uniqueId}`);
    const avatarStyle = avatarStyleEl ? avatarStyleEl.value : 'auto';
    
    // Сохраняем в localStorage
    localStorage.setItem('heygenEngine', engine);
    localStorage.setItem('videoFormat', format);
    localStorage.setItem('heygenAvatar', avatar);
    localStorage.setItem('avatarStyle', avatarStyle);
    
    btn.disabled = true;
    btn.classList.add('opacity-50', 'cursor-not-allowed');
    status.innerHTML = `<i class="fas fa-spinner fa-spin text-indigo-500"></i> Инициализация...`;
    resultContainer.classList.add('hidden');
    
    try {
        const slug = window.currentSlug || (window.location.pathname.split('/').pop());
        
        const response = await fetch('/api/generate_video_only', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                slug: slug,
                audio_url: audioUrl,
                heygen_engine: engine,
                video_format: format,
                heygen_avatar_id: avatar,
                avatar_style: avatarStyle,
                is_main: isMain
            })
        });
        
        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || errData.detail || "Ошибка сервера");
        }
        
        const data = await response.json();
        
        if (data.video_id) {
            status.innerHTML = `<i class="fas fa-check text-green-500"></i> Задача в очереди`;
            resultContainer.classList.remove('hidden');
            resultContainer.innerHTML = `
                <div class="flex flex-col items-center gap-3 w-full bg-gray-50 rounded-xl p-6 border border-dashed border-gray-300">
                    <i class="fas fa-spinner fa-spin text-3xl text-indigo-500 mb-2"></i>
                    <p class="text-brand-dark font-medium text-sm text-center">Видео генерируется...</p>
                    <p class="text-xs text-gray-500 text-center">Это займет несколько минут. Вы можете закрыть страницу.</p>
                </div>
            `;
            
            // Начинаем пуллинг
            pollSpecificVideo(data.video_id, uniqueId, slug, isMain, data.stats ? data.stats.started_at : null);
        } else {
            throw new Error("Не удалось получить Video ID");
        }
        
    } catch (e) {
        status.innerHTML = `<i class="fas fa-times text-red-500"></i> Ошибка: ${e.message}`;
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
    }
}

function pollSpecificVideo(videoId, uniqueId, slug, isMain, startedAt = null) {
    const checkVideo = async () => {
        try {
            const res = await fetch(`/api/video_status?video_id=${videoId}`);
            const stData = await res.json();
            
            const resultContainer = document.getElementById(`video-result-container-${uniqueId}`);
            const btn = document.getElementById(`btn-create-video-${uniqueId}`);
            const status = document.getElementById(`video-status-${uniqueId}`);
            
            if (!resultContainer) return; // Элемент удален со страницы
            
            if (stData.status === "completed" && stData.video_url) {
                let genTimeText = '';
                if (startedAt) {
                    const elapsedSec = Math.floor(Date.now() / 1000) - startedAt;
                    genTimeText = `<span class="text-gray-400 text-xs ml-2"><i class="fas fa-stopwatch mr-1"></i>${elapsedSec}s</span>`;
                }
                
                status.innerHTML = `<i class="fas fa-check text-green-500"></i> Готово ${genTimeText}`;
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                
                resultContainer.innerHTML = `
                    <div class="flex flex-col gap-2">
                        <video controls class="max-h-[50vh] w-auto max-w-full rounded-lg shadow border border-indigo-100" style="object-fit: contain;">
                            <source src="${stData.video_url}" type="video/mp4">
                            Ваш браузер не поддерживает видео.
                        </video>
                        <a href="${stData.video_url}" download target="_blank" class="mt-2 text-center text-sm font-medium text-indigo-600 hover:text-indigo-800">
                            <i class="fas fa-download"></i> Скачать видео
                        </a>
                    </div>
                `;
                
                // Уведомляем сервер об успешном URL, чтобы он сохранил его
                fetch('/api/update_video_result', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        slug: slug, 
                        video_url: stData.video_url,
                        video_id: videoId,
                        is_main: isMain
                    })
                });
                
            } else if (stData.status === "failed" || stData.status === "error") {
                status.innerHTML = `<i class="fas fa-times text-red-500"></i> Ошибка генерации`;
                btn.disabled = false;
                btn.classList.remove('opacity-50', 'cursor-not-allowed');
                
                resultContainer.innerHTML = `
                    <div class="text-xs text-red-500 p-3 bg-red-50 rounded-lg border border-red-100">
                        <i class="fas fa-exclamation-triangle mr-1"></i> Ошибка HeyGen: ${stData.error || 'Неизвестная ошибка'}
                    </div>
                `;
            } else {
                // Продолжаем пуллинг
                setTimeout(checkVideo, 5000);
            }
        } catch (e) {
            setTimeout(checkVideo, 5000);
        }
    };
    checkVideo();
}