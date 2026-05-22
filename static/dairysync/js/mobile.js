

(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {

        const sidebar  = document.querySelector('.sidebar');
        const main     = document.querySelector('.main');

        if (!sidebar) return;

        /* ── Create hamburger button ── */
        const hamburger = document.createElement('button');
        hamburger.className = 'hamburger';
        hamburger.setAttribute('aria-label', 'Toggle navigation menu');
        hamburger.setAttribute('aria-expanded', 'false');
        hamburger.innerHTML = `
            <span></span>
            <span></span>
            <span></span>
        `;
        document.body.appendChild(hamburger);

        /* ── Create overlay ── */
        const overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.setAttribute('aria-hidden', 'true');
        document.body.appendChild(overlay);

        /* ── State ── */
        let isOpen = false;

        function openSidebar() {
            isOpen = true;
            sidebar.classList.add('open');
            hamburger.classList.add('open');
            overlay.classList.add('visible');
            hamburger.setAttribute('aria-expanded', 'true');
            document.body.style.overflow = 'hidden'; // prevent background scroll
        }

        function closeSidebar() {
            isOpen = false;
            sidebar.classList.remove('open');
            hamburger.classList.remove('open');
            overlay.classList.remove('visible');
            hamburger.setAttribute('aria-expanded', 'false');
            document.body.style.overflow = '';
        }

        function toggleSidebar() {
            isOpen ? closeSidebar() : openSidebar();
        }

        /* ── Hamburger click ── */
        hamburger.addEventListener('click', toggleSidebar);

        /* ── Overlay click closes sidebar ── */
        overlay.addEventListener('click', closeSidebar);

        /* ── Close on nav link click (mobile) ── */
        sidebar.querySelectorAll('a.nav-link, .dropdown-content a').forEach(function (link) {
            link.addEventListener('click', function () {
                if (window.innerWidth <= 900) {
                    closeSidebar();
                }
            });
        });

        /* ── Close if window resized to desktop ── */
        window.addEventListener('resize', function () {
            if (window.innerWidth > 900 && isOpen) {
                closeSidebar();
            }
        });

        /* ── Swipe left on sidebar to close ── */
        let touchStartX = 0;
        let touchStartY = 0;

        sidebar.addEventListener('touchstart', function (e) {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }, { passive: true });

        sidebar.addEventListener('touchend', function (e) {
            const dx = e.changedTouches[0].clientX - touchStartX;
            const dy = Math.abs(e.changedTouches[0].clientY - touchStartY);

            // Only register as a left swipe if mostly horizontal
            if (dx < -60 && dy < 80) {
                closeSidebar();
            }
        }, { passive: true });

        /* ── Swipe right from left edge to open sidebar ── */
        document.addEventListener('touchstart', function (e) {
            if (e.touches[0].clientX < 20) {
                touchStartX = e.touches[0].clientX;
                touchStartY = e.touches[0].clientY;
            }
        }, { passive: true });

        document.addEventListener('touchend', function (e) {
            const dx = e.changedTouches[0].clientX - touchStartX;
            const dy = Math.abs(e.changedTouches[0].clientY - touchStartY);

            if (touchStartX < 20 && dx > 60 && dy < 80 && !isOpen) {
                openSidebar();
            }
        }, { passive: true });

        /* ── Escape key closes sidebar ── */
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && isOpen) {
                closeSidebar();
                hamburger.focus();
            }
        });

    });

})();
