// tracker.js - backend to choosing the skins you want to track, etc

// variables

const trackedGrid = document.getElementById('tracked-grid');
const skinCard = document.getElementById('skin-card');
const emptyState = document.getElementById('empty-state');
const trackedCount = document.getElementById('tracked-count');

let tracked_skins = [];

// tracked() - fetch all the tracked skins if there are any
async function tracked(){
    let response = await fetch('/api/tracked'); // fetch the tracked skins though not in JSON yet

    if (!response.ok) {
        console.error("could not fetch the tracked skins");
        return;
    }

    tracked_skins = await response.json(); // parse the body to JSON and assign it to "tracked_skins" - needs await, .json() returns a promise

    return tracked_skins;
}

// clear_grid() - clear the entire grid before anything just in case
function clear_grid(){
    trackedGrid.replaceChildren();
}

// render() - main function, it will render absolutely everything
async function render(){
    const skins = await tracked(); // fetch the tracked data, await since tracked() is asynchronous

    if (!skins){ // tracked() returns undefined if the fetch failed, so bail
        console.error("error: something went wrong with tracked() function, stopping rendering");
        return;
    }

    clear_grid(); // clear the grid of previous data

    // loop each skin object, clone the template, fill it, append it to the grid
    for (const skin of skins){
        const card = skinCard.content.cloneNode(true); // deep-clone the <template>'s contents into a fresh card

        card.querySelector('.name').textContent = skin.market_hash_name;      // fill the skin name
        card.querySelector('.buy').textContent  = skin.buy_below  ?? '-';     // null threshold -> dash instead of "null"
        card.querySelector('.sell').textContent = skin.sell_above ?? '-';     // null threshold -> dash instead of "null"

        trackedGrid.append(card); // drop the finished card into the grid
    }
     
}