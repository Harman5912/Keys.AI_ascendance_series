/* Renderer: no Node access. Everything goes through window.fieldnotes. */
const notesEl = document.getElementById("notes");
const emptyEl = document.getElementById("empty");
const errorEl = document.getElementById("error");
const metaEl = document.getElementById("meta");
const form = document.getElementById("composer");

function paint(notes) {
  notesEl.innerHTML = "";
  emptyEl.hidden = notes.length > 0;
  metaEl.textContent = `${notes.length} note${notes.length === 1 ? "" : "s"} · ${notes.filter((n) => !n.done).length} open`;

  for (const note of notes) {
    const li = document.createElement("li");
    li.className = note.done ? "done" : "";

    const text = document.createElement("span");
    text.className = "text";
    text.textContent = note.text;

    const when = document.createElement("span");
    when.className = "when";
    when.textContent = new Date(note.at).toLocaleString(undefined, {
      month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });

    const toggle = document.createElement("button");
    toggle.className = "toggle";
    toggle.type = "button";
    toggle.textContent = note.done ? "Reopen" : "Done";
    toggle.addEventListener("click", async () => {
      const result = await window.fieldnotes.toggle(note.id);
      if (result.ok) paint(result.notes);
      else showError(result.error);
    });

    li.append(text, when, toggle);
    notesEl.append(li);
  }
}

function showError(message) {
  errorEl.hidden = !message;
  errorEl.textContent = message || "";
}

async function refresh() {
  try {
    const result = await window.fieldnotes.list();
    if (!result.ok) throw new Error(result.error);
    paint(result.notes);
    showError("");
  } catch (err) {
    showError(`Could not load notes: ${err.message}`);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = form.elements.note;
  const result = await window.fieldnotes.save({ text: input.value });
  if (!result.ok) return showError(result.error);
  input.value = "";
  showError("");
  paint(result.notes);
});

refresh();
