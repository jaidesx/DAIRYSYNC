


/* ===========================
   1. TOAST SYSTEM
=========================== */

const Toast = (() => {
    let container = null;

    const icons = {
        success: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
        error:   `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        warning: `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        info:    `<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    };

    function getContainer() {
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            document.body.appendChild(container);
        }
        return container;
    }

    function show({ type = 'info', title, message, duration = 4000 }) {
        const c = getContainer();

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        toast.innerHTML = `
            ${icons[type] || icons.info}
            <div class="toast-body">
                ${title ? `<div class="toast-title">${title}</div>` : ''}
                ${message ? `<div class="toast-message">${message}</div>` : ''}
            </div>
            <button class="toast-close" aria-label="Dismiss">&times;</button>
            <div class="toast-progress" style="animation-duration: ${duration}ms;"></div>
        `;

        c.appendChild(toast);

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', () => dismiss(toast));

        // Auto dismiss
        const timer = setTimeout(() => dismiss(toast), duration);

        // Pause progress on hover
        toast.addEventListener('mouseenter', () => {
            clearTimeout(timer);
            toast.querySelector('.toast-progress').style.animationPlayState = 'paused';
        });

        toast.addEventListener('mouseleave', () => {
            toast.querySelector('.toast-progress').style.animationPlayState = 'running';
            setTimeout(() => dismiss(toast), 1500);
        });

        return toast;
    }

    function dismiss(toast) {
        if (!toast || !toast.parentNode) return;
        toast.classList.add('toast-exit');
        toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }

    // Shorthand methods
    return {
        show,
        success: (title, message, duration) => show({ type: 'success', title, message, duration }),
        error:   (title, message, duration) => show({ type: 'error',   title, message, duration }),
        warning: (title, message, duration) => show({ type: 'warning', title, message, duration }),
        info:    (title, message, duration) => show({ type: 'info',    title, message, duration }),
    };
})();


/* ===========================
   2. PAGE LOADER BAR
=========================== */

const PageLoader = (() => {
    let bar = null;

    function create() {
        if (!bar) {
            bar = document.createElement('div');
            bar.className = 'page-loader';
            document.body.appendChild(bar);
        }
        return bar;
    }

    function start() {
        const b = create();
        b.className = 'page-loader loading';
    }

    function done() {
        const b = create();
        b.className = 'page-loader done';
        setTimeout(() => { b.className = 'page-loader'; }, 700);
    }

    return { start, done };
})();


/* ===========================
   3. SKELETON HELPERS
=========================== */

const Skeleton = {
    // Replace a table body with N skeleton rows
    injectTableRows(tbodySelector, cols = 5, rows = 5) {
        const tbody = document.querySelector(tbodySelector);
        if (!tbody) return;

        const widths = ['60%', '80%', '50%', '70%', '45%'];
        let html = '';

        for (let r = 0; r < rows; r++) {
            html += '<tr class="skeleton-table-row" style="display:table-row">';
            for (let c = 0; c < cols; c++) {
                const w = widths[c % widths.length];
                html += `<td style="padding:14px 16px;border-bottom:1px solid #f3f4f6">
                    <span class="skeleton skeleton-text" style="width:${w};display:block"></span>
                </td>`;
            }
            html += '</tr>';
        }

        tbody.innerHTML = html;
    },

    // Replace a cards container with skeleton cards
    injectCards(containerSelector, count = 4) {
        const container = document.querySelector(containerSelector);
        if (!container) return;

        let html = '';
        for (let i = 0; i < count; i++) {
            html += `
            <div class="skeleton-card">
                <div class="skeleton-card-row">
                    <span class="skeleton skeleton-circle skeleton-card-icon"></span>
                    <span class="skeleton skeleton-text med" style="flex:1;display:block"></span>
                </div>
                <span class="skeleton" style="height:32px;width:60%;display:block;margin-bottom:8px;border-radius:6px"></span>
                <span class="skeleton skeleton-text short" style="display:block"></span>
            </div>`;
        }
        container.innerHTML = html;
    },

    // Remove skeleton rows and show real content
    remove(selector) {
        document.querySelectorAll(`${selector} .skeleton-table-row`).forEach(el => el.remove());
    }
};


/* ===========================
   4. FORM VALIDATION ENGINE
=========================== */

const FormValidator = {
    rules: {
        required:  (val)       => val.trim() !== ''             || 'This field is required.',
        minLength: (val, n)    => val.length >= n               || `Minimum ${n} characters.`,
        maxLength: (val, n)    => val.length <= n               || `Maximum ${n} characters.`,
        email:     (val)       => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val) || 'Enter a valid email address.',
        number:    (val)       => !isNaN(val) && val !== ''     || 'Must be a number.',
        positive:  (val)       => parseFloat(val) > 0           || 'Must be greater than zero.',
        pattern:   (val, rgx)  => rgx.test(val)                 || 'Invalid format.',
    },

    // Validate a single .field div
    validateField(fieldEl) {
        const input = fieldEl.querySelector('input, select, textarea');
        const errorEl   = fieldEl.querySelector('.field-error');
        const successEl = fieldEl.querySelector('.field-success');
        if (!input) return true;

        const rulesAttr  = input.dataset.validate || '';
        const customMsg  = input.dataset.errorMsg  || '';
        const successMsg = input.dataset.successMsg || 'Looks good!';
        const val        = input.value;

        let errorMsg = null;

        rulesAttr.split('|').forEach(rule => {
            if (errorMsg) return;
            const [name, ...args] = rule.split(':');
            const fn = this.rules[name];
            if (!fn) return;

            const result = fn(val, args[0] ? (isNaN(args[0]) ? new RegExp(args[0]) : Number(args[0])) : undefined);
            if (result !== true) {
                errorMsg = customMsg || result;
            }
        });

        if (errorMsg) {
            fieldEl.classList.add('invalid');
            fieldEl.classList.remove('valid');
            if (errorEl)   errorEl.textContent = errorMsg;
            if (successEl) successEl.style.display = 'none';
            return false;
        } else {
            fieldEl.classList.remove('invalid');
            if (val.trim()) {
                fieldEl.classList.add('valid');
                if (successEl) successEl.textContent = successMsg;
            }
            return true;
        }
    },

    // Attach live validation to a form
    attachTo(formSelector) {
        const form = document.querySelector(formSelector);
        if (!form) return;

        const fields = form.querySelectorAll('.field');

        fields.forEach(fieldEl => {
            const input = fieldEl.querySelector('input, select, textarea');
            if (!input) return;

            // Validate on blur
            input.addEventListener('blur', () => this.validateField(fieldEl));

            // Clear invalid on input
            input.addEventListener('input', () => {
                if (fieldEl.classList.contains('invalid')) {
                    this.validateField(fieldEl);
                }
            });
        });

        // Validate all on submit
        form.addEventListener('submit', (e) => {
            let allValid = true;
            fields.forEach(fieldEl => {
                if (!this.validateField(fieldEl)) allValid = false;
            });

            if (!allValid) {
                e.preventDefault();
                // Scroll to first error
                const firstErr = form.querySelector('.field.invalid');
                if (firstErr) firstErr.scrollIntoView({ behavior: 'smooth', block: 'center' });

                Toast.error('Please fix the errors below', 'Check the highlighted fields and try again.');
                return;
            }

            // Show loading state on submit button
            const btn = form.querySelector('.submit-btn');
            if (btn) {
                btn.classList.add('loading');
                btn.disabled = true;
            }
        });
    },

    // Validate entire form and return bool (manual check)
    validate(formSelector) {
        const form = document.querySelector(formSelector);
        if (!form) return true;
        let allValid = true;
        form.querySelectorAll('.field').forEach(f => {
            if (!this.validateField(f)) allValid = false;
        });
        return allValid;
    }
};


/* ===========================
   5. DJANGO MESSAGE → TOAST
   Auto-converts Django messages
   rendered in .django-messages
   into toasts on page load
=========================== */

function initDjangoMessageToasts() {
    const container = document.getElementById('django-messages-data');
    if (!container) return;

    const messages = container.querySelectorAll('[data-message]');
    messages.forEach((el, i) => {
        const text = el.dataset.message;
        const tags = el.dataset.tags || 'info';

        let type = 'info';
        if (tags.includes('success')) type = 'success';
        else if (tags.includes('error'))   type = 'error';
        else if (tags.includes('warning')) type = 'warning';

        const titles = {
            success: 'Success',
            error:   'Error',
            warning: 'Warning',
            info:    'Notice',
        };

        setTimeout(() => {
            Toast.show({ type, title: titles[type], message: text });
        }, i * 300);
    });
}


/* ===========================
   6. DELETE CONFIRMATION
   Better than browser confirm()
=========================== */

function confirmAction(message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.style.cssText = `
        position:fixed;inset:0;background:rgba(0,0,0,0.5);
        z-index:9998;display:flex;align-items:center;justify-content:center;
        animation:fadeIn 0.15s ease;
    `;

    overlay.innerHTML = `
        <div style="
            background:#fff;border-radius:14px;padding:28px 28px 22px;
            max-width:380px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.25);
        ">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
                <div style="width:40px;height:40px;background:#fee2e2;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                    </svg>
                </div>
                <div>
                    <div style="font-size:15px;font-weight:bold;color:#111827">Confirm Delete</div>
                    <div style="font-size:13px;color:#6b7280;margin-top:2px">This action cannot be undone</div>
                </div>
            </div>
            <p style="font-size:14px;color:#374151;margin-bottom:20px;line-height:1.5">${message}</p>
            <div style="display:flex;gap:10px;justify-content:flex-end">
                <button id="confirm-cancel" style="
                    padding:9px 18px;border-radius:8px;border:1px solid #d1d5db;
                    background:#fff;color:#374151;font-size:13px;cursor:pointer;font-family:inherit;
                ">Cancel</button>
                <button id="confirm-ok" style="
                    padding:9px 18px;border-radius:8px;border:none;
                    background:#dc2626;color:#fff;font-size:13px;font-weight:bold;cursor:pointer;font-family:inherit;
                ">Delete</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    overlay.querySelector('#confirm-cancel').addEventListener('click', () => {
        document.body.removeChild(overlay);
        document.body.style.overflow = '';
    });

    overlay.querySelector('#confirm-ok').addEventListener('click', () => {
        document.body.removeChild(overlay);
        document.body.style.overflow = '';
        if (typeof onConfirm === 'function') onConfirm();
    });

    // Close on backdrop click
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            document.body.removeChild(overlay);
            document.body.style.overflow = '';
        }
    });
}


/* ===========================
   INIT ON DOM READY
=========================== */

document.addEventListener('DOMContentLoaded', () => {
    // Show page loader on navigation
    PageLoader.done();

    // Auto-parse Django messages → toasts
    initDjangoMessageToasts();

    // Attach form validation to any form with data-validate-form
    document.querySelectorAll('[data-validate-form]').forEach(form => {
        FormValidator.attachTo(`#${form.id}`);
    });

    // Intercept delete links/forms — replace onclick="return confirm(...)" with modal
    document.querySelectorAll('[data-confirm]').forEach(el => {
        if (el.tagName === 'FORM') {
            // For forms with data-confirm, intercept the submit event
            el.addEventListener('submit', (e) => {
                e.preventDefault();
                const msg = el.dataset.confirm || 'Are you sure you want to delete this?';
                confirmAction(msg, () => { el.submit(); });
            });
        } else {
            // For anchor tags or other clickable elements
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const msg  = el.dataset.confirm || 'Are you sure you want to delete this?';
                const href = el.getAttribute('href');
                if (href && href !== 'null') {
                    confirmAction(msg, () => { window.location.href = href; });
                }
            });
        }
    });

    // Page loader on link navigation
    document.querySelectorAll('a:not([target="_blank"]):not([href^="#"]):not([href^="mailto"])').forEach(link => {
        link.addEventListener('click', () => PageLoader.start());
    });
});
