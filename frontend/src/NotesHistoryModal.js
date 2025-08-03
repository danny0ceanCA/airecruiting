import React from 'react';

function NotesHistoryModal({ notes = [], onClose }) {
  return (
    <div className="notes-modal-overlay">
      <div className="notes-modal">
        <button className="close-button" onClick={onClose}>X</button>
        <h3>Notes History</h3>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {notes.length > 0 ? (
              notes.map((n, idx) => (
                <tr key={idx}>
                  <td>{idx + 1}</td>
                  <td>{n.text}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan="2">No notes available.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default NotesHistoryModal;
