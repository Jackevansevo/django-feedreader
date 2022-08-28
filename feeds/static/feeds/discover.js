const form = document.getElementById("discoverForm");

form.addEventListener('submit', (event) => {
	document.getElementById('results').innerHTML = "";
	document.getElementById('loading').classList.remove('d-none');
})
