import React, { useState } from 'react';
import api from './api';
import NoteEditor from './NoteEditor';
import './NotesHistoryModal.css';

function NotesHistoryModal({ notes = [], onClose, isAdmin = false, canAdd = false, jobCode, studentEmail, onSaved }) {
  const [localNotes, setLocalNotes] = useState(notes);
  const [adding, setAdding] = useState(false);
  const [editingIndex, setEditingIndex] = useState(null);
  const [editText, setEditText] = useState('');
  const token = localStorage.getItem('token');

  const handleAddSaved = (newNote) => {
    setLocalNotes(prev => [...prev, newNote]);
    setAdding(false);
    onSaved && onSaved(newNote);
  };

  const startEdit = (idx) => {
    setEditingIndex(idx);
    setEditText(localNotes[idx].text);
  };

  const cancelEdit = () => {
    setEditingIndex(null);
    setEditText('');
  };

  const saveEdit = async () => {
    try {
      const resp = await api.put(
        '/notes/student-note',
        {
          job_code: jobCode,
          student_email: studentEmail,
          index: editingIndex,
          note: editText,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const updated = resp.data?.notes;
      if (Array.isArray(updated)) {
        setLocalNotes(updated);
      } else {
        setLocalNotes(prev =>
          prev.map((n, i) => (i === editingIndex ? { ...n, text: editText } : n))
        );
      }
      cancelEdit();
    } catch (err) {
      console.error('Failed to edit note', err);
    }
  };

  const deleteNote = async (idx) => {
    try {
      await api.delete('/notes/student-note', {
        headers: { Authorization: `Bearer ${token}` },
        data: { job_code: jobCode, student_email: studentEmail, index: idx },
      });
      setLocalNotes(prev => prev.filter((_, i) => i !== idx));
    } catch (err) {
      console.error('Failed to delete note', err);
    }
  };

  return (
    <div className="notes-modal-overlay">
      <div className="glass-modal">
        <div className="notes-modal">
          <button className="close-button" onClick={onClose}>X</button>
          <h3>Notes History</h3>
          {canAdd && !adding && (
            <button onClick={() => setAdding(true)}>Add Note</button>
          )}
          {canAdd && adding && (
            <NoteEditor
              jobCode={jobCode}
              email={studentEmail}
              onSaved={handleAddSaved}
              onCancel={() => setAdding(false)}
            />
          )}
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Date</th>
                <th>Note</th>
                {isAdmin && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {localNotes.length > 0 ? (
                localNotes.map((n, idx) => (
                  <tr key={idx}>
                    <td>{idx + 1}</td>
                    <td>{n.timestamp ? new Date(n.timestamp).toLocaleString() : ''}</td>
                    <td>
                      {editingIndex === idx ? (
                        <textarea
                          value={editText}
                          onChange={(e) => setEditText(e.target.value)}
                        />
                      ) : (
                        n.text
                      )}
                    </td>
                    {isAdmin && (
                      <td>
                        {editingIndex === idx ? (
                          <>
                            <button onClick={saveEdit}>Save</button>
                            <button onClick={cancelEdit}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => startEdit(idx)}>Edit</button>
                            <button onClick={() => deleteNote(idx)}>Delete</button>
                          </>
                        )}
                      </td>
                    )}
                  </tr>
              ))
              ) : (
                <tr>
                  <td colSpan={isAdmin ? 4 : 3}>No notes available.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default NotesHistoryModal;
