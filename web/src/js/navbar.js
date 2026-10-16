// navbar.js - turns the navbar into a floating pill once you scroll away from the very top

// variables

const navbar = document.getElementById('navbar');
const SCROLL_OFFSET = 8; // how far (px) you need to scroll before the navbar floats, so tiny trackpad nudges don't flicker it

// update_navbar() - add/remove the "scrolled" class depending on where we are on the page, the CSS handles the rest
function update_navbar(){
    navbar.classList.toggle('scrolled', window.scrollY > SCROLL_OFFSET); // true adds it, false removes it
}

window.addEventListener('scroll', update_navbar, { passive: true }); // passive since we never preventDefault, keeps scrolling smooth
update_navbar(); // run once on load, refreshing mid-page keeps your scroll position so the navbar has to match it
