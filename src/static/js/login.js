document.addEventListener('DOMContentLoaded', () => {
    const loginCard = document.querySelector('.login-container.card');
    // const loginBody = document.querySelector('body.login-page'); // No longer needed for background

    // --- Card Tilt Effect --- 
    if (loginCard) {
        const sensitivity = 20; // Lower = more tilt

        loginCard.addEventListener('mousemove', (e) => {
            const rect = loginCard.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = (centerY - y) / sensitivity;
            const rotateY = (x - centerX) / sensitivity;
            loginCard.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.03, 1.03, 1.03)`;
        });

        loginCard.addEventListener('mouseleave', () => {
            loginCard.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale3d(1, 1, 1)';
        });

        loginCard.addEventListener('mouseenter', () => {
             // Optional effect on enter
        });
    }

    // --- Background Gradient Shift Effect (REMOVED) --- 
    /* 
    if (loginBody) { 
        // ... removed variable update logic ... 
    }
    */

    // --- Water Ripple Mouse Effect --- 
    const loginBodyForRipple = document.querySelector('body.login-page');
    if (loginBodyForRipple) {
        let rippleTimeout;
        const RIPPLE_DELAY = 60; // Milliseconds between ripples - slightly slower

        loginBodyForRipple.addEventListener('mousemove', (e) => {
            clearTimeout(rippleTimeout);
            rippleTimeout = setTimeout(() => {
                const ripple = document.createElement('div');
                ripple.className = 'water-ripple'; // Use the new class
                document.body.appendChild(ripple);

                ripple.style.left = `${e.clientX}px`;
                ripple.style.top = `${e.clientY}px`;

                ripple.addEventListener('animationend', () => {
                    ripple.remove();
                });

                // Fallback removal
                setTimeout(() => {
                    if (ripple.parentNode) {
                        ripple.remove();
                    }
                }, 600); // Match animation duration
            }, RIPPLE_DELAY);
        });
    }

}); 