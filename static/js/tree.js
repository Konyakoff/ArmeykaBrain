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
const _tcAutoPolled = new Set(); // node_id-ы, для которых уже запущен авто-поллинг таймкодов

/* ─── Константы ────────────────────────────────────────────────────────── */
const NODE_ICONS  = { article:'fa-align-left', script:'fa-microphone', audio:'fa-headphones', video:'fa-film', montage:'fa-wand-magic-sparkles' };
const NODE_COLORS = { article:'#3b82f6', script:'#8b5cf6', audio:'#F47920', video:'#10b981', montage:'#e11d48' };
const NODE_BGS    = { article:'#eff6ff', script:'#f5f3ff', audio:'#fff7ed', video:'#f0fdf4', montage:'#fff1f2' };
const SECTION_LABELS  = { article:'Сценарии', script:'Аудиофайлы', audio:'Видео', video:'Видео-монтаж' };
const CHILD_TYPE      = { article:'script', script:'audio', audio:'video', video:'montage' };
const ADD_LABELS      = { article:'Новый сценарий', script:'Новое аудио', audio:'Новое видео', video:'Новый монтаж' };
const ADD_TOOLTIPS    = {
    article: 'Создать аудиосценарий на основе этой статьи',
    script:  'Сгенерировать аудиофайл из этого сценария',
    audio:   'Создать видео на основе этого аудио',
    video:   'Создать видео-монтаж через Submagic',
};

let _submagicTemplates = [];

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
            const r = await fetch(`/api/tree/${this.slug}`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            this.nodesMap.clear();
            data.nodes.forEach(n => this.nodesMap.set(n.node_id, n));
            this._autoExpand();
            this.render();
            this._startPollingProcessing();
        } catch (e) {
            console.error('Tree load error:', e);
            if (this.container) {
                this.container.innerHTML =
                    `<div class="tn-load-error"><i class="fas fa-exclamation-triangle"></i> Ошибка загрузки дерева: ${e.message}</div>`;
            }
        }
    }

    /* Автоматически раскрываем корень и последний узел каждого уровня */
    _autoExpand() {
        if (this.expanded.size > 0) return;  // уже загружены из localStorage
        this.nodesMap.forEach(n => {
            if (n.node_type === 'article') this.expanded.add(n.node_id);
        });
        // Раскрываем последний script, последний audio, последний video
        ['script', 'audio', 'video', 'montage'].forEach(type => {
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
        roots.forEach(n => {
            try {
                // Перед корневым article-узлом вставляем карточку «Результаты шага 1»
                if (n.node_type === 'article') {
                    const s1card = _buildStep1Card(n);
                    if (s1card) this.container.appendChild(s1card);
                }
                this.container.appendChild(this._buildNode(n));
            } catch (e) {
                console.error('Tree render node error:', e, n);
                const errEl = document.createElement('div');
                errEl.className = 'tn-load-error';
                errEl.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Ошибка рендера узла ${n.node_type}: ${e.message}`;
                this.container.appendChild(errEl);
            }
        });
        // Суммарная стоимость в конце дерева
        try {
            const totalBar = _buildTotalBar(this.nodesMap);
            if (totalBar) this.container.appendChild(totalBar);
        } catch(e) { console.error('_buildTotalBar error:', e); }
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
                children.forEach(c => {
                    try {
                        childrenWrap.appendChild(this._buildNode(c));
                    } catch (e) {
                        console.error('Child node render error:', e, c);
                        const errEl = document.createElement('div');
                        errEl.className = 'tn-load-error';
                        errEl.innerHTML = `<i class="fas fa-exclamation-triangle"></i> Ошибка рендера узла ${c.node_type}: ${e.message}`;
                        childrenWrap.appendChild(errEl);
                    }
                });
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

    /** Показывает нефатальное предупреждение (toast-уведомление) */
    _showWarningToast(message) {
        const existing = document.getElementById('tree-warning-toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.id = 'tree-warning-toast';
        toast.style.cssText = [
            'position:fixed', 'bottom:24px', 'left:50%', 'transform:translateX(-50%)',
            'max-width:560px', 'width:90%', 'background:#92400e', 'color:#fef3c7',
            'border:1px solid #b45309', 'border-radius:8px', 'padding:12px 16px',
            'font-size:13px', 'line-height:1.5', 'z-index:9999',
            'box-shadow:0 4px 16px rgba(0,0,0,0.4)', 'cursor:pointer',
        ].join(';');
        toast.title = 'Нажмите, чтобы закрыть';
        toast.textContent = message;
        toast.onclick = () => toast.remove();
        document.body.appendChild(toast);

        // Автоудаление через 12 секунд
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 12000);
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
        case 'montage': return _contentMontage(node);
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

    // Stats — показываем только Шаг 2 (Шаг 1 вынесен в отдельную карточку выше)
    const stats = node.stats_json;
    if (stats) {
        const s2 = stats.step2 || {};
        wrap.appendChild(_statsRow([
            s2.model   ? `Модель: ${s2.model}` : null,
            s2.in_tokens ? `${s2.in_tokens}/${s2.out_tokens} токенов` : null,
            s2.generation_time_sec ? `${s2.generation_time_sec}с` : null,
            s2.total_cost ? `$${Number(s2.total_cost).toFixed(4)}` : null,
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

    // Кнопка +таймкоды или спиннер таймкодов — если таймкодов ещё нет и аудио завершено
    if (!st.timecodes_json_url && node.status === 'completed') {
        // Если узел создан менее 5 минут назад — таймкоды могут ещё генерироваться фоном
        const createdAt = node.created_at ? new Date(node.created_at).getTime() : 0;
        const isRecent = createdAt > 0 && (Date.now() - createdAt < 5 * 60 * 1000);

        if (isRecent && !_tcAutoPolled.has(node.node_id)) {
            // Показываем спиннер и запускаем авто-поллинг
            const tcSpin = document.createElement('span');
            tcSpin.className = 'tn__tc-spin';
            tcSpin.id = `tc-spin-${node.node_id}`;
            tcSpin.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> генерация таймкодов…';
            wrap.appendChild(tcSpin);
            _startTcAutoPoll(node.node_id);
        } else {
            const tcBtn = document.createElement('button');
            tcBtn.className = 'tn__tc-btn';
            tcBtn.id = `tc-btn-${node.node_id}`;
            tcBtn.innerHTML = '<i class="fas fa-closed-captioning"></i> +таймкоды';
            tcBtn.title = 'Сгенерировать таймкоды через Deepgram ($0.0077/мин)';
            tcBtn.onclick = () => _generateTimecodes(node.node_id);
            wrap.appendChild(tcBtn);
        }
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

async function _startTcAutoPoll(nodeId) {
    _tcAutoPolled.add(nodeId);
    let attempts = 0;
    const poll = setInterval(async () => {
        attempts++;
        if (attempts > 30) { clearInterval(poll); return; }
        try {
            const nr = await fetch(`/api/tree/node/${nodeId}`);
            const nd = await nr.json();
            const nst = nd.stats_json || {};
            if (nst.timecodes_json_url) {
                clearInterval(poll);
                if (_tree) {
                    const container = document.getElementById('result-tree');
                    if (container) await _tree.init(container);
                }
            }
        } catch (e) { /* тихо */ }
    }, 5000);
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

/* ── MONTAGE ──────────────────────────────────────────────────────────── */
function _contentMontage(node) {
    const wrap = document.createElement('div');
    wrap.className = 'tn__content';

    if (node.content_url) {
        const videoWrap = document.createElement('div');
        videoWrap.className = 'tn__video-wrap';
        const video = document.createElement('video');
        video.controls = true;
        video.preload = 'none';
        video.src = node.content_url;
        video.className = 'tn__video-el';
        videoWrap.appendChild(video);
        wrap.appendChild(videoWrap);

        const dl = document.createElement('a');
        dl.href = node.content_url;
        dl.download = '';
        dl.className = 'tn__dl-btn';
        dl.title = 'Скачать видео-монтаж';
        dl.innerHTML = '<i class="fas fa-download"></i> Скачать';
        dl.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-bottom:8px;font-size:13px;font-weight:500;';
        wrap.appendChild(dl);
    } else if (node.status === 'processing') {
        const svc = ((node.params_json || {}).service || (node.stats_json || {}).service || 'submagic');
        const svcLabel = svc === 'creatomate' ? 'Creatomate' : 'Submagic';
        const pending = document.createElement('div');
        pending.className = 'tn__video-pending';
        pending.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Видео-монтаж обрабатывается в ${svcLabel}...`;
        wrap.appendChild(pending);
    } else if (node.status === 'failed') {
        const errMsg = (node.stats_json || {}).error_message || 'Неизвестная ошибка';
        const errEl = document.createElement('div');
        errEl.className = 'tn__video-error';
        errEl.innerHTML = `<i class="fas fa-exclamation-triangle"></i> <strong>Ошибка:</strong> ${errMsg}`;
        wrap.appendChild(errEl);
    }

    const st = node.stats_json || {};
    if (st.preview_url) {
        const linkEl = document.createElement('a');
        linkEl.href = st.preview_url;
        linkEl.target = '_blank';
        linkEl.className = 'tn__montage-preview-link';
        linkEl.innerHTML = '<i class="fas fa-external-link-alt"></i> Открыть в Submagic';
        wrap.appendChild(linkEl);
    }

    const paramParts = [];
    if (st.template_name) paramParts.push(`Шаблон: ${st.template_name}`);
    if (st.video_width && st.video_height) paramParts.push(`${st.video_width}×${st.video_height}`);
    if (paramParts.length) {
        const paramEl = document.createElement('div');
        paramEl.className = 'tn__param-row';
        paramEl.textContent = paramParts.join(' · ');
        wrap.appendChild(paramEl);
    }

    if (Object.keys(st).length && st.status === 'completed') {
        const genTime = st.generation_time_sec;
        wrap.appendChild(_statsRow([
            genTime ? `Время: ${Math.floor(genTime/60)}м ${genTime%60}с` : null,
            'Submagic',
        ]));
    }
    return wrap;
}

/* ── Строка статистики ─────────────────────────────────────────────────── */
/* ── Карточка «Результаты поиска — Шаг 1» ────────────────────────────────
   Парсит текст из params_json.step1_info (markdown-строка) и отрисовывает
   аккуратный блок над узлом «Экспертная статья».                          */
function _buildStep1Card(articleNode) {
    const p  = articleNode.params_json || {};
    const st = (articleNode.stats_json || {}).step1 || {};
    const raw = p.step1_info || '';
    if (!raw) return null;

    // ── Парсим markdown-строку в структурированные данные ──────────────────
    // Формат:
    //   🗂 **Классификация вопроса:** <category>
    //   ✅ **Найденные статьи (ТОП-15):**
    //   Статья/Пункт <num> - <file> - <pct>%
    //   🔍 **Взяты в работу (id объектов >= N% или Топ-3):**
    //   • <uid>
    const lines = raw.split('\n').map(l => l.trim()).filter(Boolean);

    let category  = '';
    let threshold = null;          // число-порог из текста «>= N%»
    const allArticles = [];        // { num, file, pct }
    const usedUids    = [];        // строки uid
    let section = '';

    for (const line of lines) {
        if (line.includes('Классификация вопроса:')) {
            category = line.replace(/.*Классификация вопроса:\*\*?\s*/, '').trim();
        } else if (line.includes('Найденные статьи')) {
            section = 'articles';
        } else if (line.includes('Взяты в работу')) {
            // Извлекаем порог: «>= 70%»
            const tm = line.match(/>=\s*(\d+)%/);
            if (tm) threshold = parseInt(tm[1]);
            section = 'used';
        } else if (section === 'articles' && /^Статья/.test(line)) {
            // "Статья/Пункт 18 - 3.PP_565_RaspBolezney - 95%"
            const m = line.match(/Статья\/Пункт\s+(\d+)\s+-\s+(.+?)\s+-\s+(\d+)%/);
            if (m) allArticles.push({ num: m[1], file: m[2], pct: parseInt(m[3]) });
        } else if (section === 'used' && line.startsWith('•')) {
            usedUids.push(line.replace(/^•\s*/, '').trim());
        }
    }

    // ── Строим Set «file:num» для точного сопоставления ────────────────────
    // uid-формат: <file>_<x>_<y>_<article_num>
    // Сопоставляем каждый uid с конкретной статьёй по комбинации файл + номер,
    // чтобы избежать ложных совпадений при одинаковых номерах в разных файлах.
    const usedComposites = new Set();
    for (const uid of usedUids) {
        for (const a of allArticles) {
            if (uid.startsWith(a.file + '_') && uid.endsWith('_' + a.num)) {
                usedComposites.add(`${a.file}:${a.num}`);
            }
        }
    }

    // ── Строим DOM ─────────────────────────────────────────────────────────
    const card = document.createElement('div');
    card.className = 'tn-step1-card';

    // Заголовок
    const hdr = document.createElement('div');
    hdr.className = 'tn-step1-card__header';

    // Готовим ссылку для скачивания JSON (если есть raw_data)
    const rawData = p.step1_raw_data || null;
    let downloadHtml = '';
    if (rawData) {
        downloadHtml = `<button class="tn-step1-card__dl-btn" title="Скачать оригинальный JSON ответа модели (Шаг 1)">
            <i class="fas fa-file-code"></i>
        </button>`;
    }

    hdr.innerHTML = `
        <div class="tn-step1-card__icon-wrap">
            <i class="fas fa-search"></i>
        </div>
        <div class="tn-step1-card__hdr-text">
            <span class="tn-step1-card__title">Результаты поиска — Шаг 1</span>
            ${category ? `<span class="tn-step1-card__category">${_escHtml(category)}</span>` : ''}
            ${threshold !== null ? `<span class="tn-step1-card__threshold" title="Порог отбора НПА для Шага 2">порог ≥${threshold}%</span>` : ''}
        </div>
        <div class="tn-step1-card__hdr-right">
            ${downloadHtml}
            <button class="tn-step1-card__toggle" title="Свернуть/развернуть">
                <i class="fas fa-chevron-up"></i>
            </button>
        </div>`;

    card.appendChild(hdr);

    // Навешиваем скачивание после вставки в DOM
    if (rawData) {
        hdr.querySelector('.tn-step1-card__dl-btn').addEventListener('click', e => {
            e.stopPropagation();
            const slug = articleNode.slug || 'step1';
            const filename = `step1_${slug}.json`;
            const blob = new Blob([JSON.stringify(rawData, null, 2)], { type: 'application/json' });
            const url  = URL.createObjectURL(blob);
            const a    = document.createElement('a');
            a.href = url; a.download = filename;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 1000);
        });
    }

    // Тело
    const body = document.createElement('div');
    body.className = 'tn-step1-card__body';

    // Таблица статей
    if (allArticles.length) {
        const grid = document.createElement('div');
        grid.className = 'tn-step1-card__grid';

        allArticles.forEach(a => {
            const isUsed = usedComposites.has(`${a.file}:${a.num}`);
            const row = document.createElement('div');
            row.className = 'tn-step1-card__row' + (isUsed ? ' tn-step1-card__row--used' : '');

            const pctBar = Math.round(a.pct);
            row.innerHTML = `
                <span class="tn-step1-card__num">${_escHtml(a.num)}</span>
                <span class="tn-step1-card__file">${_escHtml(a.file)}</span>
                <span class="tn-step1-card__pct-wrap">
                    <span class="tn-step1-card__pct-bar" style="width:${pctBar}%"></span>
                    <span class="tn-step1-card__pct-label">${a.pct}%</span>
                </span>
                ${isUsed
                    ? '<span class="tn-step1-card__used-badge">в работе</span>'
                    : '<span class="tn-step1-card__skip-badge">пропущена</span>'}`;
            grid.appendChild(row);
        });
        body.appendChild(grid);
    }

    // Строка статистики
    if (Object.keys(st).length) {
        const statsEl = document.createElement('div');
        statsEl.className = 'tn-step1-card__stats';
        const model = (st.model || '').replace('gemini-', 'g-').replace('-preview', '');
        const tok   = st.in_tokens ? `${st.in_tokens} / ${st.out_tokens} токенов` : null;
        const time  = st.generation_time_sec ? `${st.generation_time_sec}с` : null;
        const cost  = st.total_cost ? `$${Number(st.total_cost).toFixed(4)}` : null;
        [model, tok, time, cost].filter(Boolean).forEach(txt => {
            const tag = document.createElement('span');
            tag.className = 'tn__tag';
            tag.textContent = txt;
            statsEl.appendChild(tag);
        });
        body.appendChild(statsEl);
    }

    card.appendChild(body);

    // Сворачивание
    let collapsed = false;
    hdr.querySelector('.tn-step1-card__toggle').addEventListener('click', e => {
        e.stopPropagation();
        collapsed = !collapsed;
        body.style.display = collapsed ? 'none' : '';
        hdr.querySelector('i').className = collapsed ? 'fas fa-chevron-down' : 'fas fa-chevron-up';
    });

    return card;
}

function _escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ── Суммарная стоимость по всему дереву ────────────────────────────────── */
function _buildTotalBar(nodesMap) {
    let total = 0;
    const breakdown = [];  // { label, cost }

    nodesMap.forEach(node => {
        const st = node.stats_json || {};
        switch (node.node_type) {
            case 'article': {
                const c1 = st.step1?.total_cost || 0;
                const c2 = st.step2?.total_cost || 0;
                if (c1) breakdown.push({ label: 'Шаг 1 (поиск)', cost: c1 });
                if (c2) breakdown.push({ label: 'Шаг 2 (статья)', cost: c2 });
                total += c1 + c2;
                break;
            }
            case 'script': {
                const c = st.total_cost || 0;
                if (c) breakdown.push({ label: node.title || 'Сценарий', cost: c });
                total += c;
                break;
            }
            case 'audio': {
                const c  = st.total_cost || 0;
                const ct = st.timecodes_cost || 0;
                if (c)  breakdown.push({ label: node.title || 'Аудио', cost: c });
                if (ct) breakdown.push({ label: 'Таймкоды', cost: ct });
                total += c + ct;
                break;
            }
            case 'video': {
                const c = st.estimated_cost || st.total_cost || 0;
                if (c) breakdown.push({ label: node.title || 'Видео', cost: c });
                total += c;
                break;
            }
        }
    });

    if (!total) return null;

    const bar = document.createElement('div');
    bar.className = 'tn-total-bar';

    const parts = breakdown.map(b =>
        `<span class="tn-total-bar__item">${_escHtml(b.label)}: <strong>$${b.cost.toFixed(4)}</strong></span>`
    ).join('');

    bar.innerHTML = `
        <div class="tn-total-bar__left">
            <i class="fas fa-receipt tn-total-bar__icon"></i>
            <span class="tn-total-bar__label">Итого по запросу</span>
            <div class="tn-total-bar__breakdown">${parts}</div>
        </div>
        <div class="tn-total-bar__total">$${total.toFixed(4)}</div>`;

    return bar;
}

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
    if (node.status !== 'completed' && node.node_type !== 'video' && node.node_type !== 'montage') return base;

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

    if (node.node_type === 'montage') {
        const tpl = st.template_name || p.template_name || '';
        const dur = st.video_duration_sec;
        const extras = [tpl || null, dur ? `${Math.round(dur)}с` : null].filter(Boolean);
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
            if (st.step2) {
                const model = (st.step2.model || '').replace('gemini-', '').replace('-preview', '');
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
        case 'montage': {
            const service = (st.service || p.service || 'submagic').toLowerCase();

            if (service === 'creatomate') {
                parts.push('Creatomate');
                const fmt = st.video_format || p.video_format;
                if (fmt) parts.push(fmt);
                const fps = st.fps || p.fps;
                if (fps) parts.push(`${fps}fps`);
                const dur = st.video_duration_sec;
                if (dur) parts.push(`${Math.round(dur)}с`);
                const preset = st.subtitle_preset || p.subtitle_preset;
                if (preset) parts.push(preset.replace('_', ' '));
                const eff = st.transcript_effect || p.transcript_effect;
                if (eff && eff !== 'karaoke') parts.push(eff);
                const broll = st.broll || {};
                if (broll.fetched_count) {
                    const layoutLabel = {overlay:'overlay', pip:'PIP', split:'split'}[st.broll_layout] || '';
                    const layoutStr = layoutLabel ? ` [${layoutLabel}]` : '';
                    parts.push(`B-roll: ${broll.fetched_count}/${broll.planned_count} (${broll.provider}${layoutStr})`);
                }
                if (st.color_filter) parts.push(`фильтр: ${st.color_filter}`);
                if (st.intro_text)   parts.push('intro');
                if (st.outro_text)   parts.push('outro');
                if (st.watermark_url) parts.push('logo');
                if (st.music_url)    parts.push('music');
                const credits = st.credits;
                if (credits) parts.push(`${credits} crd`);
                const cost = st.total_cost ?? st.render_cost_usd;
                if (cost != null) parts.push(`$${Number(cost).toFixed(3)}`);
                break;
            }

            parts.push('SubMagic');
            const mode = p.mode || st.mode || 'auto';
            if (mode === 'smart') {
                parts.push('Smart');
                const brollSrc = p.broll_source || st.broll_source || 'ai';
                const brollSrcLabel = {
                    ai: 'AI', pexels: 'Pexels', pixabay: 'Pixabay',
                    pexels_pixabay: 'Pexels+Pixabay', veo: 'Veo', runway: 'Runway',
                };
                parts.push(`B-roll: ${brollSrcLabel[brollSrc] || brollSrc}`);
                const density = p.density || st.density;
                if (density) {
                    const ru = { low: 'низкая', medium: 'средняя', high: 'высокая', very_high: 'очень высокая' };
                    parts.push(`плотность: ${ru[density] || density}`);
                }
                const topic = p.topic_hint || st.topic_hint;
                if (topic && topic !== 'auto') {
                    const ruTopic = {
                        law: 'право', army: 'армия', medical: 'медкомиссия',
                        process: 'юр.процесс', general: 'общая'
                    };
                    parts.push(`тема: ${ruTopic[topic] || topic}`);
                }
                const cnt = st.broll_items_count;
                if (cnt) parts.push(`${cnt} вставок`);
                const clipDur = p.clip_duration || st.clip_duration;
                if (clipDur) parts.push(`${clipDur}с/вставка`);
                const russiaOnly = (p.russia_only ?? st.russia_only);
                if (russiaOnly) parts.push('Russia-only');
            }
            const tpl = p.template_name || st.template_name;
            if (tpl) parts.push(tpl);
            if (p.magic_zooms || st.magic_zooms) parts.push('Zoom');
            if (mode === 'auto' && (p.magic_brolls || st.magic_brolls)) parts.push('B-roll');
            if (p.clean_audio || st.clean_audio) parts.push('Clean');
            const pace = p.remove_silence_pace || st.remove_silence_pace;
            if (pace) parts.push(`silence:${pace}`);
            if (p.remove_bad_takes || st.remove_bad_takes) parts.push('NoBad');
            break;
        }
    }
    return parts.map(t => `<span class="tn__tag">${t}</span>`).join('');
}

function _buildMeta(node) {
    const st = node.stats_json || {};
    const parts = [];
    if (st.generation_time_sec) {
        parts.push(`${st.generation_time_sec}с`);
    } else if (node.node_type === 'article') {
        // Article node: show only Step 2 time (Step 1 has its own card)
        const t2 = st.step2?.generation_time_sec || 0;
        if (t2) parts.push(`${t2}с`);
    } else if (st.step1 && st.step1.generation_time_sec) {
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
    // Article node: show only Step 2 cost (Step 1 is shown in its own card)
    if (node.node_type === 'article') {
        const c = st.step2?.total_cost || 0;
        return c ? c.toFixed(4) : null;
    }
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

    const labels = { script: 'Новый сценарий для аудио', audio: 'Новое аудио', video: 'Новое видео', montage: 'Видео-монтаж (Submagic)' };
    title.textContent = labels[targetType] || 'Генерация';

    body.innerHTML = '';
    body.appendChild(_buildModalForm(targetType));

    // Сбрасываем состояние кнопки — могла остаться disabled после предыдущей генерации
    const submitBtn = document.getElementById('gm-submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        if (targetType === 'montage') {
            const mode = (localStorage.getItem('smMode') || 'auto');
            _updateMontageSubmitLabel(mode);
            _onSmBrollSrcChange(localStorage.getItem('smSmartBrollSrc') || 'ai');
            
            // Восстанавливаем сохраненную модель, если она есть
            const savedGenModel = localStorage.getItem('smSmartGenModel');
            const modelSel = document.getElementById('gm-sm-gen-model');
            if (savedGenModel && modelSel && modelSel.querySelector(`option[value="${savedGenModel}"]`)) {
                modelSel.value = savedGenModel;
            }
        } else {
            submitBtn.innerHTML = '<i class="fas fa-bolt"></i> Сгенерировать';
        }
    }

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function _updateMontageSubmitLabel(mode) {
    const btn = document.getElementById('gm-submit-btn');
    if (!btn) return;
    if (mode === 'smart') {
        btn.innerHTML = '<i class="fas fa-brain"></i> Запустить умный монтаж';
    } else {
        btn.innerHTML = '<i class="fas fa-wand-magic-sparkles"></i> Начать монтаж';
    }
}

function _onSmModeChange(mode) {
    const auto  = document.getElementById('gm-sm-auto-fields');
    const smart = document.getElementById('gm-sm-smart-fields');
    if (auto)  auto.style.display  = mode === 'auto'  ? '' : 'none';
    if (smart) smart.style.display = mode === 'smart' ? '' : 'none';
    document.querySelectorAll('.gm-mode-tab[data-group="mode"]').forEach(el => {
        const inp = el.querySelector('input[type="radio"]');
        el.classList.toggle('is-active', inp && inp.value === mode);
    });
    _updateMontageSubmitLabel(mode);
}

function _onSmServiceChange(svc) {
    const sm = document.getElementById('gm-svc-submagic');
    const ct = document.getElementById('gm-svc-creatomate');
    if (sm) sm.style.display = svc === 'submagic'  ? '' : 'none';
    if (ct) ct.style.display = svc === 'creatomate' ? '' : 'none';
    document.querySelectorAll('.gm-mode-tab[data-group="service"]').forEach(el => {
        const inp = el.querySelector('input[type="radio"]');
        el.classList.toggle('is-active', inp && inp.value === svc);
    });
}

function _onSmBrollSrcChange(src) {
    // Когда источник — не встроенный AI Submagic, clip_duration ограничен 8c (Veo) или 10c (Pexels)
    const clipDurSel = document.getElementById('gm-sm-clip-dur');
    if (clipDurSel && src === 'veo') {
        // Veo генерирует ровно 8c — зафиксируем ближайший вариант
        clipDurSel.value = '7';
    }

    const modelRow = document.getElementById('gm-sm-gen-model-row');
    const modelSel = document.getElementById('gm-sm-gen-model');
    if (modelRow && modelSel) {
        if (src === 'veo' || src === 'runway') {
            modelRow.style.display = '';
            const currentVal = modelSel.value;
            modelSel.innerHTML = '';
            if (src === 'veo') {
                modelSel.innerHTML = `
                    <option value="veo-3.1-generate-preview">Veo 3.1 (Preview)</option>
                    <option value="veo-3.0-generate-001">Veo 3.0</option>
                `;
            } else if (src === 'runway') {
                modelSel.innerHTML = `
                    <option value="gen4.5">Gen-4.5</option>
                    <option value="gen3a_turbo">Gen-3 Alpha Turbo</option>
                `;
            }
            // Restore selection if valid
            const options = Array.from(modelSel.options).map(o => o.value);
            if (options.includes(currentVal)) {
                modelSel.value = currentVal;
            } else {
                modelSel.value = options[0];
            }
        } else {
            modelRow.style.display = 'none';
        }
    }
}

function _onCtBrollProviderChange(prov) {
    const stockPanel = document.getElementById('gm-ct-stock-fields');
    const aiPanel    = document.getElementById('gm-ct-ai-fields');
    const showStock  = ['pexels', 'pixabay', 'pexels_pixabay'].includes(prov);
    const showAi     = ['veo', 'runway', 'luma'].includes(prov);
    const showAny    = showStock || showAi;
    const wrap = document.getElementById('gm-ct-broll-fields');
    if (wrap)       wrap.style.display       = showAny ? '' : 'none';
    if (stockPanel) stockPanel.style.display = showStock ? '' : 'none';
    if (aiPanel)    aiPanel.style.display    = showAi ? '' : 'none';
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

    } else if (type === 'montage') {
        const savedMode     = _ls('smMode', 'auto');
        const savedTemplate = _ls('smTemplate', 'Hormozi 2');
        const savedZooms    = _ls('smZooms', 'true') === 'true';
        const savedBrolls   = _ls('smBrolls', 'false') === 'true';
        const savedBrollPct = _ls('smBrollPct', '50');
        const savedSilence  = _ls('smSilence', '');
        const savedBadTakes = _ls('smBadTakes', 'false') === 'true';
        const savedClean    = _ls('smCleanAudio', 'false') === 'true';

        const savedDensity    = _ls('smSmartDensity', 'medium');
        const savedClipDur    = _ls('smSmartClipDur', '5');
        const savedTopic      = _ls('smSmartTopic', 'auto');
        const savedLayout     = _ls('smSmartLayout', 'cover');
        const savedRussia     = _ls('smSmartRussia', 'true') === 'true';
        const savedExtra      = _ls('smSmartExtra', '');
        const savedLlm        = _ls('smSmartLlm', 'gemini-flash-latest');
        const savedBrollSrc   = _ls('smSmartBrollSrc', 'ai');
        const savedGenModel   = _ls('smSmartGenModel', 'gen4.5');

        const templateList = _submagicTemplates.length > 0 ? _submagicTemplates : [
            'Hormozi 2','Hormozi 1','Hormozi 3','Hormozi 4','Hormozi 5',
            'Sara','Matt','Jess','Jack','Nick','Laura','Kelly 2',
            'Beast','Karl','Ella','Dan','Dan 2','Devin',
        ];
        const tplOptions = templateList.map(t =>
            `<option value="${t}"${t === savedTemplate ? ' selected' : ''}>${t}</option>`
        ).join('');

        const isAuto  = savedMode !== 'smart';
        const isSmart = savedMode === 'smart';

        const savedService = _ls('mtgService', 'submagic');
        const isSubmagic   = savedService !== 'creatomate';
        const isCreatomate = savedService === 'creatomate';

        // ── Creatomate-saved settings ──
        const ctFormat   = _ls('ctFormat', '9:16');
        const ctFps      = _ls('ctFps', '30');
        const ctSubPreset= _ls('ctSubPreset', 'hormozi_white');
        const ctSubEffect= _ls('ctSubEffect', 'karaoke');
        const ctSubSplit = _ls('ctSubSplit', 'word');
        const ctMusicUrl = _ls('ctMusicUrl', '');
        const ctMusicVol = _ls('ctMusicVol', '25');
        const ctIntroTxt = _ls('ctIntroText', '');
        const ctOutroTxt = _ls('ctOutroText', 'Подписывайтесь и будьте свободны с Армейка Нэт');
        const ctWatermark= _ls('ctWatermark', '');
        const ctWmPos    = _ls('ctWmPos', 'top-right');
        const ctColor    = _ls('ctColor', '');
        const ctColorVal = _ls('ctColorVal', '20%');

        const ctBrollProv= _ls('ctBrollProv', 'off');
        const ctBrollDens= _ls('ctBrollDens', 'medium');
        const ctBrollDur = _ls('ctBrollDur', '5');
        const ctBrollLayout = _ls('ctBrollLayout', 'overlay');
        const ctBrollTopic = _ls('ctBrollTopic', 'auto');
        const ctBrollExtra = _ls('ctBrollExtra', '');
        const ctBrollLlm   = _ls('ctBrollLlm', 'gemini-flash-latest');
        const ctBrollRu    = _ls('ctBrollRu', 'true') === 'true';

        const showCtBroll = ['pexels','pixabay','pexels_pixabay','veo','runway','luma'].includes(ctBrollProv);
        const showCtStock = ['pexels','pixabay','pexels_pixabay'].includes(ctBrollProv);
        const showCtAi    = ['veo','runway','luma'].includes(ctBrollProv);

        form.innerHTML = `
        <!-- ═════════ ПЕРЕКЛЮЧАТЕЛЬ СЕРВИСА ═════════ -->
        <div class="gm-row gm-row--mode">
            <label class="gm-label">Сервис монтажа
                <span class="gm-hint-icon" data-tooltip="Submagic — готовый AI-сервис с авто B-roll. Creatomate — программный монтаж с гибкой настройкой и выбором источника B-roll (стоки, AI-генерация).">?</span>
            </label>
            <div class="gm-mode-tabs">
                <label class="gm-mode-tab${isSubmagic ? ' is-active' : ''}" data-group="service">
                    <input type="radio" name="gm-sm-service" value="submagic" ${isSubmagic ? 'checked' : ''}
                        onchange="_onSmServiceChange('submagic')">
                    <i class="fas fa-bolt"></i> Submagic
                </label>
                <label class="gm-mode-tab${isCreatomate ? ' is-active' : ''}" data-group="service">
                    <input type="radio" name="gm-sm-service" value="creatomate" ${isCreatomate ? 'checked' : ''}
                        onchange="_onSmServiceChange('creatomate')">
                    <i class="fas fa-cubes"></i> Creatomate
                </label>
            </div>
        </div>

        <!-- ═════════ SUBMAGIC PANEL ═════════ -->
        <div id="gm-svc-submagic" style="display:${isSubmagic ? '' : 'none'}">
        <div class="gm-row gm-row--mode">
            <label class="gm-label">Режим монтажа
                <span class="gm-hint-icon" data-tooltip="Auto — Submagic сам выбирает B-roll. Smart — мы используем таймкоды Deepgram + LLM с фильтром «только Россия».">?</span>
            </label>
            <div class="gm-mode-tabs">
                <label class="gm-mode-tab${isAuto ? ' is-active' : ''}" data-group="mode">
                    <input type="radio" name="gm-sm-mode" value="auto" ${isAuto ? 'checked' : ''}
                        onchange="_onSmModeChange('auto')">
                    <i class="fas fa-magic"></i> Auto
                </label>
                <label class="gm-mode-tab${isSmart ? ' is-active' : ''}" data-group="mode">
                    <input type="radio" name="gm-sm-mode" value="smart" ${isSmart ? 'checked' : ''}
                        onchange="_onSmModeChange('smart')">
                    <i class="fas fa-brain"></i> Smart (Deepgram, RU)
                </label>
            </div>
            <p class="gm-hint">Smart-режим работает с видео 20–90 сек. Если у родительского аудио ещё нет таймкодов — мы сгенерируем их автоматически (~30–60 с).</p>
        </div>

        <div class="gm-row">
            <label class="gm-label">Шаблон субтитров
                <span class="gm-hint-icon" data-tooltip="Визуальный стиль субтитров: шрифт, анимация, цвета. Hormozi 2 — один из самых популярных.">?</span>
            </label>
            <select id="gm-sm-template" class="gm-select">${tplOptions}</select>
        </div>
        <div class="gm-row gm-row--inline">
            <label class="gm-label">AI Captions (субтитры)
                <span class="gm-hint-icon" data-tooltip="ИИ автоматически создаёт субтитры к видео с анимацией и эффектами.">?</span>
            </label>
            <input type="checkbox" id="gm-sm-captions" checked disabled>
        </div>
        <div class="gm-row gm-row--inline">
            <label class="gm-label">AI Auto Zooms
                <span class="gm-hint-icon" data-tooltip="Автоматические zoom-эффекты на ключевых моментах для усиления вовлечённости.">?</span>
            </label>
            <input type="checkbox" id="gm-sm-zooms" ${savedZooms ? 'checked' : ''}>
        </div>

        <!-- ───────── AUTO-only fields ───────── -->
        <div id="gm-sm-auto-fields" style="display:${isAuto ? '' : 'none'}">
            <div class="gm-row gm-row--inline">
                <label class="gm-label">AI Auto B-rolls
                    <span class="gm-hint-icon" data-tooltip="ИИ Submagic автоматически вставляет фоновые видеоролики (B-roll). Внимание: возможно появление иностранной символики.">?</span>
                </label>
                <input type="checkbox" id="gm-sm-brolls" ${savedBrolls ? 'checked' : ''}
                    onchange="document.getElementById('gm-sm-broll-pct-row').style.display=this.checked?'':'none'">
            </div>
            <div class="gm-row" id="gm-sm-broll-pct-row" style="display:${savedBrolls ? '' : 'none'}">
                <label class="gm-label">B-roll %
                    <span class="gm-hint-icon" data-tooltip="Какой процент видео заполнить B-roll вставками (0–100).">?</span>
                </label>
                <input type="number" id="gm-sm-broll-pct" value="${savedBrollPct}" min="0" max="100" class="gm-input">
            </div>
        </div>

        <!-- ───────── SMART-only fields ───────── -->
        <div id="gm-sm-smart-fields" style="display:${isSmart ? '' : 'none'}">
            <div class="gm-row">
                <label class="gm-label">Источник B-roll
                    <span class="gm-hint-icon" data-tooltip="AI — Submagic генерирует B-roll сам (3 кредита/вставка). Pexels/Pixabay — стоковые видео (бесплатно). Veo/Runway — ИИ-генерация (требует API-ключ и кредиты).">?</span>
                </label>
                <select id="gm-sm-broll-src" class="gm-select"
                    onchange="_onSmBrollSrcChange(this.value)">
                    <option value="ai"            ${savedBrollSrc==='ai'?'selected':''}>AI Submagic (встроенный)</option>
                    <option value="pexels"        ${savedBrollSrc==='pexels'?'selected':''}>Pexels (сток, бесплатно)</option>
                    <option value="pixabay"       ${savedBrollSrc==='pixabay'?'selected':''}>Pixabay (сток, бесплатно)</option>
                    <option value="pexels_pixabay" ${savedBrollSrc==='pexels_pixabay'?'selected':''}>Pexels + Pixabay (каскад)</option>
                    <option value="veo"           ${savedBrollSrc==='veo'?'selected':''}>Google Veo (ИИ-генерация)</option>
                    <option value="runway"        ${savedBrollSrc==='runway'?'selected':''}>Runway (ИИ-генерация)</option>
                </select>
            </div>
            <div class="gm-row" id="gm-sm-gen-model-row" style="display:none">
                <label class="gm-label">Модель генерации B-roll
                    <span class="gm-hint-icon" data-tooltip="Выберите модель для ИИ-генерации (Veo или Runway).">?</span>
                </label>
                <select id="gm-sm-gen-model" class="gm-select">
                    <!-- Заполняется динамически через JS -->
                </select>
            </div>
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Плотность B-roll
                        <span class="gm-hint-icon" data-tooltip="Низкая — 1 вставка на 30 с, Средняя — на 15 с, Высокая — на 9 с. Управляет количеством вставок.">?</span>
                    </label>
                    <select id="gm-sm-density" class="gm-select">
                        <option value="low"       ${savedDensity==='low'?'selected':''}>Низкая</option>
                        <option value="medium"    ${savedDensity==='medium'?'selected':''}>Средняя</option>
                        <option value="high"      ${savedDensity==='high'?'selected':''}>Высокая</option>
                        <option value="very_high" ${savedDensity==='very_high'?'selected':''}>Очень высокая</option>
                    </select>
                </div>
                <div>
                    <label class="gm-label">Длительность вставки
                        <span class="gm-hint-icon" data-tooltip="Максимальная длина одной B-roll вставки. 3–5 с — динамичный клиповый стиль, 7–10 с — медленные иллюстративные кадры.">?</span>
                    </label>
                    <select id="gm-sm-clip-dur" class="gm-select">
                        <option value="3"  ${savedClipDur==='3'?'selected':''}>3 с (клиповый)</option>
                        <option value="4"  ${savedClipDur==='4'?'selected':''}>4 с (быстрый)</option>
                        <option value="5"  ${savedClipDur==='5'?'selected':''}>5 с (стандарт)</option>
                        <option value="7"  ${savedClipDur==='7'?'selected':''}>7 с (плавный)</option>
                        <option value="10" ${savedClipDur==='10'?'selected':''}>10 с (длинный)</option>
                    </select>
                </div>
            </div>
            <div class="gm-row">
                <div>
                    <label class="gm-label">Тематика
                        <span class="gm-hint-icon" data-tooltip="Контекст для LLM: помогает выбирать визуально подходящие сцены без иностранной символики.">?</span>
                    </label>
                    <select id="gm-sm-topic" class="gm-select">
                        <option value="auto"    ${savedTopic==='auto'?'selected':''}>Авто (по тексту)</option>
                        <option value="law"     ${savedTopic==='law'?'selected':''}>Военное право</option>
                        <option value="army"    ${savedTopic==='army'?'selected':''}>Армия</option>
                        <option value="medical" ${savedTopic==='medical'?'selected':''}>Медкомиссия</option>
                        <option value="process" ${savedTopic==='process'?'selected':''}>Юридический процесс</option>
                        <option value="general" ${savedTopic==='general'?'selected':''}>Общая</option>
                    </select>
                </div>
            </div>
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Layout
                        <span class="gm-hint-icon" data-tooltip="Cover — B-roll на весь экран. Split 50/50 — половина экрана. PiP — картинка-в-картинке.">?</span>
                    </label>
                    <select id="gm-sm-layout" class="gm-select">
                        <option value="cover"        ${savedLayout==='cover'?'selected':''}>Cover (полный экран)</option>
                        <option value="split-50-50" ${savedLayout==='split-50-50'?'selected':''}>Split 50/50</option>
                        <option value="pip"          ${savedLayout==='pip'?'selected':''}>PiP</option>
                    </select>
                </div>
                <div>
                    <label class="gm-label">LLM для промптов
                        <span class="gm-hint-icon" data-tooltip="Gemini Flash — быстрый и почти бесплатный. Pro — качественнее, но дороже.">?</span>
                    </label>
                    <select id="gm-sm-llm" class="gm-select">
                        <option value="gemini-flash-latest" ${savedLlm==='gemini-flash-latest'?'selected':''}>Gemini Flash</option>
                        <option value="gemini-pro-latest"   ${savedLlm==='gemini-pro-latest'?'selected':''}>Gemini Pro</option>
                    </select>
                </div>
            </div>
            <div class="gm-row gm-row--inline">
                <label class="gm-label">Только российская символика
                    <span class="gm-hint-icon" data-tooltip="Запрещает в B-roll иностранные флаги, форму, политиков. Рекомендуется не выключать.">?</span>
                </label>
                <input type="checkbox" id="gm-sm-russia" ${savedRussia ? 'checked' : ''}>
            </div>
            <div class="gm-row">
                <label class="gm-label">Дополнительные пожелания к B-roll
                    <span class="gm-hint-icon" data-tooltip="Свободный текст: «больше документов», «избегать оружия» и т.п. Передаётся LLM как подсказка.">?</span>
                </label>
                <textarea id="gm-sm-extra" class="gm-input" rows="2" maxlength="300"
                    placeholder="Например: больше архивных документов и работы за столом">${savedExtra}</textarea>
            </div>
        </div>

        <div class="gm-row">
            <label class="gm-label">Remove Silence
                <span class="gm-hint-icon" data-tooltip="Удаляет паузы из видео. Natural — мягко, Fast — агрессивно, Extra-fast — максимально.">?</span>
            </label>
            <select id="gm-sm-silence" class="gm-select">
                <option value="" ${!savedSilence ? 'selected' : ''}>Отключено</option>
                <option value="natural" ${savedSilence==='natural' ? 'selected' : ''}>Natural (мягко)</option>
                <option value="fast" ${savedSilence==='fast' ? 'selected' : ''}>Fast (быстро)</option>
                <option value="extra-fast" ${savedSilence==='extra-fast' ? 'selected' : ''}>Extra-fast (максимально)</option>
            </select>
        </div>
        <div class="gm-row gm-row--inline">
            <label class="gm-label">Remove Bad Takes
                <span class="gm-hint-icon" data-tooltip="ИИ анализирует видео и удаляет неудачные дубли и паузы.">?</span>
            </label>
            <input type="checkbox" id="gm-sm-bad-takes" ${savedBadTakes ? 'checked' : ''}>
        </div>
        <div class="gm-row gm-row--inline">
            <label class="gm-label">Clean Audio
                <span class="gm-hint-icon" data-tooltip="ИИ убирает фоновые шумы из аудиодорожки видео.">?</span>
            </label>
            <input type="checkbox" id="gm-sm-clean" ${savedClean ? 'checked' : ''}>
        </div>
        </div><!-- /gm-svc-submagic -->

        <!-- ═════════ CREATOMATE PANEL ═════════ -->
        <div id="gm-svc-creatomate" style="display:${isCreatomate ? '' : 'none'}">
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Формат видео
                        <span class="gm-hint-icon" data-tooltip="9:16 — для Reels/Shorts/TikTok. 16:9 — YouTube. 1:1 — Instagram квадрат. 4:5 — Instagram портрет.">?</span>
                    </label>
                    <select id="gm-ct-format" class="gm-select">
                        <option value="9:16" ${ctFormat==='9:16'?'selected':''}>9:16 — Reels/Shorts (1080×1920)</option>
                        <option value="16:9" ${ctFormat==='16:9'?'selected':''}>16:9 — YouTube (1920×1080)</option>
                        <option value="1:1"  ${ctFormat==='1:1' ?'selected':''}>1:1 — Instagram (1080×1080)</option>
                        <option value="4:5"  ${ctFormat==='4:5' ?'selected':''}>4:5 — IG портрет (1080×1350)</option>
                    </select>
                </div>
                <div>
                    <label class="gm-label">FPS
                        <span class="gm-hint-icon" data-tooltip="Кадров в секунду. 30 — стандарт. 60 — плавнее, но в 2 раза дороже.">?</span>
                    </label>
                    <select id="gm-ct-fps" class="gm-select">
                        <option value="24" ${ctFps==='24'?'selected':''}>24 fps (киношный)</option>
                        <option value="25" ${ctFps==='25'?'selected':''}>25 fps</option>
                        <option value="30" ${ctFps==='30'?'selected':''}>30 fps (стандарт)</option>
                        <option value="60" ${ctFps==='60'?'selected':''}>60 fps (плавный, дороже)</option>
                    </select>
                </div>
            </div>

            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Стиль субтитров
                        <span class="gm-hint-icon" data-tooltip="Визуальный пресет: шрифт, цвет, обводка, фон. Hormozi — viral-стиль, армейский — зелёный фон.">?</span>
                    </label>
                    <select id="gm-ct-sub-preset" class="gm-select">
                        <option value="hormozi_white"  ${ctSubPreset==='hormozi_white' ?'selected':''}>Hormozi (белый, обводка)</option>
                        <option value="hormozi_yellow" ${ctSubPreset==='hormozi_yellow'?'selected':''}>Hormozi (жёлтый акцент)</option>
                        <option value="army_green"     ${ctSubPreset==='army_green'    ?'selected':''}>Армейский (зелёный фон)</option>
                        <option value="minimal_dark"   ${ctSubPreset==='minimal_dark'  ?'selected':''}>Минимал (тёмный фон)</option>
                        <option value="tiktok_white"   ${ctSubPreset==='tiktok_white'  ?'selected':''}>TikTok (белый)</option>
                    </select>
                </div>
                <div>
                    <label class="gm-label">Эффект слов
                        <span class="gm-hint-icon" data-tooltip="Karaoke — последовательная подсветка. Highlight — выделение текущего. Color — смена цвета.">?</span>
                    </label>
                    <select id="gm-ct-sub-effect" class="gm-select">
                        <option value="karaoke"   ${ctSubEffect==='karaoke'  ?'selected':''}>Karaoke (бегущая подсветка)</option>
                        <option value="highlight" ${ctSubEffect==='highlight'?'selected':''}>Highlight (выделение)</option>
                        <option value="color"     ${ctSubEffect==='color'    ?'selected':''}>Color (смена цвета)</option>
                        <option value="bounce"    ${ctSubEffect==='bounce'   ?'selected':''}>Bounce (анимация)</option>
                    </select>
                </div>
            </div>

            <div class="gm-row">
                <label class="gm-label">Разбиение субтитров
                    <span class="gm-hint-icon" data-tooltip="Word — по одному слову. Line — целыми строками. Word — лучше для viral-стиля.">?</span>
                </label>
                <select id="gm-ct-sub-split" class="gm-select">
                    <option value="word" ${ctSubSplit==='word'?'selected':''}>По словам</option>
                    <option value="line" ${ctSubSplit==='line'?'selected':''}>По строкам</option>
                </select>
            </div>

            <!-- ── B-roll selector ── -->
            <div class="gm-row">
                <label class="gm-label">Источник B-roll
                    <span class="gm-hint-icon" data-tooltip="Выберите откуда брать видео-вставки. Стоки бесплатны, но менее тематичны. AI-генерация дороже, но даёт уникальные сцены.">?</span>
                </label>
                <select id="gm-ct-broll-prov" class="gm-select" onchange="_onCtBrollProviderChange(this.value)">
                    <option value="off"             ${ctBrollProv==='off'?'selected':''}>Без B-roll вставок</option>
                    <optgroup label="Стоковые сервисы (бесплатно)">
                        <option value="pexels"          ${ctBrollProv==='pexels'?'selected':''}>Pexels</option>
                        <option value="pixabay"         ${ctBrollProv==='pixabay'?'selected':''}>Pixabay</option>
                        <option value="pexels_pixabay"  ${ctBrollProv==='pexels_pixabay'?'selected':''}>Pexels + Pixabay (fallback)</option>
                    </optgroup>
                    <optgroup label="AI-генерация видео (платно)">
                        <option value="veo"    ${ctBrollProv==='veo'?'selected':''}>Google Veo (~$0.50/клип)</option>
                        <option value="runway" ${ctBrollProv==='runway'?'selected':''}>Runway Gen-4 (~$0.25/клип)</option>
                        <option value="luma"   ${ctBrollProv==='luma'?'selected':''}>Luma Dream Machine (~$0.20/клип)</option>
                    </optgroup>
                </select>
            </div>

            <div id="gm-ct-broll-fields" style="display:${showCtBroll ? '' : 'none'}">
                <div class="gm-row">
                    <label class="gm-label">Режим B-roll вставки
                        <span class="gm-hint-icon" data-tooltip="Overlay — B-roll на весь экран (спикер скрывается). PIP — маленькое окно в углу (спикер виден). Split — экран делится пополам: спикер слева, B-roll справа.">?</span>
                    </label>
                    <select id="gm-ct-broll-layout" class="gm-select">
                        <option value="overlay" ${ctBrollLayout==='overlay'?'selected':''}>Overlay — на весь экран</option>
                        <option value="pip"     ${ctBrollLayout==='pip'    ?'selected':''}>PIP — окно в углу</option>
                        <option value="split"   ${ctBrollLayout==='split'  ?'selected':''}>Split — пополам</option>
                    </select>
                </div>
                <div class="gm-row gm-row--2">
                    <div>
                        <label class="gm-label">Плотность B-roll
                            <span class="gm-hint-icon" data-tooltip="Низкая — 1 на 30 с, Средняя — 1 на 15 с, Высокая — 1 на 9 с, Очень высокая — 1 на 6 с.">?</span>
                        </label>
                        <select id="gm-ct-broll-dens" class="gm-select">
                            <option value="low"       ${ctBrollDens==='low'?'selected':''}>Низкая</option>
                            <option value="medium"    ${ctBrollDens==='medium'?'selected':''}>Средняя</option>
                            <option value="high"      ${ctBrollDens==='high'?'selected':''}>Высокая</option>
                            <option value="very_high" ${ctBrollDens==='very_high'?'selected':''}>Очень высокая</option>
                        </select>
                    </div>
                    <div>
                        <label class="gm-label">Длительность вставки
                            <span class="gm-hint-icon" data-tooltip="Максимум секунд на одну B-roll. Короче = динамичнее.">?</span>
                        </label>
                        <select id="gm-ct-broll-dur" class="gm-select">
                            <option value="3"  ${ctBrollDur==='3'?'selected':''}>3 с (клиповый)</option>
                            <option value="4"  ${ctBrollDur==='4'?'selected':''}>4 с (быстрый)</option>
                            <option value="5"  ${ctBrollDur==='5'?'selected':''}>5 с (стандарт)</option>
                            <option value="7"  ${ctBrollDur==='7'?'selected':''}>7 с (плавный)</option>
                            <option value="10" ${ctBrollDur==='10'?'selected':''}>10 с (длинный)</option>
                        </select>
                    </div>
                </div>
                <div class="gm-row gm-row--2">
                    <div>
                        <label class="gm-label">Тематика
                            <span class="gm-hint-icon" data-tooltip="Подсказка LLM для генерации поисковых запросов / визуальных промптов.">?</span>
                        </label>
                        <select id="gm-ct-broll-topic" class="gm-select">
                            <option value="auto"    ${ctBrollTopic==='auto'?'selected':''}>Авто (по тексту)</option>
                            <option value="law"     ${ctBrollTopic==='law'?'selected':''}>Военное право</option>
                            <option value="army"    ${ctBrollTopic==='army'?'selected':''}>Армия</option>
                            <option value="medical" ${ctBrollTopic==='medical'?'selected':''}>Медкомиссия</option>
                            <option value="process" ${ctBrollTopic==='process'?'selected':''}>Юридический процесс</option>
                            <option value="general" ${ctBrollTopic==='general'?'selected':''}>Общая</option>
                        </select>
                    </div>
                    <div>
                        <label class="gm-label">LLM для генерации
                            <span class="gm-hint-icon" data-tooltip="Модель, которая будет генерировать поисковые запросы / визуальные промпты для каждой вставки.">?</span>
                        </label>
                        <select id="gm-ct-broll-llm" class="gm-select">
                            <option value="gemini-flash-latest" ${ctBrollLlm==='gemini-flash-latest'?'selected':''}>Gemini Flash (быстро)</option>
                            <option value="gemini-pro-latest"   ${ctBrollLlm==='gemini-pro-latest'?'selected':''}>Gemini Pro (качественнее)</option>
                        </select>
                    </div>
                </div>
                <div class="gm-row gm-row--inline">
                    <label class="gm-label">Только российская символика
                        <span class="gm-hint-icon" data-tooltip="Запрещает в B-roll иностранные флаги, форму, политиков. Рекомендуется не выключать.">?</span>
                    </label>
                    <input type="checkbox" id="gm-ct-broll-ru" ${ctBrollRu ? 'checked' : ''}>
                </div>
                <div id="gm-ct-stock-fields" style="display:${showCtStock ? '' : 'none'}">
                    <p class="gm-hint">Стоковые сервисы бесплатны, но иногда выдают неподходящие клипы. Если ничего не найдено — слот пропускается.</p>
                </div>
                <div id="gm-ct-ai-fields" style="display:${showCtAi ? '' : 'none'}">
                    <p class="gm-hint" style="color:#dc2626;"><i class="fas fa-info-circle"></i> Внимание: AI-генерация занимает 30–120 с на клип. Стоимость будет добавлена к финальной цене.</p>
                </div>
                <div class="gm-row">
                    <label class="gm-label">Дополнительные пожелания
                        <span class="gm-hint-icon" data-tooltip="Свободный текст: «больше документов», «избегать оружия» и т.п. Передаётся LLM.">?</span>
                    </label>
                    <textarea id="gm-ct-broll-extra" class="gm-input" rows="2" maxlength="300"
                        placeholder="Например: больше архивных документов и работы за столом">${ctBrollExtra}</textarea>
                </div>
            </div>

            <!-- ── Музыка ── -->
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Фоновая музыка (URL)
                        <span class="gm-hint-icon" data-tooltip="Прямая ссылка на mp3/wav. Оставьте пустым, чтобы не добавлять музыку.">?</span>
                    </label>
                    <input type="text" id="gm-ct-music" class="gm-input" value="${ctMusicUrl}"
                        placeholder="https://...mp3">
                </div>
                <div>
                    <label class="gm-label">Громкость музыки (%)
                        <span class="gm-hint-icon" data-tooltip="10–40% — рекомендованный фон, не заглушает речь.">?</span>
                    </label>
                    <input type="number" id="gm-ct-music-vol" class="gm-input" value="${ctMusicVol}" min="0" max="100">
                </div>
            </div>

            <!-- ── Intro/Outro ── -->
            <div class="gm-row">
                <label class="gm-label">Текст intro (опц.)
                    <span class="gm-hint-icon" data-tooltip="Заставка в начале видео (2 с) с этим текстом.">?</span>
                </label>
                <input type="text" id="gm-ct-intro" class="gm-input" value="${ctIntroTxt}"
                    placeholder="Например: АРМЕЙКА НЭТ">
            </div>
            <div class="gm-row">
                <label class="gm-label">Текст outro (опц.)
                    <span class="gm-hint-icon" data-tooltip="Финальная заставка (2.5 с) с CTA.">?</span>
                </label>
                <input type="text" id="gm-ct-outro" class="gm-input" value="${ctOutroTxt}"
                    placeholder="Подписывайтесь и будьте свободны с Армейка Нэт">
            </div>

            <!-- ── Watermark ── -->
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Логотип (URL)
                        <span class="gm-hint-icon" data-tooltip="Постоянный водяной знак в углу. Прямая ссылка на PNG (с прозрачностью).">?</span>
                    </label>
                    <input type="text" id="gm-ct-wm" class="gm-input" value="${ctWatermark}"
                        placeholder="https://...png">
                </div>
                <div>
                    <label class="gm-label">Положение
                        <span class="gm-hint-icon" data-tooltip="Угол экрана для логотипа.">?</span>
                    </label>
                    <select id="gm-ct-wm-pos" class="gm-select">
                        <option value="top-right"    ${ctWmPos==='top-right'?'selected':''}>Сверху справа</option>
                        <option value="top-left"     ${ctWmPos==='top-left'?'selected':''}>Сверху слева</option>
                        <option value="bottom-right" ${ctWmPos==='bottom-right'?'selected':''}>Снизу справа</option>
                        <option value="bottom-left"  ${ctWmPos==='bottom-left'?'selected':''}>Снизу слева</option>
                    </select>
                </div>
            </div>

            <!-- ── Цветокор ── -->
            <div class="gm-row gm-row--2">
                <div>
                    <label class="gm-label">Цветокор
                        <span class="gm-hint-icon" data-tooltip="Простой цветовой фильтр на исходное видео.">?</span>
                    </label>
                    <select id="gm-ct-color" class="gm-select">
                        <option value=""           ${ctColor===''?'selected':''}>Без фильтра</option>
                        <option value="brighten"   ${ctColor==='brighten'?'selected':''}>Brighten (ярче)</option>
                        <option value="contrast"   ${ctColor==='contrast'?'selected':''}>Contrast (контраст)</option>
                        <option value="grayscale"  ${ctColor==='grayscale'?'selected':''}>Grayscale (ч/б)</option>
                        <option value="sepia"      ${ctColor==='sepia'?'selected':''}>Sepia (винтаж)</option>
                    </select>
                </div>
                <div>
                    <label class="gm-label">Интенсивность
                        <span class="gm-hint-icon" data-tooltip="0% — без эффекта, 100% — максимум.">?</span>
                    </label>
                    <input type="text" id="gm-ct-color-val" class="gm-input" value="${ctColorVal}" placeholder="20%">
                </div>
            </div>
        </div><!-- /gm-svc-creatomate -->
        `;
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
    } else if (type === 'montage') {
        const svcInput = document.querySelector('input[name="gm-sm-service"]:checked');
        const service = svcInput?.value || 'submagic';

        if (service === 'creatomate') {
            return {
                service: 'creatomate',
                video_format:      g('gm-ct-format')?.value || '9:16',
                fps:               parseInt(g('gm-ct-fps')?.value || '30'),
                subtitle_preset:   g('gm-ct-sub-preset')?.value || 'hormozi_white',
                transcript_effect: g('gm-ct-sub-effect')?.value || 'karaoke',
                transcript_split:  g('gm-ct-sub-split')?.value || 'word',
                music_url:         g('gm-ct-music')?.value || '',
                music_volume_pct:  parseInt(g('gm-ct-music-vol')?.value || '25'),
                broll_provider:    g('gm-ct-broll-prov')?.value || 'off',
                broll_layout:      g('gm-ct-broll-layout')?.value || 'overlay',
                broll_density:     g('gm-ct-broll-dens')?.value || 'medium',
                broll_clip_duration: parseInt(g('gm-ct-broll-dur')?.value || '5'),
                broll_topic:       g('gm-ct-broll-topic')?.value || 'auto',
                broll_extra_prompt:g('gm-ct-broll-extra')?.value || '',
                broll_llm_model:   g('gm-ct-broll-llm')?.value || 'gemini-flash-latest',
                broll_russia_only: g('gm-ct-broll-ru')?.checked ?? true,
                intro_text:        g('gm-ct-intro')?.value || '',
                outro_text:        g('gm-ct-outro')?.value || '',
                watermark_url:     g('gm-ct-wm')?.value || '',
                watermark_position:g('gm-ct-wm-pos')?.value || 'top-right',
                color_filter:      g('gm-ct-color')?.value || '',
                color_filter_value:g('gm-ct-color-val')?.value || '20%',
            };
        }

        // Submagic
        const modeInput = document.querySelector('input[name="gm-sm-mode"]:checked');
        const mode = modeInput?.value || 'auto';
        const common = {
            service: 'submagic',
            mode,
            template_name: g('gm-sm-template')?.value || 'Hormozi 2',
            magic_zooms: g('gm-sm-zooms')?.checked ?? true,
            remove_silence_pace: g('gm-sm-silence')?.value || null,
            remove_bad_takes: g('gm-sm-bad-takes')?.checked ?? false,
            clean_audio: g('gm-sm-clean')?.checked ?? false,
        };
        if (mode === 'smart') {
            return {
                ...common,
                magic_brolls: false,
                magic_brolls_pct: 0,
                broll_source:  g('gm-sm-broll-src')?.value || 'ai',
                broll_generator_model: g('gm-sm-gen-model')?.value || null,
                density:       g('gm-sm-density')?.value || 'medium',
                clip_duration: parseInt(g('gm-sm-clip-dur')?.value || '5'),
                topic_hint:    g('gm-sm-topic')?.value || 'auto',
                layout:        g('gm-sm-layout')?.value || 'cover',
                russia_only:   g('gm-sm-russia')?.checked ?? true,
                extra_prompt:  g('gm-sm-extra')?.value || '',
                llm_model:     g('gm-sm-llm')?.value || 'gemini-flash-latest',
            };
        }
        return {
            ...common,
            magic_brolls: g('gm-sm-brolls')?.checked ?? false,
            magic_brolls_pct: parseInt(g('gm-sm-broll-pct')?.value || '50'),
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
    if (type === 'montage') {
        localStorage.setItem('mtgService',     params.service || 'submagic');

        if (params.service === 'creatomate') {
            localStorage.setItem('ctFormat',      params.video_format || '9:16');
            localStorage.setItem('ctFps',         String(params.fps || 30));
            localStorage.setItem('ctSubPreset',   params.subtitle_preset || 'hormozi_white');
            localStorage.setItem('ctSubEffect',   params.transcript_effect || 'karaoke');
            localStorage.setItem('ctSubSplit',    params.transcript_split || 'word');
            localStorage.setItem('ctMusicUrl',    params.music_url || '');
            localStorage.setItem('ctMusicVol',    String(params.music_volume_pct || 25));
            localStorage.setItem('ctIntroText',   params.intro_text || '');
            localStorage.setItem('ctOutroText',   params.outro_text || '');
            localStorage.setItem('ctWatermark',   params.watermark_url || '');
            localStorage.setItem('ctWmPos',       params.watermark_position || 'top-right');
            localStorage.setItem('ctColor',       params.color_filter || '');
            localStorage.setItem('ctColorVal',    params.color_filter_value || '20%');
            localStorage.setItem('ctBrollProv',   params.broll_provider || 'off');
            localStorage.setItem('ctBrollLayout', params.broll_layout || 'overlay');
            localStorage.setItem('ctBrollDens',   params.broll_density || 'medium');
            localStorage.setItem('ctBrollDur',    String(params.broll_clip_duration || 5));
            localStorage.setItem('ctBrollTopic',  params.broll_topic || 'auto');
            localStorage.setItem('ctBrollExtra',  params.broll_extra_prompt || '');
            localStorage.setItem('ctBrollLlm',    params.broll_llm_model || 'gemini-flash-latest');
            localStorage.setItem('ctBrollRu',     params.broll_russia_only ? 'true' : 'false');
            return;
        }

        localStorage.setItem('smMode',         params.mode || 'auto');
        localStorage.setItem('smTemplate',     params.template_name || 'Hormozi 2');
        localStorage.setItem('smZooms',        params.magic_zooms ? 'true' : 'false');
        localStorage.setItem('smBrolls',       params.magic_brolls ? 'true' : 'false');
        localStorage.setItem('smBrollPct',     String(params.magic_brolls_pct || 50));
        localStorage.setItem('smSilence',      params.remove_silence_pace || '');
        localStorage.setItem('smBadTakes',     params.remove_bad_takes ? 'true' : 'false');
        localStorage.setItem('smCleanAudio',   params.clean_audio ? 'true' : 'false');
        if (params.mode === 'smart') {
            localStorage.setItem('smSmartBrollSrc', params.broll_source || 'ai');
            if (params.broll_generator_model) localStorage.setItem('smSmartGenModel', params.broll_generator_model);
            localStorage.setItem('smSmartDensity', params.density || 'medium');
            localStorage.setItem('smSmartClipDur', String(params.clip_duration || 5));
            localStorage.setItem('smSmartTopic',   params.topic_hint || 'auto');
            localStorage.setItem('smSmartLayout',  params.layout || 'cover');
            localStorage.setItem('smSmartRussia',  params.russia_only ? 'true' : 'false');
            localStorage.setItem('smSmartExtra',   params.extra_prompt || '');
            localStorage.setItem('smSmartLlm',     params.llm_model || 'gemini-flash-latest');
        }
    }
}

/* ── SSE генерация узла (метод класса ResultTree) ──────────────────────── */
ResultTree.prototype.generateNode = async function(parentNodeId, targetType, params) {
    const slug = this.slug;
    const url  = `/api/tree/${slug}/node/${parentNodeId}/generate`;

    // Step 1: POST — немедленно получаем данные созданного узла (node_created)
    let resp;
    try {
        resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_type: targetType, params }),
        });
    } catch (e) {
        alert('Ошибка сети при запуске генерации');
        return;
    }

    if (!resp.ok) {
        let errMsg = 'Ошибка запуска генерации';
        try { const j = await resp.json(); errMsg = j.message || errMsg; } catch {}
        alert(errMsg);
        return;
    }

    const data = await resp.json();

    if (data.step === 'error') {
        alert('Ошибка: ' + (data.message || 'неизвестная ошибка'));
        return;
    }

    // Step 2: Вставляем узел немедленно — он появляется в дереве сразу
    const node = data.node;
    const nodeId = node.node_id;
    this.insertNode(node);
    if (!this.expanded.has(parentNodeId)) this.toggle(parentNodeId);

    // Step 3: Открываем EventSource для получения прогресса и финального обновления
    const es = new EventSource(`/api/tree/node/${nodeId}/stream`);

    es.onmessage = (e) => {
        try {
            const evt = JSON.parse(e.data);

            if (evt.step === 'done' && evt.node) {
                this.updateNode(evt.node);
                this.expanded.add(evt.node.node_id);
                this._saveExpanded();
                if (!this.expanded.has(evt.node.node_id)) this.toggle(evt.node.node_id);
                es.close();
                this._pollers.delete(nodeId);

            } else if (evt.step === 'error') {
                console.error('Tree generate error:', evt.message);
                const n = this.nodesMap.get(nodeId);
                if (n) { n.status = 'failed'; this.updateNode(n); }
                alert('Ошибка генерации: ' + evt.message);
                es.close();
            } else if (evt.warning) {
                // Нефатальное предупреждение (напр. B-roll не получен)
                console.warn('Tree warning:', evt.warning);
                this._showWarningToast(evt.warning);
            }
            // Промежуточные step-события (статус) можно использовать для обновления спиннера
        } catch (err) { /* ignore parse errors */ }
    };

    es.onerror = () => {
        // При ошибке соединения — закрываем ES, поллинг подхватит оставшееся
        es.close();
    };
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
        const HIDDEN_KEYS = new Set(['v1', 'v2', 'evaluation']);
        _treeStep3Prompts = Object.fromEntries(
            Object.entries(pm.prompts?.step3 || {}).filter(([k]) => !HIDDEN_KEYS.has(k))
        );
    } catch (e) { console.warn('Не удалось загрузить промпты:', e); }

    try {
        const sm = await fetch('/api/submagic/templates').then(r => r.json());
        _submagicTemplates = sm.templates || [];
    } catch (e) { console.warn('Не удалось загрузить Submagic шаблоны:', e); }

    _tree = new ResultTree(slug);
    window._tree = _tree;
    await _tree.init(container);
}
