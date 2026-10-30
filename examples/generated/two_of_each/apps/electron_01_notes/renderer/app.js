// Notes app

const electronAPI = window.electronAPI

const notesList = document.getElementById('notes-list')

async function loadNotes() {
  try {
    const notes = await electronAPI.listNotes()
    notesList.innerHTML = ''
    notes.forEach(note => {
      const noteDiv = document.createElement('div')
      noteDiv.textContent = note
      notesList.appendChild(noteDiv)
    })
  } catch (error) {
    console.error('Failed to load notes:', error)
  }
}

async function saveNote() {
  const noteInput = document.getElementById('note-input')
  const note = noteInput.value
  if (note.trim() === '') return

  try {
    await electronAPI.saveNote(note)
    noteInput.value = ''
    loadNotes()
  } catch (error) {
    console.error('Failed to save note:', error)
  }
}

loadNotes()

// Add event listener for Enter key
document.getElementById('note-input').addEventListener('keypress', function (e) {
  if (e.key === 'Enter') {
    saveNote()
  }
})