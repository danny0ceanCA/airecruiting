import React, { useState } from 'react';
import api from './api';

export default function NoteEditor({ jobCode, email, initialNote = '', onSaved, onCancel }) {
  const [note, setNote] = useState(initialNote);
  const token = localStorage.getItem('token');

  const save = async () => {
    await api.post(
      '/student-note',
      {
        job_code: jobCode,
        student_email: email,
        note,
      },
      { headers: { Authorization: `Bearer ${token}` } }
    );
    onSaved && onSaved(note);
  };

  return (
    <div className="note-editor">
      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button onClick={save}>Save</button>
      {onCancel && <button onClick={onCancel}>Cancel</button>}
    </div>
  );
}
