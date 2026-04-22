/* ═══════════════════════════════════════════════════════════════════════════
   tree.js  —  Дерево генерации результатов ArmeykaBrain
   ═══════════════════════════════════════════════════════════════════════════ */

'use strict';

/* ─── Глобальное состояние ─────────────────────────────────────────────── */
let _tree = null;              // экземпляр ResultTree
let _treeAvatars    = [];      // список аватаров (загружается из /api/config)
let _treeVoices     = [];      // список голосов ElevenLabs
let _treeModels     = [];      // список AI-моделей (загружается из /api/config)
let _treeStep3Prompts = {};    // словарь step3-промптов {name: text} (из /api/prompts)

/* ─── Константы ────────────────────────────────────────────────────────── */
const NODE_ICONS  = { article:'fa-align-left', script:'fa-microphone', audio:'fa-headphones', video:'fa-film' };
const NODE_COLORS = { article:'#3b82f6', script:'#8b5cf6', audio:'#F47920', video:'#10b981' };
const NODE_BGS    = { article:'#eff6ff', script:'#f5f3ff', audio:'#fff7ed', video:'#f0fdf4' };
const SECTION_LABELS  = { article:'Сценарии', script:'Аудиофайлы', audio:'Видео' };
const CHILD_TYPE      = { article:'script', script:'audio', audio:'video' };
const ADD_LABELS      = { article:'Новый сценарий', script:'Новое аудио', audio:'Новое видео' };
const ADD_TOOLTIPS    = {
    article: 'Создать аудиосценарий на основе этой статьи',
    script:  'Сгенерировать аудиофайл из этого сценария',
    audio:   'Создать видео на основе этого аудио',
};

/* ══════════════════════════════════════════════════════════════════════════
   CLASS ResultTree
   ══════════════════════════════════════════════════════════════════════════ */
class ResultTree {
    constructor(slug) {
        this.slug = slug;
        this.nodesMap = new Map();   // node_id → nodeData (plain object)
        this.expanded  = new Set();  // раскрытые node_id
        this.container = null;
        this._pollers  = new Map();  // node_id → intervalId
    }

    /* ── Инициализация ──────────────────────────────────────────────────── */
    async init(container) {
        this.container = container;
        this._loadExpanded();
        await this.load();
    }

    async load() {
        try {
            const data = await fetch(`/api/tree/${this.slug}`).then(r => r.json());
            this.nodesMap.clear();
            data.nodes.forEach(n => this.nodesMap.set(n.node_id, n));
            this._autoExpand();
            this.render();
            this._startPollingProcessing();
        } catch (e) {
            console.error('Tree load error:', e);
        }
    }

    /* Автоматически раскрываем корень и последний узел каждого уровня */
    _autoExpand() {
        if (this.expanded.size > 0) return;  // уже загружены из localStorage
        this.nodesMap.forEach(n => {
            if (n.node_type === 'article') this.expanded.add(n.node_id);
        });
        // Раскрываем последний script, последний audio, последний video
        ['script', 'audio', 'video'].forEach(type => {
            let last = null;
            this.nodesMap.forEach(n => { if (n.node_type === type) last = n; });
            if (last) this.expanded.add(last.node_id);
        });
    }

    /* ── Рендер ─────────────────────────────────────────────────────────── */
    render() {
        if (!this.container) return;
        this.container.innerHTML = '';
        const roots = [...this.nodesMap.values()].filter(n => !n.parent_node_id);
        roots.sort((a, b) => a.position - b.position);
        roots.forEach(n => this.container.appendChild(this._buildNode(n)));
    }

    _buildNode(nodeData) {
        const isExpanded = this.expanded.has(nodeData.node_id);
        const children   = this._getChildren(nodeData.node_id);
        const color      = NODE_COLORS[nodeData.node_type] || '#94a3b8';
        const bg         = NODE_BGS[nodeData.node_type]    || '#f8fafc';

        const wrap = document.createElement('div');
        wrap.className = `tn tn--${nodeData.node_type}`;
        wrap.id = `tn-${nodeData.node_id}`;
        wrap.setAttribute('data-node-id', nodeData.node_id);
        wrap.style.setProperty('--tn-color', color);
        wrap.style.setProperty('--tn-bg',    bg);

        wrap.appendChild(this._buildHeader(nodeData, children.length, isExpanded));

        const body = this._buildBody(nodeData, children);
        if (!isExpanded) body.classList.add('tn__body--hidden');
        wrap.appendChild(body);

        return wrap;
    }

    _buildHeader(node, childCount, isExpanded) {
        const hdr = document.createElement('div');
        hdr.className = 'tn__header';
        hdr.onclick = () => this.toggle(node.node_id);

        /* ── Иконка в цветном круге ── */
        const iconWrap = document.createElement('div');
        iconWrap.className = 'tn__icon-wrap';
        iconWrap.style.background    = `var(--tn-bg)`;
        iconWrap.style.color         = `var(--tn-color)`;
        iconWrap.style.borderColor   = `var(--tn-color)`;
        iconWrap.innerHTML = `<i class="fas ${NODE_ICONS[node.node_type] || 'fa-circle'}"></i>`;

        /* ── Центральная группа: название + теги ── */
        const center = document.createElement('div');
        center.className = 'tn__center';

        const titleRow = document.createElement('div');
        titleRow.className = 'tn__title-row';

        if (node.status === 'processing') {
            const spin = document.createElement('i');
            spin.className = 'fas fa-circle-notch fa-spin tn__spin-icon';
            titleRow.appendChild(spin);
        } else if (node.status === 'failed') {
            const dot = document.createElement('span');
            dot.className = 'tn__fail-dot';
            titleRow.appendChild(dot);
        }

        const titleEl = document.createElement('span');
        titleEl.className = 'tn__title';
        titleEl.textContent = _buildDisplayTitle(node, this.nodesMap);
        titleEl.ondblclick = (e) => { e.stopPropagation(); this._startRename(node.node_id, titleEl); };
        titleRow.appendChild(titleEl);

        if (childCount > 0) {
            const counter = document.createElement('span');
            counter.className = 'tn__counter';
            counter.textContent = childCount;
            titleRow.appendChild(counter);
        }

        center.appendChild(titleRow);

        const tagsEl = document.createElement('div');
        tagsEl.className = 'tn__tags';
        tagsEl.innerHTML = _buildTags(node, this.nodesMap);
        if (tagsEl.innerHTML) center.appendChild(tagsEl);

        /* ── Правая группа: дата + стоимость + стрелка + удаление ── */
        const right = document.createElement('div');
        right.className = 'tn__right';

        const dateStr = _fmtNodeDate(node.created_at);
        if (dateStr) {
            const d = document.createElement('span');
            d.className = 'tn__date-tag';
            d.textContent = dateStr;
            right.appendChild(d);
        }

        const cost = _totalCost(node);
        if (cost && parseFloat(cost) > 0) {
            const c = document.createElement('span');
            c.className = 'tn__cost-tag';
            c.textContent = `$${cost}`;
            right.appendChild(c);
        }

        const arrow = document.createElement('span');
        arrow.className = 'tn__arrow' + (isExpanded ? ' tn__arrow--open' : '');
        arrow.innerHTML = '<i class="fas fa-chevron-right"></i>';
        right.appendChild(arrow);

        hdr.append(iconWrap, center, right);
        return hdr;
    }

    _buildBody(node, children) {
        const body = document.createElement('div');
        body.className = 'tn__body';

        /* ── Контент узла ── */
        const content = _buildContent(node);
        if (content) body.appendChild(content);

        /* ── Кнопка удаления (только для не-article, в самом низу) ── */
        if (node.node_type !== 'article') {
            const delRow = document.createElement('div');
            delRow.className = 'tn__del-row';
            const delBtn = document.createElement('button');
            delBtn.className = 'tn__del-btn';
            delBtn.innerHTML = '<i class="fas fa-trash-alt"></i> Удалить';
            delBtn.onclick = (e) => { e.stopPropagation(); this._confirmDelete(node.node_id, node.title); };
            delRow.appendChild(delBtn);
            body.appendChild(delRow);
        }

        /* ── Секция дочерних узлов ── */
        const hasChildren  = children.length > 0;
        const canAdd       = !!CHILD_TYPE[node.node_type];

        if (hasChildren || canAdd) {
            const section = document.createElement('div');
            section.className = 'tn__section';

            const childType  = CHILD_TYPE[node.node_type];
            const nextColor  = childType ? (NODE_COLORS[childType] || '#94a3b8') : '#94a3b8';
            const nextBg     = childType ? (NODE_BGS[childType]    || '#f8fafc') : '#f8fafc';
            const labelText  = SECTION_LABELS[node.node_type] || '';
            const childIcon  = childType ? (NODE_ICONS[childType] || 'fa-circle') : 'fa-circle';

            /* ── Строка-разделитель с кнопкой «+» ── */
            const sectionLabel = document.createElement('div');
            sectionLabel.className = 'tn__section-label';
            sectionLabel.style.setProperty('--tn-next-color', nextColor);

            // Левая часть: иконка + текст + счётчик
            const leftPart = document.createElement('span');
            leftPart.className = 'tn__section-left';
            leftPart.innerHTML = `
                <i class="fas ${childIcon} tn__section-icon"></i>
                <span class="tn__section-text">${labelText}</span>
                ${hasChildren ? `<span class="tn__section-count">${children.length}</span>` : ''}`;

            // Правая часть: тонкая линия + кнопка «+»
            const line = document.createElement('span');
            line.className = 'tn__section-line';

            sectionLabel.appendChild(leftPart);
            sectionLabel.appendChild(line);

            if (canAdd) {
                const tooltip = ADD_TOOLTIPS[node.node_type] || 'Добавить';
                const addBtn = document.createElement('button');
                addBtn.className = 'tn__section-add';
                addBtn.style.setProperty('--add-color', nextColor);
                addBtn.style.setProperty('--add-bg',    nextBg);
                addBtn.setAttribute('aria-label', tooltip);
                addBtn.innerHTML = `
                    <i class="fas ${childIcon}"></i>
                    <i class="fas fa-plus tn__section-add-plus"></i>
                    <span class="tn__section-add-tooltip">${tooltip}</span>`;
                addBtn.onclick = (e) => {
                    e.stopPropagation();
                    openGenerateModal(node.node_id, CHILD_TYPE[node.node_type]);
                };
                sectionLabel.appendChild(addBtn);
            }

            section.appendChild(sectionLabel);

            /* ── Дочерние карточки ── */
            if (hasChildren) {
                const childrenWrap = document.createElement('div');
                childrenWrap.className = 'tn__children';
                childrenWrap.style.setProperty('--tn-next-color', nextColor);
                children.sort((a, b) => a.position - b.position);
                children.forEach(c => childrenWrap.appendChild(this._buildNode(c)));
                section.appendChild(childrenWrap);
            }

            body.appendChild(section);
        }

        return body;
    }

    /* ── Expand / Collapse ──────────────────────────────────────────────── */
    toggle(nodeId) {
        const el = document.getElementById(`tn-${nodeId}`);
        if (!el) return;
        const body  = el.querySelector(':scope > .tn__body');
        const arrow = el.querySelector(':scope > .tn__header .tn__arrow');
        if (!body) return;

        if (this.expanded.has(nodeId)) {
            this.expanded.delete(nodeId);
            body.classList.add('tn__body--hidden');
            arrow.classList.remove('tn__arrow--open');
        } else {
            this.expanded.add(nodeId);
            body.classList.remove('tn__body--hidden');
            arrow.classList.add('tn__arrow--open');
        }
        this._saveExpanded();
    }

    /* ── Добавление нового узла (из SSE) ───────────────────────────────── */
    insertNode(nodeData) {
        this.nodesMap.set(nodeData.node_id, nodeData);

        const parentEl = document.getElementById(`tn-${nodeData.parent_node_id}`);
        if (!parentEl) { this.render(); return; }

        const childrenWrap = parentEl.querySelector(':scope > .tn__body > .tn__children');
        if (!childrenWrap) { this.render(); return; }

        const el = this._buildNode(nodeData);
        el.classList.add('tn--new');
        childrenWrap.appendChild(el);

        // Обновляем счётчик родителя
        this._updateCounter(nodeData.parent_node_id);

        setTimeout(() => el.classList.remove('tn--new'), 800);
    }

    updateNode(nodeData) {
        this.nodesMap.set(nodeData.node_id, nodeData);
        const el = document.getElementById(`tn-${nodeData.node_id}`);
        if (!el) return;

        // Перестраиваем только заголовок и контент (не трогаем детей)
        const children = this._getChildren(nodeData.node_id);
        const isExpanded = this.expanded.has(nodeData.node_id);

        const oldHeader = el.querySelector(':scope > .tn__header');
        const oldBody   = el.querySelector(':scope > .tn__body');

        const newHeader = this._buildHeader(nodeData, children.length, isExpanded);
        const newBody   = this._buildBody(nodeData, children);
        if (!isExpanded) newBody.classList.add('tn__body--hidden');

        if (oldHeader) el.replaceChild(newHeader, oldHeader);
        if (oldBody)   el.replaceChild(newBody,   oldBody);
    }

    /* ── Polling для processing-узлов ──────────────────────────────────── */
    _startPollingProcessing() {
        this.nodesMap.forEach(n => {
            if (n.status === 'processing') this._pollNode(n.node_id);
        });
    }

    _pollNode(nodeId) {
        if (this._pollers.has(nodeId)) return;
        const timer = setInterval(async () => {
            try {
                const data = await fetch(`/api/tree/node/${nodeId}`).then(r => r.json());
                if (data.status !== 'processing') {
                    clearInterval(timer);
                    this._pollers.delete(nodeId);
                    this.updateNode(data);
                }
            } catch (e) {
                clearInterval(timer);
                this._pollers.delete(nodeId);
            }
        }, 8000);
        this._pollers.set(nodeId, timer);
    }

    /* ── Переименование ─────────────────────────────────────────────────── */
    _startRename(nodeId, titleEl) {
        const old = titleEl.textContent;
        const input = document.createElement('input');
        input.className = 'tn__rename-input';
        input.value = old;
        titleEl.replaceWith(input);
        input.focus();
        input.select();

        const commit = async () => {
            const val = input.value.trim() || old;
            const span = document.createElement('span');
            span.className = 'tn__title';
            span.textContent = val;
            span.ondblclick = (e) => { e.stopPropagation(); this._startRename(nodeId, span); };
            input.replaceWith(span);
            if (val !== old) {
                await fetch(`/api/tree/node/${nodeId}/title`, {
                    method: 'PATCH', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ title: val })
                });
                const n = this.nodesMap.get(nodeId);
                if (n) n.title = val;
            }
        };
        input.onblur = commit;
        input.onkeydown = (e) => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { input.value = old; input.blur(); } };
    }

    /* ── Удаление ───────────────────────────────────────────────────────── */
    _confirmDelete(nodeId, title) {
        if (!confirm(`Удалить "${title}" и все дочерние узлы?`)) return;
        this._deleteNode(nodeId);
    }

    async _deleteNode(nodeId) {
        try {
            await fetch(`/api/tree/node/${nodeId}`, { method: 'DELETE' });
            // Удаляем из карты все потомки
            const toDelete = this._collectDescendants(nodeId);
            toDelete.forEach(id => this.nodesMap.delete(id));
            // Обновляем счётчик родителя
            const node = this.nodesMap.get(nodeId);
            const parentId = node?.parent_node_id;
            this.nodesMap.delete(nodeId);
            if (parentId) this._updateCounter(parentId);
            // Удаляем DOM-элемент
            const el = document.getElementById(`tn-${nodeId}`);
            if (el) el.remove();
        } catch (e) {
            alert('Ошибка удаления: ' + e.message);
        }
    }

    _collectDescendants(nodeId) {
        const ids = [nodeId];
        this.nodesMap.forEach(n => {
            if (n.parent_node_id === nodeId) ids.push(...this._collectDescendants(n.node_id));
        });
        return ids;
    }

    /* ── Хелперы ────────────────────────────────────────────────────────── */
    _getChildren(nodeId) {
        return [...this.nodesMap.values()].filter(n => n.parent_node_id === nodeId);
    }

    _updateCounter(parentId) {
        const el = document.getElementById(`tn-${parentId}`);
        if (!el) return;
        const cnt = this._getChildren(parentId).length;

        // Счётчик в заголовке карточки
        const counter = el.querySelector(':scope > .tn__header .tn__counter');
        if (counter) counter.textContent = cnt > 0 ? String(cnt) : '';

        // Счётчик в строке секции
        const secCount = el.querySelector(':scope > .tn__body .tn__section-count');
        if (secCount) {
            secCount.textContent = String(cnt);
            secCount.style.display = cnt > 0 ? '' : 'none';
        }
    }

    _saveExpanded() {
        try { localStorage.setItem(`tree_exp_${this.slug}`, JSON.stringify([...this.expanded])); } catch(e) {}
    }
    _loadExpanded() {
        try {
            const saved = localStorage.getItem(`tree_exp_${this.slug}`);
            if (saved) JSON.parse(saved).forEach(id => this.expanded.add(id));
        } catch(e) {}
    }
}

/* ══════════════════════════════════════════════════════════════════════════
   CONTENT BUILDERS (по типу узла)
   ══════════════════════════════════════════════════════════════════════════ */

function _buildContent(node) {
    switch (node.node_type) {
        case 'article': return _contentArticle(node);
        case 'script':  return _contentScript(node);
        case 'audio':   return _contentAudio(node);
        case 'video':   return _contentVideo(node);
        default: return null;
    }
}

function _contentArticle(node) {
    const wrap = document.createElement('div');
    wrap.className = 'tn__content';

    if (node.content_text) {
        const text = document.createElement('div');
        text.className = 'tn__article-text markdown-body';
        const full  = node.content_text;
        const short = full.length > 600 ? full.slice(0, 600) + '…' : full;
        text.innerHTML = typeof marked !== 'undefined' ? marked.parse(short) : short;

        if (full.length > 600) {
            const expandBtn = document.createElement('button');
            expandBtn.className = 'tn__expand-text-btn';
            expandBtn.textContent = 'Показать полностью ▼';
            let expanded = false;
            expandBtn.onclick = () => {
                expanded = !expanded;
                text.innerHTML = typeof marked !== 'undefined'
                    ? marked.parse(expanded ? full : short)
                    : (expanded ? full : short);
                // Снимаем ограничение высоты когда раскрыто
                text.style.maxHeight = expanded ? 'none' : '';
                text.style.overflowY = expanded ? 'visible' : '';
                expandBtn.textContent = expanded ? 'Свернуть ▲' : 'Показать полностью ▼';
            };
            wrap.append(text, expandBtn);
        } else {
            wrap.appendChild(text);
        }
    }

    // Stats
    const stats = node.stats_json;
    if (stats) {
        const s1 = stats.step1 || {};
        const s2 = stats.step2 || {};
        const total = (s1.total_cost || 0) + (s2.total_cost || 0);
        const t1 = s1.generation_time_sec || 0;
        const t2 = s2.generation_time_sec || 0;
        wrap.appendChild(_statsRow([
            s1.model ? `Модель: ${s1.model}` : null,
            s1.in_tokens ? `Шаг 1: ${s1.in_tokens}/${s1.out_tokens} токенов` : null,
            s2.in_tokens ? `Шаг 2: ${s2.in_tokens}/${s2.out_tokens} токенов` : null,
            (t1 || t2) ? `Время: ${t1}с + ${t2}с` : null,
            total ? `$${total.toFixed(4)}` : null,
        ]));
    }
    return wrap;
}

function _contentScript(node) {
    const wrap = document.createElement('div');
    wrap.className = 'tn__content';

    if (node.content_text) {
        const text = document.createElement('div');
        text.className = 'tn__script-text';
        text.textContent = node.content_text;
        wrap.appendChild(text);
    }

    const st = node.stats_json || {};
    if (Object.keys(st).length) {
        wrap.appendChild(_statsRow([
            st.model ? `Модель: ${st.model}` : null,
            st.in_tokens ? `${st.in_tokens}/${st.out_tokens} токенов` : null,
            st.generation_time_sec ? `${st.generation_time_sec}с` : null,
            st.total_cost ? `$${Number(st.total_cost).toFixed(4)}` : null,
        ]));
    }
    return wrap;
}

function _contentAudio(node) {
    const wrap = document.createElement('div');
    wrap.className = 'tn__content';

    const st = node.stats_json || {};

    if (node.content_url) {
        const player = document.createElement('div');
        player.className = 'tn__audio-player';

        const audio = document.createElement('audio');
        audio.controls = true;
        audio.preload = 'none';
        audio.className = 'tn__audio-el';
        audio.src = node.content_url;
        player.appendChild(audio);

        // Кнопка скачать MP3
        if (node.content_url_original || node.content_url) {
            const dl = document.createElement('a');
            dl.href = node.content_url_original || node.content_url;
            dl.download = '';
            dl.className = 'tn__dl-btn';
            dl.innerHTML = '<i class="fas fa-download"></i>';
            dl.title = 'Скачать';
            player.appendChild(dl);
        }

        // Иконки таймкодов (JSON + VTT) — если уже есть
        if (st.timecodes_json_url) {
            const jsonLink = document.createElement('a');
            jsonLink.href = st.timecodes_json_url;
            jsonLink.download = '';
            jsonLink.className = 'tn__tc-icon';
            jsonLink.title = 'Скачать таймкоды JSON';
            jsonLink.innerHTML = '<i class="fas fa-code"></i>';
            player.appendChild(jsonLink);

            const vttLink = document.createElement('a');
            vttLink.href = st.timecodes_vtt_url;
            vttLink.download = '';
            vttLink.className = 'tn__tc-icon';
            vttLink.title = 'Скачать субтитры VTT';
            vttLink.innerHTML = '<i class="fas fa-closed-captioning"></i>';
            player.appendChild(vttLink);
        }

        wrap.appendChild(player);
    }

    const p = node.params_json || {};
    const paramParts = [
        p.voice_name ? `Голос: ${p.voice_name}` : null,
        p.elevenlabs_model ? `Модель: ${p.elevenlabs_model}` : null,
        p.wpm ? `${p.wpm} WPM` : null,
        p.stability != null ? `Stab: ${p.stability}` : null,
        p.similarity_boost != null ? `Sim: ${p.similarity_boost}` : null,
    ].filter(Boolean);
    if (paramParts.length) {
        const paramEl = document.createElement('div');
        paramEl.className = 'tn__param-row';
        paramEl.textContent = paramParts.join(' · ');
        wrap.appendChild(paramEl);
    }

    // Оценка
    const ev = node.evaluation_json;
    if (ev && ev.percent_ideal != null) {
        const evalEl = document.createElement('div');
        evalEl.className = 'tn__eval-badge';
        evalEl.innerHTML = `⭐ ${ev.percent_ideal}% · Stab→${ev.recommended_stability} · Sim→${ev.recommended_similarity}`;
        if (ev.do_better) {
            evalEl.title = ev.do_better;
            evalEl.style.cursor = 'help';
        }
        wrap.appendChild(evalEl);
    }

    // Кнопка оценить
    if (!ev) {
        const evalBtn = document.createElement('button');
        evalBtn.className = 'tn__eval-btn';
        evalBtn.innerHTML = '<i class="fas fa-star"></i> Оценить качество';
        evalBtn.onclick = () => _evaluateAudioNode(node.node_id);
        wrap.appendChild(evalBtn);
    }

    // Кнопка +таймкоды — если таймкодов ещё нет и аудио завершено
    if (!st.timecodes_json_url && node.status === 'completed') {
        const tcBtn = document.createElement('button');
        tcBtn.className = 'tn__tc-btn';
        tcBtn.id = `tc-btn-${node.node_id}`;
        tcBtn.innerHTML = '<i class="fas fa-closed-captioning"></i> +таймкоды';
        tcBtn.title = 'Сгенерировать таймкоды через Deepgram ($0.0077/мин)';
        tcBtn.onclick = () => _generateTimecodes(node.node_id);
        wrap.appendChild(tcBtn);
    }

    if (Object.keys(st).length) {
        wrap.appendChild(_statsRow([
            st.char_count ? `${st.char_count} символов` : null,
            st.generation_time_sec ? `${st.generation_time_sec}с` : null,
            st.total_cost ? `ElevenLabs $${Number(st.total_cost).toFixed(4)}` : null,
            st.timecodes_cost ? `Deepgram $${Number(st.timecodes_cost).toFixed(4)}` : null,
        ]));
    }
    return wrap;
}

async function _generateTimecodes(nodeId) {
    const btn = document.getElementById(`tc-btn-${nodeId}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> генерация…';
    }
    try {
        const r = await fetch(`/api/tree/node/${nodeId}/timecodes`, { method: 'POST' });
        const data = await r.json();
        if (!data.ok) {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-closed-captioning"></i> +таймкоды';
            }
            alert(data.message || 'Ошибка запуска');
            return;
        }
        // Поллим узел каждые 4с пока timecodes_json_url не появится
        let attempts = 0;
        const poll = setInterval(async () => {
            attempts++;
            if (attempts > 30) { clearInterval(poll); return; } // максимум 2 мин
            try {
                const nr = await fetch(`/api/tree/node/${nodeId}`);
                const nd = await nr.json();
                const nst = nd.stats_json || {};
                if (nst.timecodes_json_url) {
                    clearInterval(poll);
                    // Перерисовываем дерево
                    if (_tree) {
                        const container = document.getElementById('result-tree');
                        if (container) await _tree.init(container);
                    }
                }
            } catch (e) { /* тихо */ }
        }, 4000);
    } catch (e) {
        console.error('_generateTimecodes error:', e);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-closed-captioning"></i> +таймкоды';
        }
    }
}

function _contentVideo(node) {
    const wrap = document.createElement('div');
    wrap.className = 'tn__content';

    if (node.content_url) {
        const p = node.params_json || {};
        const isVertical = (p.video_format === '9:16');
        const isSquare   = (p.video_format === '1:1');

        const videoWrap = document.createElement('div');
        videoWrap.className = 'tn__video-wrap' +
            (isVertical ? ' tn__video-wrap--vertical' : '') +
            (isSquare   ? ' tn__video-wrap--square'   : '');

        const video = document.createElement('video');
        video.controls = true;
        video.preload = 'none';
        video.src = node.content_url;
        video.className = 'tn__video-el';
        videoWrap.appendChild(video);
        wrap.appendChild(videoWrap);
    } else if (node.status === 'processing') {
        const pending = document.createElement('div');
        pending.className = 'tn__video-pending';
        pending.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Видео генерируется...';
        wrap.appendChild(pending);
    } else if (node.status === 'failed') {
        const errMsg = (node.stats_json || {}).error_message || 'Неизвестная ошибка';
        const errEl = document.createElement('div');
        errEl.className = 'tn__video-error';
        errEl.innerHTML = `<i class="fas fa-exclamation-triangle"></i> <strong>Ошибка:</strong> ${errMsg}`;
        wrap.appendChild(errEl);
    }

    const p = node.params_json || {};
    const st = node.stats_json || {};

    const paramParts = [
        p.avatar_name ? `Аватар: ${p.avatar_name}` : (p.avatar_id ? `Аватар: ${p.avatar_id}` : null),
        p.heygen_engine ? `Движок: ${p.heygen_engine === 'avatar_iv' ? 'Avatar IV' : 'Avatar III'}` : null,
        p.video_format ? `Формат: ${p.video_format}` : null,
    ].filter(Boolean);
    if (paramParts.length) {
        const paramEl = document.createElement('div');
        paramEl.className = 'tn__param-row';
        paramEl.textContent = paramParts.join(' · ');
        wrap.appendChild(paramEl);
    }

    if (Object.keys(st).length) {
        const genTime = st.generation_time_sec;
        wrap.appendChild(_statsRow([
            genTime ? `Время: ${Math.floor(genTime/60)}м ${genTime%60}с` : null,
            st.total_cost ? `$${Number(st.total_cost).toFixed(2)}` : null,
            'HeyGen v2',
        ]));
    }
    return wrap;
}

/* ── Строка статистики ─────────────────────────────────────────────────── */
function _statsRow(parts) {
    const el = document.createElement('div');
    el.className = 'tn__stats-row';
    el.textContent = parts.filter(Boolean).join(' · ');
    return el;
}

/* ── Теги параметров в заголовке ──────────────────────────────────────── */
/**
 * Builds a display title for a node, appending key metadata in parentheses
 * for audio and video nodes when they are completed.
 * @param {object} node
 * @returns {string}
 */
function _buildDisplayTitle(node, nodesMap) {
    const base = node.title || node.node_type;
    // Audio: only show extras when completed (duration is calculated at that point)
    // Video: always show format/duration since params are set at creation time
    if (node.status !== 'completed' && node.node_type !== 'video') return base;

    const p  = node.params_json || {};
    const st = node.stats_json  || {};

    if (node.node_type === 'audio') {
        // Keep only the person's name: "Laura - энтузиаст..." → "Laura", "Lisa Bykova" → "Lisa Bykova"
        const rawVoice  = p.voice_name || st.voice_name || '';
        const voiceName = rawVoice.split('(')[0].split(' - ')[0].trim();
        // audio_duration_sec (tree flow) or duration_sec (main pipeline)
        const dur = st.audio_duration_sec || st.duration_sec;
        const extras = [voiceName || null, dur ? `${dur}с` : null].filter(Boolean);
        return extras.length ? `${base} (${extras.join(', ')})` : base;
    }

    if (node.node_type === 'video') {
        const format = p.video_format || st.video_format || '';

        // Duration: stored value first; otherwise look up parent audio node
        let dur = st.audio_duration_sec;
        if (!dur && nodesMap && node.parent_node_id) {
            const parentNode = nodesMap.get(node.parent_node_id);
            if (parentNode) {
                const pst = parentNode.stats_json || {};
                dur = pst.audio_duration_sec || pst.duration_sec;
            }
        }

        // Voice name: strip description part
        const rawVoice  = p.voice_name || st.voice_name || '';
        const voiceName = rawVoice.split('(')[0].split(' - ')[0].trim();
        const extras    = [format || null, dur ? `${dur}с` : null, voiceName || null].filter(Boolean);
        return extras.length ? `${base} (${extras.join(', ')})` : base;
    }

    return base;
}

function _buildTags(node, nodesMap) {
    const p  = node.params_json || {};
    const st = node.stats_json  || {};
    const parts = [];
    switch (node.node_type) {
        case 'article': {
            if (st.step1) {
                const model = (st.step1.model || '').replace('gemini-', '').replace('-preview', '');
                if (model) parts.push(model);
            }
            const charLen = node.content_text?.length;
            if (charLen) parts.push(`${Math.round(charLen / 100) * 100}с`);
            break;
        }
        case 'script': {
            // Primary source: params_json (tree-modal-generated scripts)
            let dur = p.audio_duration_sec;
            let wpm = p.audio_wpm;
            // step3_prompt_key — новое поле; style — старое (обратная совместимость)
            let promptLabel = p.step3_prompt_key || p.style;
            // Fallback for initial scripts (no params_json): look at first child audio node
            if (!dur && nodesMap) {
                const childAudio = [...nodesMap.values()].find(
                    n => n.parent_node_id === node.node_id && n.node_type === 'audio'
                );
                if (childAudio) {
                    const cst = childAudio.stats_json || {};
                    const cp  = childAudio.params_json || {};
                    dur         = cst.audio_duration_sec || cst.duration_sec;
                    wpm         = wpm         || cst.wpm || cp.audio_wpm;
                    promptLabel = promptLabel || cp.step3_prompt_key || cp.style || cp.elevenlabs_model;
                }
            }
            if (dur)         parts.push(`${dur}с`);
            if (wpm)         parts.push(`${wpm}wpm`);
            if (promptLabel) parts.push(promptLabel);
            break;
        }
        case 'audio': {
            // elevenlabs_model: tree flow uses params_json/stats_json.elevenlabs_model;
            // main pipeline uses stats_json.model
            const elModel = (p.elevenlabs_model || st.elevenlabs_model || st.model || '');
            if (elModel) parts.push(elModel.replace('eleven_', '').replace(/_/g, ' '));
            const wpm = st.wpm || p.audio_wpm;
            if (wpm) parts.push(`${wpm}wpm`);
            break;
        }
        case 'video': {
            const avatarName = (p.avatar_name || st.avatar_name || '').split(' ')[0];
            if (avatarName) parts.push(avatarName);
            if (p.heygen_engine) parts.push(p.heygen_engine === 'avatar_iv' ? 'Av.IV' : 'Av.III');
            const style = p.avatar_style || st.avatar_style;
            if (style && style !== 'auto') parts.push(style);
            break;
        }
    }
    return parts.map(t => `<span class="tn__tag">${t}</span>`).join('');
}

function _buildMeta(node) {
    const st = node.stats_json || {};
    const parts = [];
    if (st.generation_time_sec) parts.push(`${st.generation_time_sec}с`);
    else if (st.step1 && st.step1.generation_time_sec) {
        const t = (st.step1.generation_time_sec || 0) + (st.step2?.generation_time_sec || 0);
        if (t) parts.push(`${t}с`);
    }
    const cost = _totalCost(node);
    if (cost) parts.push(`$${cost}`);
    return parts.join(' · ');
}

function _totalCost(node) {
    const st = node.stats_json || {};
    if (st.total_cost != null) return Number(st.total_cost).toFixed(4);
    if (st.step1 || st.step2) {
        const c = (st.step1?.total_cost || 0) + (st.step2?.total_cost || 0);
        return c ? c.toFixed(4) : null;
    }
    return null;
}

function _statusIcon(status) {
    if (status === 'processing') return '<i class="fas fa-circle-notch fa-spin tn__status--processing"></i>';
    if (status === 'failed')     return '<i class="fas fa-times-circle tn__status--failed"></i>';
    return '';
}

function _fmtDur(sec) {
    if (!sec) return '';
    const m = Math.floor(sec / 60), s = sec % 60;
    return m > 0 ? `${m}:${String(s).padStart(2,'0')}` : `0:${String(s).padStart(2,'0')}`;
}

/* ══════════════════════════════════════════════════════════════════════════
   МОДАЛЬНОЕ ОКНО ГЕНЕРАЦИИ
   ══════════════════════════════════════════════════════════════════════════ */

let _genModalParentId  = null;
let _genModalTargetType = null;

function openGenerateModal(parentNodeId, targetType) {
    _genModalParentId   = parentNodeId;
    _genModalTargetType = targetType;

    const modal = document.getElementById('generate-modal');
    const title = document.getElementById('gm-title');
    const body  = document.getElementById('gm-body');
    if (!modal) return;

    const labels = { script: 'Новый сценарий для аудио', audio: 'Новое аудио', video: 'Новое видео' };
    title.textContent = labels[targetType] || 'Генерация';

    body.innerHTML = '';
    body.appendChild(_buildModalForm(targetType));

    // Сбрасываем состояние кнопки — могла остаться disabled после предыдущей генерации
    const submitBtn = document.getElementById('gm-submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-bolt"></i> Сгенерировать';
    }

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeGenerateModal() {
    const modal = document.getElementById('generate-modal');
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = '';
}

function _buildModalForm(type) {
    const form = document.createElement('div');
    form.className = 'gm-form';

    if (type === 'script') {
        const wpmVal = _ls('audioWpm','150');
        const savedPromptKey = _ls('step3PromptKey', 'yur_bud_svoboden');
        const savedAiModel   = _ls('treeScriptModel', 'gemini-flash-latest');

        // Динамически строим список промптов из загруженных с сервера
        const promptKeys = Object.keys(_treeStep3Prompts);
        const promptOptions = promptKeys.length > 0
            ? promptKeys.map(k => `<option value="${k}"${k === savedPromptKey ? ' selected' : ''}>${k}</option>`).join('')
            : `<option value="default" selected>default</option>`;

        // Строим сгруппированный список AI-моделей
        const geminiModels = _treeModels.filter(m => m.provider === 'gemini' || !m.provider);
        const claudeModels = _treeModels.filter(m => m.provider === 'claude');
        let modelOptionsHtml = '';
        if (geminiModels.length > 0) {
            modelOptionsHtml += `<optgroup label="Gemini (Google)">` +
                geminiModels.map(m => `<option value="${m.id}" ${m.id === savedAiModel ? 'selected' : ''}>${m.name}</option>`).join('') +
                `</optgroup>`;
        }
        if (claudeModels.length > 0) {
            modelOptionsHtml += `<optgroup label="Claude (Anthropic)">` +
                claudeModels.map(m => `<option value="${m.id}" ${m.id === savedAiModel ? 'selected' : ''}>${m.name}</option>`).join('') +
                `</optgroup>`;
        }
        if (!modelOptionsHtml) {
            modelOptionsHtml = `<option value="gemini-flash-latest" selected>gemini-flash-latest</option>`;
        }

        form.innerHTML = `
        <div class="gm-row">
            <label class="gm-label">Длительность аудио (сек)</label>
            <input type="number" id="gm-duration" value="${_ls('audioDuration','60')}" min="14" max="300" class="gm-input">
        </div>
        ${_wpmSliderHtml(wpmVal)}
        <div class="gm-row">
            <label class="gm-label">Модель ИИ</label>
            <select id="gm-ai-model" class="gm-select">${modelOptionsHtml}</select>
        </div>
        <div class="gm-row">
            <label class="gm-label">Промпт для сценария</label>
            <select id="gm-step3-prompt" class="gm-select">${promptOptions}</select>
        </div>`;

    } else if (type === 'audio') {
        const _savedVoice = _ls('elevenlabsVoice', 'FGY2WhTYpPnroxEErjIq');
        const _myVoices = _treeVoices.filter(v => v.category === 'my');
        const _pubVoices = _treeVoices.filter(v => v.category !== 'my');
        const _optHtml = (v) => `<option value="${v.voice_id}" ${v.voice_id === _savedVoice ? 'selected' : ''}>${v.name}</option>`;
        const voiceOptions = _treeVoices.length === 0
            ? '<option value="FGY2WhTYpPnroxEErjIq">Laura</option>'
            : (_myVoices.length > 0
                ? `<optgroup label="Мои голоса">${_myVoices.map(_optHtml).join('')}</optgroup><optgroup label="Публичные">${_pubVoices.map(_optHtml).join('')}</optgroup>`
                : _pubVoices.map(_optHtml).join(''));

        form.innerHTML = `
        <div class="gm-row">
            <label class="gm-label">Голос диктора</label>
            <select id="gm-voice" class="gm-select">${voiceOptions}</select>
        </div>
        <div class="gm-row">
            <label class="gm-label">Модель ElevenLabs</label>
            <select id="gm-el-model" class="gm-select">
                <option value="eleven_v3" ${_ls('elevenlabsModel','eleven_v3')==='eleven_v3'?'selected':''}>Eleven v3</option>
                <option value="eleven_multilingual_v2" ${_ls('elevenlabsModel','eleven_v3')==='eleven_multilingual_v2'?'selected':''}>Eleven Multilingual v2</option>
                <option value="eleven_turbo_v2_5" ${_ls('elevenlabsModel','eleven_v3')==='eleven_turbo_v2_5'?'selected':''}>Eleven Turbo v2.5</option>
                <option value="eleven_flash_v2_5">Eleven Flash v2.5</option>
            </select>
        </div>
        <div class="gm-row gm-row--3">
            <div>
                <label class="gm-label">Stability</label>
                <input type="number" id="gm-stability" value="${_ls('audioStability','0.5')}" min="0" max="1" step="0.05" class="gm-input">
            </div>
            <div>
                <label class="gm-label">Similarity</label>
                <input type="number" id="gm-similarity" value="${_ls('audioSimilarity','0.75')}" min="0" max="1" step="0.05" class="gm-input">
            </div>
            <div>
                <label class="gm-label">Style</label>
                <input type="number" id="gm-style-el" value="${_ls('audioStyle','0.25')}" min="0" max="1" step="0.05" class="gm-input">
            </div>
        </div>
        <div class="gm-row gm-row--inline">
            <label class="gm-label">Speaker Boost</label>
            <input type="checkbox" id="gm-boost" ${_ls('useSpeakerBoost','true')==='true'?'checked':''}>
        </div>
        ${_wpmSliderHtml(_ls('audioWpm','150'))}`;  

    } else if (type === 'video') {
        const savedAvatar = _ls('heygenAvatar', '');
        const savedFormat = _ls('videoFormat', '9:16');
        const savedEngine = _ls('heygenEngine', 'avatar_iv');
        const savedStyle  = _ls('avatarStyle',  'normal');

        form.innerHTML = `
        <div class="gm-row">
            <label class="gm-label">Аватар</label>
            <button type="button" id="gm-avatar-btn"
                onclick="openAvatarModal('gm-video-format','gm-avatar-id','gm-avatar-btn')"
                class="gm-avatar-btn">
                <i class="fas fa-user-circle"></i> Выбрать аватар...
            </button>
            <input type="hidden" id="gm-avatar-id" value="${savedAvatar}">
        </div>
        <div class="gm-row gm-row--2">
            <div>
                <label class="gm-label">Движок</label>
                <select id="gm-engine" class="gm-select">
                    <option value="avatar_iv" ${savedEngine==='avatar_iv'?'selected':''}>Avatar IV</option>
                    <option value="avatar_iii" ${savedEngine==='avatar_iii'?'selected':''}>Avatar III</option>
                </select>
            </div>
            <div>
                <label class="gm-label">Формат видео</label>
                <select id="gm-video-format" class="gm-select"
                    onchange="updateAvatarStyleHint('gm-video-format','gm-style-av','gm-style-av-hint')">
                    <option value="9:16" ${savedFormat==='9:16'?'selected':''}>Вертикальный (9:16)</option>
                    <option value="16:9" ${savedFormat==='16:9'?'selected':''}>Горизонтальный (16:9)</option>
                    <option value="1:1"  ${savedFormat==='1:1'?'selected':''}>Квадратный (1:1)</option>
                </select>
            </div>
        </div>
        <div class="gm-row">
            <label class="gm-label">Стиль кадрирования</label>
            <select id="gm-style-av" class="gm-select">
                <option value="normal"  ${savedStyle==='normal'?'selected':''}>Нормальный</option>
                <option value="auto"    ${savedStyle==='auto'?'selected':''}>Авто (по формату)</option>
                <option value="closeUp" ${savedStyle==='closeUp'?'selected':''}>Крупный план</option>
                <option value="circle"  ${savedStyle==='circle'?'selected':''}>Круг</option>
            </select>
            <p id="gm-style-av-hint" class="gm-hint hidden">Для 9:16 рекомендуется «Крупный план»</p>
        </div>`;

        // После вставки HTML — обновляем кнопку аватара: показываем имя и ставим дефолт (Лиза пиджак)
        setTimeout(() => {
            const inp = document.getElementById('gm-avatar-id');
            if (!inp) return;

            // Если нет сохранённого аватара — ищем Лизу (пиджак, горизонтальный) среди приватных
            if (!inp.value) {
                const allPrivate = (typeof windowPrivateAvatars !== 'undefined') ? windowPrivateAvatars : [];
                const lisa = allPrivate.find(a =>
                    (a.avatar_name || '').toLowerCase().includes('лиза') &&
                    (a.avatar_name || '').toLowerCase().includes('пиджак')
                );
                if (lisa) {
                    inp.value = lisa.avatar_id;
                } else if (allPrivate.length > 0) {
                    inp.value = allPrivate[0].avatar_id;
                }
            }

            updateAvatarButtonText('gm-avatar-id', 'gm-avatar-btn', 'gm-video-format');
        }, 0);
    }

    return form;
}

async function submitGenerateModal() {
    if (!_genModalParentId || !_genModalTargetType) return;

    const btn = document.getElementById('gm-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Генерация...'; }
    closeGenerateModal();

    const params = _collectModalParams(_genModalTargetType);

    // Сохраняем выбранные параметры в localStorage
    _saveModalParams(_genModalTargetType, params);

    // Запускаем SSE-генерацию
    await _tree.generateNode(_genModalParentId, _genModalTargetType, params);
}

function _collectModalParams(type) {
    const g = id => document.getElementById(id);
    if (type === 'script') {
        return {
            audio_duration_sec: parseInt(g('gm-duration')?.value || 60),
            audio_wpm: parseInt(g('gm-wpm')?.value || 150),
            step3_prompt_key: g('gm-step3-prompt')?.value || 'default',
            ai_model: g('gm-ai-model')?.value || 'gemini-flash-latest',
        };
    } else if (type === 'audio') {
        const voiceSel = g('gm-voice');
        const voiceName = voiceSel ? voiceSel.options[voiceSel.selectedIndex]?.text : '';
        return {
            voice_id: g('gm-voice')?.value || 'FGY2WhTYpPnroxEErjIq',
            voice_name: voiceName,
            elevenlabs_model: g('gm-el-model')?.value || 'eleven_v3',
            audio_wpm: parseInt(g('gm-wpm')?.value || 150),
            stability: parseFloat(g('gm-stability')?.value || 0.5),
            similarity_boost: parseFloat(g('gm-similarity')?.value || 0.75),
            style: parseFloat(g('gm-style-el')?.value || 0.25),
            use_speaker_boost: g('gm-boost')?.checked ?? true,
        };
    } else if (type === 'video') {
        const avatarId = g('gm-avatar-id')?.value || '';
        const avatarObj = _treeAvatars.find(a => a.avatar_id === avatarId);
        return {
            avatar_id: avatarId,
            avatar_name: avatarObj?.avatar_name || avatarId,
            heygen_engine: g('gm-engine')?.value || 'avatar_iv',
            video_format: g('gm-video-format')?.value || '9:16',
            avatar_style: g('gm-style-av')?.value || 'auto',
        };
    }
    return {};
}

function _saveModalParams(type, params) {
    if (type === 'audio') {
        if (params.voice_id)          localStorage.setItem('elevenlabsVoice',  params.voice_id);
        if (params.elevenlabs_model)  localStorage.setItem('elevenlabsModel',  params.elevenlabs_model);
        if (params.audio_wpm)         localStorage.setItem('audioWpm',         params.audio_wpm);
        if (params.stability != null) localStorage.setItem('audioStability',   params.stability);
        if (params.similarity_boost != null) localStorage.setItem('audioSimilarity', params.similarity_boost);
        if (params.style != null)     localStorage.setItem('audioStyle',       params.style);
        localStorage.setItem('useSpeakerBoost', params.use_speaker_boost ? 'true' : 'false');
    }
    if (type === 'script') {
        if (params.audio_duration_sec) localStorage.setItem('audioDuration',   params.audio_duration_sec);
        if (params.audio_wpm)          localStorage.setItem('audioWpm',         params.audio_wpm);
        if (params.step3_prompt_key)   localStorage.setItem('step3PromptKey',   params.step3_prompt_key);
        if (params.ai_model)           localStorage.setItem('treeScriptModel',  params.ai_model);
    }
    if (type === 'video') {
        if (params.avatar_id)     localStorage.setItem('heygenAvatar', params.avatar_id);
        if (params.heygen_engine) localStorage.setItem('heygenEngine', params.heygen_engine);
        if (params.video_format)  localStorage.setItem('videoFormat',  params.video_format);
        if (params.avatar_style)  localStorage.setItem('avatarStyle',  params.avatar_style);
    }
}

/* ── SSE генерация узла (метод класса ResultTree) ──────────────────────── */
ResultTree.prototype.generateNode = async function(parentNodeId, targetType, params) {
    const slug = this.slug;
    const url  = `/api/tree/${slug}/node/${parentNodeId}/generate`;

    let placeholderNodeId = null;

    const resp = await fetch(url, {
        method: 'POST',
        headers: { 
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream'
        },
        body: JSON.stringify({ target_type: targetType, params }),
    });

    if (!resp.ok) { alert('Ошибка запуска генерации'); return; }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split('\n');
        buf = lines.pop();

        for (const line of lines) {
            if (!line.startsWith('data:')) continue;
            try {
                const evt = JSON.parse(line.slice(5).trim());

                if (evt.step === 'node_created' && evt.node) {
                    placeholderNodeId = evt.node.node_id;
                    this.insertNode(evt.node);
                    // Раскрываем родителя если закрыт
                    if (!this.expanded.has(parentNodeId)) this.toggle(parentNodeId);

                } else if (evt.step === 'done' && evt.node) {
                    this.updateNode(evt.node);
                    this.expanded.add(evt.node.node_id);
                    this._saveExpanded();
                    if (!this.expanded.has(evt.node.node_id)) this.toggle(evt.node.node_id);

                } else if (evt.step === 'error') {
                    console.error('Tree generate error:', evt.message);
                    if (placeholderNodeId) {
                        const n = this.nodesMap.get(placeholderNodeId);
                        if (n) { n.status = 'failed'; this.updateNode(n); }
                    }
                    alert('Ошибка генерации: ' + evt.message);
                }
            } catch (e) { /* ignore parse errors */ }
        }
    }
};

/* ── Оценка качества аудио ─────────────────────────────────────────────── */
async function _evaluateAudioNode(nodeId) {
    const node = _tree?.nodesMap.get(nodeId);
    if (!node || !node.content_url) return;

    const btn = document.querySelector(`#tn-${nodeId} .tn__eval-btn`);
    if (btn) { btn.disabled = true; btn.textContent = 'Оценка...'; }

    try {
        const slug = _tree.slug;
        const p    = node.params_json || {};
        const resp = await fetch('/api/evaluate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                audio_url: node.content_url_original || node.content_url,
                text: _tree.nodesMap.get(node.parent_node_id)?.content_text || '',
                elevenlabs_model: p.elevenlabs_model || 'eleven_v3',
                elevenlabs_voice: p.voice_id || '',
                stability: p.stability || 0.5,
                similarity_boost: p.similarity_boost || 0.75,
                style: p.style || 0.25,
                use_speaker_boost: p.use_speaker_boost ?? true,
                slug,
                is_main: false,
            })
        });
        const data = await resp.json();
        if (data.evaluation) {
            await fetch(`/api/tree/node/${nodeId}/evaluation`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data.evaluation),
            });
            node.evaluation_json = data.evaluation;
            _tree.updateNode(node);
        }
    } catch (e) {
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-star"></i> Оценить качество'; }
        alert('Ошибка оценки: ' + e.message);
    }
}

/* ── Утилиты ────────────────────────────────────────────────────────────── */
function _ls(key, def = '') {
    try { return localStorage.getItem(key) || def; } catch(e) { return def; }
}

/**
 * Возвращает HTML блока WPM-слайдера с:
 * - динамическим числом над ползунком (обновляется при движении)
 * - фиксированным маркером «150 (норм)» под дорожкой
 */
function _wpmSliderHtml(val) {
    const v = parseInt(val) || 150;
    // Позиция маркера «150» в процентах вдоль дорожки (min=105, max=180, range=75)
    const markerPct = ((150 - 105) / 75 * 100).toFixed(2); // ≈ 60%
    return `
    <div class="gm-row">
        <div class="gm-wpm-header">
            <label class="gm-label">Скорость (WPM)</label>
            <span class="gm-wpm-badge" id="gm-wpm-val">${v}</span>
        </div>
        <div class="gm-wpm-track">
            <input type="range" id="gm-wpm" min="105" max="180" value="${v}"
                class="gm-range gm-wpm-range"
                oninput="document.getElementById('gm-wpm-val').textContent=this.value">
            <div class="gm-wpm-marks">
                <span class="gm-wpm-mark-left">105</span>
                <span class="gm-wpm-mark-norm" style="left:${markerPct}%">▲<br>150<br><span>норм</span></span>
                <span class="gm-wpm-mark-right">180</span>
            </div>
        </div>
    </div>`;
}

/** Форматирует дату/время узла для тега в заголовке */
function _fmtNodeDate(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr + 'Z'); // UTC → local
        const now = new Date();
        const isToday = d.toDateString() === now.toDateString();
        if (isToday) {
            return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
        }
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' });
    } catch(e) { return ''; }
}

/* ══════════════════════════════════════════════════════════════════════════
   ИНИЦИАЛИЗАЦИЯ (вызывается из result.html)
   ══════════════════════════════════════════════════════════════════════════ */

async function initResultTree(slug) {
    const container = document.getElementById('result-tree');
    if (!container) return;

    // Загружаем голоса, аватары и step3-промпты (нужны для модального окна генерации)
    try {
        const cfg = await fetch('/api/config').then(r => r.json());
        _treeVoices  = cfg.voices  || [];
        _treeAvatars = cfg.avatars || [];
        _treeModels  = cfg.models  || [];
        if (typeof windowAvatars !== 'undefined')        windowAvatars        = _treeAvatars;
        if (typeof windowPrivateAvatars !== 'undefined') windowPrivateAvatars = cfg.private_avatars || [];
    } catch (e) { console.warn('Не удалось загрузить config:', e); }

    try {
        const pm = await fetch('/api/prompts').then(r => r.json());
        // Фильтруем служебные ключи, оставляем только пользовательские промпты
        const HIDDEN_KEYS = new Set(['v1', 'v2', 'evaluation']);
        _treeStep3Prompts = Object.fromEntries(
            Object.entries(pm.prompts?.step3 || {}).filter(([k]) => !HIDDEN_KEYS.has(k))
        );
    } catch (e) { console.warn('Не удалось загрузить промпты:', e); }

    _tree = new ResultTree(slug);
    window._tree = _tree;
    await _tree.init(container);
}
