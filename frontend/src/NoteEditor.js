import React, { useState } from 'react';
import api from './api';
import './NoteEditor.css';

export default function NoteEditor({ jobCode, email, notes = [], onSaved, onCancel }) {
  const [note, setNote] = useState('');
  const token = localStorage.getItem('token');

  const save = async () => {
    const resp = await api.post(
      '/notes/student-note',
      {
        job_code: jobCode,
        student_email: email,
        note,
      },
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const newNote = resp.data.notes[resp.data.notes.length - 1];
    setNote('');
    onSaved && onSaved(newNote);
  };

  return (
    <div className="glass-modal">
      <div className="note-editor">
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button onClick={save}>Save</button>
        {onCancel && <button onClick={onCancel}>Cancel</button>}
        {notes.length > 0 && (
          <div className="note-history">
            {notes.map((n, i) => (
              <div key={i} className="note-history-item">
                {n.text}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
