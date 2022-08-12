const categories = JSON.parse(
  document.getElementById("categories").textContent
);
const form = document.getElementById("subscriptionCreateForm");
const urlInput = form.elements.namedItem("url");
const resultsSection = document.getElementById("results");

let searched = undefined;

urlInput.addEventListener(
  "blur",
  (event) => {
    if (event.target.value === searched) {
      console.log("nothing to do here");
      return;
    }

    resultsSection.innerHTML = "";

    if (event.target.value === "") {
      return;
    }

    let spinnerContainer = document.createElement("div");
    spinnerContainer.classList.add(
      "d-flex",
      "justify-content-center",
      "pt-5",
      "mt-5"
    );

    let spinner = document.createElement("div");
    spinner.classList.add("spinner-border");

    spinnerContainer.appendChild(spinner);

    let spinnerHelp = document.createElement("span");
    spinnerHelp.classList.add("visually-hidden");
    spinnerHelp.innerHTML = "Loading...";

    spinner.appendChild(spinnerHelp);

    resultsSection.appendChild(spinnerContainer);

    resultsSection.classList.remove("d-none");

    // TODO: Show some sort of spinner whilst awaiting a response from search?

    fetch(`/feeds/search?q=${encodeURIComponent(event.target.value)}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
      },
    })
      .then((response) => response.json())
      .then((resp) => {
        searched = event.target.value;

        resultsSection.innerHTML = "";

        for (feed of resp) {
          let resultCard = document.createElement("div");
          resultCard.classList.add("card");

          let cardBody = document.createElement("div");
          cardBody.classList.add("card-body");

          resultCard.appendChild(cardBody);

          let title = document.createElement("h5");
          title.classList.add("card-title");
          title.innerHTML = feed.title;

          let feedLink = document.createElement("a");
          feedLink.classList.add("text-decoration-none");
          feedLink.setAttribute("href", feed.links["internal"]);
          feedLink.appendChild(title);

          let subtitle = document.createElement("h6");
          subtitle.classList.add("card-subtitle", "mb-2", "text-muted");
          subtitle.innerHTML = feed.subtitle;

          let linkElement = document.createElement("a");
          linkElement.classList.add("card-link", "text-decoration-none");
          linkElement.setAttribute("href", feed.links["external"]);
          linkElement.innerHTML = feed.links["external"].replace(
            /(^\w+:|^)\/\//,
            ""
          );

          let actionButton = undefined;

          if (feed.subscribed) {
            actionButton = document.createElement("button");
            actionButton.classList.add(
              "btn",
              "btn-outline-success",
              "d-block",
              "btn-sm",
              "mt-3"
            );
            actionButton.innerHTML = "Following";
          } else {
            // TODO would it be better to have an intermediary 'follow' page where
            // the information is filled out?

            actionButton = document.createElement("div");
            actionButton.classList.add("dropdown");
            let dropdownButton = document.createElement("button");
            dropdownButton.classList.add(
              "btn",
              "btn-primary",
              "dropdown-toggle",
              "mt-2"
            );
            dropdownButton.setAttribute("type", "button");
            dropdownButton.setAttribute("data-bs-toggle", "dropdown");
            dropdownButton.setAttribute("aria-expanded", "false");
            dropdownButton.innerHTML = "Follow";
            actionButton.appendChild(dropdownButton);

            let dropdownList = document.createElement("ul");
            dropdownList.classList.add("dropdown-menu");

            let x = document.createElement("li");
            let y = document.createElement("a");
            y.classList.add("dropdown-item");
            y.setAttribute("href", "#");
            y.innerHTML = "Select category";
            x.appendChild(y);

            dropdownList.appendChild(x);

            let listDivider = document.createElement("li");
            let divider = document.createElement("hr");
            divider.classList.add("dropdown-divider");

            listDivider.appendChild(divider);
            dropdownList.appendChild(listDivider);

            for (category of categories) {
              let categoryItem = document.createElement("li");
              let anchorTag = document.createElement("a");
              anchorTag.classList.add("dropdown-item");
              anchorTag.innerHTML = category.name;
              categoryItem.appendChild(anchorTag);
              dropdownList.appendChild(categoryItem);
            }

            actionButton.appendChild(dropdownList);
          }

          let unorderedList = document.createElement("ul");
          unorderedList.classList.add("pt-3");

          for (entry of feed.entries) {
            let listEntry = document.createElement("li");

            let entryLink = document.createElement("a");
            entryLink.classList.add("text-decoration-none");
            entryLink.setAttribute("href", entry.link);
            entryLink.innerHTML = entry.title;

            listEntry.appendChild(entryLink);

            unorderedList.appendChild(listEntry);
          }

          cardBody.appendChild(feedLink);
          cardBody.appendChild(subtitle);
          cardBody.appendChild(linkElement);
          cardBody.appendChild(actionButton);
          cardBody.appendChild(unorderedList);

          resultsSection.appendChild(resultCard);
        }
      })
      .catch((err) => console.log(err));
  },
  true
);
