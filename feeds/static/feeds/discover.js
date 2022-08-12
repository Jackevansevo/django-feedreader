const categories = JSON.parse(
  document.getElementById("categories").textContent
);
const form = document.getElementById("discoverForm");
const searchInput = form.elements.namedItem("q");
const resultsSection = document.getElementById("results");

let timer;
let searched;
const waitTime = 250;

const search = (text) => {
	// TODO actually utilize this
	fetch(`/feeds/search?q=${encodeURIComponent(text)}`, {
		method: "GET",
		headers: {
			"Content-Type": "application/json",
		},
	})
		.then((response) => response.json())
		.then((resp) => {
			console.log(resp);
		})
		.catch((err) => console.log(err));
}

form.addEventListener('submit', (event) => {
	document.getElementById('results').innerHTML = "";
	document.getElementById('loading').classList.remove('d-none');
})

searchInput.addEventListener(
  "keyup",
  (event) => {
    if (event.target.value === searched) {
      console.log("nothing to do here");
      return;
    }

		clearTimeout(timer);

		timer = setTimeout(() => {
			searched = event.target.value;
			search(event.target.value);
		}, waitTime);

  },
);
